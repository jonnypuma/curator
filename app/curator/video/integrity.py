"""Video file integrity: decode the file with ffmpeg and flag broken or truncated downloads.

A quick check decodes the first and the last minute, which finds most broken downloads (a cut-off end, a damaged
start) in seconds. A full check decodes the whole file. Any decode error marks the file Corrupt. The result is kept
on video_files with the file's size and mtime, so a replaced file is not reported for the old copy's errors.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

from resonance import db, history

logger = logging.getLogger(__name__)

QUICK_SECONDS = 60
QUICK_TIMEOUT = 600
FULL_TIMEOUT = 6 * 3600
MAX_ERRORS = 12
DISC_IMAGES = {".iso", ".img", ".mdf", ".nrg"}
# A seek into the last minute can start decoding on a frame whose references were skipped. That is the seek, not
# the file, so these lines are ignored for the tail of a quick check.
_SEEK_NOISE = ("could not find ref with poc", "missing reference picture", "number of reference frames")


def _decode(path, before=(), timeout=QUICK_TIMEOUT):
    """Decode the main video and audio streams, discarding the output. Returns (returncode, error lines)."""
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", *before, "-i", path,
               "-map", "0:v:0?", "-map", "0:a?", "-f", "null", "-"]
    completed = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout, check=False)
    lines = [line.strip() for line in (completed.stderr or "").splitlines() if line.strip()]
    return completed.returncode, lines


def check(path, full=False):
    """{"status": "ok" | "corrupt" | "error", "errors": [...], "mode": "quick" | "full"} for one file."""
    mode = "full" if full else "quick"
    if not path or not os.path.isfile(path):
        return {"status": "error", "errors": ["The file is not on disk"], "mode": mode}
    if os.path.splitext(path)[1].lower() in DISC_IMAGES:
        return {"status": "error", "errors": ["Disc images are not checked"], "mode": mode}
    try:
        if full:
            code, errors = _decode(path, timeout=FULL_TIMEOUT)
        else:
            code, head = _decode(path, ("-t", str(QUICK_SECONDS)))
            tail_code, tail = _decode(path, ("-sseof", f"-{QUICK_SECONDS}"))
            tail = [line for line in tail if not any(noise in line.lower() for noise in _SEEK_NOISE)]
            code = code or tail_code
            errors = head + tail
    except FileNotFoundError:
        return {"status": "error", "errors": ["ffmpeg is not installed"], "mode": mode}
    except subprocess.TimeoutExpired:
        return {"status": "error", "errors": ["The check took too long and was stopped"], "mode": mode}
    except OSError as exc:
        return {"status": "error", "errors": [str(exc)], "mode": mode}
    unique = list(dict.fromkeys(errors))
    if code and not unique:
        unique = [f"ffmpeg stopped with exit code {code}"]
    return {"status": "corrupt" if unique else "ok", "errors": unique[:MAX_ERRORS], "mode": mode}


def store(path, result):
    """Keep the result on the file row, stamped with the size and mtime it was taken for."""
    if result.get("status") == "error":
        return
    db.execute(
        """
        UPDATE video_files
        SET integrity = %s, integrity_errors = %s::jsonb, integrity_mode = %s, integrity_checked_at = LOCALTIMESTAMP,
            integrity_size = size_bytes, integrity_mtime = mtime
        WHERE path = %s
        """,
        (result["status"], json.dumps(result.get("errors") or []), result.get("mode") or "quick", path),
    )


def corrupt(row):
    """True when the stored result says Corrupt and the file has not changed since it was checked."""
    if str((row or {}).get("integrity") or "") != "corrupt":
        return False
    checked_size, size = row.get("integrity_size"), row.get("size_bytes")
    if checked_size is not None and size is not None and int(checked_size) != int(size):
        return False
    checked_mtime, mtime = row.get("integrity_mtime"), row.get("mtime")
    if checked_mtime is not None and mtime is not None and abs(float(checked_mtime) - float(mtime)) > 1:
        return False
    return True


def run_paths(paths, full, log):
    """Check each path and store the result. Returns (checked, corrupt) counts."""
    checked = broken = 0
    for path in paths:
        result = check(path, full)
        name = os.path.basename(path)
        if result["status"] == "error":
            log(f"{name}: not checked - {result['errors'][0]}")
            continue
        store(path, result)
        checked += 1
        if result["status"] == "corrupt":
            broken += 1
            log(f"{name}: Corrupt ({result['mode']} check) - {result['errors'][0]}")
            history.record("corrupt", name, "video", path, result["errors"][0])
        else:
            log(f"{name}: OK ({result['mode']} check)")
    return checked, broken


def after_import(kind, ids, cfg, log):
    """Quick check of freshly imported files. A corrupt one sends a notification and can ask the app to search again.

    The search does not delete the file: Radarr or Sonarr only replace it when their profile allows the new release.
    """
    from curator import outbound

    rows = _import_rows(kind, ids)
    broken = []
    for row in rows:
        result = check(row["path"])
        if result["status"] == "error":
            log(f"{row['path']}: not checked - {result['errors'][0]}")
            continue
        store(row["path"], result)
        if result["status"] == "corrupt":
            broken.append(row)
            history.record("corrupt", row["label"], kind, row["path"], result["errors"][0])
            outbound.send("file_corrupt", f"Corrupt file: {row['label']}", f"{row['path']}\n{result['errors'][0]}", "warning")
    if broken and cfg.get("integrity_research"):
        _search_again(broken)
    return len(rows), len(broken)


def _import_rows(kind, ids):
    if not ids:
        return []
    if kind == "movie":
        rows = db.fetchall(
            "SELECT m.title, m.year, COALESCE(f.path, m.path) AS path, m.tmdb_id FROM movies m "
            "LEFT JOIN video_files f ON f.id = m.file_id WHERE m.id = ANY(%s::uuid[])", (list(ids),))
        return [{**dict(row), "kind": "movie", "label": f"{row['title']} ({row['year']})" if row.get("year") else row["title"]} for row in rows]
    where = "e.id" if kind == "episode" else "e.show_id"
    rows = db.fetchall(
        f"""
        SELECT e.title, e.path, e.season_number, e.episode_number, s.tvdb_id, s.tmdb_id, s.title AS show_title
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
        WHERE {where} = ANY(%s::uuid[]) AND NOT e.missing AND e.path NOT LIKE '%%://%%'
        """,
        (list(ids),),
    )
    return [{**dict(row), "kind": "episode",
             "label": f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"} for row in rows]


def _search_again(rows):
    from curator.arr_queue import enqueue, search_title

    movies = [row for row in rows if row["kind"] == "movie" and row.get("tmdb_id")]
    if movies:
        enqueue("radarr", search_title("radarr", [row["label"] for row in movies]), "radarr",
                {"tmdb_ids": [row["tmdb_id"] for row in movies]})
    episodes = [row for row in rows if row["kind"] == "episode" and (row.get("tvdb_id") or row.get("tmdb_id"))]
    if episodes:
        payload = [{key: row.get(key) for key in ("title", "season_number", "episode_number", "tvdb_id", "tmdb_id", "show_title")} for row in episodes]
        enqueue("sonarr", search_title("sonarr", [row["label"] for row in episodes]), "sonarr", {"episodes": payload})


# The scheduled pass: each day, a full check of the files checked longest ago, while nothing else is running.

_timer = {"thread": None, "day": ""}


def scheduled_pass(count, log=logger.info):
    """Fully check up to count files, stopping when a scan or job starts. Returns (checked, corrupt)."""
    from curator import outbound
    from resonance import scan_queue

    rows = db.fetchall(
        """
        SELECT path FROM video_files
        WHERE probe_error IS NULL AND probed_at IS NOT NULL AND COALESCE(size_bytes, 0) > 0
          AND lower(COALESCE(container, '')) <> ALL(%s)
        ORDER BY (integrity_mode = 'full') NULLS FIRST, integrity_checked_at NULLS FIRST
        LIMIT %s
        """,
        (["iso", "vob", "bdmv", "disc"], int(count)),
    )
    checked = broken = 0
    for row in rows:
        if scan_queue.busy():
            log("The scheduled integrity pass stopped: a scan or job started")
            break
        result = check(row["path"], full=True)
        if result["status"] == "error":
            continue
        store(row["path"], result)
        checked += 1
        if result["status"] == "corrupt":
            broken += 1
            name = os.path.basename(row["path"])
            with history.why("Scheduled integrity pass"):
                history.record("corrupt", name, "video", row["path"], result["errors"][0])
            outbound.send("file_corrupt", f"Corrupt file: {name}", f"{row['path']}\n{result['errors'][0]}", "warning")
    return checked, broken


def start_timer():
    import threading
    from datetime import date

    from curator.video import config

    if _timer["thread"] and _timer["thread"].is_alive():
        return

    def loop():
        stop = threading.Event()
        while True:
            stop.wait(3600)
            try:
                count = int(config.current().get("integrity_pass_files") or 0)
                today = date.today().isoformat()
                if count and _timer["day"] != today:
                    from resonance import scan_queue

                    if not scan_queue.busy():
                        _timer["day"] = today
                        scheduled_pass(count)
            except Exception:
                logger.exception("the scheduled integrity pass failed")

    _timer["thread"] = threading.Thread(target=loop, name="integrity-pass", daemon=True)
    _timer["thread"].start()
