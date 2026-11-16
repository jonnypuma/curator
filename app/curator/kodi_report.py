"""The Kodi report: Kodi's video library side by side with Curator's, by file.

Kodi lists its movies and episodes with the file of each (paged, so a large library is read in steps). Every file is
translated through Settings, Integrations, Kodi paths into the path Curator sees, then compared:

- missing: Kodi has an entry whose file is not on disk. A Kodi library clean removes it.
- not_indexed: Kodi has the file and it is on disk, but Curator has no movie or episode for it.
- not_in_kodi: Curator has the file but Kodi has no entry for it. A scan of that folder in Kodi adds it.
- unmapped: Kodi paths no Kodi path row translates (they cannot be checked), and Curator folders no row reaches (Kodi
  cannot be asked to scan them on their own).

Only reading happens here; Clean and Scan in Kodi are separate requests. A file under a library folder that is not
mounted is never called missing, and Curator files under such a folder are left out, so an offline drive shows
nothing. Music is not part of it: Kodi lists music by song, which for a large library is slow on Kodi's side.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

PAGE = 2000
EXAMPLES = 500           # rows kept per list; the counts are always complete
_lock = threading.Lock()
_state = {"status": "idle", "message": "", "started_at": None, "finished_at": None, "result": None}


def _rows(answer, key):
    """The list under key in a Kodi answer, whether or not it is still wrapped in "result"."""
    answer = answer or {}
    if isinstance(answer.get("result"), dict):
        answer = answer["result"]
    return answer.get(key) or [], int(((answer.get("limits") or {}).get("total")) or 0)


def _paged(target, method, key, properties, say):
    from curator.notify import kodi_call

    found, start = [], 0
    while True:
        answer = kodi_call(*target, method, {"properties": properties, "limits": {"start": start, "end": start + PAGE}},
                           timeout=120)
        rows, total = _rows(answer, key)
        found.extend(rows)
        say(f"Reading Kodi {key}: {len(found)}{f' of {total}' if total else ''}")
        if not rows or len(rows) < PAGE or (total and len(found) >= total):
            return found
        start += PAGE


def _norm(path):
    return os.path.normpath(str(path or "")).rstrip(os.sep)


def _library_files():
    """{file: (kind, id, label, folder)} for every movie file and episode file Curator lists (second episode files too)."""
    from curator.video.store import movie_file_paths

    files = {}
    for row in db.fetchall(
        "SELECT m.id::text AS id, m.title, m.year, m.folder, m.root, m.parts, f.path AS file_path "
        "FROM movies m LEFT JOIN video_files f ON f.id = m.file_id WHERE NOT COALESCE(m.wanted, FALSE)"
    ):
        label = f"{row['title']} ({row['year']})" if row.get("year") else str(row.get("title") or "")
        for path in movie_file_paths(dict(row)):
            files[_norm(path)] = ("movie", row["id"], label, row.get("folder") or os.path.dirname(path), row.get("root"))
    for row in db.fetchall(
        "SELECT e.id::text AS id, e.path, e.season_number, e.episode_number, s.title, s.root "
        "FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE NOT e.missing AND strpos(e.path, '://') = 0"
    ):
        label = f"{row['title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"
        files[_norm(row["path"])] = ("episode", row["id"], label, os.path.dirname(row["path"]), row.get("root"))
    for row in db.fetchall(
        "SELECT c.path, e.id::text AS id, e.season_number, e.episode_number, s.title, s.root "
        "FROM episode_copies c JOIN tv_episodes e ON e.id = c.episode_id JOIN tv_shows s ON s.id = e.show_id"
    ):
        label = f"{row['title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d} (second file)"
        files[_norm(row["path"])] = ("episode", row["id"], label, os.path.dirname(row["path"]), row.get("root"))
    return files


def build(target, mappings, say=lambda text: None):
    """The report. target is (host, user, password); mappings the Kodi path rows."""
    from curator import folders, notify

    mounted = {_norm(root) for root in folders.mounted("movies") + folders.mounted("tv")}

    def online(path):
        real = _norm(os.path.realpath(path)) if path else ""
        return any(real == root or real.startswith(root + os.sep) for root in mounted)

    say("Reading Kodi movies")
    kodi_movies = _paged(target, "VideoLibrary.GetMovies", "movies", ["file", "title", "year"], say)
    say("Reading Kodi episodes")
    kodi_episodes = _paged(target, "VideoLibrary.GetEpisodes", "episodes", ["file", "showtitle", "season", "episode"], say)
    say("Reading the library")
    library = _library_files()
    report = {"missing": [], "not_indexed": [], "not_in_kodi": [], "unmapped_kodi": [], "unmapped_folders": []}
    counts = dict.fromkeys(report, 0)
    seen = set()

    def add(bucket, row):
        counts[bucket] += 1
        if len(report[bucket]) < EXAMPLES:
            report[bucket].append(row)

    entries = [("movie", item, f"{item.get('title') or ''}" + (f" ({item['year']})" if item.get("year") else ""))
               for item in kodi_movies]
    entries += [("episode", item, f"{item.get('showtitle') or ''} S{int(item.get('season') or 0):02d}E{int(item.get('episode') or 0):02d}")
                for item in kodi_episodes]
    for kind, item, label in entries:
        for part in notify._kodi_parts(item.get("file")):
            local = notify._local_from_kodi(part, mappings)
            if not local:
                add("unmapped_kodi", {"kind": kind, "label": label, "kodi_path": part})
                continue
            key = _norm(local)
            seen.add(key)
            if key in library:
                continue
            if not online(local):
                continue                      # an offline drive: nothing can be judged
            if os.path.isfile(local):
                add("not_indexed", {"kind": kind, "label": label, "path": local, "kodi_path": part})
            else:
                add("missing", {"kind": kind, "label": label, "path": local, "kodi_path": part})
    folder_rows = {}
    for path, (kind, item_id, label, folder, root) in library.items():
        if path in seen or not root or not online(root):
            continue
        if notify._kodi_folder(folder, mappings) is None:
            folder_rows.setdefault(folder, 0)
            folder_rows[folder] += 1
            continue
        add("not_in_kodi", {"kind": kind, "id": item_id, "label": label, "path": path, "folder": folder})
    for folder, count in sorted(folder_rows.items()):
        add("unmapped_folders", {"folder": folder, "files": count})
    return {"counts": counts, "lists": report, "kodi_movies": len(kodi_movies), "kodi_episodes": len(kodi_episodes),
            "library_files": len(library)}


def _target():
    from curator import automation, notify

    _, cfg = automation.current()
    target = notify._library_target(cfg)
    mappings = cfg.get("kodi_paths") or []
    if not target:
        raise AppError("Set the Kodi library address under Settings, Integrations first.", 400)
    if not mappings:
        raise AppError("Add Kodi path rows under Settings, Integrations first: without them no Kodi file can be "
                       "matched to a library file.", 400)
    return target, mappings


def start():
    """Read Kodi and the library in the background. Returns the state; refuses while one runs."""
    target, mappings = _target()
    with _lock:
        if _state["status"] == "running":
            return status()
        _state.update({"status": "running", "message": "Starting", "started_at": time.time(), "finished_at": None})

    def say(text):
        _state["message"] = text

    def run():
        try:
            result = build(target, mappings, say)
            _state.update({"status": "done", "result": result, "message": "Done"})
        except RuntimeError as exc:
            _state.update({"status": "failed", "message": str(exc)})
        except Exception as exc:
            logger.exception("the Kodi report failed")
            _state.update({"status": "failed", "message": str(exc)})
        finally:
            _state["finished_at"] = time.time()

    threading.Thread(target=run, name="kodi-report", daemon=True).start()
    return status()


def status():
    return dict(_state)


def scan_folders(folders_wanted):
    """Ask Kodi (only Kodi) to scan these library folders. Returns how many jobs were queued."""
    from curator import automation
    from curator.library_queue import queue_for

    wanted = sorted({str(folder) for folder in folders_wanted or [] if folder})
    if not wanted:
        raise AppError("No folder to scan", 400)
    _, cfg = automation.current()
    return queue_for(["kodi"], "video", wanted, False, f"Scan from the Kodi report ({len(wanted)} folder"
                     f"{'s' if len(wanted) != 1 else ''})", cfg)


def clean():
    """Ask Kodi for a video library clean, which drops the entries whose file is gone. Runs in the background (Kodi
    first finishes a scan it is running); the automatic clean switch does not apply to this button."""
    from curator import notify

    _target()

    def run():
        try:
            notify.clean_kodi("video")
        except Exception as exc:
            logger.warning("the Kodi clean from the report did not run: %s", exc)

    threading.Thread(target=run, name="kodi-report-clean", daemon=True).start()
    return {"queued": True}
