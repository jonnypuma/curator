"""Turn a Kodi sources.xml into Curator path mappings the user can edit.

A row is certain when this container mounts that NFS or SMB share, or when the
source host is this machine and the URL path is the library folder. A shared
folder name (Media under /EC2480/Media) is only a suggestion.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from curator import automation
from resonance.paths import config_dir

logger = logging.getLogger(__name__)

_MAX_XML = 512_000
_SCHEMES = {"nfs", "smb", "cifs"}
_PROBE_TIMEOUT = (5, 90)
_PROBE_RETRY_WAIT = 5
_probe_lock = threading.Lock()


def parse_sources(text):
    """Video and music sources with an NFS or SMB address."""
    raw = str(text or "")
    if len(raw.encode("utf-8", errors="replace")) > _MAX_XML:
        raise ValueError("That sources.xml is larger than 512 KB")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("That file is not a Kodi sources.xml") from exc
    found = []
    for section in ("video", "music"):
        parent = root.find(section)
        if parent is None:
            continue
        for source in parent.findall("source"):
            name = (source.findtext("name") or "").strip()[:200]
            for node in source.findall("path"):
                url = (node.text or "").strip()
                if url:
                    found.append({"name": name, "media": section, "url": url[:500]})
    return found[:200]


def suggest(text):
    """Proposed mappings plus sources that could not be lined up with a library folder."""
    roots = _library_roots()
    mounts = _share_mounts()
    mounts.extend(_volume_mounts(mounts))
    own = _host_ips()
    rows = []
    guesses = []
    unmatched = []
    for source in parse_sources(text):
        host, scheme = _url_host(source["url"])
        if not host or scheme not in _SCHEMES:
            unmatched.append({**source, "reason": "Only NFS and SMB sources can be mapped"})
            continue
        certain = _from_mount(source, mounts, roots)
        if certain:
            rows.extend(certain)
            continue
        guessed = _from_name(source, roots, own)
        if guessed:
            guesses.extend(guessed)
            continue
        unmatched.append({
            **source,
            "reason": "No library folder lines up with this share. Type the Curator path yourself if it is yours.",
        })
    rows.extend(_pick_guesses(guesses, unmatched))
    return {"rows": _dedupe(rows)[:50], "unmatched": unmatched[:50]}


def probe(rows):
    """Ask the Kodi library host to open each path, one after another, then see if a listed item is on disk here."""
    if not _probe_lock.acquire(blocking=False):
        raise RuntimeError("A Kodi path test is already running. Wait for it to finish.")
    try:
        return [_probe_one(row) for row in (rows or [])[:50]]
    finally:
        _probe_lock.release()


def _probe_one(row):
    from curator.notify import kodi_call

    _, cfg = automation.current()
    if not cfg["kodi_library_host"]:
        raise RuntimeError("Set the Kodi library host first, then save settings")
    local = automation.clean_path((row or {}).get("local"))
    kodi = str((row or {}).get("kodi") or "").strip()
    media = "music" if (row or {}).get("media") == "music" or _under_music(local) else "video"
    if not local or not kodi:
        return {"ok": False, "status": "error", "message": "Both paths are needed"}
    directory = kodi if kodi.endswith("/") else kodi + "/"
    result = None
    error = None
    for attempt in range(2):
        try:
            result = kodi_call(
                cfg["kodi_library_host"], cfg["kodi_library_user"], cfg["kodi_library_password"],
                "Files.GetDirectory", {"directory": directory, "media": media},
                timeout=_PROBE_TIMEOUT,
            )
            error = None
            break
        except RuntimeError as exc:
            error = exc
            if attempt == 0 and _timed_out(exc):
                time.sleep(_PROBE_RETRY_WAIT)
                continue
            break
    if error is not None:
        return {"ok": False, "status": "error", "message": str(error)}
    files = (result or {}).get("files") if isinstance(result, dict) else None
    checked, hits = _sample(files or [], local, kodi)
    if hits:
        return {
            "ok": True, "status": "match",
            "message": "Kodi lists this folder and the first item is on disk in Curator",
        }
    if checked:
        return {
            "ok": False, "status": "mismatch",
            "message": f"Kodi lists this folder, but none of {checked} items are at the Curator path",
        }
    return {
        "ok": True, "status": "empty",
        "message": "Kodi opened this path. It has nothing inside to compare",
    }


def _timed_out(exc):
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _from_mount(source, mounts, roots):
    host, scheme = _url_host(source["url"])
    kodi_path = _url_path(source["url"])
    path = kodi_path.rstrip("/") or "/"
    matches = []
    for mount in mounts:
        if not _same_host(mount["host"], host):
            continue
        export = mount["export"].rstrip("/") or "/"
        if export == "/":
            continue
        if path == export or path.startswith(export + "/"):
            matches.append((len(export), mount, export))
    if not matches:
        return []
    _length, mount, export = max(matches, key=lambda item: item[0])
    rest = "" if path == export else path[len(export):]
    landed = mount["target"].rstrip("/") + rest
    covered = _roots_for(landed, roots, source["media"])
    if not covered:
        return []
    return [
        _row(source, root["configured"], _kodi_for_root(source["url"], path, landed, root["real"]), True,
             f"{scheme.upper()} {host}:{export} is mounted at {mount['target']}")
        for root in covered
    ]


def _from_name(source, roots, own):
    """Folder-name alignment. Certain only when this machine owns the share and the paths are the same."""
    host, _scheme = _url_host(source["url"])
    ours = host in own or any(_same_host(host, ip) for ip in own)
    path = _url_path(source["url"])
    rows = []
    for root in roots:
        if source["media"] == "music" and root["media"] != "music":
            continue
        if source["media"] == "video" and root["media"] == "music":
            continue
        aligned = _align(root["real"], path)
        if not aligned:
            aligned = _align(root["configured"], path)
        if not aligned:
            continue
        local_prefix, kodi_prefix = aligned
        shown = root["configured"]
        real = root["real"].rstrip("/")
        if real.startswith(local_prefix.rstrip("/") + "/"):
            kodi_prefix = kodi_prefix.rstrip("/") + real[len(local_prefix.rstrip("/")):]
        elif local_prefix not in {real, root["configured"].rstrip("/")}:
            shown = local_prefix
        sure = ours and path.rstrip("/") in {real, root["configured"].rstrip("/")}
        reason = ("This share path is the library folder"
                  if sure else "The share name lines up with this library folder. Check it before accepting.")
        score = len([part for part in str(kodi_prefix).split("/") if part])
        row = _row(source, shown, _with_path(source["url"], kodi_prefix), sure, reason)
        row["score"] = score
        row["url"] = source.get("url") or ""
        rows.append(row)
    return rows


def _pick_guesses(guesses, unmatched):
    """Keep one Kodi path per library folder. A tie between hosts is left for the user to type."""
    by_local = {}
    for row in guesses:
        by_local.setdefault(row["local"], []).append(row)
    chosen = []
    used_kodi = set()
    skipped = []
    for items in by_local.values():
        best = max(item["score"] for item in items)
        top = [item for item in items if item["score"] == best]
        urls = {item["kodi"] for item in top}
        if len(urls) != 1 or top[0]["kodi"] in used_kodi:
            skipped.extend(top)
            continue
        used_kodi.add(top[0]["kodi"])
        chosen.append(top[0])
    seen = {item["kodi"] for item in chosen}
    reported = set()
    for item in skipped:
        url = item.get("url") or item["kodi"]
        if url in seen or url in reported:
            continue
        reported.add(url)
        unmatched.append({
            "name": item.get("name") or "",
            "media": item.get("media") or "video",
            "url": url,
            "reason": "More than one library folder shares this name. Type the Curator path.",
        })
    return chosen


def _roots_for(landed, roots, media):
    landed_real = os.path.realpath(landed) if os.path.isdir(landed) else landed.rstrip("/")
    found = []
    for root in roots:
        if media == "music" and root["media"] != "music":
            continue
        if media == "video" and root["media"] == "music":
            continue
        real = root["real"].rstrip("/")
        base = landed_real.rstrip("/")
        if real == base or real.startswith(base + "/") or base.startswith(real + "/"):
            found.append(root)
    return found


def _kodi_for_root(url, source_path, landed, root_real):
    source_path = source_path.rstrip("/") or "/"
    landed = landed.rstrip("/")
    root_real = root_real.rstrip("/")
    if root_real == landed or root_real.startswith(landed + "/"):
        extra = root_real[len(landed):]
        return _with_path(url, source_path + extra)
    if landed.startswith(root_real + "/"):
        extra = landed[len(root_real):]
        if source_path.endswith(extra):
            return _with_path(url, source_path[:-len(extra)] or "/")
    return _with_path(url, source_path)


def _align(root, kodi_path):
    """Library folder and Kodi path sharing a tail, such as /EC2480/Media and /Media/Movies."""
    rparts = [part for part in str(root).strip("/").split("/") if part]
    kparts = [part for part in str(kodi_path).strip("/").split("/") if part]
    if not rparts or not kparts:
        return None
    for length in range(min(len(rparts), len(kparts)), 0, -1):
        window = kparts[:length]
        for index in range(len(rparts) - length, -1, -1):
            if rparts[index:index + length] != window:
                continue
            if index + length != len(rparts) and length != len(kparts):
                continue
            local = "/" + "/".join(rparts[:index + length])
            return local, "/" + "/".join(window)
    return None


def _row(source, local, kodi, sure, reason):
    return {
        "local": automation.clean_path(local),
        "kodi": str(kodi or "").rstrip("/"),
        "name": source.get("name") or "",
        "media": source.get("media") or "video",
        "sure": bool(sure),
        "reason": reason,
    }


def _dedupe(rows):
    seen = set()
    kept = []
    for row in sorted(rows, key=lambda item: (not item["sure"], -len(item["kodi"]))):
        key = (row["local"], row["kodi"])
        if not row["local"] or not row["kodi"] or key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _sample(files, local, kodi):
    checked = 0
    for item in files:
        if not isinstance(item, dict):
            continue
        target = _local_for(item.get("file") or "", local, kodi)
        if not target:
            continue
        checked += 1
        if os.path.exists(target):
            return checked, 1
        if checked >= 8:
            break
    return checked, 0


def _local_for(kodi_file, local, kodi):
    file_path = _url_path(kodi_file) if "://" in kodi_file else automation.clean_path(kodi_file)
    base = _url_path(kodi) if "://" in kodi else automation.clean_path(kodi)
    file_path = file_path.rstrip("/")
    base = base.rstrip("/")
    if file_path != base and not file_path.startswith(base + "/"):
        return ""
    return local.rstrip("/") + file_path[len(base):]


def _library_roots():
    from resonance.settings import load

    data = load()
    rows = []
    seen = set()
    for key, media in (("movie_paths", "video"), ("tv_paths", "video"), ("music_paths", "music")):
        for item in data.get(key) or []:
            text = automation.clean_path(item)
            if not text or (text, media) in seen:
                continue
            seen.add((text, media))
            rows.append({
                "configured": text,
                "real": os.path.realpath(text) if os.path.isdir(text) else text,
                "media": media,
            })
    return rows


def _under_music(path):
    for root in _library_roots():
        if root["media"] != "music":
            continue
        base = root["configured"].rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False


def _share_mounts():
    found = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        source = parts[0].replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n")
        target = parts[1].replace("\\040", " ")
        host, export = _mount_share(source, parts[2])
        if not host or not export or not os.path.isdir(target):
            continue
        found.append({"host": host, "export": export if export.startswith("/") else "/" + export,
                      "target": os.path.realpath(target)})
    return found


def _volume_mounts(existing):
    """Paths from config/volume-mounts.json. Each remote may be nfs:// or smb://."""
    path = os.path.join(config_dir(), "volume-mounts.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("volume-mounts.json could not be read: %s", exc)
        return []
    rows = data.get("mounts") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        logger.warning("volume-mounts.json must be a list of local and remote paths")
        return []
    known = {(str(item["host"]).lower(), item["target"].rstrip("/")) for item in existing}
    found = []
    for item in rows:
        parsed = _volume_row(item)
        if not parsed:
            continue
        key = (parsed["host"].lower(), parsed["target"].rstrip("/"))
        if key in known:
            continue
        known.add(key)
        found.append(parsed)
    return found


def _volume_row(item):
    if not isinstance(item, dict):
        return None
    local = automation.clean_path(item.get("local"))
    remote = str(item.get("remote") or "").strip()
    host, scheme = _url_host(remote)
    export = _url_path(remote).rstrip("/") or "/"
    if not local.startswith("/") or not host or scheme not in _SCHEMES or export == "/":
        return None
    target = os.path.realpath(local) if os.path.isdir(local) else local
    return {"host": host, "export": export, "target": target}


def _mount_share(source, fstype):
    kind = (fstype or "").lower()
    if kind.startswith("nfs") and ":" in source:
        host, export = source.split(":", 1)
        if export.startswith("/"):
            return host.strip("[]"), export
    if kind in {"cifs", "smb3", "smbfs"} or source.startswith("//"):
        rest = source[2:] if source.startswith("//") else source
        bits = [bit for bit in rest.split("/") if bit]
        if len(bits) >= 2:
            return bits[0], "/" + "/".join(bits[1:])
    return "", ""


def _host_ips():
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            if info[4]:
                found.add(info[4][0])
    except OSError:
        pass
    previous = ""
    try:
        with open("/proc/net/fib_trie", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        lines = []
    for line in lines:
        if "host LOCAL" in line:
            ip = previous.strip().lstrip("|+- ").strip()
            if ip:
                found.add(ip)
        else:
            previous = line
    found.discard("0.0.0.0")
    found.discard("127.0.0.1")
    found.discard("::1")
    return found


def _url_host(url):
    parts = urlsplit(str(url or "").strip())
    return (parts.hostname or "").lower(), (parts.scheme or "").lower()


def _url_path(url):
    parts = urlsplit(str(url or "").strip())
    path = parts.path or "/"
    return path if path.startswith("/") else "/" + path


def _with_path(url, path):
    parts = urlsplit(str(url or "").strip())
    path = path if str(path).startswith("/") else "/" + str(path or "")
    path = path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


def _same_host(left, right):
    return str(left or "").strip("[]").lower() == str(right or "").strip("[]").lower()
