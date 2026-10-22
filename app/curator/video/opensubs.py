"""Find and download subtitles from OpenSubtitles.com (REST API v1).

A search needs only an API key. A download also needs the account's login, because the site counts
downloads per account and a free account has a daily quota. The login token is kept in memory and
reused until it expires.

Results are ranked: a file-hash match first (the subtitle was made for exactly this file), then
trusted uploaders, then download count. Machine translated and foreign-parts-only subtitles are
skipped unless nothing else exists.

A subtitle is saved next to the video as <video>.<lang>[.sdh].srt, the same names the library scan reads.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
import time

import httpx

from curator.video import languages, naming, subtitles, writes
from resonance.errors import AppError

logger = logging.getLogger(__name__)

HOST = "api.opensubtitles.com"
USER_AGENT = "Curator v1.0"
TIMEOUT = 30.0
TOKEN_SECONDS = 20 * 3600
SPACING = 0.3                 # seconds between calls; the API allows a few a second
HASH_CHUNK = 65536

_lock = threading.Lock()
_session = {"token": "", "base": HOST, "key": "", "user": "", "at": 0.0}
_last_call = [0.0]


class QuotaError(AppError):
    """The account has used today's downloads."""


# ======================================================================================
# settings
# ======================================================================================

def credentials(cfg):
    return {
        "key": str(cfg.get("opensubtitles_key") or "").strip(),
        "user": str(cfg.get("subs_username") or "").strip(),
        "password": str(cfg.get("opensubtitles_password") or "").strip(),
    }


def configured(cfg):
    return bool(credentials(cfg)["key"])


def can_download(cfg):
    found = credentials(cfg)
    return bool(found["key"] and found["user"] and found["password"])


def wanted_languages(cfg):
    """The configured languages as (canonical 3-letter code, OpenSubtitles tag)."""
    out, seen = [], set()
    for token in str(cfg.get("subs_languages") or "en").replace(";", ",").split(","):
        token = {"nb": "no"}.get(token.strip().lower(), token.strip().lower())
        if not token:
            continue
        code = languages.normalize_lang(token)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append((code, _os_tag(token, code)))
    return out


def _os_tag(token, code):
    """OpenSubtitles language tags: two letters, with pt-br, pt-pt, zh-cn and zh-tw for the regional ones."""
    token = token.lower().replace("_", "-")
    if token in ("pt-br", "pt-pt", "zh-cn", "zh-tw"):
        return token
    if token in ("zh-hans", "chs"):
        return "zh-cn"
    if token in ("zh-hant", "cht"):
        return "zh-tw"
    if len(token) == 2:
        return token
    return subtitles._ISO1.get(code, token[:2])


# ======================================================================================
# HTTP
# ======================================================================================

def _pause():
    with _lock:
        wait = _last_call[0] + SPACING - time.monotonic()
        _last_call[0] = time.monotonic() + max(0.0, wait)
    if wait > 0:
        time.sleep(wait)


