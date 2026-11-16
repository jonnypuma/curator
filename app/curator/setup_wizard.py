"""The setup wizard: whether it opens by itself, and the checks behind its folder and path-mapping Test buttons.

The wizard saves through the same PUT /api/settings as the Settings window and tests connections through the same
endpoints, so this module only holds what Settings had no answer for: a first-run marker, a folder check that says
why a folder cannot be used, and a test that a path mapping points at folders that exist on both sides.
"""
from __future__ import annotations

import json
import logging
import os
import time

from resonance.paths import config_dir

logger = logging.getLogger(__name__)

MEDIA_LABELS = {"music": "music", "movies": "movie", "tv": "TV", "musicvideos": "music video"}
ARR_APPS = {"radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr", "bazarr": "Bazarr"}
PLAYER_APPS = {"kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex"}

# Settings that only someone who has set Curator up would have: a key, an app address or a player address.
_CONFIG_KEYS = (
    "tmdb_key", "tvdb_key", "omdb_key", "fanart_key", "acoustid_key", "lastfm_key",
    "radarr_url", "radarr_api_key", "sonarr_url", "sonarr_api_key", "lidarr_url", "lidarr_api_key",
    "bazarr_url", "bazarr_api_key", "kodi_password", "kodi_library_password", "plex_token", "emby_token",
    "jellyfin_token", "webhook_navidrome", "webhook_jellyfin", "webhook_plex", "webhook_emby",
)
_CONFIG_NOTIFY = ("kodi_library_host", "kodi_notify_host", "emby_url", "jellyfin_url", "plex_url")


def marker_path():
    return os.path.join(config_dir(), "setup.json")


