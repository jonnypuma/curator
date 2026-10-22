"""Tell Kodi, Emby, Jellyfin and Plex that the library changed.

Kodi library updates wait for their own timer, one for video and one for music, so a burst of imports
or tag writes becomes one list of scans. Each new request restarts that timer. Kodi runs one scan at
a time and drops any other scan sent while one is running, so each folder is sent on its own, and the
next folder waits until Kodi reports the current scan has finished. Kodi on-screen notifications can
go to a different Kodi instance than the library updates.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from urllib.parse import urlsplit

import requests

from curator import automation

logger = logging.getLogger(__name__)
TIMEOUT = 15

_guard = threading.Lock()
_pending = {"video": None, "music": None}
_busy = {"video": False, "music": False}
_worker = {"video": False, "music": False}
_queue = {"video": deque(), "music": deque()}
_jobs = {"video": None, "music": None}
_job_log = {"video": [], "music": []}
# Kodi can take a while to raise Library.IsScanningVideo after it accepts a scan.
_POLL_SECONDS = 5
_SCAN_START_GRACE = 90


def _jsonrpc_url(host):
    text = str(host or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    if not parts.port and not parts.path.strip("/"):
        text = f"{parts.scheme}://{parts.hostname}:8080"
    text = text.rstrip("/")
    return text if text.endswith("/jsonrpc") else f"{text}/jsonrpc"


def kodi_call(host, user, password, method, params=None, timeout=None):
    """One JSON-RPC call. Returns the result, or raises RuntimeError with a readable reason."""
    url = _jsonrpc_url(host)
    if not url:
        raise RuntimeError("No Kodi host is set")
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params:
        body["params"] = params
    auth = (user, password) if user else None
    try:
        response = requests.post(url, json=body, auth=auth, timeout=TIMEOUT if timeout is None else timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"Kodi at {url} did not answer: {exc}") from exc
    if response.status_code == 401:
        raise RuntimeError("Kodi refused the user name or password")
    if response.status_code >= 400:
        raise RuntimeError(f"Kodi answered HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Kodi did not answer with JSON-RPC") from exc
    if data.get("error"):
        raise RuntimeError(f"Kodi: {data['error'].get('message') or data['error']}")
    return data.get("result")


KODI_SCHEMES = ("nfs://", "smb://", "dav://", "davs://", "ftp://", "ftps://", "http://", "https://", "upnp://", "special://")


def kodi_directories(local_dirs, mappings):
    """Kodi paths for the changed folders, or None when any folder has no mapping (then Kodi scans everything)."""
    if not local_dirs:
        return None
    found = []
    for folder in sorted(set(local_dirs)):
        target = _kodi_folder(folder, mappings)
        if target is None:
            return None
        found.append(target)
    return found


def _folder_name(directory):
    text = str(directory or "").strip().rstrip("/\\")
    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _scan_title(items, directory):
    """Names for the webhook log. A folder name fills in when no title matches it."""
    labels = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        labels.append(text)
    folder = _folder_name(directory)
    if folder:
        matched = [label for label in labels if label.lower() == folder.lower()]
        if matched:
            labels = matched
    if labels:
        shown = ", ".join(labels[:8])
        extra = len(labels) - 8
        if extra > 0:
            shown += f" and {extra} more"
        return shown
    if folder:
        return folder
    return "Full library"


def _items_for_folder(items, directory, alone):
    """One folder keeps every title. Several folders keep the title that matches that folder."""
    if alone:
        return list(items or [])
    folder = _folder_name(directory).lower()
    if not folder:
        return []
    return [item for item in items or [] if str(item or "").strip().lower() == folder]


def _activity(message, outcome="done", path="", title=""):
    """Write a Kodi update into the same alert list as the webhook queue."""
    logger.info("%s", message)
    try:
        from curator import ingest
        ingest._event("kodi", "Update", title or "", path or "", outcome, message)
    except Exception:
        logger.exception("could not record the Kodi update")


def _job_note(kind, message, status=None, create=True):
    """One Jobs row per library kind. Later steps update that row until the scan finishes."""
    from resonance import jobs

    with _guard:
        lines = _job_log[kind]
        if message and (not lines or lines[-1] != message):
            lines.append(message)
        log = "\n".join(lines[-30:])
        job_id = _jobs[kind]
        if status:
            _jobs[kind] = None
            _job_log[kind] = []
    try:
        if status:
            if not job_id:
                if not create:
                    return
                job_id = jobs.begin_work(f"kodi-{kind}", message, 1)["id"]
            jobs.finish_work(job_id, status, message, log=log)
            return
        if job_id:
            jobs.touch_work(job_id, 0, message, log)
            return
        row = jobs.begin_work(f"kodi-{kind}", message, 1)
    except Exception:
        logger.exception("could not record the Kodi job")
        return
    with _guard:
        if _jobs[kind] is None:
            _jobs[kind] = row["id"]
            return
        job_id = _jobs[kind]
    try:
        jobs.finish_work(row["id"], "completed", message, 1, log)
        jobs.touch_work(job_id, 0, message, log)
    except Exception:
        logger.exception("could not record the Kodi job")


def _side_enabled(cfg, kind):
    """True when the Kodi switch for this library is on. An old single switch covers both."""
    key = "kodi_music_enabled" if kind == "music" else "kodi_video_enabled"
    if key in cfg:
        return bool(cfg.get(key))
    return bool(cfg.get("kodi_library_enabled", True))


def _skip_reason(cfg, kind):
    noun = "video" if kind == "video" else "music"
    if not _side_enabled(cfg, kind):
        return f"Kodi {noun} library update skipped. {noun.capitalize()} library updates are turned off."
    return f"Kodi {noun} library update skipped. No Kodi library address is set."


def request(kind, folders=(), clean=False, message=None, queue_ids=(), front=False, media=None, items=()):
    """Hand changed folders to the library queue. One job per enabled player.

    The webhook row is removed by the caller without waiting for any player.
    front and queue_ids are unused.
    """
    del queue_ids, front
    if kind not in ("video", "music"):
        return
    _, cfg = automation.current()
    from curator.library_queue import handoff

    media_name = media or ("music" if kind == "music" else "video")
    notice = notice_kind(kind, message)
    if notice:
        announce(notice, message)
    if not handoff(media_name, folders, clean, message or "", items):
        text = _skip_reason(cfg, kind)
        _activity(text, "noted")
        _job_note(kind, text, status="completed")
    return


def run_kodi(kind, folders=(), clean=False, message=None, items=()):
    """Scan the queued folders one at a time, waiting until Kodi reports each one finished."""
    del message
    if kind not in ("video", "music"):
        return
    _, cfg = automation.current()
    if not _library_target(cfg):
        text = _skip_reason(cfg, kind)
        _activity(text, "noted")
        _job_note(kind, text, status="completed")
        return
    if kind == "video" or folders:
        jobs = jobs_for_folders(folders, {}, cfg.get("kodi_paths") or [], clean=bool(clean))
    else:
        jobs = [{"directory": None, "clean": False, "ids": []}]
    alone = len(jobs) == 1
    for job in jobs:
        chosen = _items_for_folder(items, job.get("directory"), alone)
        job["title"] = _scan_title(chosen, job.get("directory"))
    noun = "video" if kind == "video" else "music"
    count = len(jobs)
    where = "the full library" if count == 1 and jobs[0]["directory"] is None else f"{count} folder{'s' if count != 1 else ''}, one at a time"
    text = f"Kodi {noun} library update is running. {where[0].upper()}{where[1:]}."
    summary = ", ".join(job["title"] for job in jobs if job.get("title"))
    path = (jobs[0].get("directory") or "") if count == 1 else ""
    _activity(text, "done", path, summary)
    _job_note(kind, text)
    for job in jobs:
        _run_one(kind, job)
    _job_note(kind, f"Kodi {noun} library scan finished.", status="completed", create=False)
    if not folders or (count == 1 and jobs[0]["directory"] is None):
        return f"Kodi finished scanning the {noun} library."
    return f"Kodi updated {len(folders)} folder{'s' if len(folders) != 1 else ''}."


def _pause():
    """Wait one poll, and stop when this library job was cancelled."""
    from curator.library_queue import Cancelled, aborted

    if aborted():
        raise Cancelled()
    time.sleep(_POLL_SECONDS)
    if aborted():
        raise Cancelled()


def run_library(player, media, full, paths, clean=False, items=()):
    """Run one player's library job on that player's own thread."""
    from curator.library_queue import Cancelled

    if player == "kodi":
        kind = "music" if media == "music" else "video"
        noun = "music" if kind == "music" else "video"
        try:
            if full:
                _run_one(kind, {"directory": None, "clean": bool(clean) and kind == "video", "ids": [], "title": _scan_title(items, None)})
            else:
                named = list(paths or [])
                alone = len(named) == 1
                for path in named:
                    folder = path if str(path).endswith(("/", "\\")) else f"{path}/"
                    chosen = _items_for_folder(items, folder, alone)
                    _run_one(kind, {
                        "directory": folder,
                        "clean": False,
                        "ids": [],
                        "title": _scan_title(chosen, folder),
                    })
                if clean and kind == "video":
                    _send_clean(kind)
        except Cancelled:
            _job_note(kind, f"Kodi {noun} library update cancelled.", status="completed", create=False)
            raise
        except Exception:
            _job_note(kind, f"Kodi {noun} library scan failed.", status="failed", create=False)
            raise
        _job_note(kind, f"Kodi {noun} library scan finished.", status="completed", create=False)
        if full or not paths:
            return f"Kodi finished scanning the {noun} library."
        count = len(paths)
        return f"Kodi updated {count} folder{'s' if count != 1 else ''}."
    if player == "navidrome":
        from resonance.webhooks import send_navidrome_scan

        return send_navidrome_scan()
    return _run_server(player, media, full, paths)


def _run_server(player, media, full, paths):
    _, cfg = automation.current()
    label = {"emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex"}.get(player, player)
    try:
        if player == "plex":
            return _plex_job(cfg, media, full, paths)
        if player in {"emby", "jellyfin"}:
            return _server_job(cfg, player, label, media, full, paths)
    except (RuntimeError, requests.RequestException) as exc:
        raise RuntimeError(f"{label} library update failed. {exc}") from exc
    return ""


def _auth_headers(player, token):
    """Jellyfin 10.11 and later reject the old X-Emby-Token header with HTTP 401.

    Sending that header together with Authorization also fails, so Jellyfin gets only the MediaBrowser header. Emby still uses X-Emby-Token.
    """
    key = str(token or "").strip().replace('"', "")
    if player == "jellyfin":
        return {
            "Authorization": (
                f'MediaBrowser Token="{key}", Client="Curator", Device="Curator", '
                'DeviceId="curator", Version="1"'
            ),
        }
    return {"X-Emby-Token": key}


def _refresh_kinds(media):
    """Libraries a full scan of this media type is allowed to touch."""
    if media == "music":
        return {"music"}
    if media == "movies":
        return {"movies"}
    if media == "tv":
        return {"tv"}
    return {"movies", "tv"}


def _server_job(cfg, player, label, media, full, paths):
    url = _base(cfg[f"{player}_url"])
    headers = _auth_headers(player, cfg[f"{player}_token"])
    if full or not paths:
        folders = _virtual_folders(cfg, player)
        wanted = _refresh_kinds(media)
        chosen = [row for row in (folders or []) if row.get("kind") in wanted and row.get("id")]
        if not chosen and (folders is not None or media == "music"):
            noun = "music" if wanted == {"music"} else "video"
            return f"{label} has no {noun} library."
        if chosen:
            for row in chosen:
                response = requests.post(
                    f"{url}/Items/{row['id']}/Refresh",
                    headers=headers,
                    params={
                        "Recursive": "true",
                        "MetadataRefreshMode": "Default",
                        "ImageRefreshMode": "Default",
                        "ReplaceAllMetadata": "false",
                        "ReplaceAllImages": "false",
                    },
                    timeout=TIMEOUT,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"{label} answered HTTP {response.status_code}")
            _wait_library_task(cfg, player)
            noun = "music" if wanted == {"music"} else "video"
            return f"{label} finished scanning the {noun} library."
        response = requests.post(f"{url}/Library/Refresh", headers=headers, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise RuntimeError(f"{label} answered HTTP {response.status_code}")
        _wait_library_task(cfg, player)
        return f"{label} finished scanning the library."
    response = requests.post(
        f"{url}/Library/Media/Updated",
        headers=headers,
        json={"Updates": [{"Path": path, "UpdateType": "Modified"} for path in paths]},
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{label} answered HTTP {response.status_code}")
    return f"{label} updated {len(paths)} folder{'s' if len(paths) != 1 else ''}."


def _library_task_running(cfg, player):
    """True while Emby or Jellyfin reports the library scan task running. None when the server does not say."""
    try:
        response = requests.get(
            f"{_base(cfg[f'{player}_url'])}/ScheduledTasks",
            headers=_auth_headers(player, cfg[f"{player}_token"]),
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None
    tasks = response.json() if response.content else []
    if isinstance(tasks, dict):
        tasks = tasks.get("Items") or []
    for task in tasks or []:
        name = str(task.get("Name") or "").lower()
        key = str(task.get("Key") or "").lower()
        if "scan media library" in name or "refreshlibrary" in key:
            return str(task.get("State") or "").lower() == "running"
    return None


def _wait_library_task(cfg, player):
    """Wait until the library scan task is idle again. A task that never starts does not wait."""
    deadline = time.monotonic() + _SERVER_START_GRACE
    saw = False
    while True:
        running = _library_task_running(cfg, player)
        if running:
            saw = True
        elif saw or running is None or time.monotonic() > deadline:
            return
        _pause()


_SERVER_START_GRACE = 45


def _kodi_folder(folder, mappings):
    """Kodi path for one local folder, with a trailing slash. None when nothing maps it."""
    if not folder:
        return None
    text = str(folder).strip()
    if any(text.startswith(scheme) for scheme in KODI_SCHEMES):
        return text.rstrip("/") + "/"
    clean = automation.clean_path(text)
    ranked = sorted(mappings or [], key=lambda row: len(automation.clean_path(row.get("local") or "")), reverse=True)
    for row in ranked:
        kodi_root = str(row.get("kodi") or row.get("remote") or "").rstrip("/")
        if kodi_root and (clean == kodi_root or clean.startswith(kodi_root + "/")):
            return clean.rstrip("/") + "/"
    for row in ranked:
        local = automation.clean_path(row.get("local") or "")
        kodi_target = str(row.get("kodi") or row.get("remote") or "").rstrip("/")
        if not local or not kodi_target:
            continue
        if clean == local or clean.startswith(local + "/"):
            rest = clean[len(local):]
            return (kodi_target + rest).rstrip("/") + "/"
    return None


def jobs_for_folders(folders, folder_ids, mappings, clean=False):
    """One scan per Kodi folder, carrying the webhook rows that belong to it.

    A folder with no mapping becomes one full-library scan that carries every id.
    """
    groups = {}
    order = []
    for folder in sorted(set(folders or [])):
        target = _kodi_folder(folder, mappings)
        if target is None:
            return [{"directory": None, "clean": bool(clean), "ids": _flat_ids(folder_ids)}]
        if target not in groups:
            order.append(target)
            groups[target] = []
        groups[target].extend(list((folder_ids or {}).get(folder) or []))
    jobs = [{"directory": target, "clean": False, "ids": groups[target]} for target in order]
    if not jobs:
        jobs = [{"directory": None, "clean": False, "ids": _flat_ids(folder_ids)}]
    if clean:
        jobs[-1]["clean"] = True
    return jobs


def _flat_ids(folder_ids):
    found = []
    for values in (folder_ids or {}).values():
        found.extend(values or [])
    return found


def scan_jobs(directories, clean=False):
    """One Kodi scan per folder. None means a single full-library scan. Clean stays on the last scan."""
    if directories is None:
        steps = [None]
    else:
        steps = []
        seen = set()
        for directory in directories:
            if directory in seen:
                continue
            seen.add(directory)
            steps.append(directory)
        if not steps:
            steps = [None]
    jobs = [{"directory": directory, "clean": False} for directory in steps]
    if clean and jobs:
        jobs[-1]["clean"] = True
    return jobs


def _remember_ids(pending, queue_ids):
    bucket = pending.setdefault("ids", {})
    for folder, item_id in queue_ids or ():
        if not item_id:
            continue
        key = folder or ""
        found = bucket.setdefault(key, [])
        if item_id not in found:
            found.append(item_id)


def _finish_queue(ids):
    """Drop webhook rows whose Kodi scan has finished. Missing rows are left alone."""
    if not ids:
        return
    try:
        from curator import ingest
        ingest.complete_running(ids)
    except Exception:
        logger.exception("could not update the webhook queue")


def _fire(kind):
    with _guard:
        item = _pending[kind]
        _pending[kind] = None
    if not item:
        return
    _, cfg = automation.current()
    if not _library_target(cfg):
        _finish_queue(_flat_ids(item.get("ids")))
        return
    if kind == "video":
        jobs = jobs_for_folders(item["folders"], item.get("ids"), cfg["kodi_paths"], clean=bool(item.get("clean")))
    else:
        jobs = [{"directory": None, "clean": False, "ids": _flat_ids(item.get("ids"))}]
    noun = "video" if kind == "video" else "music"
    count = len(jobs)
    where = "the full library" if count == 1 and jobs[0]["directory"] is None else f"{count} folder{'s' if count != 1 else ''}, one at a time"
    message = f"Kodi {noun} library update is queued. {where[0].upper()}{where[1:]}."
    _activity(message)
    _job_note(kind, message)
    refresh_servers(cfg, item.get("folders") or [])
    texts = [text for text in item.get("messages") or [] if text]
    if texts:
        joined = "; ".join(texts[:3]) + (f" (+{len(texts) - 3} more)" if len(texts) > 3 else "")
        notice = notice_kind(kind, joined)
        if notice:
            announce(notice, joined)
    _enqueue(kind, jobs)


def _enqueue(kind, jobs):
    with _guard:
        waiting = _worker[kind]
        _queue[kind].extend(jobs)
        _worker[kind] = True
        _busy[kind] = True
    if waiting:
        noun = "video" if kind == "video" else "music"
        message = f"Kodi {noun} library update is queued behind the scan that is already running."
        _activity(message)
        _job_note(kind, message)
        return
    threading.Thread(target=_drain, args=(kind,), name=f"kodi-{kind}", daemon=True).start()


def _drain(kind):
    """Send each queued scan only after Kodi reports the one in front of it has finished."""
    noun = "video" if kind == "video" else "music"
    try:
        while True:
            with _guard:
                if not _queue[kind]:
                    _busy[kind] = False
                    _worker[kind] = False
                    break
                job = _queue[kind].popleft()
            _run_one(kind, job)
        _job_note(kind, f"Kodi {noun} library scan finished.", status="completed", create=False)
    except Exception:
        logger.exception("Kodi %s scan queue failed", kind)
        _job_note(kind, f"Kodi {noun} library scan queue failed.", status="failed")
        with _guard:
            _busy[kind] = False
            _worker[kind] = False



def _local_from_kodi(kodi_path, mappings):
    """Container path for a path Kodi reported, or "" when nothing maps it.

    Inverse of _kodi_folder, so a file Kodi stored as nfs://host/share/x/y.mkv (or whatever
    the user mapped it to) can be checked against the live filesystem the container sees.
    Longest-match wins, so a nested mapping beats a parent one.
    """
    clean = str(kodi_path or "").replace("\\", "/").strip()
    if not clean:
        return ""
    ranked = sorted(mappings or [], key=lambda row: len(str(row.get("kodi") or row.get("remote") or "")), reverse=True)
    for row in ranked:
        kodi_root = str(row.get("kodi") or row.get("remote") or "").rstrip("/")
        local_root = automation.clean_path(row.get("local") or "")
        if not kodi_root or not local_root:
            continue
        if clean == kodi_root or clean.startswith(kodi_root + "/"):
            return local_root + clean[len(kodi_root):]
    return ""


def _prune_stale_kodi(kind, cfg, directory):
    """Remove Kodi library entries whose file is gone from disk, before scanning this folder.

    Kodi can hold an old row for an episode, movie or album after the file was upgraded or
    renamed outside Kodi's own view: the scan that follows writes the new file but leaves
    the stale row alongside it. Querying by path prefix catches every stale row in the
    folder we are about to scan, regardless of what identity (TVDB id, TMDB id, artist +
    album) brought it in.

    Safe by design:
      - Only an entry whose `file` property Kodi gave us is considered.
      - That path is translated through kodi_paths back to a container path. If no mapping
        exists we leave the entry alone - we cannot verify the file is gone, so we must not
        remove.
      - An entry is removed only when the file does not exist on disk. An entry whose file
        is still there (same path, or a sibling in the same folder) stays.
      - Failure anywhere is logged and swallowed, so a stale-check problem never blocks
        the scan that follows.
    """
    if not directory or not cfg.get("kodi_paths"):
        return 0
    target = _library_target(cfg)
    if not target:
        return 0
    prefix = str(directory).replace("\\", "/")
    if not prefix.endswith("/"):
        prefix = prefix + "/"
    try:
        if kind == "video":
            removed = _prune_stale_video(target, cfg["kodi_paths"], prefix)
        elif kind == "music":
            removed = _prune_stale_music(target, cfg["kodi_paths"], prefix)
        else:
            return 0
    except RuntimeError as exc:
        logger.warning("Kodi stale-prune skipped for %s: %s", directory, exc)
        return 0
    except Exception:
        logger.exception("Kodi stale-prune failed for %s", directory)
        return 0
    if removed:
        logger.info("Kodi stale-prune removed %d entrie(s) under %s", removed, directory)
    return removed


def _prune_stale_video(target, mappings, prefix):
    """Remove stale episode and movie rows whose file is no longer on disk."""
    removed = 0
    for method, remove_method, key_id, media_key in (
        ("VideoLibrary.GetEpisodes", "VideoLibrary.RemoveEpisode", "episodeid", "episodes"),
        ("VideoLibrary.GetMovies", "VideoLibrary.RemoveMovie", "movieid", "movies"),
    ):
        response = kodi_call(*target, method, {
            "filter": {"field": "path", "operator": "startswith", "value": prefix},
            "properties": ["file"],
        })
        rows = ((response or {}).get("result") or {}).get(media_key) or []
        for row in rows:
            kodi_file = str(row.get("file") or "")
            if not kodi_file:
                continue
            local = _local_from_kodi(kodi_file, mappings)
            if not local:
                continue
            if os.path.isfile(local):
                continue
            item_id = row.get(key_id)
            if item_id is None:
                continue
            try:
                kodi_call(*target, remove_method, {key_id: int(item_id)})
                removed += 1
                logger.info("Removed stale Kodi %s %s (%s)", media_key[:-1], item_id, kodi_file)
            except RuntimeError as exc:
                logger.warning("Could not remove stale Kodi %s %s: %s", media_key[:-1], item_id, exc)
    return removed


def _prune_stale_music(target, mappings, prefix):
    """Remove stale song rows (and the album, when it empties out) whose file is gone.

    Albums are judged indirectly: a song is the thing with a `file` property. When every
    song in an album has been removed, Kodi.AudioLibrary.Clean would drop the album; doing
    it here keeps the follow-up scan clean rather than relying on a later Clean pass.
    """
    removed_songs = 0
    response = kodi_call(*target, "AudioLibrary.GetSongs", {
        "filter": {"field": "path", "operator": "startswith", "value": prefix},
        "properties": ["file", "albumid"],
    })
    songs = ((response or {}).get("result") or {}).get("songs") or []
    stale_album_ids = set()
    for song in songs:
        kodi_file = str(song.get("file") or "")
        if not kodi_file:
            continue
        local = _local_from_kodi(kodi_file, mappings)
        if not local or os.path.isfile(local):
            continue
        song_id = song.get("songid")
        if song_id is None:
            continue
        try:
            kodi_call(*target, "AudioLibrary.RemoveSong", {"songid": int(song_id)})
            removed_songs += 1
            if song.get("albumid"):
                stale_album_ids.add(int(song["albumid"]))
            logger.info("Removed stale Kodi song %s (%s)", song_id, kodi_file)
        except RuntimeError as exc:
            logger.warning("Could not remove stale Kodi song %s: %s", song_id, exc)
    # An album Kodi still holds with no remaining songs is itself stale.
    for album_id in stale_album_ids:
        try:
            check = kodi_call(*target, "AudioLibrary.GetSongs", {
                "filter": {"field": "albumid", "operator": "is", "value": str(album_id)},
                "limits": {"start": 0, "end": 1},
            })
            still = ((check or {}).get("result") or {}).get("limits", {}).get("total", 0)
        except RuntimeError:
            continue
        if still:
            continue
        try:
            kodi_call(*target, "AudioLibrary.RemoveAlbum", {"albumid": album_id})
            logger.info("Removed stale Kodi album %s (now empty)", album_id)
        except RuntimeError as exc:
            logger.warning("Could not remove stale Kodi album %s: %s", album_id, exc)
    return removed_songs


def _run_one(kind, job):
    where = job["directory"] or "the full library"
    path = job.get("directory") or ""
    title = job.get("title") or _scan_title(job.get("items"), job.get("directory"))
    for attempt in (1, 2):
        if _kodi_scanning(kind):
            noun = "video" if kind == "video" else "music"
            message = f"Kodi is still scanning the {noun} library. {where} waits until that scan finishes."
            _activity(message, "done", path, title)
            _job_note(kind, message)
            _wait_idle(kind)
        if attempt == 1:
            _prune_stale_kodi(kind, automation.current()[1], job.get("directory"))
        if not _send_scan(kind, job["directory"], title):
            if attempt == 1:
                _pause()
                continue
            break
        if _wait_started(kind):
            _wait_idle(kind)
            break
        if attempt == 1:
            message = f"Kodi has not reported a scan for {where}. It stays queued and will be asked again."
            _activity(message, "done", path, title)
            _job_note(kind, message)
            continue
        message = f"Kodi did not report a scan for {where}. The rest of the queue will still run."
        _activity(message, "error", path, title)
        _job_note(kind, message)
    _finish_queue(job.get("ids"))
    if job["clean"]:
        _send_clean(kind)


def _wait_idle(kind):
    """Stay here while Kodi reports a scan. A minute without an answer is treated as idle."""
    misses = 0
    while True:
        state = _kodi_scanning(kind)
        if state is False:
            return
        if state is None:
            misses += 1
            if misses >= 12:
                return
        else:
            misses = 0
        _pause()


def _wait_started(kind):
    """True once Kodi reports a scan. Gives the flag _SCAN_START_GRACE seconds to come up."""
    deadline = time.monotonic() + _SCAN_START_GRACE
    while time.monotonic() < deadline:
        if _kodi_scanning(kind):
            return True
        _pause()
    return _kodi_scanning(kind)


def _send_scan(kind, directory, title=""):
    _, cfg = automation.current()
    target = _library_target(cfg)
    noun = "video" if kind == "video" else "music"
    where = directory or "the full library"
    label = title or _scan_title((), directory)
    if not target:
        _job_note(kind, _skip_reason(cfg, kind), status="completed")
        return False
    params = {"showdialogs": False}
    if directory:
        params["directory"] = directory
    method = "VideoLibrary.Scan" if kind == "video" else "AudioLibrary.Scan"
    try:
        kodi_call(*target, method, params)
    except RuntimeError as exc:
        message = f"Kodi {noun} library scan failed for {where}. {exc}"
        _activity(message, "error", directory or "", label)
        _job_note(kind, message)
        return False
    message = f"Kodi is scanning {where}."
    _activity(f"Kodi {noun} library scan sent for {where}.", "done", directory or "", label)
    _job_note(kind, message)
    return True


def clean_kodi(kind):
    """Ask Kodi to clean one library. kind is video or music."""
    _, cfg = automation.current()
    target = _library_target(cfg)
    noun = "video" if kind == "video" else "music"
    if not target:
        raise RuntimeError(_skip_reason(cfg, kind))
    from curator.library_queue import Cancelled

    method = "VideoLibrary.Clean" if kind == "video" else "AudioLibrary.Clean"
    try:
        _wait_idle(kind)
        kodi_call(*target, method, {"showdialogs": False})
    except RuntimeError as exc:
        message = f"Kodi {noun} library clean failed. {exc}"
        _activity(message, "error")
        _job_note(kind, message, status="failed", create=False)
        raise RuntimeError(message) from exc
    except Cancelled:
        _job_note(kind, f"Kodi {noun} library clean cancelled.", status="completed", create=False)
        raise
    message = f"Kodi is cleaning the {noun} library."
    _activity(message)
    _job_note(kind, message)
    if _wait_started(kind):
        _wait_idle(kind)
    _job_note(kind, f"Kodi {noun} library clean finished.", status="completed", create=False)


def clean_after_queue():
    """Clean once. False when more library updates arrived while Kodi was still busy."""
    return _send_clean("video")


def _send_clean(kind):
    _, cfg = automation.current()
    if kind != "video" or not cfg["kodi_clean"]:
        return True
    target = _library_target(cfg)
    if not target:
        return
    _wait_idle(kind)
    from curator import library_queue

    if not library_queue.updates_finished("kodi"):
        return False
    try:
        kodi_call(*target, "VideoLibrary.Clean", {"showdialogs": False})
    except RuntimeError as exc:
        message = f"Kodi video library clean failed. {exc}"
        _activity(message, "error")
        _job_note(kind, message)
        return
    _activity("Kodi is cleaning the video library.")
    _job_note(kind, "Kodi is cleaning the video library.")
    if _wait_started(kind):
        _wait_idle(kind)
    return True


def _kodi_scanning(kind):
    _, cfg = automation.current()
    target = _library_target(cfg)
    if not target:
        return False
    flag = "Library.IsScanningVideo" if kind == "video" else "Library.IsScanningMusic"
    try:
        result = kodi_call(*target, "XBMC.GetInfoBooleans", {"booleans": [flag]})
    except RuntimeError:
        return None
    if not isinstance(result, dict) or flag not in result:
        return None
    return bool(result.get(flag))


def _library_target(cfg):
    if not cfg["kodi_library_host"]:
        return None
    if not (_side_enabled(cfg, "video") or _side_enabled(cfg, "music")):
        return None
    return cfg["kodi_library_host"], cfg["kodi_library_user"], cfg["kodi_library_password"]


def notice_kind(kind, message):
    """Which on-screen message a library hand-off is, or None when it should stay quiet."""
    text = str(message or "").strip().lower()
    if text.startswith("removed"):
        return "removed"
    if kind == "music" and (text.startswith("updated") or text.startswith("added")):
        return "music"
    if kind == "video" and (text.startswith("updated") or text.startswith("added")):
        return "video"
    return None


def announce(kind, message):
    """Show one short message on the players that can display it."""
    text = str(message or "").strip()
    if kind not in {"video", "removed", "music", "failed"} or not text:
        return
    _, cfg = automation.current()
    if cfg.get(f"kodi_notify_{kind}"):
        show_message(cfg, text)
    for player in ("emby", "jellyfin"):
        if cfg.get(f"{player}_on", True) is False:
            continue
        if not cfg.get(f"{player}_notify_{kind}"):
            continue
        try:
            _session_message(player, cfg, text)
        except (RuntimeError, requests.RequestException) as exc:
            logger.info("%s notification: %s", player, exc)


def show_message(cfg, message, title="Curator"):
    if not cfg.get("kodi_notify_host") or not message:
        return
    try:
        kodi_call(cfg["kodi_notify_host"], cfg["kodi_notify_user"], cfg["kodi_notify_password"],
                  "GUI.ShowNotification", {"title": title, "message": message[:200], "displaytime": 8000})
    except RuntimeError as exc:
        logger.info("Kodi notification: %s", exc)


def _can_message(session):
    commands = session.get("SupportedCommands") or []
    if not isinstance(commands, list) or not commands:
        return True
    return any(str(item).lower() == "displaymessage" for item in commands)


def _session_message(player, cfg, message):
    """Show a message on Emby or Jellyfin sessions. Uses the Integrations server and key."""
    label = "Emby" if player == "emby" else "Jellyfin"
    url = _base(cfg.get(f"{player}_url"))
    token = str(cfg.get(f"{player}_token") or "").strip()
    if not url or not token:
        raise RuntimeError(f"Set the {label} address and API key on Integrations first")
    headers = {**_auth_headers(player, token), "Content-Type": "application/json"}
    response = requests.get(f"{url}/Sessions", headers=headers, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(f"{label} answered HTTP {response.status_code}")
    sessions = response.json() if response.content else []
    if not isinstance(sessions, list):
        sessions = []
    chosen = [item for item in sessions if isinstance(item, dict) and item.get("Id") and _can_message(item)]
    if not chosen:
        raise RuntimeError(f"{label} has no sessions that can show a message")
    body = {"Header": "Curator", "Text": str(message)[:200], "TimeoutMs": 8000}
    sent = 0
    for session in chosen:
        posted = requests.post(f"{url}/Sessions/{session['Id']}/Message", headers=headers, json=body, timeout=TIMEOUT)
        if posted.status_code < 400:
            sent += 1
    if not sent:
        raise RuntimeError(f"{label} did not accept the message")
    return sent


def _base(url):
    text = str(url or "").strip().rstrip("/")
    if text and "://" not in text:
        text = f"http://{text}"
    return text


def _mapped_paths(folders, mappings):
    """Server paths for the changed folders. None when any folder has no mapping, so the caller scans everything."""
    if not folders:
        return None
    found = []
    ranked = sorted(mappings or [], key=lambda row: len(automation.clean_path(row.get("local") or "")), reverse=True)
    for folder in folders:
        text = str(folder or "").strip()
        if not text:
            continue
        if any(text.startswith(scheme) for scheme in KODI_SCHEMES):
            if text not in found:
                found.append(text)
            continue
        clean = automation.clean_path(text)
        remote = ""
        for row in ranked:
            local = automation.clean_path(row.get("local") or "")
            base = str(row.get("remote") or row.get("kodi") or "").strip().rstrip("/\\")
            if not local or not base:
                continue
            if clean == local or clean.startswith(local + "/"):
                rest = clean[len(local):]
                slash = "\\" if "\\" in base and "/" not in base else "/"
                remote = base + rest.replace("/", slash)
                break
        if not remote:
            return None
        if remote not in found:
            found.append(remote)
    return found


def _library_post(cfg, url_key, token_key, label, folders=()):
    paths = _mapped_paths(folders, cfg.get(f"{url_key[:-4]}_paths"))
    url = _base(cfg[url_key])
    player = "jellyfin" if "jellyfin" in token_key else "emby"
    headers = _auth_headers(player, cfg[token_key])
    if paths:
        response = requests.post(
            f"{url}/Library/Media/Updated",
            headers=headers,
            json={"Updates": [{"Path": path, "UpdateType": "Modified"} for path in paths]},
            timeout=TIMEOUT,
        )
        detail = f"{label} is scanning {len(paths)} folder{'s' if len(paths) != 1 else ''}."
    else:
        response = requests.post(f"{url}/Library/Refresh", headers=headers, timeout=TIMEOUT)
        detail = f"{label} library refresh sent."
    if response.status_code >= 400:
        raise RuntimeError(f"{label} answered HTTP {response.status_code}")
    return detail


def emby_refresh(cfg, folders=()):
    return _library_post(cfg, "emby_url", "emby_token", "Emby", folders)


def jellyfin_refresh(cfg, folders=()):
    return _library_post(cfg, "jellyfin_url", "jellyfin_token", "Jellyfin", folders)


_KIND_CACHE = {}
_KIND_TTL = 60
_COLLECTION = {
    "movies": "movies",
    "movie": "movies",
    "tvshows": "tv",
    "tv": "tv",
    "show": "tv",
    "music": "music",
    "artist": "music",
}


def _virtual_folders(cfg, player):
    """Emby or Jellyfin libraries. None when the server could not be asked."""
    url = _base(cfg.get(f"{player}_url") or "")
    token = cfg.get(f"{player}_token") or ""
    if not url or not token:
        return None
    try:
        response = requests.get(
            f"{url}/Library/VirtualFolders",
            headers=_auth_headers(player, token),
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        logger.info("%s library list could not be read", player, exc_info=True)
        return None
    if response.status_code >= 400:
        return None
    payload = response.json() if response.content else []
    if isinstance(payload, dict):
        payload = payload.get("Items") or payload.get("VirtualFolders") or []
    rows = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        kind = _COLLECTION.get(str(item.get("CollectionType") or "").lower())
        item_id = str(item.get("ItemId") or item.get("Id") or "")
        if kind and item_id:
            rows.append({"kind": kind, "id": item_id})
    return rows


def hosted_kinds(player, cfg):
    """movies, tv, and music libraries this server actually has. None when it could not be asked."""
    cfg = cfg or {}
    if player not in {"emby", "jellyfin", "plex"}:
        return None
    url = str(cfg.get(f"{player}_url") or "").strip()
    if not url or not str(cfg.get(f"{player}_token") or "").strip():
        return None
    key = (player, url)
    cached = _KIND_CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _KIND_TTL:
        return set(cached[1])
    try:
        if player == "plex":
            kinds = set()
            for section in _plex_sections(cfg):
                kind = _COLLECTION.get(str(section.get("type") or "").lower())
                if kind:
                    kinds.add(kind)
        else:
            folders = _virtual_folders(cfg, player)
            if folders is None:
                return None
            kinds = {row["kind"] for row in folders}
    except (RuntimeError, requests.RequestException):
        logger.info("%s library list could not be read", player, exc_info=True)
        return None
    _KIND_CACHE[key] = (time.monotonic(), set(kinds))
    return set(kinds)


def _plex_sections(cfg):
    response = requests.get(
        f"{_base(cfg['plex_url'])}/library/sections",
        params={"X-Plex-Token": cfg["plex_token"]},
        headers={"Accept": "application/json"},
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Plex answered HTTP {response.status_code}")
    payload = response.json() if response.content else {}
    sections = ((payload.get("MediaContainer") or {}).get("Directory")) or []
    if isinstance(sections, dict):
        sections = [sections]
    return sections


def _plex_section_key(path, sections):
    """The library section whose location is the longest prefix of this path."""
    target = str(path or "").rstrip("/\\")
    winner = ("", "")
    for section in sections:
        locations = section.get("Location") or []
        if isinstance(locations, dict):
            locations = [locations]
        for location in locations:
            root = str((location or {}).get("path") or "").rstrip("/\\")
            if not root:
                continue
            if target == root or target.startswith(root + "/") or target.startswith(root + "\\"):
                if len(root) > len(winner[0]):
                    winner = (root, str(section.get("key") or ""))
    return winner[1]


def plex_refresh(cfg, folders=()):
    paths = _mapped_paths(folders, cfg.get("plex_paths"))
    url = _base(cfg["plex_url"])
    token = cfg["plex_token"]
    if paths:
        sections = _plex_sections(cfg)
        grouped = {}
        for path in paths:
            key = _plex_section_key(path, sections)
            if not key:
                paths = None
                break
            grouped.setdefault(key, []).append(path)
        if paths:
            for key, group in grouped.items():
                for path in group:
                    response = requests.get(
                        f"{url}/library/sections/{key}/refresh",
                        params={"path": path, "X-Plex-Token": token},
                        timeout=TIMEOUT,
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(f"Plex answered HTTP {response.status_code}")
            return f"Plex is scanning {len(paths)} folder{'s' if len(paths) != 1 else ''}."
    response = requests.get(f"{url}/library/sections/all/refresh", params={"X-Plex-Token": token}, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(f"Plex answered HTTP {response.status_code}")
    return "Plex library refresh sent."


def _plex_get(url, token, path, extra):
    params = {"X-Plex-Token": token}
    params.update(extra)
    response = requests.get(f"{url}{path}", params=params, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(f"Plex answered HTTP {response.status_code}")


def _plex_put(url, token, path, extra=None):
    params = {"X-Plex-Token": token}
    params.update(extra or {})
    response = requests.put(f"{url}{path}", params=params, timeout=TIMEOUT)
    if response.status_code >= 400:
        raise RuntimeError(f"Plex answered HTTP {response.status_code}")


def clean_plex(media):
    """Empty the trash on the Plex sections of this media type.

    Plex has no VideoLibrary.Clean equivalent. Emptying a section's trash is the operation
    that removes items whose files are gone, so that is what a Plex clean does here.
    """
    _, cfg = automation.current()
    url = _base(cfg["plex_url"])
    token = cfg["plex_token"]
    if not url or not token:
        return "Plex is not configured."
    sections = _plex_sections(cfg)
    want = {"music": "artist"}.get(media)
    kinds = {want} if want else {"movie", "show"}
    keys = [
        str(section.get("key") or "")
        for section in sections
        if section.get("key") and section.get("type") in kinds
    ]
    if not keys:
        noun = "music" if want else "video"
        return f"Plex has no {noun} library."
    for key in keys:
        _plex_put(url, token, f"/library/sections/{key}/emptyTrash")
    noun = "music" if want else "video"
    return f"Plex emptied the trash on {len(keys)} {noun} section{'s' if len(keys) != 1 else ''}."


def _plex_job(cfg, media, full, paths):
    """Refresh one Plex media type, or the mapped folders, then wait until those sections stop refreshing."""
    url = _base(cfg["plex_url"])
    token = cfg["plex_token"]
    if not full and paths:
        sections = _plex_sections(cfg)
        grouped = {}
        for path in paths:
            key = _plex_section_key(path, sections)
            if not key:
                full = True
                break
            grouped.setdefault(key, []).append(path)
        if not full:
            for key, group in grouped.items():
                for path in group:
                    _plex_get(url, token, f"/library/sections/{key}/refresh", {"path": path})
            _wait_plex(cfg, set(grouped))
            count = len(paths)
            return f"Plex updated {count} folder{'s' if count != 1 else ''}."
    sections = _plex_sections(cfg)
    want = {"movies": "movie", "tv": "show", "music": "artist"}.get(media)
    keys = [str(section.get("key") or "") for section in sections if section.get("key") and (not want or section.get("type") == want)]
    noun = "music" if media == "music" else "video"
    if not keys:
        if want:
            noun = {"movie": "movie", "show": "TV", "artist": "music"}.get(want, media or "library")
            return f"Plex has no {noun} library."
        _plex_get(url, token, "/library/sections/all/refresh", {})
        return "Plex library refresh sent."
    for key in keys:
        _plex_get(url, token, f"/library/sections/{key}/refresh", {})
    _wait_plex(cfg, set(keys))
    return f"Plex finished scanning the {noun} library." if want else "Plex finished scanning the library."


def _plex_busy(cfg, keys):
    try:
        sections = _plex_sections(cfg)
    except (RuntimeError, requests.RequestException):
        return None
    seen = False
    for section in sections:
        if str(section.get("key") or "") not in keys:
            continue
        seen = True
        if section.get("refreshing") in (True, 1, "1"):
            return True
    return False if seen else None


def _wait_plex(cfg, keys):
    """Wait while the chosen sections report refreshing. A flag that never rises does not wait."""
    deadline = time.monotonic() + _SERVER_START_GRACE
    saw = False
    while True:
        busy = _plex_busy(cfg, keys)
        if busy:
            saw = True
        elif saw or busy is None or time.monotonic() > deadline:
            return
        _pause()


_SERVERS = (
    ("Emby", "emby_enabled", "emby_url", "emby_token", emby_refresh),
    ("Jellyfin", "jellyfin_enabled", "jellyfin_url", "jellyfin_token", jellyfin_refresh),
    ("Plex", "plex_enabled", "plex_url", "plex_token", plex_refresh),
)


def _server_enabled(cfg, name):
    """True when the player is enabled and its video switch or its music switch is on."""
    if cfg.get(f"{name}_on", True) is False:
        return False
    video = f"{name}_video_enabled"
    music = f"{name}_music_enabled"
    if video in cfg or music in cfg:
        return bool(cfg.get(video)) or bool(cfg.get(music))
    return bool(cfg.get(f"{name}_enabled", True))


def _ready_servers(cfg):
    """Enabled players that have an address and a key."""
    return [
        (name, call)
        for name, enabled, url_key, token_key, call in _SERVERS
        if _server_enabled(cfg, enabled[:-8]) and cfg.get(url_key) and cfg.get(token_key)
    ]


def refresh_servers(cfg, folders=()):
    """Ask every enabled player to scan. The calls run together and do not wait for Kodi."""
    ready = _ready_servers(cfg)
    if not ready:
        return

    def send(name, call):
        try:
            detail = call(cfg, folders)
        except (RuntimeError, requests.RequestException) as exc:
            _player_event(name, f"{name} library refresh failed. {exc}", "error")
            return
        _player_event(name, detail or f"{name} library refresh sent.")

    for name, call in ready:
        threading.Thread(target=send, args=(name, call), name=f"library-{name.lower()}", daemon=True).start()


def _player_event(name, message, outcome="done"):
    logger.info("%s", message)
    try:
        from curator import ingest
        ingest._event(name.lower(), "Update", "", "", outcome, message)
    except Exception:
        logger.exception("could not record the %s update", name)


def _apply_draft(cfg, pairs):
    """Copy non-empty form values over the saved settings."""
    for key, value in pairs:
        text = str(value or "").strip()
        if text:
            cfg[key] = text


def test(target, draft=None):
    """Check one connection from the settings screen. Returns a short success message or raises RuntimeError."""
    _, cfg = automation.current()
    cfg = dict(cfg)
    draft = draft or {}
    if target == "kodi_library":
        _apply_draft(cfg, (
            ("kodi_library_host", draft.get("url")),
            ("kodi_library_user", draft.get("user")),
            ("kodi_library_password", draft.get("secret")),
        ))
    elif target == "kodi_notify":
        _apply_draft(cfg, (
            ("kodi_notify_host", draft.get("url")),
            ("kodi_notify_user", draft.get("user")),
            ("kodi_notify_password", draft.get("secret")),
        ))
    elif target in {"jellyfin", "jellyfin_notify"}:
        _apply_draft(cfg, (("jellyfin_url", draft.get("url")), ("jellyfin_token", draft.get("secret"))))
    elif target in {"emby", "emby_notify"}:
        _apply_draft(cfg, (("emby_url", draft.get("url")), ("emby_token", draft.get("secret"))))
    elif target == "plex":
        _apply_draft(cfg, (("plex_url", draft.get("url")), ("plex_token", draft.get("secret"))))
    if target == "kodi_library":
        if not cfg["kodi_library_host"]:
            raise RuntimeError("Set the Kodi library host first")
        version = kodi_call(cfg["kodi_library_host"], cfg["kodi_library_user"], cfg["kodi_library_password"],
                            "Application.GetProperties", {"properties": ["version", "name"]}) or {}
        return f"Connected to {version.get('name') or 'Kodi'} {_kodi_version(version)}".strip()
    if target == "kodi_notify":
        if not cfg["kodi_notify_host"]:
            raise RuntimeError("Set the Kodi notification host first")
        kodi_call(cfg["kodi_notify_host"], cfg["kodi_notify_user"], cfg["kodi_notify_password"],
                  "GUI.ShowNotification", {"title": "Curator", "message": "Test notification", "displaytime": 5000})
        return "Kodi showed the test notification"
    if target in {"jellyfin", "emby"}:
        label = "Emby" if target == "emby" else "Jellyfin"
        url = cfg.get(f"{target}_url")
        token = cfg.get(f"{target}_token")
        if not url or not token:
            raise RuntimeError(f"Set the {label} address and API key first")
        try:
            response = requests.get(f"{_base(url)}/System/Info",
                                    headers=_auth_headers(target, token), timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise RuntimeError(f"{label} did not answer: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"{label} answered HTTP {response.status_code}")
        info = response.json() if response.content else {}
        return f"Connected to {info.get('ServerName') or label} {info.get('Version') or ''}".strip()
    if target == "plex":
        if not cfg["plex_url"] or not cfg["plex_token"]:
            raise RuntimeError("Set the Plex address and token first")
        try:
            response = requests.get(f"{_base(cfg['plex_url'])}/library/sections",
                                    params={"X-Plex-Token": cfg["plex_token"]}, timeout=TIMEOUT,
                                    headers={"Accept": "application/json"})
        except requests.RequestException as exc:
            raise RuntimeError(f"Plex did not answer: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Plex answered HTTP {response.status_code}")
        return "Connected to Plex"
    if target in {"emby_notify", "jellyfin_notify"}:
        player = "emby" if target == "emby_notify" else "jellyfin"
        label = "Emby" if player == "emby" else "Jellyfin"
        try:
            sent = _session_message(player, cfg, "Test notification")
        except requests.RequestException as exc:
            raise RuntimeError(f"{label} did not answer: {exc}") from exc
        return f"{label} showed the test notification on {sent} session{'s' if sent != 1 else ''}"
    if target == "navidrome":
        from resonance import webhooks
        from resonance.settings import load as load_settings

        saved = dict(load_settings())
        _apply_draft(saved, (
            ("webhook_navidrome", draft.get("url")),
            ("webhook_navidrome_user", draft.get("user")),
            ("webhook_navidrome_key", draft.get("secret")),
        ))
        method, url, headers = webhooks.target("navidrome", saved)
        if not url:
            raise RuntimeError("Set the Navidrome address first")
        if "u=" not in url or "t=" not in url:
            raise RuntimeError("Set the Navidrome user name and password first")
        try:
            response = requests.request(method, url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise RuntimeError(f"Navidrome did not answer: {exc}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Navidrome answered HTTP {response.status_code}")
        problem = webhooks.subsonic_error(response)
        if problem:
            raise RuntimeError(problem)
        return "Navidrome accepted the scan"
    raise RuntimeError("Unknown connection")


def _kodi_version(result):
    version = result.get("version") or {}
    if version.get("major") is None:
        return ""
    return f"{version.get('major')}.{version.get('minor', 0)}"
