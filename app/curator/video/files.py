"""File jobs on the video library: rename, subtitle clean-up, extras layout and trailer downloads.

One job runs at a time in a worker thread, never alongside a scan or a scrape, because all of them
move or read the same files.
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime

from curator import notify
from curator.video import activity, config, extras, rename, scanner, scrape, store, subtitles, trailers
from resonance import backup, db, history
from resonance.errors import AppError

logger = logging.getLogger(__name__)

OPS = {"rename": "Renaming", "subtitles": "Cleaning subtitles", "extras": "Sorting extras", "trailers": "Downloading trailers",
       "themes": "Downloading theme songs", "thumbs": "Generating episode thumbnails", "move": "Moving",
       "origlang": "Switching to the original language", "integrity": "Checking file integrity (quick)",
       "integrity_full": "Checking file integrity (full)",
       "cleanfanart": "Replacing artwork",
       "cleanfanart_any": "Replacing artwork",
       "cleanfanart_suggested": "Replacing artwork"}
CLEAN_FANART = {"cleanfanart", "cleanfanart_any", "cleanfanart_suggested"}
KINDS = {"movie", "show", "season", "episode", "artist", "musicvideo", "set"}
MOVIE_ONLY = set()
LOG_LINES = 3000

_lock = threading.Lock()
_cancel = threading.Event()
_listeners = []
_state = {"status": "idle", "op": None, "message": "Idle", "processed": 0, "total": 0, "current": "",
          "started_at": None, "finished_at": None, "result": {}, "job": ""}
_log = deque(maxlen=LOG_LINES)
# Every status carries the job it belongs to and a number that only grows (with the process it came from), so the
# page can drop a status that was on its way before a newer one: a slow refresh must not report the last job's end.
_BOOT = uuid.uuid4().hex[:8]
_seq = 0


def _failure_line(title, exc):
    """Some errors already begin with the title of the item; do not print it twice."""
    text = str(exc)
    return text if text.startswith(title) else f"{title}: {text}"


def add_listener(callback):
    _listeners.append(callback)


def _notify():
    snapshot = status(include_log=False)
    for callback in list(_listeners):
        try:
            callback(snapshot)
        except Exception:
            logger.exception("file job listener failed")


def status(include_log=True):
    global _seq
    with _lock:
        _seq += 1
        snapshot = dict(_state)
        snapshot["seq"] = _seq
        snapshot["boot"] = _BOOT
        snapshot["result"] = dict(_state["result"])
        if include_log:
            snapshot["log"] = "\n".join(_log)
    return snapshot


def running():
    with _lock:
        return _state["status"] == "running"


def cancel():
    if not running():
        return False
    _cancel.set()
    with _lock:
        _state["message"] = "Stopping"
    _notify()
    return True


def _log_line(line):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")


def _count(key, step=1):
    with _lock:
        _state["result"][key] = _state["result"].get(key, 0) + step


def _check_op(op, kind):
    if op not in OPS:
        raise AppError(f"Unknown file job {op}", 400)
    if kind not in KINDS:
        raise AppError("Unknown item type", 400)
    if kind == "set" and op not in CLEAN_FANART:
        raise AppError("A movie set can only have its artwork cleaned here", 400)
    if kind == "musicvideo" and op not in ("integrity", "integrity_full"):
        raise AppError("A music video can only be checked for damage here", 400)
    if op in MOVIE_ONLY and kind != "movie":
        raise AppError("That file job is only for movies", 400)
    if op == "extras" and kind not in {"movie", "show", "season", "episode"}:
        raise AppError("Extras are sorted for a movie, or for the show of a show, season or episode", 400)
    if op == "trailers" and kind not in {"movie", "show", "season"}:
        raise AppError("Trailers are downloaded for a movie, show or season", 400)
    if op in CLEAN_FANART and kind not in {"movie", "show", "set"}:
        raise AppError("Clean artwork works on a movie, a show or a movie set", 400)
    if op == "themes" and kind not in {"movie", "show"}:
        raise AppError("Theme songs are downloaded for a movie or show", 400)
    if op == "thumbs" and kind not in {"show", "season", "episode"}:
        raise AppError("Episode thumbnails are generated for a show, season or episode", 400)
    if op == "origlang" and kind not in {"movie", "show", "season", "episode"}:
        raise AppError("The original language is set on a movie, a show, a season or an episode", 400)
    if op == "move" and kind not in {"movie", "show", "artist"}:
        raise AppError("Move a movie, a whole show, or an artist. Seasons and episodes stay with their show.", 400)
    if kind == "artist" and op != "move":
        raise AppError("An artist can only be moved to another music folder", 400)


def _units(op, kind, ids):
    """Group the picked items into work units: ("movie", id) or ("show", show_id, episode_ids, whole_show)."""
    if kind == "musicvideo":
        return [("musicvideo", item) for item in ids]
    if kind == "artist":
        return [("artist", item) for item in ids]
    if op in ("trailers", "themes", "origlang") or op in CLEAN_FANART:
        return [(kind, item) for item in ids]
    if op == "thumbs":
        if kind == "episode":
            return [("episode", item) for item in ids]
        if kind == "season":
            rows = db.fetchall("SELECT id FROM tv_episodes WHERE season_id = ANY(%s::uuid[]) AND NOT missing ORDER BY season_number, episode_number", (list(ids),))
            return [("episode", str(row["id"])) for row in rows]
        rows = db.fetchall("SELECT id FROM tv_episodes WHERE show_id = ANY(%s::uuid[]) AND NOT missing ORDER BY season_number, episode_number", (list(ids),))
        return [("episode", str(row["id"])) for row in rows]
    if kind == "movie":
        return [("movie", item) for item in ids]
    if kind == "show":
        return [("show", item, None, True) for item in ids]
    if kind == "season":
        rows = db.fetchall(
            "SELECT e.show_id, e.id FROM tv_episodes e JOIN tv_seasons s ON s.show_id = e.show_id "
            "AND s.season_number = e.season_number WHERE s.id = ANY(%s::uuid[])", (list(ids),))
    else:
        rows = db.fetchall("SELECT show_id, id FROM tv_episodes WHERE id = ANY(%s::uuid[])", (list(ids),))
    shows = {}
    for row in rows:
        shows.setdefault(str(row["show_id"]), []).append(str(row["id"]))
    return [("show", show_id, episode_ids, False) for show_id, episode_ids in shows.items()]


def _plan(op, unit, cfg):
    if op == "rename":
        if unit[0] == "movie":
            return rename.plan_movie(unit[1], cfg)
        return rename.plan_show(unit[1], cfg, episode_ids=unit[2], rename_folder=unit[3])
    if op == "extras":
        if unit[0] == "movie":
            return extras.plan_movie(unit[1], cfg["extras_layout"])
        return extras.plan_show(unit[1], cfg["extras_layout"])
    return None


def preview(op, kind, ids, limit=500):
    """The moves a rename or extras job would make, without touching anything."""
    _check_op(op, kind)
    if op not in ("rename", "extras", "subtitles", "origlang"):
        raise AppError("Only rename, extras, subtitle and original language jobs can be previewed", 400)
    cfg = config.current()
    if op == "origlang":
        from curator.video import original_language

        plans, moves = original_language.preview(kind, ids, cfg)
        return {"op": op, "plans": plans, "moves": moves}
    plans, moves = [], 0
    if op == "subtitles":
        for unit in _units(op, kind, ids):
            for path in _video_paths(unit):
                try:
                    entries = subtitles.preview(path, cfg)
                except OSError:
                    continue
                if entries:
                    moves += len(entries)
                    plans.append({"title": os.path.basename(path), "error": None, "moves": entries[:limit]})
        return {"op": op, "plans": plans, "moves": moves}
    for unit in _units(op, kind, ids):
        plan = _plan(op, unit, cfg)
        if not plan:
            continue
        moves += len(plan["moves"])
        if plan["moves"] or plan["error"]:
            plans.append({"title": plan["title"], "error": plan["error"], "moves": [
                {"from": move["from"], "to": move["to"], "dir": move["dir"]} for move in plan["moves"][:limit]]})
    return {"op": op, "plans": plans, "moves": moves}


_options = threading.local()       # per job thread: options a file job carries (Replace artwork: art_types)


def start(op, kind, ids, label=None, dest=None, players=None, art_types=None, fill_missing=True):
    """Returns False when a file job is already running."""
    _check_op(op, kind)
    if op == "move" and not dest:
        raise AppError("Pick a library folder", 400)
    from curator.video import split

    if scanner.running() or scrape.running() or split.running():
        raise AppError("Wait for the running scan or scrape to finish", 409)
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    with _lock:
        if _state["status"] == "running":
            return False
        _cancel.clear()
        _log.clear()
        _state.update({
            "status": "running", "op": op, "message": OPS[op], "processed": 0, "total": 0, "current": "",
            "job": uuid.uuid4().hex,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"), "finished_at": None,
            "result": {"changed": 0, "skipped": 0, "failed": 0, "failures": [], "art_paths": []},
        })
    threading.Thread(target=_run, args=(op, kind, list(ids), label, dest, players, art_types, fill_missing), name=f"files-{op}",
                     daemon=True).start()
    return True


def run_now(op, kind, ids, log=None, keep_going=False):
    """Run a job in the calling thread (the webhook queue uses this after its own scrape).

    keep_going: a unit that fails is logged and the rest still run (the webhook queue hands over every imported item
    at once). Without it the first failure is raised, as before."""
    _check_op(op, kind)
    cfg = config.current()
    write = log or _log_line
    folders = []
    for unit in _units(op, kind, ids):
        try:
            folders += _unit(op, unit, cfg, write)
        except Exception as exc:
            if not keep_going:
                raise
            logger.warning("%s failed for %s %s: %s", op, unit[0], unit[1], exc)
            write(f"{OPS.get(op, op)} failed for {unit[0]} {unit[1]}: {exc}")
    return folders


def _version():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "VERSION"),
                  encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return "?"


def _run(op, kind, ids, label, dest=None, send_players=None, art_types=None, fill_missing=True):
    _options.art_types = list(art_types) if art_types else None
    _options.fill_missing = bool(fill_missing)
    folders = []
    titles = []              # what the job worked on, for the Jobs panel's Recent list
    players = contextlib.ExitStack()
    if op in CLEAN_FANART:
        from curator.video import art_pick

        # The new pictures reach the players as artwork refreshes, handed over in batches, not one queue write per item.
        # send_players: the players ticked in the Clean fanart window (None: every enabled one, []: none).
        players.enter_context(art_pick.batched_player_art(players=send_players))
        types = ", ".join(art_types) if art_types else "fanart"
        _log_line(f"Curator {_version()}: {types}, each chosen exactly as the artwork window marks Suggested")
        if send_players is not None and not send_players:
            _log_line("No player is updated; use Update artwork in players later")
    try:
        cfg = config.current()
        units = _units(op, kind, ids)
        with _lock:
            _state["total"] = len(units)
        _log_line(f"{OPS[op]}: {len(units)} item(s){f' ({label})' if label else ''}")
        _notify()
        for unit in units:
            if _cancel.is_set():
                _log_line("Stopped")
                break
            title = unit[1]
            if unit[0] == "artist":
                row = db.fetchone("SELECT name FROM artists WHERE id = %s", (unit[1],))
                title = (row or {}).get("name") or unit[1]
            elif unit[0] == "musicvideo":
                row = db.fetchone("SELECT artist, title FROM music_videos WHERE id = %s", (unit[1],))
                title = f"{row['artist']} — {row['title']}" if row else unit[1]
            elif unit[0] == "episode":
                row = db.fetchone(
                    "SELECT s.title AS show_title, e.season_number, e.episode_number, e.title "
                    "FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE e.id = %s",
                    (unit[1],),
                )
                if row:
                    title = f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"
                else:
                    title = unit[1]
            else:
                table = ("movies" if unit[0] == "movie" else "tv_seasons" if unit[0] == "season"
                         else "movie_sets" if unit[0] == "set" else "tv_shows")
                title = store.title_of(table, unit[1]) or unit[1]
            with _lock:
                _state["current"] = title
                _state["message"] = f"{OPS[op]} {_state['processed'] + 1}/{len(units)}: {title}"
            titles.append(title)
            _notify()
            try:
                with activity.holding() as hold:
                    _hold_unit(hold, unit)
                    folders += _unit(op, unit, cfg, _log_line, dest)
                if op in ("rename", "extras", "move"):
                    from curator.video import local_extras

                    local_extras.refresh_item(unit[0], unit[1])
            except AppError as exc:
                _count("failed")
                with _lock:
                    _state["result"]["failures"].append({"title": title, "error": str(exc)})
                _log_line(_failure_line(title, exc))
            except Exception as exc:
                logger.exception("file job failed on %s", title)
                _count("failed")
                with _lock:
                    _state["result"]["failures"].append({"title": title, "error": str(exc)})
                _log_line(_failure_line(title, exc))
            with _lock:
                _state["processed"] += 1
            _notify()
        players.close()
        if folders:
            notify.request("video", folders=sorted(set(folders)), clean=op in ("rename", "extras", "move"),
                           trigger=f"File job ({op})")
        final, message = ("cancelled", "Stopped") if _cancel.is_set() else ("done", "Finished")
    except Exception as exc:
        logger.exception("file job failed")
        _log_line(f"Failed: {exc}")
        final, message = "failed", str(exc)
    players.close()          # also after a failure: the items already replaced still reach the players
    with _lock:
        _state.update({"status": final, "message": message, "current": "",
                       "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")})
        result = dict(_state.get("result") or {})
        started = _state.get("started_at")
        lines = "\n".join(_log)
    _notify()
    # Kept for the Jobs panel's Recent list: the log of a file job lives only in memory until the next one starts.
    from curator import job_history

    summary = (f"{int(result.get('changed') or 0)} changed, {int(result.get('skipped') or 0)} unchanged"
               + (f", {int(result.get('failed') or 0)} failed" if result.get("failed") else ""))
    kept = {key: value for key, value in result.items() if key != "art_paths"}
    kept.update(job_history.items_result(titles))
    job_history.record(op, label or OPS.get(op, op), final, summary if final == "done" else message,
                       kept, lines, started_at=started)
    from resonance import scan_queue

    scan_queue.finished()


def _note_art_path(path):
    """A picture a file job wrote: the page loads it again instead of the copy it already shows (same file name)."""
    with _lock:
        paths = _state.setdefault("result", {}).setdefault("art_paths", [])
        if path and path not in paths and len(paths) < 5000:
            paths.append(path)


def _bump(changed):
    if running():
        _count("changed" if changed else "skipped")


def _hold_unit(hold, unit):
    kind = unit[0]
    if kind == "musicvideo":
        return
    if kind == "movie":
        hold(unit[1])
        return
    if kind in ("artist", "set"):
        hold(unit[1])
        return
    if kind == "show":
        hold(unit[1])
        episode_ids = unit[2] if len(unit) > 2 else None
        if not episode_ids:
            return
        rows = db.fetchall(
            "SELECT id, season_id FROM tv_episodes WHERE id = ANY(%s::uuid[])",
            (list(episode_ids),),
        )
        for row in rows:
            hold(row["id"], unit[1], row["season_id"])
        return
    if kind == "season":
        row = db.fetchone("SELECT show_id FROM tv_seasons WHERE id = %s", (unit[1],))
        hold(unit[1], row["show_id"] if row else None)
        return
    row = db.fetchone("SELECT show_id, season_id FROM tv_episodes WHERE id = %s", (unit[1],))
    hold(unit[1], row["show_id"] if row else None, row["season_id"] if row else None)


def _unit(op, unit, cfg, log, dest=None):
    """Process one work unit. Returns the folders that changed, for the Kodi update."""
    if op == "move" and unit[0] == "artist":
        from resonance import relocate as music_move

        folders = music_move.apply_one(unit[1], dest, log)
        _bump(bool(folders))
        if folders:
            history.record("moved", str(unit[1]), "artist", dest, "Moved to another music folder")
        return folders
    if op == "move":
        from curator.video import relocate

        folders = relocate.apply_one(unit[0], unit[1], dest, log)
        _bump(bool(folders))
        if folders:
            history.record("moved", str(unit[1]), unit[0], dest, "Moved to another library folder")
        return folders
    if op in ("rename", "extras"):
        plan = _plan(op, unit, cfg)
        if not plan:
            return []
        if plan["error"]:
            raise AppError(plan["error"])
        if not plan["moves"]:
            log(f"{plan['title']}: already in place")
            _bump(False)
            return []
        count = rename.apply(plan)
        for path in rename.new_videos(plan):
            store.refresh_external_subs(path)
        log(f"{plan['title']}: moved {count} file(s)")
        history.record("renamed" if op == "rename" else "moved", plan["title"], unit[0], "",
                       f"{OPS[op]}: {count} file(s)")
        _bump(True)
        return list(plan["folders"])
    if op in ("integrity", "integrity_full"):
        from curator.video import integrity

        paths = _video_paths(unit)
        checked, broken = integrity.run_paths(paths, op == "integrity_full", log)
        _bump(broken > 0)
        if broken:
            _count("corrupt", broken)
        return []
    if op == "subtitles":
        changed = False
        folders = []
        for path in _video_paths(unit):
            renamed, converted = subtitles.process(path, cfg, log)
            if renamed or converted:
                changed = True
                folders.append(os.path.dirname(path))
        _bump(changed)
        return folders
    if op == "origlang":
        from curator.video import original_language

        folders = []
        for row in original_language.targets(unit[0], [unit[1]]):
            if original_language.apply(row, cfg, log, manual=True):
                folders.append(os.path.dirname(row["path"]))
                history.record("changed", os.path.basename(row["path"]), unit[0], row["path"], "Default language switched to the original language")
        _bump(bool(folders))
        return folders
    if op in CLEAN_FANART:
        from curator.video import clean_fanart

        folder = clean_fanart.replace(unit[0], unit[1], cfg, log, any_unknown=op == "cleanfanart_any",
                                      on_saved=_note_art_path,
                                      art_types=getattr(_options, "art_types", None),
                                      fill_missing=getattr(_options, "fill_missing", True),
                                      suggested_only=op == "cleanfanart_suggested")
        _bump(bool(folder))
        return []            # the players get an artwork refresh of the item (art_pick), not a folder scan
    if op == "themes":
        saved = trailers.download_theme(unit[0], unit[1], cfg, log)
        _bump(bool(saved))
        return [os.path.dirname(saved)] if saved else []
    if op == "thumbs":
        from curator.routes.library import generate_episode_thumb

        ep = store.episode_detail(unit[1])
        label = f"S{int(ep.get('season_number') or 0):02d}E{int(ep.get('episode_number') or 0):02d}" if ep else unit[1]
        show_title = (ep or {}).get("show_title") or ""
        prefix = f"{show_title} {label}".strip()
        video_name = os.path.basename((ep or {}).get("path") or "")
        log(f"{prefix}: picking a frame from {video_name}" if video_name else f"{prefix}: picking a frame")
        started = time.monotonic()
        res = generate_episode_thumb(unit[1])
        thumb_path = res.get("thumb_path")
        log(f"{prefix}: saved {res.get('thumb_name') or os.path.basename(thumb_path or '')} in {time.monotonic() - started:.1f} s")
        _bump(bool(thumb_path))
        return [os.path.dirname(thumb_path)] if thumb_path else []
    saved = trailers.download(unit[0], unit[1], cfg, log)
    _bump(bool(saved))
    return [os.path.dirname(saved)] if saved else []


def _video_paths(unit):
    if unit[0] == "musicvideo":
        row = db.fetchone("SELECT path FROM music_videos WHERE id = %s", (unit[1],))
        return [row["path"]] if row else []
    if unit[0] == "movie":
        row = store.movie_row(unit[1])
        if not row or row.get("disc_format"):
            return []
        return list(row.get("parts") or [row["path"]])
    if unit[2]:
        rows = db.fetchall("SELECT DISTINCT path FROM tv_episodes WHERE id = ANY(%s::uuid[])", (unit[2],))
    else:
        rows = db.fetchall("SELECT DISTINCT path FROM tv_episodes WHERE show_id = %s", (unit[1],))
    return sorted(row["path"] for row in rows if row.get("path"))