def _read_marker():
    try:
        with open(marker_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("could not read the setup marker: %s", exc)
        return {"done": True}       # unreadable: never trap the user in the wizard


def mark_done():
    """Remember that the wizard was finished or closed, so it does not open by itself again."""
    from resonance.paths import atomic_write

    data = {"done": True, "done_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        os.makedirs(config_dir(), exist_ok=True)
        atomic_write(marker_path(), json.dumps(data) + "\n", binary=False)
    except OSError as exc:
        logger.warning("could not write the setup marker: %s", exc)
    return status()


def configured(cfg):
    """True when the settings hold anything a user set: a key, an app or player address, or a key from compose."""
    cfg = cfg or {}
    if cfg.get("key_sources"):
        return True
    if any(str(cfg.get(key) or "").strip() for key in _CONFIG_KEYS):
        return True
    notify = cfg.get("notify") or {}
    return any(str(notify.get(key) or "").strip() for key in _CONFIG_NOTIFY)


LIBRARY_SQL = """
    SELECT EXISTS (SELECT 1 FROM albums) OR EXISTS (SELECT 1 FROM movies)
        OR EXISTS (SELECT 1 FROM tv_shows) OR EXISTS (SELECT 1 FROM music_videos) AS found
"""


def library_empty():
    """True when no album, movie, show or music video is in the database. False when the database cannot say."""
    from resonance import db

    try:
        row = db.fetchone(LIBRARY_SQL)
    except Exception as exc:
        logger.info("setup wizard: library check failed: %s", exc)
        return False
    return not (row or {}).get("found")


def first_run(marker, cfg, empty):
    """The wizard opens by itself only on a fresh install: never finished, nothing configured, nothing scanned."""
    return not (marker or {}).get("done") and not configured(cfg) and bool(empty)


def status():
    from resonance import settings

    marker = _read_marker()
    fresh = False if marker.get("done") else first_run(marker, settings.load(), library_empty())
    return {"done": bool(marker.get("done")), "done_at": marker.get("done_at") or "", "first_run": fresh}


def _mount_for(real, mounts):
    from resonance.paths import inside

    best = None
    for mount in mounts or []:
        if inside(mount["path"], real) and (best is None or len(mount["path"]) > len(best["path"])):
            best = mount
    return best


def check_folder(path, media="music", mounts=None):
    """Whether a library folder can be used: it exists, can be listed, can be written, and is on a mounted volume.

    The library-path rules are the ones saving settings applies (resonance.paths.assert_library_path), so a folder
    that passes here also saves. Nothing is written to the folder: write access is read from the mount and the
    folder's permissions.
    """
    from resonance.errors import AppError
    from resonance.paths import assert_library_path, discover_mounts

    label = MEDIA_LABELS.get(media, "library")
    text = str(path or "").strip()
    result = {"path": text, "media": media, "ok": False, "exists": False, "readable": False, "writable": False,
              "mounted": False, "entries": 0, "problems": [], "notes": []}
    if not text or not os.path.isabs(text):
        result["problems"].append("Use the path inside the container. It starts with /, for example /movies.")
        return result
    real = os.path.realpath(text)
    result["path"] = real
    if not os.path.isdir(real):
        result["problems"].append(
            f"{real} does not exist inside the container. Mount the host folder in docker-compose, recreate the "
            "container, then add it here."
        )
        return result
    result["exists"] = True
    try:
        with os.scandir(real) as entries:
            count = 0
            for _entry in entries:
                count += 1
                if count >= 1000:
                    break
        result["entries"] = count
        result["readable"] = True
    except OSError as exc:
        result["problems"].append(f"Curator cannot list {real}: {exc.strerror or exc}. Check the folder's permissions "
                                  "(PUID and PGID in docker-compose) or the mount.")
    mount = _mount_for(real, discover_mounts() if mounts is None else mounts)
    result["mounted"] = mount is not None
    result["writable"] = bool(os.access(real, os.W_OK) and (mount is None or mount.get("writable")))
    try:
        assert_library_path(real, label)
    except AppError as exc:
        result["problems"].append(str(exc))
    from resonance.paths import own_folder_clash

    own = own_folder_clash(real)
    if own:
        result["problems"].append(f"{real} overlaps {own}, Curator's own folder for settings, cache or artwork. "
                                  "Pick a library folder outside it.")
    if result["readable"] and not result["writable"]:
        why = "the volume is mounted read-only (:ro)" if mount is not None and not mount.get("writable") else \
            "the folder's permissions do not allow it"
        result["notes"].append(f"Curator can read this folder but not write to it, because {why}. Scans work, but "
                               ".nfo files, artwork, renames and deletes need write access.")
    if result["readable"] and not result["entries"]:
        result["notes"].append("The folder is empty. That is fine for a new library; a scan finds nothing yet.")
    result["ok"] = result["readable"] and not result["problems"]
    return result


def _clean(value):
    text = str(value or "").strip().replace("\\", "/")
    return text.rstrip("/") if len(text) > 1 else text


def _under(prefix, path):
    """True when path is prefix or inside it, compared as text (the other side's paths do not exist here)."""
    prefix, path = _clean(prefix), _clean(path)
    if not prefix or not path:
        return False
    if prefix == "/":
        return path.startswith("/")
    return path == prefix or path.startswith(prefix + "/")


def _translate(path, remote, local):
    path, remote, local = _clean(path), _clean(remote), _clean(local)
    rest = path[len(remote):].lstrip("/") if remote != "/" else path.lstrip("/")
    return f"{local.rstrip('/')}/{rest}" if rest else local


def _arr_ready(app):
    """True when the download app has an address and a key saved (or set in docker-compose)."""
    from resonance import settings

    cfg = settings.load()
    return bool(str(cfg.get(f"{app}_url") or "").strip() and str(cfg.get(f"{app}_api_key") or "").strip())


def _arr_roots(app):
    """Root folders of a download app, from the saved address and key."""
    if app == "radarr":
        from curator import radarr

        return [item["path"] for item in radarr.options().get("root_folders") or []]
    if app == "sonarr":
        from curator import sonarr

        return [item["path"] for item in sonarr.options().get("root_folders") or []]
    if app == "lidarr":
        from resonance import lidarr

        return [item["path"] for item in lidarr.options().get("root_folders") or [] if item.get("path")]
    return None


def compare_roots(rows, roots, exists=os.path.isdir):
    """For each mapping row: the other app's folders under its remote path, where they land here, and if they exist.

    `roots` are the folders the other app reports (download-app root folders, or player library folders). A row
    whose remote path holds none of them, and sits inside none of them, maps nothing that app uses.
    """
    results = []
    for row in rows:
        remote, local = _clean(row.get("remote")), _clean(row.get("local"))
        hits = []
        for root in roots or []:
            if _under(remote, root):
                target = _translate(root, remote, local)
                hits.append({"remote": _clean(root), "local": target, "exists": bool(exists(target))})
            elif _under(root, remote):
                hits.append({"remote": remote, "local": local, "exists": bool(exists(local))})
        results.append({"remote": remote, "local": local, "matches": hits})
    return results


def check_mappings(app, rows):
    """Test path mappings for a download app or a player, using the saved settings.

    Every row's Curator path must exist here. For Radarr, Sonarr and Lidarr the app's root folders are read and
    translated through the row; each must exist here. For Emby, Jellyfin and Plex the server's library folders are
    read and the row's player path must hold one of them or sit inside one. Kodi is asked to open the folder (the
    same test as Settings, Integrations, Upload sources.xml, Test in Kodi).
    """
    from curator import automation, notify

    if app not in ARR_APPS and app not in PLAYER_APPS:
        raise ValueError(f"Unknown app {app}")
    label = ARR_APPS.get(app) or PLAYER_APPS.get(app)
    clean_rows = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        remote, local = _clean(row.get("remote")), _clean(row.get("local"))
        if remote or local:
            clean_rows.append({"remote": remote, "local": local})
    clean_rows = clean_rows[:50]
    if not clean_rows:
        return {"app": app, "results": [], "message": "Add a mapping row first."}
    results = []
    for row in clean_rows:
        problems = []
        if not row["remote"] or not row["local"]:
            problems.append("Fill in both paths.")
        elif not os.path.isabs(row["local"]):
            problems.append("The Curator path is a path inside the container. It starts with /.")
        elif not os.path.isdir(row["local"]):
            problems.append(f"{row['local']} does not exist inside Curator's container.")
        results.append({**row, "ok": not problems, "problems": problems, "matches": [], "notes": []})
    roots, error = None, ""
    try:
        if app == "kodi":
            from curator import kodi_sources

            probes = kodi_sources.probe([{"local": row["local"], "kodi": row["remote"]} for row in results if row["ok"]])
            for row, probe in zip([item for item in results if item["ok"]], probes):
                if probe.get("ok"):
                    row["notes"].append(probe.get("message") or "Kodi opened the folder and its files are here too.")
                else:
                    row["ok"] = False
                    row["problems"].append(probe.get("message") or "Kodi could not open the folder.")
            return {"app": app, "results": results, "message": ""}
        if app in ARR_APPS:
            # An app that is not set up is not asked: the failed request would raise an error notice of its own.
            if app != "bazarr" and not _arr_ready(app):
                error = f"{label} has no address and API key saved yet, so only the Curator paths were checked."
            else:
                roots = _arr_roots(app)
        else:
            _auto, cfg = automation.current()
            roots = [item["path"] for item in notify.library_locations(app, cfg)]
    except Exception as exc:
        error = f"{label} could not be asked for its folders: {exc}"
        logger.info("setup wizard: %s", error)
    if roots is not None:
        compared = compare_roots(results, roots)
        what = "root folders" if app in ARR_APPS else "library folders"
        for row, found in zip(results, compared):
            row["matches"] = found["matches"]
            if not row["remote"] or not row["local"]:
                continue
            if not found["matches"]:
                listed = ", ".join(roots[:6]) or "none"
                row["notes"].append(f"None of {label}'s {what} ({listed}) is under {row['remote']}, so this row maps "
                                    f"nothing {label} uses yet.")
            missing = [hit["local"] for hit in found["matches"] if not hit["exists"]]
            if missing:
                row["ok"] = False
                row["problems"].append("These folders do not exist inside Curator's container: " + ", ".join(missing))
    return {"app": app, "results": results, "message": error}