def _headers(key, token=""):
    headers = {"Api-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _message(response):
    try:
        data = response.json()
        return str(data.get("message") or data.get("errors") or response.text)[:200]
    except ValueError:
        return (response.text or f"HTTP {response.status_code}")[:200]


def _request(method, url, *, key, token="", params=None, body=None, retries=2, binary=False):
    for attempt in range(retries + 1):
        _pause()
        try:
            response = httpx.request(
                method, url, params=params, json=body, headers=_headers(key, token),
                timeout=TIMEOUT, follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            if attempt >= retries:
                raise AppError(f"OpenSubtitles could not be reached ({exc.__class__.__name__})", 502) from exc
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt >= retries:
                raise AppError(f"OpenSubtitles answered {response.status_code}", 502)
            try:
                wait = float(response.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0.0
            time.sleep(min(30.0, wait or 2.0 * (attempt + 1)))
            continue
        if response.status_code == 406:
            raise QuotaError("The OpenSubtitles download quota for today is used up", 429)
        if response.status_code in (401, 403):
            raise AppError(f"OpenSubtitles refused the login or API key: {_message(response)}", 401)
        if response.status_code >= 400:
            raise AppError(f"OpenSubtitles: {_message(response)}", 502)
        return response.content if binary else response.json()
    return None


def login(cfg, force=False):
    """(token, host). Reuses the saved token until it is old or the account changed."""
    found = credentials(cfg)
    if not (found["key"] and found["user"] and found["password"]):
        raise AppError("Set the OpenSubtitles API key, username and password in Settings to download subtitles", 400)
    with _lock:
        fresh = (
            _session["token"] and _session["key"] == found["key"] and _session["user"] == found["user"]
            and time.time() - _session["at"] < TOKEN_SECONDS
        )
        if fresh and not force:
            return _session["token"], _session["base"]
    data = _request("POST", f"https://{HOST}/api/v1/login", key=found["key"],
                    body={"username": found["user"], "password": found["password"]})
    token = str((data or {}).get("token") or "")
    if not token:
        raise AppError("OpenSubtitles did not return a login token", 502)
    base = str((data or {}).get("base_url") or HOST).replace("https://", "").replace("http://", "").strip("/") or HOST
    with _lock:
        _session.update({"token": token, "base": base, "key": found["key"], "user": found["user"], "at": time.time()})
    return token, base


def test(cfg):
    """Check the key with a search, and the login too when a username and password are set."""
    found = credentials(cfg)
    if not found["key"]:
        raise AppError("Enter an OpenSubtitles API key first", 400)
    _request("GET", f"https://{HOST}/api/v1/subtitles", key=found["key"], params={"query": "matrix", "type": "movie"})
    if found["user"] and found["password"]:
        login(cfg, force=True)
        return {"ok": True, "message": "The API key and login work"}
    return {"ok": True, "message": "The API key works. Add a username and password to download"}


# ======================================================================================
# file hash
# ======================================================================================

def file_hash(path):
    """The OpenSubtitles hash: file size plus the 64-bit words of the first and last 64 KiB."""
    try:
        size = os.path.getsize(path)
        if size < HASH_CHUNK * 2:
            return ""
        total = size
        with open(path, "rb") as handle:
            for position in (0, size - HASH_CHUNK):
                handle.seek(position)
                data = handle.read(HASH_CHUNK)
                for (value,) in struct.iter_unpack("<Q", data):
                    total = (total + value) & 0xFFFFFFFFFFFFFFFF
        return f"{total:016x}"
    except OSError:
        return ""


# ======================================================================================
# the library item behind a lookup
# ======================================================================================

def target(kind, item_id):
    """What the search needs for one movie or episode, and what the file already has."""
    from curator.video import store

    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        file = row.get("file") or {}
        return {
            "kind": "movie", "id": str(row["id"]), "path": row.get("path") or "", "title": row.get("title") or "",
            "year": row.get("year"), "imdb": row.get("imdb_id") or "", "tmdb": row.get("tmdb_id") or "",
            "file": file,
        }
    if kind == "episode":
        row = store.episode_detail(item_id)
        if not row:
            raise AppError("Episode not found", 404)
        return {
            "kind": "episode", "id": str(row["id"]), "path": row.get("path") or "",
            "title": row.get("show_title") or "", "year": row.get("show_year"),
            "imdb": row.get("show_imdb_id") or "", "tmdb": row.get("show_tmdb_id") or "",
            "season": row.get("season_number"), "episode": row.get("episode_number"),
            "episode_title": row.get("title") or "", "file": row.get("file") or {},
        }
    raise AppError("Choose a movie or an episode", 400)


def _digits(value):
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    return text.lstrip("0") if text else ""


def present_languages(item):
    """Languages the file already has as full subtitles, embedded or beside it. Forced subtitles do not count."""
    have = set()
    file = item.get("file") or {}
    for track in file.get("subtitle_tracks") or []:
        if "forced" not in (track.get("flags") or []) and track.get("lang"):
            have.add(track["lang"])
    for sub in file.get("external_subtitles") or []:
        if "forced" not in (sub.get("flags") or []) and sub.get("lang"):
            have.add(sub["lang"])
    return have


# ======================================================================================
# search
# ======================================================================================

def search(cfg, item, tags, hearing="include"):
    """Ranked candidate list for one item. `tags` are OpenSubtitles language tags."""
    found = credentials(cfg)
    if not found["key"]:
        raise AppError("Set the OpenSubtitles API key in Settings first", 400)
    params = {"languages": ",".join(sorted(set(tags))) or "en", "order_by": "download_count", "order_direction": "desc"}
    if hearing in ("exclude", "only"):
        params["hearing_impaired"] = hearing
    else:
        params["hearing_impaired"] = "include"
    digest = file_hash(item["path"]) if item.get("path") else ""
    if digest:
        params["moviehash"] = digest
    if item["kind"] == "movie":
        params["type"] = "movie"
        if _digits(item.get("tmdb")):
            params["tmdb_id"] = _digits(item["tmdb"])
        elif _digits(item.get("imdb")):
            params["imdb_id"] = _digits(item["imdb"])
        else:
            params["query"] = item["title"]
            if item.get("year"):
                params["year"] = item["year"]
    else:
        params["type"] = "episode"
        if _digits(item.get("tmdb")):
            params["parent_tmdb_id"] = _digits(item["tmdb"])
        elif _digits(item.get("imdb")):
            params["parent_imdb_id"] = _digits(item["imdb"])
        else:
            params["query"] = item["title"]
        params["season_number"] = item.get("season")
        params["episode_number"] = item.get("episode")
    data = _request("GET", f"https://{HOST}/api/v1/subtitles", key=found["key"], params=params)
    results = []
    for entry in (data or {}).get("data") or []:
        attrs = entry.get("attributes") or {}
        files = attrs.get("files") or []
        if not files:
            continue
        results.append({
            "file_id": files[0].get("file_id"),
            "file_name": files[0].get("file_name") or "",
            "release": attrs.get("release") or "",
            "language": attrs.get("language") or "",
            "downloads": int(attrs.get("download_count") or 0),
            "hearing_impaired": bool(attrs.get("hearing_impaired")),
            "hash_match": bool(attrs.get("moviehash_match")),
            "trusted": bool(attrs.get("from_trusted")),
            "machine": bool(attrs.get("machine_translated")) or bool(attrs.get("ai_translated")),
            "foreign_only": bool(attrs.get("foreign_parts_only")),
            "fps": attrs.get("fps"),
            "uploaded": str(attrs.get("upload_date") or "")[:10],
            "uploader": ((attrs.get("uploader") or {}).get("name") or ""),
            "rating": attrs.get("ratings"),
        })
    results.sort(key=rank, reverse=True)
    return results


def rank(result):
    return (
        result["hash_match"], not result["machine"], not result["foreign_only"], result["trusted"],
        result["downloads"],
    )


def best_for(results, tag, hearing):
    """The top candidate for one language, or None. SDH is only taken when the setting allows it."""
    for result in results:
        if result["language"].lower() != tag.lower():
            continue
        if result["machine"] or result["foreign_only"]:
            continue
        if hearing == "exclude" and result["hearing_impaired"]:
            continue
        if hearing == "only" and not result["hearing_impaired"]:
            continue
        return result
    return None


# ======================================================================================
# download
# ======================================================================================

def sidecar_path(item_path, tag, hearing_impaired, cfg):
    stem = os.path.splitext(item_path)[0]
    code = languages.normalize_lang(tag) or tag
    region = tag.lower() if tag.lower() in subtitles._REGIONAL else None
    info = {"lang": code, "region": region, "flags": ["sdh"] if hearing_impaired else [], "rest": [], "ext": ".srt"}
    name = subtitles.target_name(os.path.basename(stem), info, cfg.get("sub_lang_standard", "iso639-2"))
    return os.path.join(os.path.dirname(item_path), name)


def _sync_after(cfg, video, sub, log):
    """Line a downloaded subtitle up with the audio. A refused or already-right proposal leaves it as it is."""
    from curator.video import sub_auto, sub_sync, work_track

    name = os.path.basename(sub)
    try:
        found = sub_auto.run(video, sub, "fine")
        if found.get("rejected"):
            log(f"Subtitles: {name} was not shifted: the proposed change was too large to trust")
            work_track.record("sub-sync", f"{name}: sync proposal refused", "completed")
            return
        if found.get("unchanged"):
            log(f"Subtitles: {name} already lines up")
            return
        data = sub_sync.read(sub)
        anchors, mode = found["anchors"], found["mode"]
        segments = sub_sync.segments_for(anchors, mode)
        if segments is not None:
            cues = sub_sync.apply_segments(data["cues"], segments)
        else:
            scale, offset = sub_sync.transform(anchors)
            cues = sub_sync.apply(data["cues"], scale, offset)
        sub_sync.write(sub, cues, line_endings=str(cfg.get("sub_line_endings") or "lf").lower())
        log(f"Subtitles: synced {name} (moved by up to {found.get('max_shift_ms', 0) / 1000:.1f} s)")
        work_track.record("sub-sync", f"Synced {name} after download")
    except Exception as exc:
        log(f"Subtitles: could not sync {name}: {getattr(exc, 'message', None) or exc}")


def download(cfg, item, result, log=None, background=False):
    """Save one search result beside the video. Returns (file name, downloads left today or None).

    With Sync after download on, a subtitle that was not made for this exact file is lined up with the audio.
    A manual download does that in the background; a scan does it before it moves on."""
    if not item.get("path"):
        raise AppError("This item has no file on disk", 400)
    destination = sidecar_path(item["path"], result["language"], result["hearing_impaired"], cfg)
    if os.path.exists(destination):
        raise AppError(f"{os.path.basename(destination)} already exists", 409)
    writes.check(destination)
    token, base = login(cfg)
    found = credentials(cfg)
    data = _request("POST", f"https://{base}/api/v1/download", key=found["key"], token=token,
                    body={"file_id": int(result["file_id"]), "sub_format": "srt"})
    link = str((data or {}).get("link") or "")
    if not link:
        raise AppError("OpenSubtitles did not return a download link", 502)
    try:
        _pause()
        response = httpx.get(link, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise AppError(f"The subtitle could not be downloaded ({exc.__class__.__name__})", 502) from exc
    if response.status_code >= 400 or not response.content:
        raise AppError(f"The subtitle download answered {response.status_code}", 502)
    writes.atomic_write(destination, response.content)
    try:
        subtitles.normalize_text(destination, cfg.get("sub_line_endings", "lf"))
    except OSError:
        pass
    from curator.video import store

    store.refresh_external_subs(item["path"])
    from curator.video import work_track

    work_track.record("sub-download", f"Subtitle saved: {os.path.basename(destination)}")
    remaining = data.get("remaining") if isinstance(data, dict) else None
    if remaining is not None:
        logger.info("OpenSubtitles downloads left today: %s", remaining)
        try:
            from curator import outbound

            outbound.quota_low(remaining)
        except Exception:
            logger.exception("could not check the subtitle quota for a notification")
    if cfg.get("subs_sync_after") and not result.get("hash_match"):
        from curator.video import sub_auto

        say = log or (lambda text: logger.info(text))
        if sub_auto.available():
            if background:
                threading.Thread(target=_sync_after, args=(cfg, item["path"], destination, say), name="sub-sync-after", daemon=True).start()
            else:
                _sync_after(cfg, item["path"], destination, say)
        else:
            say("Subtitles: alass is not installed, so the new subtitle was not synced")
    return os.path.basename(destination), remaining


# ======================================================================================
# automatic download
# ======================================================================================

def auto_item(cfg, kind, item_id, log):
    """Download the best subtitle for each wanted language the file lacks. Returns (saved, downloads left or None)."""
    item = target(kind, item_id)
    if not item.get("path") or not os.path.isfile(item["path"]):
        return 0, None
    wanted = wanted_languages(cfg)
    have = present_languages(item)
    missing = [(code, tag) for code, tag in wanted if code not in have]
    if not missing:
        return 0, None
    hearing = cfg.get("subs_hearing_impaired", "exclude")
    results = search(cfg, item, [tag for _code, tag in missing], hearing)
    saved, remaining = 0, None
    label = item["title"] if kind == "movie" else f"{item['title']} S{int(item['season'] or 0):02d}E{int(item['episode'] or 0):02d}"
    for _code, tag in missing:
        pick = best_for(results, tag, hearing)
        if not pick:
            log(f"Subtitles: none found for {label} in {tag}")
            continue
        try:
            name, left = download(cfg, item, pick, log=log)
            if left is not None:
                remaining = left
        except QuotaError:
            raise
        except AppError as exc:
            log(f"Subtitles: {label} ({tag}): {exc}")
            continue
        saved += 1
        log(f"Subtitles: saved {name}")
    return saved, remaining
