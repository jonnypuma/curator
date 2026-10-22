"""Movie and TV scans.

A scan walks the folders of one media type. Incremental and full finish that walk
and the list of files that need work before any probe starts. Deep counts folders and
video files first, then probes every file, keeping one group the size of the worker
setting in the probe workers.
Incremental and full leave a file alone when its size, time, .nfo and folder have not
changed. Full still retries a file whose last probe failed. Rows are removed when a mounted library
folder was read and the movie or show folder is gone. A folder that cannot be read is left as it is.
"""
from __future__ import annotations

import copy
import logging
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait as wait_futures
from datetime import datetime, timezone

from curator.video import activity, artwork, mediainfo_xml, naming, nfo, probe, store

logger = logging.getLogger(__name__)

MODES = ("incremental", "full", "deep")
LOG_LINES = 3000
LIST_LIMIT = 200

_lock = threading.Lock()
_cancel = threading.Event()
_import_cancel = threading.Event()
_pause_guard = threading.Lock()
_pause = threading.Event()
_paused = threading.Event()
_resume = threading.Event()
_pause_owner = None
_importing = False
PAUSE_MESSAGE = "Paused for queued imports"
_listeners = []
_removed = {"movies": [], "tv": []}
_state = {"status": "idle", "media": None, "mode": None, "roots": [], "message": "Idle", "phase": "",
          "processed": 0, "total": 0, "started_at": None, "finished_at": None, "result": {}, "id": None}
_log = deque(maxlen=LOG_LINES)
_parked = None

_media_states = {
    "movies": {"status": "idle", "media": "movies", "mode": None, "roots": [], "message": "Idle", "phase": "",
               "processed": 0, "total": 0, "started_at": None, "finished_at": None, "result": {}, "id": None},
    "tv": {"status": "idle", "media": "tv", "mode": None, "roots": [], "message": "Idle", "phase": "",
           "processed": 0, "total": 0, "started_at": None, "finished_at": None, "result": {}, "id": None},
}
_media_logs = {
    "movies": deque(maxlen=LOG_LINES),
    "tv": deque(maxlen=LOG_LINES),
}
_media_initialized = {"movies": False, "tv": False}


def _load_initial_media_state(media):
    if _media_initialized.get(media):
        return
    _media_initialized[media] = True
    try:
        from resonance import db
        row = db.fetchone(
            "SELECT * FROM video_scan_jobs WHERE media = %s ORDER BY started_at DESC NULLS LAST LIMIT 1",
            (media,),
        )
        from curator import scan_logs
        latest = scan_logs.latest_log(media)
        if row:
            res = row.get("result") or {}
            if not isinstance(res, dict):
                res = {}
            with _lock:
                _media_states[media].update({
                    "status": row.get("status") or "completed",
                    "media": media,
                    "mode": row.get("mode") or "incremental",
                    "roots": list(row.get("roots") or []),
                    "message": row.get("message") or ("Scan finished" if row.get("status") == "completed" else "Idle"),
                    "phase": "done" if row.get("status") == "completed" else "",
                    "started_at": row.get("started_at").isoformat(timespec="seconds") if row.get("started_at") else None,
                    "finished_at": row.get("finished_at").isoformat(timespec="seconds") if row.get("finished_at") else None,
                    "result": res,
                    "id": str(row.get("id")) if row.get("id") else None,
                })
        if latest and latest.get("text"):
            lines = latest["text"].splitlines()
            with _lock:
                _media_logs[media].clear()
                _media_logs[media].extend(lines[-LOG_LINES:])
    except Exception:
        logger.exception("could not load previous %s scan state", media)


def _media_snapshot(media, include_log):
    state_snap = dict(_media_states.get(media) or {})
    state_snap["result"] = dict(state_snap.get("result") or {})
    if include_log:
        state_snap["log"] = "\n".join(_media_logs.get(media) or [])
    return state_snap


def workers():
    """Files probed at once. A number saved in Settings overrides CMM_PROBE_WORKERS."""
    try:
        from curator.video.config import current

        return max(1, min(20, int(current().get("probe_workers") or 8)))
    except (TypeError, ValueError):
        return 8


def add_listener(callback):
    _listeners.append(callback)


def _notify():
    snapshot = status(include_log=False)
    for callback in list(_listeners):
        try:
            callback(snapshot)
        except Exception:
            logger.exception("scan listener failed")


def status(include_log=True, media=None):
    from resonance import scan_pace

    _load_initial_media_state("movies")
    _load_initial_media_state("tv")

    with _lock:
        live_running = _state.get("status") == "running"
        live_media = _state.get("media")

        scans = {}
        for m in ("movies", "tv"):
            if live_running and live_media == m:
                snap = dict(_state)
                snap["result"] = dict(_state.get("result") or {})
                if include_log:
                    snap["log"] = "\n".join(_log)
            else:
                snap = _media_snapshot(m, include_log)
            scans[m] = snap

        target_media = media if media in ("movies", "tv") else None
        if live_running and not target_media:
            snapshot = dict(_state)
            snapshot["result"] = dict(_state.get("result") or {})
            if include_log:
                snapshot["log"] = "\n".join(_log)
        elif target_media:
            snapshot = dict(scans[target_media])
        elif live_media in ("movies", "tv"):
            snapshot = dict(scans[live_media])
        else:
            snapshot = dict(_state)
            snapshot["result"] = dict(_state.get("result") or {})
            if include_log:
                snapshot["log"] = "\n".join(_log)

        snapshot["scans"] = scans
        parked = _paused_view(include_log)
    if live_running:
        snapshot["pace"] = scan_pace.snapshot()
    if parked:
        snapshot["paused_scan"] = parked
    try:
        from curator.video import store
        movies, shows = store.pending_match_ids()
        snapshot["pending_match"] = len(movies) + len(shows)
        snapshot["pending_match_movies"] = len(movies)
        snapshot["pending_match_tv"] = len(shows)
    except Exception:
        snapshot["pending_match"] = 0
        snapshot["pending_match_movies"] = 0
        snapshot["pending_match_tv"] = 0
    return snapshot


def _paused_view(include_log):
    """The library scan parked behind a webhook import. Its own media, log, and progress."""
    if not _parked:
        return None
    view = copy.deepcopy(_parked["state"])
    view["status"] = "paused"
    view["message"] = PAUSE_MESSAGE
    view["paused"] = True
    view["interrupt"] = False
    if include_log:
        view["log"] = "\n".join(_parked["log"])
    return view


def _hold_parked(saved):
    global _parked
    with _lock:
        _parked = saved


def _drop_parked():
    global _parked
    with _lock:
        _parked = None


def running():
    with _lock:
        return _state["status"] == "running"


def note_removed(media, ids):
    """Remember movie or show ids a scan deleted, so the page can drop those rows."""
    kind = "tv" if media == "tv" else "movies"
    with _lock:
        bucket = _removed[kind]
        for item in ids or []:
            text = str(item)
            if text and text not in bucket:
                bucket.append(text)


def removed_ids(media):
    kind = "tv" if media == "tv" else "movies"
    with _lock:
        return list(_removed[kind])


def _begin(media, mode, roots, force=False, reset_cancel=True, interrupt=False, origin="manual"):
    with _lock:
        if _state["status"] == "running" and not force:
            return False
        if reset_cancel:
            _cancel.clear()
        _log.clear()
        if media in _media_logs:
            _media_logs[media].clear()
        _removed["movies"] = []
        _removed["tv"] = []
        _state.update({
            "status": "running", "media": media, "mode": mode, "roots": list(roots), "phase": "walk",
            "message": "Reading folders", "processed": 0, "total": 0,
            "folders_done": 0, "folders_total": 0, "files_done": 0, "files_total": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"), "finished_at": None, "id": None,
            "trailers_alongside": False, "trailers_done": False, "interrupt": bool(interrupt), "origin": origin,
            "result": {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "probed": 0, "probe_failed": 0,
                       "failures": [], "unmatched": [], "empty": [], "failure_count": 0, "unmatched_count": 0,
                       "empty_count": 0},
        })
        if media in _media_states:
            _media_states[media] = copy.deepcopy(_state)
    from resonance import scan_pace

    scan_pace.begin(media, "walk")
    return True


def start(media, mode, roots, targets=None, season_id=None, episode_id=None, verbose=False, origin="manual"):
    if mode not in MODES:
        mode = "incremental"
    if not _begin(media, mode, roots, origin=origin):
        return False
    thread = threading.Thread(
        target=_run_and_release,
        args=(media, mode, list(roots), list(targets or []) or None, season_id, episode_id, bool(verbose)),
        name=f"{media}-scan", daemon=True,
    )
    thread.start()
    return True


def run_targeted(media, root, targets, held=False, interrupt=False):
    """Scan only these folders inside one library folder, in the calling thread.

    Movies: each target is a movie folder. TV: each target is a show folder. A target that no longer
    exists drops its rows, unless the library folder itself looks unmounted. Returns the final status,
    or None when another scan is running. held means the caller already reserved the library gate.
    interrupt snapshots the paused library scan and restores it when these folders are done.
    """
    from resonance import scan_queue

    saved = _snapshot() if interrupt else None
    if saved:
        _hold_parked(saved)
    if not held and not interrupt and not scan_queue.claim():
        return None
    if not _begin(media, "incremental", [root], force=interrupt, reset_cancel=not interrupt, interrupt=interrupt, origin="webhook"):
        if saved:
            _drop_parked()
            _restore(saved)
            _notify()
        elif not held:
            scan_queue.finished()
        return None
    result = None
    try:
        _run(media, "incremental", [root], targets=list(targets), interrupt=interrupt)
        result = status(include_log=False)
    finally:
        if interrupt:
            clear_import_cancel()
        if saved:
            _drop_parked()
            _restore(saved)
            _notify()
        elif not held:
            scan_queue.finished()
    return result


def bind_pause():
    """This thread is the library scan. A webhook scan on another thread does not park here."""
    global _pause_owner
    with _pause_guard:
        _pause_owner = threading.current_thread()


def unbind_pause():
    global _pause_owner, _importing
    with _pause_guard:
        _pause_owner = None
        _importing = False
        _pause.clear()
        _paused.clear()
    _resume.set()


def library_active():
    with _pause_guard:
        owner = _pause_owner
    return owner is not None and owner.is_alive()


def request_pause():
    """Park the library scan at its next folder. The job stays running."""
    with _pause_guard:
        owner = _pause_owner
        if owner is None or not owner.is_alive():
            return False
        _resume.clear()
        _pause.set()
    return True


def paused():
    return _paused.is_set()


def pause_requested():
    return _pause.is_set()


def yield_for_imports():
    """Drop the scrape lock, park until the webhook batch finishes, then take the lock back."""
    from curator.video import scrape

    saved = scrape.suspend()
    try:
        _wait_if_paused()
    finally:
        scrape.restore(saved)


def begin_import():
    """A cancel during the webhook batch stays parked until that batch finishes."""
    global _importing
    with _pause_guard:
        _importing = True


def finish_import():
    """Let the paused library scan continue."""
    global _importing
    with _pause_guard:
        _importing = False
        _pause.clear()
    _resume.set()


def _embedded_scrape():
    from curator.video import scrape

    snap = scrape.status(include_log=False)
    return snap.get("status") == "running" and bool(snap.get("embedded"))


def _wait_if_paused():
    """Park the library scan. The webhook thread is not the pause owner, so it must not park itself."""
    if threading.current_thread() is not _pause_owner:
        return
    if not _pause.is_set() or _embedded_scrape():
        return
    with _lock:
        if _state.get("status") == "running" and not _state.get("interrupt"):
            _state["message"] = PAUSE_MESSAGE
    _notify()
    _paused.set()
    try:
        while True:
            with _pause_guard:
                pause = _pause.is_set()
                importing = _importing
            if not pause or (_cancel.is_set() and not importing):
                break
            _resume.wait(0.4)
            _resume.clear()
    finally:
        _paused.clear()


def _snapshot():
    with _lock:
        return {
            "state": copy.deepcopy(dict(_state)),
            "log": list(_log),
            "removed": {key: list(value) for key, value in _removed.items()},
            "cancel": _cancel.is_set(),
        }


def _restore(saved):
    with _lock:
        extra = {key: list(value) for key, value in _removed.items()}
        _state.clear()
        _state.update(copy.deepcopy(saved["state"]))
        _log.clear()
        _log.extend(saved["log"])
        for key, value in saved["removed"].items():
            merged = list(value)
            for item in extra.get(key) or []:
                if item not in merged:
                    merged.append(item)
            _removed[key] = merged
    if saved["cancel"] or _cancel.is_set():
        _cancel.set()
    else:
        _cancel.clear()


def cancel():
    """Stop the library scan. A webhook scan keeps running; the parked scan stops when that import lets go."""
    with _lock:
        parked = bool(_parked and (_parked.get("state") or {}).get("status") == "running")
        interrupt = bool(_state.get("interrupt"))
    if not running() and not _paused.is_set() and not parked:
        return False
    _cancel.set()
    _resume.set()
    if _importing or (interrupt and parked):
        with _lock:
            if _parked and _parked.get("state") is not None:
                _parked["state"]["message"] = "Stopping"
        _notify()
        return True
    probe.kill_all()
    with _lock:
        _state["message"] = "Stopping"
    _notify()
    return True


def cancel_import():
    """Stop the webhook scan that is using the lane. The parked library scan is left as it is."""
    if not import_active():
        return False
    _import_cancel.set()
    _resume.set()
    probe.kill_all()
    from curator.video import scrape

    if scrape.running():
        scrape.cancel()
    with _lock:
        if _state.get("status") == "running":
            _state["message"] = "Stopping"
    _notify()
    return True


def import_active(media=None):
    with _lock:
        if _state.get("status") != "running" or not _state.get("interrupt"):
            return False
        if media and _state.get("media") != media:
            return False
        return True


def import_cancelled():
    return _import_cancel.is_set()


def clear_import_cancel():
    _import_cancel.clear()


class _Job:
    def __init__(self, media, mode):
        self.media = media
        self.mode = mode
        self.seen = threading.Lock()
        self.last_push = 0.0
        self._changed = set()
        self._changed_lock = threading.Lock()
        self.extras = []
        self._replaced_movies = set()
        self._replaced_episodes = {}
        self.during_import = False
        self.stopped = False
        self.verbose = False

    def note_changed(self, item_id):
        if item_id:
            with self._changed_lock:
                self._changed.add(str(item_id))

    def note_extra(self, show_id, season, episode, path):
        with self.seen:
            self.extras.append({
                "show_id": str(show_id), "season": season, "episode": episode, "path": path,
            })

    def changed_ids(self):
        with self._changed_lock:
            return list(self._changed)

    def note_replaced_movie(self, movie_id):
        if movie_id:
            with self._changed_lock:
                self._replaced_movies.add(str(movie_id))

    def note_replaced_episode(self, show_id, episode_id):
        if show_id and episode_id:
            with self._changed_lock:
                self._replaced_episodes.setdefault(str(show_id), set()).add(str(episode_id))

    def replaced(self):
        with self._changed_lock:
            episodes = {show_id: list(ids) for show_id, ids in self._replaced_episodes.items()}
            return list(self._replaced_movies), episodes

    def log(self, line):
        if self.verbose:
            logger.info("scan: %s", line)
        stamp = datetime.now().strftime("%H:%M:%S")
        with _lock:
            _log.append(f"{stamp} {line}")
            if self.media in _media_logs:
                _media_logs[self.media].append(f"{stamp} {line}")

    def detail(self, line):
        """A per-file line. Written only when this scan's verbose log is on."""
        if self.verbose:
            self.log(line)

    def count(self, key, step=1):
        with _lock:
            _state["result"][key] = _state["result"].get(key, 0) + step
            if self.media in _media_states:
                _media_states[self.media]["result"][key] = _media_states[self.media]["result"].get(key, 0) + step

    def fail(self, path, error):
        self.log(f"Failed: {path}: {error}")
        with _lock:
            result = _state["result"]
            result["failure_count"] += 1
            if len(result["failures"]) < LIST_LIMIT:
                result["failures"].append({"path": path, "error": str(error)})
            if self.media in _media_states:
                m_result = _media_states[self.media]["result"]
                m_result["failure_count"] += 1
                if len(m_result["failures"]) < LIST_LIMIT:
                    m_result["failures"].append({"path": path, "error": str(error)})

    def unmatched(self, path):
        self.log(f"No season and episode number: {path}")
        with _lock:
            result = _state["result"]
            result["unmatched_count"] += 1
            if len(result["unmatched"]) < LIST_LIMIT:
                result["unmatched"].append(path)
            if self.media in _media_states:
                m_result = _media_states[self.media]["result"]
                m_result["unmatched_count"] += 1
                if len(m_result["unmatched"]) < LIST_LIMIT:
                    m_result["unmatched"].append(path)

    def note_empty(self, path):
        self.log(f"Empty folder: {path}")
        with _lock:
            result = _state["result"]
            result["empty_count"] = result.get("empty_count", 0) + 1
            found = result.setdefault("empty", [])
            if len(found) < LIST_LIMIT:
                found.append(path)
            if self.media in _media_states:
                m_result = _media_states[self.media]["result"]
                m_result["empty_count"] = m_result.get("empty_count", 0) + 1
                m_found = m_result.setdefault("empty", [])
                if len(m_found) < LIST_LIMIT:
                    m_found.append(path)

    def progress(self, message=None, processed=None, total=None, phase=None, force=False,
                 folders_done=None, folders_total=None, files_done=None, files_total=None):
        with _lock:
            target = _media_states.get(self.media)
            if message is not None:
                _state["message"] = message
                if target:
                    target["message"] = message
            if processed is not None:
                _state["processed"] = processed
                if target:
                    target["processed"] = processed
            if total is not None:
                _state["total"] = total
                if target:
                    target["total"] = total
            if folders_done is not None:
                _state["folders_done"] = folders_done
                if target:
                    target["folders_done"] = folders_done
            if folders_total is not None:
                _state["folders_total"] = folders_total
                if target:
                    target["folders_total"] = folders_total
            if files_done is not None:
                _state["files_done"] = files_done
                if target:
                    target["files_done"] = files_done
            if files_total is not None:
                _state["files_total"] = files_total
                if target:
                    target["files_total"] = files_total
            if phase is not None:
                _state["phase"] = phase
                if target:
                    target["phase"] = phase
        from resonance import scan_pace

        scan_pace.note(phase, processed, total)
        now = time.monotonic()
        if force or now - self.last_push > 0.5:
            self.last_push = now
            _notify()

    @property
    def cancelled(self):
        if self.during_import:
            return _import_cancel.is_set()
        if threading.current_thread() is _pause_owner:
            _wait_if_paused()
            with _pause_guard:
                still_held = _importing and _pause.is_set()
            return _cancel.is_set() and not still_held
        with _pause_guard:
            if _importing and _pause_owner is not None:
                return False
        return _cancel.is_set()


def _group_targets(roots, targets):
    from resonance.paths import inside

    groups = {}
    for path in targets:
        real = os.path.realpath(path)
        best = None
        for root in roots:
            if real == root or inside(root, real):
                if best is None or len(root) > len(best):
                    best = root
        if best:
            groups.setdefault(best, []).append(real)
    return groups


def _run_and_release(media, mode, roots, targets=None, season_id=None, episode_id=None, verbose=False):
    try:
        _run(media, mode, roots, targets, season_id, episode_id, verbose=verbose)
    finally:
        from resonance import scan_queue

        scan_queue.finished()


def _run(media, mode, roots, targets=None, season_id=None, episode_id=None, interrupt=False, verbose=False):
    owner = targets is None and not season_id and not episode_id
    if owner:
        bind_pause()
    try:
        _execute_scan(media, mode, roots, targets, season_id, episode_id, interrupt=interrupt, verbose=verbose)
    finally:
        if owner:
            unbind_pause()


def _probe_token(job):
    """Stop flag for a probe. Stopping the parked library scan does not stop the webhook batch."""
    if job.during_import:
        return _import_cancel
    return _cancel


def _pass_finished(job):
    """True when every file in this pass was saved. An unfinished pass must not delete what it found."""
    return not job.cancelled and not job.stopped


def _execute_scan(media, mode, roots, targets=None, season_id=None, episode_id=None, interrupt=False, verbose=False):
    from resonance.settings import verbose_enabled

    job = _Job(media, mode)
    job.verbose = bool(verbose or verbose_enabled())
    job.during_import = bool(interrupt)
    try:
        with _lock:
            recorded = mode if mode in ("incremental", "full", "deep") else "incremental"
            job_id = store.start_job(media, recorded, targets or roots)
            _state["id"] = str(job_id) if job_id else None
    except Exception:
        logger.exception("could not record the scan job")
    noun = "movie" if media == "movies" else "TV"
    word = {"incremental": "Incremental", "full": "Full", "deep": "Deep"}.get(mode, mode.capitalize())
    if episode_id:
        job.log(f"{word} {noun} scan of one episode")
    elif season_id:
        job.log(f"{word} {noun} scan of one season")
    elif targets:
        job.log(f"{word} {noun} scan of {', '.join(targets)}")
    else:
        job.log(f"{word} {noun} scan of {', '.join(roots)}")
    if job.verbose:
        job.log("Verbose log is on. Each file is written here and to the container log.")
    final, message = "completed", ""
    limited = bool(targets) or bool(season_id) or bool(episode_id)
    try:
        if episode_id:
            _scan_one_episode(job, episode_id)
        elif season_id:
            _scan_one_season(job, season_id)
        elif targets:
            groups = _group_targets(roots, targets)
            scan_targets = _scan_movie_targets if media == "movies" else _scan_tv_targets
            if not groups:
                job.log("None of the selected folders are inside a library folder")
            for root, paths in groups.items():
                if job.cancelled:
                    break
                scan_targets(job, root, paths)
        elif media == "movies":
            _scan_movies(job, roots)
        else:
            _scan_tv(job, roots)
        if not job.cancelled and media == "tv" and limited and mode == "deep" and not episode_id:
            from curator.video import scrape

            show_ids, season_numbers = _shows_just_scanned(targets, season_id)
            if show_ids:
                scrape.fill_missing_during_scan(job, show_ids, season_numbers)
            else:
                job.log("Missing episodes: no show was found for this scan")
        if not job.cancelled:
            _log_saved_artwork(job, roots, targets, season_id, episode_id)
        if not job.cancelled and not limited:
            _fill_and_trailers(job, roots)
            if not job.cancelled:
                _subtitles_from_scan(job, roots)
        # A scan of one episode or season cannot change the trailer or theme song of anything else.
        # This runs before the saved filters so "Missing trailer" tags see what is on disk now.
        if not job.cancelled and (not limited or targets):
            try:
                from curator.video import local_extras

                local_extras.refresh(media, targets=targets or None)
            except Exception as exc:
                job.log(f"Could not check trailers and theme songs on disk: {exc}")
        if not job.cancelled and not season_id and not episode_id:
            from curator.video import saved_filters

            try:
                saved_filters.apply_scan_tags(job, roots, targets)
            except Exception as exc:
                job.log(f"Could not apply saved filter tags: {exc}")
            if media == "tv":
                try:
                    _generate_missing_ep_thumbs(job, roots)
                except Exception as exc:
                    job.log(f"Episode thumb generation failed: {exc}")
            _nfos_from_scan(job, roots, targets)
        if not job.cancelled:
            _refresh_replaced(job)
        _note_copies(job)
        if job.cancelled:
            final, message = "cancelled", "Scan stopped. Items already read were kept."
    except probe.Cancelled:
        final, message = "cancelled", "Scan stopped. Items already read were kept."
    except Exception as exc:
        logger.exception("%s scan failed", media)
        final, message = "failed", str(exc)
        job.log(f"Scan failed: {exc}")
    with _lock:
        result = dict(_state["result"])
    _finish_scan(media, final, message, result, job=job)


def _finish_scan(media, final, message, result, job=None):
    if final == "completed" and not message:
        message = _summary(media, result)
    if job:
        job.log(message)
    from resonance import scan_pace

    scan_pace.finish(final == "completed")
    with _lock:
        _state.update({"status": final, "message": message, "phase": "done",
                       "finished_at": datetime.now().isoformat(timespec="seconds")})
        job_id = _state["id"]
        lines = list(_log)
        if media in _media_states:
            _media_states[media] = copy.deepcopy(_state)
            _media_logs[media] = deque(_log, maxlen=LOG_LINES)
    try:
        store.finish_job(job_id, final, message, result)
    except Exception:
        logger.exception("could not record the scan result")
    try:
        from curator import outbound

        outbound.scan_done(media, final, message, _state.get("origin") or "manual")
    except Exception:
        logger.exception("could not send the scan notification")
    _write_log(media, lines)
    _notify()


def _summary(media, result):
    noun = "movies" if media == "movies" else "episodes"
    parts = [f"{result.get('added', 0)} {noun} added", f"{result.get('updated', 0)} updated",
             f"{result.get('unchanged', 0)} unchanged", f"{result.get('removed', 0)} removed",
             f"{result.get('probed', 0)} files probed"]
    if result.get("probe_failed"):
        parts.append(f"{result['probe_failed']} probes failed")
    if result.get("unmatched_count"):
        parts.append(f"{result['unmatched_count']} files without an episode number")
    if result.get("empty_count"):
        parts.append(f"{result['empty_count']} empty folders")
    if result.get("scraped"):
        parts.append(f"{result['scraped']} scraped")
    if result.get("art"):
        parts.append(f"{result['art']} images saved")
    if result.get("scrape_failed"):
        parts.append(f"{result['scrape_failed']} metadata or artwork failures")
    if result.get("subtitles"):
        parts.append(f"{result['subtitles']} subtitles saved")
    if result.get("subtitle_failed"):
        parts.append(f"{result['subtitle_failed']} subtitle lookups failed")
    if result.get("trailers"):
        parts.append(f"{result['trailers']} trailers saved")
    if result.get("trailer_failed"):
        parts.append(f"{result['trailer_failed']} trailer downloads failed")
    if result.get("themes"):
        parts.append(f"{result['themes']} theme songs saved")
    if result.get("theme_failed"):
        parts.append(f"{result['theme_failed']} theme song downloads failed")
    if result.get("nfo"):
        parts.append(f"{result['nfo']} .nfo files written")
    return ", ".join(parts) + "."


_ARTWORK_ORDER = (
    "poster", "fanart", "banner", "clearlogo", "clearart", "landscape", "characterart",
    "discart", "keyart", "squareart", "thumb", "extrafanart", "extrathumbs",
)


def _art_bucket(key):
    """extrafanart12 and extrathumbs3 count as those artwork types."""
    text = str(key or "")
    if text.startswith("extrafanart"):
        return "extrafanart"
    if text.startswith("extrathumbs"):
        return "extrathumbs"
    return text


def _bucket_artwork(rows):
    counts = {}
    for row in rows or []:
        kind = _art_bucket(row.get("key"))
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + int(row.get("n") or 0)
    return counts


def _artwork_report(media, nfos, counts):
    """One line for the .nfo files and every artwork type stored by the folder walk."""
    nfos = nfos or {}
    if media == "movies":
        parts = [f"{int(nfos.get('nfo') or 0)} movie NFO"]
    else:
        parts = [
            f"{int(nfos.get('show_nfo') or 0)} tvshow NFO",
            f"{int(nfos.get('season_nfo') or 0)} season NFO",
            f"{int(nfos.get('episode_nfo') or 0)} episode NFO",
        ]
    seen = set()
    for kind in _ARTWORK_ORDER:
        seen.add(kind)
        amount = int(counts.get(kind) or 0)
        if amount:
            parts.append(f"{amount} {kind}")
    for kind in sorted(set(counts) - seen):
        amount = int(counts.get(kind) or 0)
        if amount:
            parts.append(f"{amount} {kind}")
    return "Saved artwork: " + ", ".join(parts)


def _artwork_folders(roots, targets, season_id, episode_id):
    """Folders this scan just read. None means the whole library roots."""
    if episode_id:
        episode = store.episode_detail(episode_id)
        show = store.show_row(episode["show_id"]) if episode else None
        return [show["path"]] if show and show.get("path") else []
    if season_id:
        season = store.season_row(season_id)
        show = store.show_row(season["show_id"]) if season else None
        return [show["path"]] if show and show.get("path") else []
    if targets:
        return [path for path in targets if path]
    return None


def _under_clause(column, folders):
    from resonance.paths import like_prefix

    clauses, params = [], []
    for folder in folders:
        clauses.append(f"({column} = %s OR {column} LIKE %s ESCAPE '\\')")
        params.extend([folder, like_prefix(folder)])
    return "(" + " OR ".join(clauses) + ")", params


def _log_saved_artwork(job, roots, targets=None, season_id=None, episode_id=None):
    """Log the .nfo files and artwork stored while folders and files were read."""
    from resonance import db

    roots = [root for root in roots if root]
    if not roots:
        job.log("Saved artwork: no library folder")
        return
    folders = _artwork_folders(roots, targets, season_id, episode_id)
    if folders is not None and not folders:
        job.log("Saved artwork: none")
        return
    limit, limit_params = ("", [])
    if folders:
        limit, limit_params = _under_clause("path" if job.media == "movies" else "h.path", folders)
        limit = " AND " + limit
    if job.media == "movies":
        nfos = db.fetchone(
            f"""
            SELECT count(*) FILTER (WHERE nfo_path IS NOT NULL)::int AS nfo
            FROM movies
            WHERE root = ANY(%s){limit}
            """,
            (roots, *limit_params),
        ) or {}
        rows = db.fetchall(
            f"""
            SELECT art.key, count(*)::int AS n
            FROM movies m
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(m.artwork, '{{}}'::jsonb)) AS art(key, value)
            WHERE m.root = ANY(%s){limit.replace("path", "m.path")}
              AND btrim(art.value) <> ''
            GROUP BY art.key
            """,
            (roots, *limit_params),
        )
    else:
        show_limit = limit.replace("h.path", "path")
        nfos = db.fetchone(
            f"""
            SELECT
                (SELECT count(*)::int FROM tv_shows WHERE root = ANY(%s){show_limit} AND nfo_path IS NOT NULL) AS show_nfo,
                (SELECT count(*)::int FROM tv_seasons s
                    JOIN tv_shows h ON h.id = s.show_id
                    WHERE h.root = ANY(%s){limit} AND s.nfo_path IS NOT NULL) AS season_nfo,
                (SELECT count(*)::int FROM tv_episodes e
                    JOIN tv_shows h ON h.id = e.show_id
                    WHERE h.root = ANY(%s){limit} AND e.nfo_path IS NOT NULL) AS episode_nfo
            """,
            (roots, *limit_params, roots, *limit_params, roots, *limit_params),
        ) or {}
        rows = db.fetchall(
            f"""
            SELECT art.key, count(*)::int AS n
            FROM (
                SELECT h.artwork
                FROM tv_shows h
                WHERE h.root = ANY(%s){limit}
                UNION ALL
                SELECT s.artwork
                FROM tv_seasons s
                JOIN tv_shows h ON h.id = s.show_id
                WHERE h.root = ANY(%s){limit}
                UNION ALL
                SELECT e.artwork
                FROM tv_episodes e
                JOIN tv_shows h ON h.id = e.show_id
                WHERE h.root = ANY(%s){limit}
            ) items
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(items.artwork, '{{}}'::jsonb)) AS art(key, value)
            WHERE btrim(art.value) <> ''
            GROUP BY art.key
            """,
            (roots, *limit_params, roots, *limit_params, roots, *limit_params),
        )
    job.log(_artwork_report(job.media, nfos, _bucket_artwork(rows)))


def _refresh_replaced(job):
    """Download artwork that is still missing, then write the new release into the .nfo."""
    movies, episodes = job.replaced()
    if not movies and not episodes:
        return
    from curator.video import config, exports, scrape

    cfg = config.current()
    scrape.fill_replaced_artwork(job, movies, episodes)
    if job.cancelled:
        return
    written = 0
    for movie_id in movies:
        if job.cancelled:
            return
        try:
            if exports.write_movie(movie_id, cfg, "overwrite"):
                written += 1
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
    for show_id, episode_ids in episodes.items():
        if job.cancelled:
            return
        try:
            written += len(exports.write_show(show_id, cfg, "overwrite", episode_ids, True) or [])
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
    if written:
        job.count("nfo", written)
        job.log(f"NFO: rewrote {written} after a replaced file")


def _shows_just_scanned(targets, season_id):
    """Show ids a folder or season deep scan just walked, and the one season when that is all it walked."""
    if season_id:
        season = store.season_row(season_id)
        if not season:
            return [], None
        return [str(season["show_id"])], {int(season["season_number"])}
    return store.show_ids_by_path(targets or []), None


def _trailers_enabled(job, cfg):
    if job.media == "tv":
        return bool(cfg.get("scan_download_tv_trailers"))
    return bool(cfg.get("scan_download_trailers"))


def _themes_enabled(job, cfg):
    if job.media == "tv":
        return bool(cfg.get("scan_download_tv_themes"))
    return bool(cfg.get("scan_download_themes"))


def _subtitles_enabled(job, cfg):
    return bool(cfg.get("subs_download_tv" if job.media == "tv" else "subs_download_movies"))


def _subtitle_units(job, roots, db):
    """Movie or episode ids this scan covers: new and changed ones for an incremental scan, otherwise every one."""
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND COALESCE(path, '') <> ''", (ids,))
        else:
            rows = db.fetchall("SELECT id FROM movies WHERE root = ANY(%s) AND COALESCE(path, '') <> ''", (list(roots),))
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        show_ids = job.changed_ids()
        if not show_ids:
            return []
        rows = db.fetchall(
            "SELECT id FROM tv_episodes WHERE show_id = ANY(%s::uuid[]) AND COALESCE(path, '') <> '' "
            "ORDER BY season_number, episode_number", (show_ids,),
        )
    else:
        rows = db.fetchall(
            "SELECT e.id FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id "
            "WHERE s.root = ANY(%s) AND COALESCE(e.path, '') <> '' ORDER BY s.sort_title, e.season_number, e.episode_number",
            (list(roots),),
        )
    return [("episode", str(row["id"])) for row in rows]


def _subtitles_from_scan(job, roots):
    """Download missing subtitles from OpenSubtitles.com for the wanted languages."""
    from curator.video import config, opensubs
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _subtitles_enabled(job, cfg):
        return
    if not opensubs.can_download(cfg):
        job.log("Subtitles: set the OpenSubtitles API key, username and password in Settings to download them")
        return
    units = _subtitle_units(job, roots, db)
    if not units:
        job.log("Subtitles: nothing to look up")
        return
    saved = failed = 0
    remaining = None
    job.progress(message=f"Subtitles 0/{len(units)}", processed=0, total=len(units), phase="subtitles", force=True)
    for index, (kind, item_id) in enumerate(units, start=1):
        if job.cancelled:
            return
        job.progress(message=f"Subtitles {index}/{len(units)}", processed=index, total=len(units), phase="subtitles")
        try:
            got, left = opensubs.auto_item(cfg, kind, item_id, job.log)
            saved += got
            if left is not None:
                remaining = left
        except opensubs.QuotaError as exc:
            job.log(f"Subtitles: {exc}. The rest wait for the next scan")
            break
        except AppError as exc:
            failed += 1
            job.log(f"Subtitles: {exc}")
            if exc.status == 401:
                break
    job.count("subtitles", saved)
    if failed:
        job.count("subtitle_failed", failed)
    job.log(f"Subtitles: {saved} saved" + (f". {remaining} OpenSubtitles download{'s' if remaining != 1 else ''} left today" if remaining is not None else ""))


def _fill_and_trailers(job, roots):
    """Look up metadata and artwork, and download trailers and theme songs during that same stretch."""
    from curator.video import config

    cfg = config.current()
    job.scan_trailers = _trailers_enabled(job, cfg)
    job.scan_themes = _themes_enabled(job, cfg)
    thread = None
    if job.scan_trailers and cfg.get("scan_fill_missing", True):
        thread = threading.Thread(
            target=_trailers_from_scan, args=(job, roots), kwargs={"alongside": True},
            name="scan-trailers", daemon=True,
        )
        thread.start()
    theme_thread = None
    if job.scan_themes and cfg.get("scan_fill_missing", True):
        theme_thread = threading.Thread(
            target=_themes_from_scan, args=(job, roots), kwargs={"alongside": True},
            name="scan-themes", daemon=True,
        )
        theme_thread.start()
    _fill_from_scan(job, roots)
    if thread:
        thread.join()
    elif job.scan_trailers and not job.cancelled:
        _trailers_from_scan(job, roots)
    if theme_thread:
        theme_thread.join()
    elif job.scan_themes and not job.cancelled:
        _themes_from_scan(job, roots)


def _fill_from_scan(job, roots):
    """Same idea as the music scan: local files first, then missing metadata and artwork."""
    from curator.video import config, scrape

    cfg = config.current()
    if not cfg.get("scan_fill_missing", True):
        job.log("Metadata and artwork during a scan are off in Settings")
        return
    if job.mode == "incremental":
        ids = job.changed_ids()
    elif job.mode == "deep":
        ids = store.ids_in(job.media, roots, "all")
    else:
        ids = list(dict.fromkeys([*store.ids_with_gaps(job.media, roots, cfg), *job.changed_ids()]))
    scrape.fill_during_scan(job, ids, limited=bool(cfg.get("scan_limited_art")))


def _trailers_from_scan(job, roots, alongside=False):
    """Download YouTube trailers that are already known and not on disk yet.

    alongside keeps the lookup progress on screen. Several trailers download at once.
    """
    from curator.video import config, trailers
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _trailers_enabled(job, cfg):
        return
    units = _trailer_units(job, roots, db)
    if job.cancelled:
        return
    if not units:
        job.log("Trailers: nothing to download")
        if not alongside:
            job.progress(message="Trailers: nothing to download", phase="trailers", force=True)
        return
    saved = skipped = 0
    counts = threading.Lock()
    workers = max(1, min(len(units), int(cfg.get("concurrency") or 4)))
    if alongside:
        with _lock:
            _state["trailers_alongside"] = True
            _state["trailers_done"] = False
    if not alongside:
        job.progress(message=f"Trailers 0/{len(units)}", processed=0, total=len(units), phase="trailers", force=True)
    else:
        job.log(f"Trailers: downloading {len(units)} while the lookup runs")

    def one(index_unit):
        nonlocal saved, skipped
        index, unit = index_unit
        if job.cancelled:
            return
        kind, item_id = unit[0], unit[1]
        show_id = unit[2] if len(unit) > 2 else None
        if not alongside:
            job.progress(message=f"Trailers {index}/{len(units)}", processed=index, total=len(units), phase="trailers")
        try:
            with activity.holding() as hold:
                hold(item_id, show_id)
                path = trailers.download(kind, item_id, cfg, job.log, quiet_skip=True)
        except AppError as exc:
            job.log(str(exc))
            job.count("trailer_failed")
            return
        with counts:
            if path:
                saved += 1
                job.count("trailers")
            else:
                skipped += 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trailer") as pool:
        list(pool.map(one, enumerate(units, start=1)))
    if alongside:
        with _lock:
            _state["trailers_alongside"] = False
            _state["trailers_done"] = True
    job.log(f"Trailers: {saved} saved, {skipped} already on disk or without a YouTube link")


def _trailer_units(job, roots, db):
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall(
                "SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
                (ids,),
            )
        else:
            rows = db.fetchall(
                "SELECT id FROM movies WHERE root = ANY(%s) AND COALESCE(trailer, '') <> ''",
                (list(roots),),
            )
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        show_ids = job.changed_ids()
        if not show_ids:
            return []
        shows = db.fetchall(
            "SELECT id FROM tv_shows WHERE id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
            (show_ids,),
        )
        seasons = db.fetchall(
            "SELECT id, show_id FROM tv_seasons WHERE show_id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
            (show_ids,),
        )
    else:
        shows = db.fetchall(
            "SELECT id FROM tv_shows WHERE root = ANY(%s) AND COALESCE(trailer, '') <> ''",
            (list(roots),),
        )
        seasons = db.fetchall(
            """
            SELECT x.id, x.show_id FROM tv_seasons x
            JOIN tv_shows s ON s.id = x.show_id
            WHERE s.root = ANY(%s) AND COALESCE(x.trailer, '') <> ''
            """,
            (list(roots),),
        )
    return [("show", str(row["id"])) for row in shows] + [
        ("season", str(row["id"]), str(row["show_id"])) for row in seasons
    ]


def _themes_from_scan(job, roots, alongside=False):
    """Download theme songs (theme.mp3) for movies or shows that do not have one on disk yet."""
    from curator.video import config, trailers
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _themes_enabled(job, cfg):
        return
    units = _theme_units(job, roots, db)
    if job.cancelled:
        return
    if not units:
        job.log("Theme songs: nothing to download")
        if not alongside:
            job.progress(message="Theme songs: nothing to download", phase="themes", force=True)
        return
    saved = skipped = 0
    counts = threading.Lock()
    workers = max(1, min(len(units), int(cfg.get("concurrency") or 4)))
    if not alongside:
        job.progress(message=f"Theme songs 0/{len(units)}", processed=0, total=len(units), phase="themes", force=True)
    else:
        job.log(f"Theme songs: checking {len(units)} while the lookup runs")

    def one(index_unit):
        nonlocal saved, skipped
        index, unit = index_unit
        if job.cancelled:
            return
        kind, item_id = unit[0], unit[1]
        if not alongside:
            job.progress(message=f"Theme songs {index}/{len(units)}", processed=index, total=len(units), phase="themes")
        try:
            with activity.holding() as hold:
                hold(item_id)
                path = trailers.download_theme(kind, item_id, cfg, job.log, quiet_skip=True)
        except AppError as exc:
            job.log(str(exc))
            job.count("theme_failed")
            return
        with counts:
            if path:
                saved += 1
                job.count("themes")
            else:
                skipped += 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="theme") as pool:
        list(pool.map(one, enumerate(units, start=1)))
    job.log(f"Theme songs: {saved} saved, {skipped} already on disk")


def _theme_units(job, roots, db):
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[])", (ids,))
        else:
            rows = db.fetchall("SELECT id FROM movies WHERE root = ANY(%s)", (list(roots),))
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        show_ids = job.changed_ids()
        if not show_ids:
            return []
        shows = db.fetchall("SELECT id FROM tv_shows WHERE id = ANY(%s::uuid[])", (show_ids,))
    else:
        shows = db.fetchall("SELECT id FROM tv_shows WHERE root = ANY(%s)", (list(roots),))
    return [("show", str(row["id"])) for row in shows]


def _generate_missing_ep_thumbs(job, roots):
    """Generate episode thumbnails using ffmpeg for episodes that have no thumb file.

    Enabled by the scan_generate_ep_thumb setting (default: on).
    Samples from ~40% into the file, skips black frames.
    """
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile
    from curator.video import config
    from resonance import db

    cfg = config.current()
    if not cfg.get("scan_generate_ep_thumb", True):
        return
    if not _shutil.which("ffmpeg") or not _shutil.which("ffprobe"):
        job.log("Episode thumb generation skipped: ffmpeg not found")
        return

    rows = db.fetchall(
        """
        SELECT e.id, e.path, e.season_number, e.episode_number,
               e.artwork
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        WHERE s.root = ANY(%s)
          AND e.path IS NOT NULL
          AND e.path NOT LIKE 'missing://%%'
          AND e.path NOT LIKE 'wanted://%%'
          AND e.status IS DISTINCT FROM 'IGNORED'
        ORDER BY e.path
        """,
        [db.text_array(roots)],
    )
    need_thumb = []
    for row in rows:
        art = row.get("artwork") or {}
        if art.get("thumb") and os.path.isfile(str(art["thumb"])):
            continue
        path = str(row.get("path") or "")
        if not path or not os.path.isfile(path):
            continue
        folder = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        season_num = row.get("season_number")
        ep_num = row.get("episode_number")
        if season_num is not None and ep_num is not None:
            ep_mark = naming.episode_mark(season_num, ep_num)
            thumb_name = f"{stem}-{ep_mark}-thumb.jpg" if ep_mark else f"{stem}-thumb.jpg"
        else:
            thumb_name = f"{stem}-thumb.jpg"
        thumb_path = os.path.join(folder, thumb_name)
        if os.path.isfile(thumb_path):
            continue
        need_thumb.append((row, path, thumb_path))

    if not need_thumb:
        return

    job.progress(message=f"Generating episode thumbs 0/{len(need_thumb)}", processed=0, total=len(need_thumb), phase="nfo", force=True)
    for index, (row, vid_path, thumb_path) in enumerate(need_thumb, start=1):
        if job.cancelled:
            break
        try:
            # Get duration
            probe_result = _subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", vid_path],
                capture_output=True, text=True, timeout=30
            )
            import json as _json
            probe_data = _json.loads(probe_result.stdout or "{}")
            duration = float((probe_data.get("format") or {}).get("duration") or 0)
            if duration < 30:
                continue
            min_pos = max(30, duration * 0.05)
            seek_start = max(0, duration * 0.40 - 60)
            with _tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                result = _subprocess.run(
                    ["ffmpeg", "-y", "-v", "error",
                     "-ss", str(seek_start), "-i", vid_path,
                     "-t", "120",
                     "-vf", r"select=gt(scene\,0.05),scale=1280:-2",
                     "-frames:v", "1", "-q:v", "2", tmp_path],
                    capture_output=True, timeout=60
                )
                if result.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
                    _subprocess.run(
                        ["ffmpeg", "-y", "-v", "error",
                         "-ss", str(min(max(duration * 0.40, min_pos), duration * 0.90)),
                         "-i", vid_path,
                         "-vf", "scale=1280:-2",
                         "-frames:v", "1", "-q:v", "2", tmp_path],
                        capture_output=True, timeout=30
                    )
                if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                    import shutil as _sh2
                    _sh2.move(tmp_path, thumb_path)
                    store.set_artwork("tv_episodes", row["id"], {**(row.get("artwork") or {}), "thumb": thumb_path})
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as exc:
            job.log(f"Episode thumb: {os.path.basename(vid_path)}: {exc}")
        job.progress(message=f"Generating episode thumbs {index}/{len(need_thumb)}", processed=index, total=len(need_thumb), phase="nfo")


def _nfos_from_scan(job, roots, targets=None):
    """Write an .nfo for anything that does not have one. Optionally replace the ones that do."""
    from curator.video import config, exports

    cfg = config.current()
    rewrite = bool(cfg.get("scan_rewrite_nfo"))
    policy = "overwrite" if rewrite else "missing"
    ids = store.ids_for_nfo(job.media, roots, targets or None, rewrite)
    if job.cancelled:
        return
    if not ids:
        job.log("NFO: nothing to write")
        job.progress(message="NFO", processed=1, total=1, phase="nfo", force=True)
        return
    label = "Rewriting .nfo" if rewrite else "Writing missing .nfo"
    written = 0
    job.progress(message=f"{label} 0/{len(ids)}", processed=0, total=len(ids), phase="nfo", force=True)
    for index, item_id in enumerate(ids, start=1):
        if job.cancelled:
            return
        job.progress(message=f"{label} {index}/{len(ids)}", processed=index, total=len(ids), phase="nfo")
        try:
            with activity.holding() as hold:
                hold(item_id)
                made = exports.write_movie(item_id, cfg, policy) if job.media == "movies" else exports.write_show(item_id, cfg, policy)
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
            continue
        made = [made] if isinstance(made, str) else list(made or [])
        if made:
            written += len(made)
            job.count("nfo", len(made))
    note = " Existing files were replaced." if rewrite and written else ""
    job.log(f"NFO: {written} written.{note}")


def _note_copies(job):
    from curator.video import copies

    try:
        count = copies.refresh_movies() if job.media == "movies" else copies.refresh_episodes()
        if count:
            job.log(f"Catalogue: {count} items have a higher-quality copy")
    except Exception as exc:
        job.log(f"Could not record duplicates and upgrades: {exc}")


def _write_log(media, lines):
    from resonance.paths import config_dir
    from resonance.settings import load as load_settings

    folder = os.path.join(config_dir(), "logs")
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        name = f"{stamp}_{media}_scan.log"
        path = os.path.join(folder, name)
        suffix = 2
        while os.path.exists(path):
            name = f"{stamp}-{suffix}_{media}_scan.log"
            path = os.path.join(folder, name)
            suffix += 1
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        keep = max(1, int(load_settings().get("scan_log_keep") or 30))
        stamp_re = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})")
        old = [
            item
            for item in os.listdir(folder)
            if (f"_{media}_scan" in item or item.startswith(f"{media}-scan-"))
            and item.endswith(".log")
        ]
        old.sort(key=lambda item: (stamp_re.search(item).group(1) if stamp_re.search(item) else "", item))
        for item in old[:-keep]:
            os.remove(os.path.join(folder, item))
    except OSError as exc:
        logger.warning("could not write the scan log: %s", exc)


def _stat(path):
    try:
        info = os.stat(path)
        return info.st_size, info.st_mtime
    except OSError:
        return None, None


def _changed(previous, size, mtime):
    if previous is None:
        return True
    if previous["size_bytes"] != size:
        return True
    return previous["mtime"] is None or mtime is None or abs(float(previous["mtime"]) - mtime) > 1


def _stored_epoch(value):
    """A database timestamp as seconds. Naive values are UTC, which is the session timezone."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return None


def _folder_newer(folder, folder_mtime_stored):
    """True when the folder (or any immediate sub-directory) changed after the stored mtime.

    We walk one level into sub-directories (e.g. Subs/) so that a file added there is
    detected even if the parent directory mtime did not change on all NAS/CIFS mounts.
    Pass the folder_mtime column value (TIMESTAMPTZ or None) rather than updated_at.
    """
    if folder_mtime_stored is None:
        return True
    try:
        if isinstance(folder_mtime_stored, str):
            stored_dt = datetime.fromisoformat(folder_mtime_stored)
            if stored_dt.tzinfo is None:
                stored_dt = stored_dt.replace(tzinfo=timezone.utc)
            stamp = stored_dt.timestamp()
        elif hasattr(folder_mtime_stored, "timestamp"):
            dt = folder_mtime_stored
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            stamp = dt.timestamp()
        else:
            return True
    except Exception:
        return True
    try:
        max_mtime = os.stat(folder).st_mtime
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        max_mtime = max(max_mtime, entry.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    pass
    except OSError:
        return True
    return max_mtime > stamp + 1


def _nfo_same(previous):
    """True when the stored .nfo is still the same file with the same modification time."""
    path = (previous or {}).get("nfo_path")
    if not path:
        return True
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return False
    stored = previous.get("nfo_mtime")
    if stored is None:
        return False
    return abs(float(stored) - mtime) <= 1


def _needs_file_work(job, path, known_files):
    """True when this video file has to be opened. Deep opens every file."""
    if job.mode == "deep":
        return True
    size, mtime = _stat(path)
    if size is None:
        return True
    previous = known_files.get(path)
    if previous is None or _changed(previous, size, mtime):
        return True
    extension = naming.ext(os.path.basename(path))
    open_iso = job.media != "tv" and probe.scan_iso()
    name_only = extension == ".vob" or (extension == ".iso" and not open_iso)
    if name_only and previous.get("probe_error"):
        return True
    if extension == ".iso" and open_iso and not previous.get("duration_seconds") and not previous.get("probe_error"):
        return True
    if job.mode == "full" and (previous.get("probe_error") or not previous.get("probed_at")):
        return True
    return False


def _loose_nfo_arrived(unit, previous):
    """A movie that sits in the library root gained an .nfo beside the file."""
    if previous.get("nfo_path") or unit.get("own"):
        return False
    folder = unit["folder"]
    main = (unit.get("files") or [None])[0]
    names = ["movie.nfo"]
    if main:
        names.append(f"{os.path.splitext(os.path.basename(main))[0]}.nfo")
    return any(os.path.isfile(os.path.join(folder, name)) for name in names)


def _movie_can_skip(job, unit, known_files, known_movies):
    """An incremental or full scan leaves this movie alone. Deep never skips."""
    if job.mode == "deep":
        return False
    files = unit.get("files") or []
    if any(_needs_file_work(job, path, known_files) for path in files):
        return False
    if not files and job.mode == "full":
        return False
    previous = _previous_movie(unit, known_movies)
    if previous is None or not _nfo_same(previous):
        return False
    if _loose_nfo_arrived(unit, previous):
        return False
    if unit.get("own") and _folder_newer(unit["folder"], previous.get("folder_mtime") or previous.get("updated_at")):
        return False
    return True


def _files_without_episodes(files, rows):
    """Video paths in this folder that are not stored as an episode yet."""
    stored = {row.get("path") for row in rows or [] if row.get("path")}
    return [os.path.join(folder, name) for folder, name, _season in files if os.path.join(folder, name) not in stored]


def _show_can_skip(job, show, previous, files, known_files, rows):
    """True when every episode file, the show .nfo, and the show folders are unchanged."""
    if job.mode == "deep" or not previous:
        return False
    if _files_without_episodes(files, rows):
        return False
    if not _nfo_same(previous):
        return False
    if not previous.get("nfo_path") and os.path.isfile(os.path.join(show, "tvshow.nfo")):
        return False
    updated = previous.get("folder_mtime") or previous.get("updated_at")
    if _folder_newer(show, updated):
        return False
    seen = set()
    for folder, name, _season in files:
        path = os.path.join(folder, name)
        seen.add(path)
        if _needs_file_work(job, path, known_files) or _folder_newer(folder, updated):
            return False
    known_paths = {row.get("path") for row in rows or []}
    return all(path in known_paths for path in seen)


def _episode_needs_work(job, unit, updated_at):
    """True when this episode must be read. The show parse has already produced the unit."""
    known = unit.get("known") or {}
    pairs = naming.episode_pairs(unit["parsed"])
    if not pairs or any(not known.get(key) or known[key].get("missing") for key in pairs):
        return True
    if job.mode == "deep" or _needs_file_work(job, unit["path"], unit["known_files"]):
        return True
    if _folder_newer(unit["folder"], unit.get("folder_mtime") or updated_at):
        return True
    for key in pairs:
        previous = known.get(key)
        nfo_path = (unit.get("nfo_paths") or {}).get(key)
        nfo_time = nfo.mtime(nfo_path) if nfo_path else None
        if previous is None or previous.get("path") != unit["path"]:
            return True
        if previous.get("nfo_path") != nfo_path or not _mtime_same(previous.get("nfo_mtime"), nfo_time):
            return True
    return False


def _mtime_same(stored, current):
    if stored is None or current is None:
        return stored is None and current is None
    return abs(float(stored) - float(current)) <= 1


def _probe_file(job, path, kind, known_files, folder_names):
    """Probe when needed, store the file row, and return (file_id, changed)."""
    size, mtime = _stat(path)
    if size is None:
        raise FileNotFoundError("The file disappeared during the scan")
    previous = known_files.get(path)
    changed = _changed(previous, size, mtime)
    retry = job.mode == "full" and previous is not None and (previous["probe_error"] or not previous["probed_at"])
    extension = naming.ext(os.path.basename(path))
    open_iso = job.media != "tv" and probe.scan_iso()
    name_only = extension == ".vob" or (extension == ".iso" and not open_iso)
    disc_name = name_only and previous and previous.get("probe_error")
    iso_pending = extension == ".iso" and open_iso and previous and not previous.get("duration_seconds") and not previous.get("probe_error")
    summary = None
    if job.mode != "deep" and not iso_pending:
        summary = mediainfo_xml.read_matching(path, size)
        if summary is not None and not (changed or retry or previous is None):
            summary = None
        elif summary is not None:
            job.log(f"Media info imported from sidecar: {os.path.basename(path)}")
    if summary is None and (job.mode == "deep" or changed or retry or disc_name or iso_pending):
        label = "Reading the disc name" if name_only else "Probing"
        job.log(f"{label} {os.path.basename(path)}")
        summary = probe.analyze(path, _probe_token(job), open_iso=open_iso)
        job.count("probed")
        if summary.get("probe_error"):
            job.count("probe_failed")
            job.log(f"Probe failed: {path}: {summary['probe_error']}")
    video_name = os.path.basename(path)
    external = []
    for real in folder_names.values():
        if naming.ext(real) in naming.SUBTITLE_EXTS:
            info = naming.subtitle_info(video_name, real)
            if info:
                external.append(info)
    file_id = store.save_file(path, kind, size, mtime, summary, external)
    return file_id, changed or summary is not None


def _first_existing(folder, names, candidates):
    for candidate in candidates:
        real = names.get(candidate.lower())
        if real:
            return os.path.join(folder, real)
    return None


class _Stream:
    """Collect the files a walk decides to read, then probe them.

    Incremental and full hold every file until the walk has finished, then probe that list.
    Deep keeps `workers()` files open at once and hands over the next group as workers free.
    """

    def __init__(self, job, worker, label):
        self.job = job
        self.worker = worker
        self.label = label
        self.width = workers()
        self.defer = job.mode != "deep"
        self.later = []
        self.pool = None if self.defer else ThreadPoolExecutor(max_workers=self.width, thread_name_prefix=f"{job.media}-probe")
        self.pending = {}
        self.done = 0
        self.file_done = 0
        self.queued = 0
        self.skipped = 0
        self.walking = True
        self._lock = threading.Lock()

    def skip(self, count=1):
        with self._lock:
            self.skipped += count
        self.job.count("unchanged", count)
        self._progress()

    def submit(self, unit):
        if self.defer:
            self.later.append(unit)
            return
        self._reap(wait=False)
        while not self.job.cancelled:
            with self._lock:
                if len(self.pending) < self.width:
                    break
            self._reap(wait=True)
        if self.job.cancelled:
            return
        future = self.pool.submit(_guarded, self.job, self.worker, unit)
        with self._lock:
            self.pending[future] = unit
            self.queued += 1
        self._progress()

    def close_walk(self):
        self.walking = False
        ready = len(self.later) if self.defer else self.queued
        self.job.log(f"{self.label}: {self.skipped} unchanged, {ready} to read, {self.width} at a time")
        if not self.defer:
            self._progress(force=True)
            return
        units = self.later
        self.later = []
        if units and not self.job.cancelled:
            _run_pool(self.job, units, self.worker, self.label)
            return
        self._progress(force=True)

    def finish(self):
        self.walking = False
        if self.pool is None:
            return
        try:
            while True:
                with self._lock:
                    if not self.pending:
                        break
                if self.job.cancelled:
                    with self._lock:
                        for future in self.pending:
                            future.cancel()
                self._reap(wait=True)
        finally:
            self.pool.shutdown(wait=True, cancel_futures=True)
        self._progress(force=True)

    def _reap(self, wait):
        with self._lock:
            pending = set(self.pending)
        if not pending:
            return
        if wait:
            finished, _ = wait_futures(pending, return_when=FIRST_COMPLETED)
        else:
            finished = {future for future in pending if future.done()}
        if not finished:
            return
        for future in finished:
            with self._lock:
                unit = self.pending.pop(future, None)
                self.done += 1
                files = (unit or {}).get("files")
                self.file_done += len(files) if files else 1
            try:
                future.result()
            except CancelledError:
                pass
            if self.done % 25 == 0:
                from resonance.memory import release

                release()
        self._progress()

    def _progress(self, force=False):
        with self._lock:
            done, queued, skipped, walking = self.done, self.queued, self.skipped, self.walking
            file_done = self.file_done
        if walking:
            if not self.defer:
                self.job.progress(files_done=file_done)
            return
        # The folder walk has its own count. This bar starts again at the files still left to read.
        shown_total = queued or 1
        shown_done = done if queued else 1
        message = f"{self.label} {done}/{queued}" if queued else f"{self.label}: {skipped} unchanged"
        if self.defer:
            self.job.progress(
                message=message, processed=shown_done, total=shown_total,
                files_done=done, files_total=queued, phase="read", force=force,
            )
            return
        self.job.progress(
            message=message, processed=shown_done, total=shown_total,
            files_done=file_done, phase="read", force=force,
        )


def _run_pool(job, units, worker, label):
    """Probe a few files at a time. A large library does not queue every file at once."""
    total = len(units)
    width = workers()
    job.detail(f"{label}: {total} files, {width} at a time")
    job.progress(message=f"{label} 0/{total}", processed=0, total=total, files_done=0, files_total=total, phase="read", force=True)
    done = 0
    pending = {}
    incoming = iter(units)

    def launch(pool):
        if job.cancelled:
            return False
        try:
            unit = next(incoming)
        except StopIteration:
            return False
        pending[pool.submit(_guarded, job, worker, unit)] = unit
        return True

    with ThreadPoolExecutor(max_workers=width, thread_name_prefix=f"{job.media}-probe") as pool:
        for _ in range(width):
            if not launch(pool):
                break
        while pending:
            finished, _ = wait_futures(set(pending), return_when=FIRST_COMPLETED)
            for future in finished:
                pending.pop(future, None)
                future.result()
                done += 1
                job.progress(message=f"{label} {done}/{total}", processed=done, total=total, files_done=done, files_total=total)
                if done % 25 == 0:
                    from resonance.memory import release

                    release()
            if job.cancelled:
                for future in pending:
                    future.cancel()
                break
            while len(pending) < width and launch(pool):
                pass
    job.progress(processed=done, force=True)


def _guarded(job, worker, unit):
    if job.cancelled:
        return
    from resonance.memory import wait as wait_for_memory

    wait_for_memory(job.log, stop=lambda: job.cancelled)
    if job.cancelled:
        return
    try:
        worker(unit)
    except probe.Cancelled:
        job.stopped = True
        return
    except Exception as exc:
        logger.exception("scan item failed: %s", unit.get("path"))
        job.fail(unit.get("path") or "", f"{type(exc).__name__}: {exc}" if job.verbose else exc)


# Movies


def _claim_part_dirs(dirpath, dirnames, loose_names):
    """Take CD1/CD2 folders out of the walk when they are discs of one movie.

    A lone CD2 folder stays where it is. Two part numbers, from these folders or from
    cd1/cd2 file names beside them, are one movie in the parent folder.
    """
    candidates = []
    for name in dirnames:
        number = naming.part_dir_number(name)
        if number is None:
            continue
        rel = _one_part_video(os.path.join(dirpath, name), name)
        if rel is None:
            continue
        candidates.append((number, rel, name))
    loose_numbers = set()
    for name in loose_names:
        stacked = naming.stack_key(name)
        if stacked:
            loose_numbers.add(stacked[1])
    numbers = {number for number, _rel, _name in candidates} | loose_numbers
    if len(numbers) < 2:
        return []
    drop = {name for _number, _rel, name in candidates}
    dirnames[:] = [name for name in dirnames if name not in drop]
    return [(number, rel) for number, rel, _name in candidates]


def _contains_video(folder, depth=4):
    """True when a sidecar folder holds a real video. Image folders such as trickplay do not."""
    if depth < 0:
        return True
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return True
    for entry in entries:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return True
        if is_dir:
            if naming.skip_dir(entry.name) or naming.is_extra_dir(entry.name):
                continue
            if _contains_video(entry.path, depth - 1):
                return True
            continue
        if entry.name.startswith(".") or not naming.is_video(entry.name) or naming.is_extra_file(entry.name):
            continue
        return True
    return False


def _one_part_video(folder, dirname):
    """Relative path of the one video in a part folder, or None when the folder is not that simple."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return None
    videos = []
    for entry in entries:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return None
        if is_dir:
            if entry.name.lower() in naming.DISC_DIRS or naming.part_dir_number(entry.name):
                return None
            if naming.skip_dir(entry.name) or naming.is_extra_dir(entry.name):
                continue
            if _contains_video(entry.path):
                return None
            continue
        if entry.name.startswith(".") or not naming.is_video(entry.name) or naming.is_extra_file(entry.name):
            continue
        videos.append(entry.name)
    if len(videos) != 1:
        return None
    return os.path.join(dirname, videos[0])


def _stack_group_head(names):
    heads = []
    for name in names:
        stacked = naming.stack_key(os.path.basename(name))
        if not stacked:
            return None
        heads.append(stacked[0].split("|")[0])
    if not heads or len(set(heads)) != 1:
        return None
    return heads[0]


def _merge_part_files(groups, part_rels):
    """Add CD-folder videos to the matching cd1/cd2 file group, or make one group of them."""
    if not part_rels:
        return groups
    stacked = {}
    plain = []
    for group in groups:
        head = _stack_group_head(group)
        if head is None:
            plain.append(group)
            continue
        bucket = stacked.setdefault(head, [])
        for name in group:
            bucket.append((naming.stack_key(name)[1], name))
    folder_parts = []
    for number, rel in part_rels:
        base = os.path.basename(rel)
        key = naming.stack_key(base)
        head = key[0].split("|")[0] if key else None
        part = key[1] if key else number
        if head and head in stacked:
            stacked[head].append((part, rel))
            continue
        if len(stacked) == 1:
            only = next(iter(stacked.values()))
            if part not in {item[0] for item in only}:
                only.append((part, rel))
                continue
        folder_parts.append((part, rel))
    out = list(plain)
    for items in stacked.values():
        items.sort()
        out.append([rel for _part, rel in items])
    if folder_parts:
        folder_parts.sort()
        out.append([rel for _part, rel in folder_parts])
    out.sort(key=lambda group: group[0].lower())
    return out


def _in_part_dir(dirpath, path):
    rel = os.path.relpath(path, dirpath)
    first, sep, _rest = rel.partition(os.sep)
    return bool(sep) and naming.part_dir_number(first) is not None


def _prefers_folder(dirpath, files):
    """A multi-disc movie that uses CD1/CD2 folders is the movie at the parent folder."""
    return len(files) > 1 and any(_in_part_dir(dirpath, path) for path in files)


def _count_tree(job, folder, library_root, tv):
    """Folders and video files under one folder. Names only: no .nfo read and no probe."""
    folders = 0
    files = 0
    for _dirpath, dirnames, filenames in os.walk(folder):
        if job.cancelled:
            break
        folders += 1
        at_library_root = os.path.normcase(os.path.normpath(_dirpath)) == os.path.normcase(os.path.normpath(library_root))
        disc = any(name.lower() in naming.DISC_DIRS for name in dirnames)
        dirnames[:] = [
            name for name in dirnames
            if not naming.skip_dir(name)
            and name.lower() not in naming.DISC_DIRS
            and (tv or at_library_root or not naming.is_extra_dir(name))
            and (not tv or not naming.is_extra_dir(name, tv=True))
        ]
        if disc and _dirpath != library_root:
            files += 1
            dirnames[:] = []
            continue
        files += sum(
            1 for name in filenames
            if not name.startswith(".") and naming.is_video(name) and not naming.is_extra_file(name)
        )
        if folders % 250 == 0:
            job.progress(message=f"Counting folders and files: {folders} folders, {files} video files")
    return folders, files


def _count_for_deep(job, places, tv):
    """A deep scan counts first so the progress bar has a fixed file total."""
    if job.mode != "deep":
        return
    job.progress(message="Counting folders and files", force=True)
    folders = 0
    files = 0
    for folder, library_root in places:
        if job.cancelled:
            break
        if not folder or not os.path.isdir(folder):
            continue
        more_folders, more_files = _count_tree(job, folder, library_root, tv)
        folders += more_folders
        files += more_files
    job.log(f"Counted {folders} folders, {files} video files")
    job.progress(
        message=f"Counted {folders} folders, {files} video files",
        folders_done=0, folders_total=folders or 1, files_done=0, files_total=files, force=True,
    )


def _top_names(folder):
    """Names directly inside a library or movie folder, in walk order."""
    try:
        with os.scandir(folder) as entries:
            names = [entry.name for entry in entries if entry.name and not naming.skip_dir(entry.name)]
    except OSError:
        return []
    names.sort(key=str.lower)
    return names


def _movie_units(job, root, start=None, on_ready=None, on_folder=None):
    """List movie units. on_ready receives each folder's units as soon as that folder is grouped."""
    units = []
    _bad_dirs: set[str] = set()

    def unreadable(exc):
        bad = getattr(exc, "filename", None)
        if bad and bad not in _bad_dirs:
            _bad_dirs.add(bad)
            job.log(f"Cannot read folder (skipped): {bad}: {exc}")

    def hand(ready):
        if on_ready and ready:
            on_ready(ready)

    origin = start or root
    seen_tops = set()
    _seen_real: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(origin, onerror=unreadable, followlinks=True):
        if job.cancelled:
            break
        _real = os.path.realpath(dirpath)
        if _real in _seen_real:
            dirnames[:] = []
            continue
        _seen_real.add(_real)
        relative = os.path.relpath(dirpath, origin)
        top = None if relative == "." else relative.split(os.sep)[0]
        if top and top not in seen_tops:
            seen_tops.add(top)
            if on_folder:
                on_folder(len(seen_tops))
        disc = next((naming.DISC_DIRS[name.lower()] for name in dirnames if name.lower() in naming.DISC_DIRS), None)
        at_library_root = os.path.normcase(os.path.normpath(dirpath)) == os.path.normcase(os.path.normpath(root))
        dirnames[:] = sorted(
            name for name in dirnames
            if not naming.skip_dir(name)
            and (at_library_root or not naming.is_extra_dir(name))
            and name.lower() not in naming.DISC_DIRS
        )
        if disc and dirpath != root:
            unit = {"root": root, "folder": dirpath, "path": dirpath, "files": [], "disc": disc, "own": True}
            units.append(unit)
            dirnames[:] = []
            hand([unit])
            continue
        videos = [name for name in filenames if naming.is_video(name) and not name.startswith(".")
                  and not naming.is_extra_file(name)]
        part_rels = _claim_part_dirs(dirpath, dirnames, videos)
        if not videos and not part_rels:
            continue
        groups = _merge_part_files(naming.group_stacks(videos) if videos else [], part_rels)
        exclusive = dirpath != root and len(groups) == 1
        folder_taken = False
        ready = []
        for group in groups:
            files = [os.path.join(dirpath, name) for name in group]
            use_folder = exclusive or (not folder_taken and _prefers_folder(dirpath, files))
            if use_folder:
                folder_taken = True
            unit = {"root": root, "folder": dirpath, "path": dirpath if use_folder else files[0],
                    "files": files, "disc": None, "own": dirpath != root and use_folder}
            units.append(unit)
            ready.append(unit)
        hand(ready)
        if len(units) % 200 == 0:
            job.progress(message=f"Reading folders: {len(units)} movies found")
    return units


def _movie_name(unit):
    folder_name = os.path.basename(unit["folder"])
    main = unit["files"][0] if unit["files"] else None
    if unit["own"]:
        parsed = naming.parse_title(folder_name)
        if main and not parsed["year"]:
            from_file = naming.parse_title(os.path.basename(main), strip_ext=True)
            if from_file["year"]:
                return from_file
        return parsed
    return naming.parse_title(os.path.basename(main), strip_ext=True)


def _filled(value):
    """True when a stored field already has something worth keeping."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def kept_metadata(previous, values):
    """Keep title, year, plot, tagline, ratings, cast and certification when the stored copy has them.

    An empty field is left for the new .nfo, folder name or scrape to fill in.
    """
    if not previous:
        return values
    for key in ("title", "plot", "tagline", "mpaa"):
        if _filled(previous.get(key)):
            values[key] = previous.get(key)
    if _filled(previous.get("year")):
        values["year"] = previous.get("year")
    if _filled(previous.get("ratings")):
        values["ratings"] = previous.get("ratings")
    if _filled(previous.get("rating")):
        values["rating"] = previous.get("rating")
    if _filled(previous.get("votes")):
        values["votes"] = previous.get("votes")
    for key in ("actors", "guest_stars"):
        if _filled(previous.get(key)):
            values[key] = previous.get(key)
    if _filled(previous.get("certifications")):
        values["certifications"] = previous.get("certifications")
    return values


def _same_paths(left, right):
    def norm(path):
        return os.path.normcase(os.path.normpath(path))

    return {norm(path) for path in left if path} == {norm(path) for path in right if path}


def files_replaced(old_paths, new_paths):
    """True when the video file changed and the previous file is no longer on disk."""
    old_paths = [path for path in (old_paths or []) if path]
    new_paths = [path for path in (new_paths or []) if path]
    if not old_paths or not new_paths or _same_paths(old_paths, new_paths):
        return False
    return any(not os.path.exists(path) for path in old_paths)


def _video_stems(paths):
    stems = []
    for path in paths or []:
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem and stem not in stems:
            stems.append(stem)
        head = naming.stack_head(path)
        if head and head not in stems:
            stems.append(head)
    return stems


def _other_videos(folder, own_files):
    own = {os.path.normcase(os.path.abspath(path)) for path in own_files or []}
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    for name in names:
        if not naming.is_video(name):
            continue
        path = os.path.join(folder, name)
        if os.path.normcase(os.path.abspath(path)) not in own:
            found.append(path)
    return found


def _previous_movie(unit, known_movies):
    direct = known_movies.get(unit["path"])
    if direct:
        return direct
    folder = os.path.normcase(os.path.normpath(unit["folder"]))
    gone = []
    for row in known_movies.values():
        row_folder = row.get("folder") or os.path.dirname(row.get("path") or "")
        if os.path.normcase(os.path.normpath(row_folder)) != folder:
            continue
        old = list(row.get("parts") or []) or [row.get("path") or ""]
        if old and all(path and not os.path.exists(path) for path in old):
            gone.append(row)
    if len(gone) == 1:
        return gone[0]
    return None


def _release_for(unit):
    main = unit["files"][0] if unit.get("files") else ""
    folder_name = os.path.basename(unit["folder"]) if unit.get("own") else ""
    return probe.combined_release(os.path.basename(main) if main else "", folder_name)


def _fill_named_edition(previous, unit):
    """An unchanged movie with no edition takes one named in the file or its folder.

    A stored NONE is the empty placeholder from an .nfo, so it is cleared first.
    """
    if not previous:
        return
    from curator.video.sources import canonical_edition

    stored = str(previous.get("edition") or "").strip()
    if stored and not canonical_edition(stored):
        store.clear_placeholder_edition(previous["id"], previous.get("file_id"))
        previous["edition"] = ""
        stored = ""
    if stored:
        return
    edition = (_release_for(unit) or {}).get("edition")
    if edition:
        store.set_movie_edition(previous["id"], previous.get("file_id"), edition)


def _process_movie(job, unit, known_files, known_movies, listings):
    with activity.holding() as hold:
        _process_movie_held(job, unit, known_files, known_movies, listings, hold)


def _process_movie_held(job, unit, known_files, known_movies, listings, hold):
    folder = unit["folder"]
    main = unit["files"][0] if unit["files"] else None
    stem = os.path.splitext(os.path.basename(main))[0] if main else None
    art_stem = stem
    if stem and len(unit["files"]) > 1:
        head = naming.stack_head(main)
        if head:
            art_stem = head
    previous = _previous_movie(unit, known_movies)
    if previous:
        hold(previous["id"])
    old_paths = list((previous or {}).get("parts") or []) or ([previous["path"]] if previous and previous.get("path") else [])
    replaced = files_replaced(old_paths, unit["files"])
    if replaced and art_stem:
        moved = artwork.retarget_sidecars(
            folder, _video_stems(old_paths), art_stem, _other_videos(folder, unit["files"]),
        )
        listings.pop(folder, None)
        if moved:
            job.log(f"Renamed {len(moved)} artwork file{'s' if len(moved) != 1 else ''} for {os.path.basename(main or folder)}")
    if replaced and previous and previous.get("path") and previous["path"] != unit["path"]:
        store.retarget_movie(previous["id"], unit["path"], folder)
        known_movies.pop(previous["path"], None)
        previous = dict(previous)
        previous["path"] = unit["path"]
        previous["folder"] = folder
        known_movies[unit["path"]] = previous
    names = artwork.listing(folder, listings)
    release = naming.release_nfo_dir(folder, unit.get("files") or [], unit.get("root") or "")
    release_nfo = os.path.join(release, f"{os.path.basename(release)}.nfo") if release else ""
    candidates = []
    if stem:
        candidates.append(f"{stem}.nfo")
        stacked = naming.stack_key(os.path.basename(main))
        if stacked and len(unit["files"]) > 1:
            head = stacked[0].split("|")[0]
            candidates.append(f"{head}.nfo")
    if unit["own"]:
        candidates.extend(["movie.nfo", f"{os.path.basename(folder)}.nfo"])
    nfo_path = release_nfo if release_nfo and os.path.isfile(release_nfo) else _first_existing(folder, names, candidates)
    nfo_time = nfo.mtime(nfo_path) if nfo_path else None
    art = artwork.movie(folder, art_stem, own_folder=unit["own"], cache={folder: names})

    file_id, file_changed = (None, False)
    for part in unit["files"]:
        part_id, changed = _probe_file(job, part, "movie", known_files, names)
        if file_id is None:
            file_id, file_changed = part_id, changed
        else:
            file_changed = file_changed or changed
    unchanged = (previous is not None and not file_changed and previous["nfo_path"] == nfo_path
                 and previous["nfo_mtime"] == nfo_time and previous["file_id"] == file_id)
    if job.mode == "incremental" and unchanged:
        if (previous["artwork"] or {}) != art:
            store.set_artwork("movies", previous["id"], art)
        _fill_named_edition(previous, unit)
        job.count("unchanged")
        job.detail(f"Unchanged: {os.path.basename(main or folder)}")
        return

    parsed = _movie_name(unit)
    data = nfo.read_movie(nfo_path) if nfo_path else None
    if nfo_path and data is None:
        job.log(f"Unreadable .nfo, using the folder name: {nfo_path}")
    data = data or {}
    ids = dict(parsed["ids"])
    ids.update(data.get("ids") or {})
    release_facts = _release_for(unit) if replaced else None
    if file_id and data.get("source") and not replaced:
        store.fill_empty_source(file_id, data["source"])
    from curator.video.sources import canonical_edition

    if release_facts is not None:
        edition = release_facts.get("edition")
    else:
        edition = canonical_edition(data.get("edition") or parsed["edition"])
        if not edition:
            edition = (_release_for(unit) or {}).get("edition")
    set_id = None
    if data.get("set"):
        set_id = store.save_set(data["set"])
    values = {
        "path": unit["path"], "root": unit["root"], "folder": folder, "file_id": file_id,
        "parts": unit["files"], "disc_format": unit["disc"],
        "title": data.get("title") or parsed["title"], "original_title": data.get("original_title"),
        "english_title": data.get("english_title"),
        "sort_title": data.get("sort_title"), "year": data.get("year") or parsed["year"], "edition": edition,
        "tagline": data.get("tagline"), "outline": data.get("outline"), "plot": data.get("plot"),
        "runtime_minutes": data.get("runtime"), "mpaa": data.get("mpaa"),
        "premiered": data.get("premiered"),
        "genres": data.get("genres") or [], "countries": data.get("countries") or [],
        "studios": data.get("studios") or [], "tags": data.get("tags") or [],
        "directors": data.get("directors") or [], "writers": data.get("writers") or [],
        "actors": data.get("actors") or [], "ids": ids, "imdb_id": ids.get("imdb"), "tmdb_id": ids.get("tmdb"),
        "ratings": data.get("ratings") or {}, "rating": data.get("rating"), "votes": data.get("votes"),
        "top250": data.get("top250"), "set_id": set_id, "trailer": data.get("trailer"),
        "playcount": data.get("playcount") or 0, "last_played": data.get("last_played"),
        "date_added": data.get("date_added"), "nfo_path": nfo_path, "nfo_mtime": nfo_time, "artwork": art,
    }
    if data.get("certifications"):
        values["certifications"] = data["certifications"]
    if replaced:
        kept_metadata(previous, values)
    store.claim_wanted_movie(ids.get("tmdb"), unit["path"], folder)
    movie_id, inserted = store.save_movie(values)
    hold(movie_id)
    if replaced and file_id and release_facts:
        store.apply_release_names(file_id, release_facts)
        job.note_replaced_movie(movie_id)
    if set_id and (inserted or str((previous or {}).get("set_id") or "") != str(set_id)):
        store.note_set_new(set_id)
    job.note_changed(movie_id)
    if inserted:
        job.count("added")
        year = f" ({values['year']})" if values["year"] else ""
        job.log(f"Added: {values['title']}{year}")
    else:
        job.count("updated")


def _offer_movies(job, ready, known_files, known_movies, stream):
    """Hand one folder's movies to the probe workers, or count them unchanged."""
    for unit in ready:
        if _movie_can_skip(job, unit, known_files, known_movies):
            _fill_named_edition(_previous_movie(unit, known_movies), unit)
            stream.skip(1)
            name = (unit.get("files") or [unit["folder"]])[0]
            job.detail(f"Unchanged: {os.path.basename(name)}")
        else:
            stream.submit(unit)


def _scan_movies(job, roots):
    _drop_removed_paths("movie_paths", "movies")
    _count_for_deep(job, [(root, root) for root in roots], tv=False)
    known_files = store.known_files(roots)
    known_movies = store.known_movies(roots)
    listings = {}
    walked = []
    stream = _Stream(job, lambda unit: _process_movie(job, unit, known_files, known_movies, listings), "Movies")
    counted = {root: _top_names(root) for root in roots if os.path.isdir(root)}
    folder_total = sum(len(names) for names in counted.values()) or 1
    folder_base = 0
    job.progress(processed=0, total=folder_total, folders_done=0, folders_total=folder_total, force=True)
    try:
        for root in roots:
            if not os.path.isdir(root) or not _has_entries(root):
                job.fail(root, "The folder is empty or not mounted")
                continue
            if job.cancelled:
                break
            job.progress(message=f"Reading folders in {root}", force=True)
            base = folder_base

            def report_folder(done, base=base):
                job.progress(processed=base + done, total=folder_total, folders_done=base + done, folders_total=folder_total)

            found = _movie_units(
                job, root,
                on_ready=lambda ready: _offer_movies(job, ready, known_files, known_movies, stream),
                on_folder=report_folder,
            )
            folder_base += len(counted.get(root, ()))
            if found is None:
                job.fail(root, "The folder could not be read")
                continue
            walked.append((root, {unit["path"] for unit in found}))
        stream.close_walk()
    finally:
        stream.finish()
    if not _pass_finished(job):
        if job.stopped:
            job.log("Stopped before every movie was saved, so nothing was removed")
        return
    job.progress(message="Checking for movies that are gone", phase="cleanup", force=True)
    # Measure every root first, so the mount each one sits on can be judged as a whole.
    from resonance.paths import mount_for
    from resonance.settings import prune_safety_on

    safety = prune_safety_on()
    measured = []
    for root, keep in walked:
        known_in_root = sum(1 for m in (store.known_movies([root]) or {}).values()
                            if m.get("root") == root or str(m.get("root", "")).startswith(root))
        measured.append((root, keep, known_in_root))

    # A mount can hold several library paths, of more than one media type, so a mount that came
    # back half-populated has to be judged across all of its paths at once: each path on its own
    # could stay under the per-path limit while the mount loses a great deal.
    mounts = {}
    for root, keep, known_in_root in measured:
        agg = mounts.setdefault(mount_for(root), {"known": 0, "remove": 0, "roots": []})
        agg["known"] += known_in_root
        agg["remove"] += max(0, known_in_root - len(keep))
        agg["roots"].append(root)
    blocked = set()
    for mount, agg in mounts.items():
        if safety and mount and agg["known"] > 10 and agg["remove"] > agg["known"] * 0.20:
            blocked.add(mount)
            job.log(
                f"Prune safety: the mount {mount} would lose {agg['remove']}/{agg['known']} "
                f"movies ({100 * agg['remove'] // agg['known']}%) across {len(agg['roots'])} "
                f"library path(s), so none of them were pruned. Run a full scan if this is "
                f"expected."
            )

    for root, keep, known_in_root in measured:
        if mount_for(root) in blocked:
            store.mark_prune_held("movies", root, keep, True)
            continue
        to_remove = max(0, known_in_root - len(keep))
        if not keep and known_in_root:
            # Readable but nothing found: a mount that came back empty. Pruning here would
            # wipe the whole root, so leave it and let the user remove the path instead.
            job.log(
                f"Prune safety: {root} is readable but no movie was found in it, so none of "
                f"its {known_in_root} indexed movies were removed. Remove the path in "
                f"Settings and scan again if they should go."
            )
            store.mark_prune_held("movies", root, keep, True)
            continue
        if safety and known_in_root > 10 and to_remove > known_in_root * 0.20:
            job.log(
                f"Prune safety: would remove {to_remove}/{known_in_root} movies from {root} "
                f"({100 * to_remove // known_in_root}%) – skipping. "
                f"Run a full scan if this is expected."
            )
            store.mark_prune_held("movies", root, keep, True)
            continue
        removed = store.prune_movies(root, keep)
        store.mark_prune_held("movies", root, keep, False)
        if removed:
            job.count("removed", len(removed))
            note_removed("movies", removed)
            job.log(f"Removed {len(removed)} movies that are no longer under {root}")
    _clear_removed_paths(job, "movies")
    files, sets = store.drop_orphans()
    if sets:
        job.log(f"Removed {sets} movie sets with no movies")


def _clear_removed_paths(job, media):
    """Remove items filed under library paths the user took out of Settings.

    This is the only thing that removes a folder's items wholesale, and it removes rows only:
    no file is touched. A path that merely stopped being configured - an offline mount, an
    excluded folder, a hand-edited config - is never treated as a removal.
    """
    from resonance.settings import take_path_removals

    noun = "movies" if media == "movies" else "shows"
    for gone in take_path_removals(media):
        removed, wanted_gone = store.remove_under_root(media, gone)
        if removed:
            note_removed(media, removed)
            job.count("removed", len(removed))
        extra = f", {wanted_gone} of them wanted" if wanted_gone else ""
        job.log(
            f"Removed {len(removed)} {noun}{extra} from the database, indexed under {gone}, "
            f"which is no longer a library path. No files were touched."
        )
    # Anything still filed under a root that Settings no longer lists, whether or not the
    # folder exists on another mount: it does not belong to this media type's library.
    from resonance.paths import configured_library_paths

    kind = "movies" if media == "movies" else "tv"
    from curator import folders

    roots = list(configured_library_paths(kind)) + list(folders.mounted(kind))
    removed, wanted_gone = store.remove_outside_roots(media, roots)
    if removed:
        note_removed(media, removed)
        job.count("removed", len(removed))
        extra = f", {wanted_gone} of them wanted" if wanted_gone else ""
        job.log(
            f"Removed {len(removed)} {noun}{extra} from the database that sat outside every "
            f"{kind} library path. No files were touched."
        )


def _has_entries(folder):
    try:
        with os.scandir(folder) as entries:
            return any(True for _ in entries)
    except OSError:
        return False


def _scan_movie_targets(job, root, targets):
    if not _has_entries(root):
        job.fail(root, "The movie folder is empty or not mounted")
        return
    _count_for_deep(job, [(target, root) for target in targets if os.path.isdir(target)], tv=False)
    known_files = store.known_files([root])
    known_movies = store.known_movies([root])
    listings = {}
    walked = []
    stream = _Stream(job, lambda unit: _process_movie(job, unit, known_files, known_movies, listings), "Movies")
    try:
        for target in targets:
            if job.cancelled:
                break
            start = target if os.path.isdir(target) else None
            names = _top_names(start) if start else []
            folder_total = len(names) or 1

            def report_folder(done, total=folder_total):
                job.progress(processed=done, total=total, folders_done=done, folders_total=total)

            found = _movie_units(
                job, root, start=start,
                on_ready=lambda ready: _offer_movies(job, ready, known_files, known_movies, stream),
                on_folder=report_folder,
            ) if start else []
            if found is None:
                job.fail(target, "The folder could not be read")
                continue
            walked.append((target, {unit["path"] for unit in found}))
            if not start:
                job.log(f"Gone from disk: {target}")
        stream.close_walk()
    finally:
        stream.finish()
    if not _pass_finished(job):
        if job.stopped:
            job.log("Stopped before every movie was saved, so nothing was removed")
        return
    job.progress(message="Checking for movies that are gone", phase="cleanup", force=True)
    for target, keep in walked:
        removed = store.prune_movies_under(root, target, keep)
        if removed:
            job.count("removed", len(removed))
            note_removed("movies", removed)
            job.log(f"Removed {len(removed)} movies that are no longer in {target}")
    store.drop_orphans()


# TV shows


def _drop_removed_paths(key, label):
    """Rows left behind after a library folder was taken out of Settings."""
    from resonance.settings import load

    paths = load().get(key) or []
    if not paths:
        return
    movies, shows = store.drop_unconfigured(paths if key == "movie_paths" else None,
                                            paths if key == "tv_paths" else None)
    removed = movies if key == "movie_paths" else shows
    if removed:
        logger.info("Removed %s %s whose library folder is no longer configured", removed, label)


def _show_folders(root):
    has_nfo = os.path.isfile(os.path.join(root, "tvshow.nfo"))
    shows = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_dir() and not naming.skip_dir(entry.name):
                    shows.append(entry.path)
    except OSError:
        return None
    # Only treat the root as the single show when tvshow.nfo exists AND there are no show
    # sub-folders.  If sub-folders exist the nfo belongs to one show in a multi-show root
    # and we must not accidentally wipe the others during prune.
    if has_nfo and not shows:
        return [root]
    return sorted(shows, key=str.lower)


def _episode_files(job, show):
    """Episode files, plus folders that contain none.

    An empty folder is a show or season directory with no episode video in it. Extras are
    ignored. The reason the folder is empty does not matter, and it is never treated as work
    for the episode probe.
    """
    found = []
    walk_failed = False
    show_has_video = False
    child_has_video = set()
    children = []

    def on_error(err):
        nonlocal walk_failed
        walk_failed = True
        job.log(f"Error reading {getattr(err, 'filename', show)}: {err}")

    _ep_seen_real: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(show, onerror=on_error, followlinks=True):
        if job.cancelled:
            break
        _ep_real = os.path.realpath(dirpath)
        if _ep_real in _ep_seen_real:
            dirnames[:] = []
            continue
        _ep_seen_real.add(_ep_real)
        dirnames[:] = sorted(name for name in dirnames if not naming.skip_dir(name) and not naming.is_extra_dir(name, tv=True))
        relative = os.path.relpath(dirpath, show)
        if relative == ".":
            children = list(dirnames)
        folder_season = None
        if relative != ".":
            for part in reversed(relative.split(os.sep)):
                folder_season = naming.season_from_dir(part)
                if folder_season is not None:
                    break
        videos = [name for name in filenames if naming.is_video(name) and not name.startswith(".") and not naming.is_extra_file(name)]
        if videos:
            show_has_video = True
            if relative != ".":
                child_has_video.add(relative.split(os.sep)[0])
        for name in sorted(videos, key=str.lower):
            found.append((dirpath, name, folder_season))
    if walk_failed:
        return None, []
    empty = [os.path.join(show, name) for name in children if name not in child_has_video]
    if not show_has_video and not empty:
        empty.append(show)
    return found, empty


def _episode_numbers(job, folder, name, folder_season, names):
    parsed = naming.parse_episode(name, folder_season)
    stem = os.path.splitext(name)[0]
    combined = _first_existing(folder, names, [f"{stem}.nfo"])
    blocks = nfo.read_episodes(combined) if combined else []
    if parsed is None:
        numbered = [block for block in blocks if block.get("season") is not None and block.get("episode") is not None]
        if not numbered:
            return None, {}, blocks
        parsed = {"season": numbered[0]["season"], "episodes": [block["episode"] for block in numbered
                   if block["season"] == numbered[0]["season"]], "title": None,
                  "parts": []}
        for block in numbered:
            part = next((item for item in parsed["parts"] if item["season"] == block["season"]), None)
            if part is None:
                parsed["parts"].append({"season": block["season"], "episodes": [block["episode"]]})
            elif block["episode"] not in part["episodes"]:
                part["episodes"].append(block["episode"])
    pairs = naming.episode_pairs(parsed)
    paths = {}
    multi = len(pairs) > 1
    for season, number in pairs:
        if multi:
            specific = _first_existing(folder, names, [f"{stem}-{naming.episode_mark(season, number)}.nfo"])
            if specific:
                paths[(season, number)] = specific
                blocks = [block for block in blocks
                          if not (block.get("season") == season and block.get("episode") == number)]
                blocks.extend(nfo.read_episodes(specific))
            elif combined:
                paths[(season, number)] = combined
        elif combined:
            paths[(season, number)] = combined
    return parsed, paths, blocks


def _season_nfo_number(name):
    """2 for season02.nfo. None for season.nfo and any other file."""
    lowered = str(name or "").lower()
    if not lowered.startswith("season") or not lowered.endswith(".nfo"):
        return None
    number = lowered[len("season"):-len(".nfo")]
    return int(number) if number.isdigit() else None


def _stored_nfo_differs(row, path):
    """True when this .nfo is new or its modification time no longer matches the stored one."""
    if not path or not os.path.isfile(path):
        return False
    if not row or row.get("nfo_path") != path:
        return True
    return not _mtime_same(row.get("nfo_mtime"), nfo.mtime(path))


def _loose_season_nfos(show, names, occupied):
    """Season .nfo files whose season has no episode files.

    occupied is the set of season numbers already being read from episode files.
    """
    found = []
    seen = set(occupied)
    try:
        children = list(os.scandir(show))
    except OSError:
        children = []
    for entry in children:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if not is_dir or naming.skip_dir(entry.name) or naming.is_extra_dir(entry.name, tv=True):
            continue
        season = naming.season_from_dir(entry.name)
        if season is None or season in seen:
            continue
        listing = artwork.listing(entry.path)
        nfo_path = _first_existing(entry.path, listing, ["season.nfo"])
        if not nfo_path:
            nfo_path = _first_existing(show, names, [f"season{season:02d}.nfo", f"season{season}.nfo"])
        if not nfo_path:
            continue
        found.append((season, entry.path, nfo_path))
        seen.add(season)
    for key, real in names.items():
        season = _season_nfo_number(key)
        if season is None or season in seen:
            continue
        found.append((season, None, os.path.join(show, real)))
        seen.add(season)
    return found


def _save_one_season(job, show, show_id, season, folder, season_nfo, names, folders, values, data, announce=False):
    season_names = folders.get(folder) or {} if folder else {}
    season_data = (nfo.read_season(season_nfo) if season_nfo else None) or {}
    season_values = {
        "show_id": show_id, "season_number": season, "path": folder,
        "title": season_data.get("title") or (values.get("season_names") or {}).get(str(season)),
        "sort_title": season_data.get("sort_title"),
        "artwork": artwork.season(show, season, folder, cache={show: names, **folders}),
        "nfo_path": season_nfo, "nfo_mtime": nfo.mtime(season_nfo) if season_nfo else None,
    }
    plot = season_data.get("plot") or (data.get("season_plots") or {}).get(str(season))
    if plot:
        season_values["plot"] = plot
    if season_data.get("premiered"):
        season_values["premiered"] = season_data["premiered"]
    if season_data.get("ids"):
        season_values["ids"] = season_data["ids"]
    year = season_data.get("year")
    if year:
        season_values["year"] = year
    season_id, inserted = store.save_season(season_values)
    if announce and season_nfo:
        label = "Specials" if season == 0 else f"season {season}"
        verb = "Added" if inserted else "Updated"
        job.log(f"{verb} {label} from {os.path.basename(season_nfo)}")
    return season_id


def _save_loose_seasons(job, show, show_id, names, folders, values, data, occupied, only_changed=False):
    """Read a season .nfo that has no episode files beside it."""
    loose = _loose_season_nfos(show, names, occupied)
    if only_changed and loose:
        stored = store.season_nfo_index(show_id)
        loose = [item for item in loose if _stored_nfo_differs(stored.get(item[0]), item[2])]
    for season, folder, nfo_path in loose:
        _save_one_season(job, show, show_id, season, folder, nfo_path, names, folders, values, data, announce=True)
    return loose


def _scan_show(job, root, show, known_shows, known_files, units, file_list=None):
    with activity.holding() as hold:
        previous = known_shows.get(show)
        if previous:
            hold(previous["id"])
        return _scan_show_held(job, root, show, known_files, units, hold, file_list)


def _scan_show_held(job, root, show, known_files, units, hold, file_list=None):
    names = artwork.listing(show)
    nfo_path = _first_existing(show, names, ["tvshow.nfo"])
    data = (nfo.read_show(nfo_path) if nfo_path else None) or {}
    parsed = naming.parse_title(os.path.basename(show))
    ids = dict(parsed["ids"])
    ids.update(data.get("ids") or {})
    values = {
        "path": show, "root": root, "title": data.get("title") or parsed["title"],
        "original_title": data.get("original_title"), "english_title": data.get("english_title"),
        "sort_title": data.get("sort_title"),
        "year": data.get("year") or parsed["year"], "plot": data.get("plot"), "outline": data.get("outline"),
        "tagline": data.get("tagline"), "countries": data.get("countries") or [],
        "show_status": data.get("show_status"), "premiered": data.get("premiered"), "mpaa": data.get("mpaa"),
        "runtime_minutes": data.get("runtime"), "genres": data.get("genres") or [],
        "studios": data.get("studios") or [], "tags": data.get("tags") or [], "actors": data.get("actors") or [],
        "directors": data.get("directors") or [],
        "ids": ids, "imdb_id": ids.get("imdb"), "tmdb_id": ids.get("tmdb"), "tvdb_id": ids.get("tvdb"),
        "ratings": data.get("ratings") or {}, "rating": data.get("rating"), "votes": data.get("votes"),
        "user_rating": data.get("user_rating"), "top250": data.get("top250"),
        "playcount": data.get("playcount") or 0, "last_played": data.get("last_played"),
        "original_language": data.get("original_language"),
        "season_names": data.get("season_names") or {}, "nfo_path": nfo_path,
        "nfo_mtime": nfo.mtime(nfo_path) if nfo_path else None, "artwork": artwork.show(show, cache={show: names}),
    }
    if data.get("certifications"):
        values["certifications"] = data["certifications"]
    if file_list is None:
        file_list, empty_folders = _episode_files(job, show)
        for folder in empty_folders:
            job.note_empty(folder)
    if file_list is None:
        job.fail(show, "Could not read all episode files in show")
        return None
    store.claim_wanted_show(ids.get("tvdb"), ids.get("tmdb"), show)
    show_id, inserted = store.save_show(values)
    hold(show_id)
    if inserted:
        job.note_changed(show_id)
        job.log(f"Added show: {values['title']}")
    episodes = []
    folders = {}
    known_now = store.known_episodes(show_id)
    for folder, name, folder_season in file_list:
        path = os.path.join(folder, name)
        parsed_guess = naming.parse_episode(name, folder_season)
        if parsed_guess:
            stem = os.path.splitext(name)[0]
            renamed = False
            for season, number in naming.episode_pairs(parsed_guess):
                previous = known_now.get((season, number))
                if not previous or not files_replaced([previous.get("path")], [path]):
                    continue
                moved = artwork.retarget_sidecars(
                    folder, _video_stems([previous["path"]]), stem, _other_videos(folder, [path]),
                )
                if moved:
                    renamed = True
                    job.log(f"Renamed {len(moved)} artwork file{'s' if len(moved) != 1 else ''} for {name}")
            if renamed:
                folders.pop(folder, None)
        if folder not in folders:
            folders[folder] = artwork.listing(folder)
        parsed_episode, nfo_paths, blocks = _episode_numbers(job, folder, name, folder_season, folders[folder])
        if parsed_episode is None:
            job.unmatched(path)
            continue
        episodes.append({"path": path, "folder": folder, "name": name, "parsed": parsed_episode,
                         "nfo_paths": nfo_paths, "blocks": blocks, "folder_season": folder_season})
    season_ids = {}
    season_dirs = {}
    for episode in episodes:
        for season, _episode_number in naming.episode_pairs(episode["parsed"]):
            if episode["folder_season"] == season and episode["folder"] != show:
                season_dirs.setdefault(season, episode["folder"])
    for season in sorted({item for episode in episodes for item, _episode_number in naming.episode_pairs(episode["parsed"])}):
        folder = season_dirs.get(season)
        season_names = folders.get(folder) or {} if folder else {}
        season_nfo = _first_existing(folder, season_names, ["season.nfo"]) if folder else None
        if not season_nfo:
            seen = set()
            for episode in episodes:
                if season not in {item for item, _episode in naming.episode_pairs(episode["parsed"])} or episode["folder"] == show or episode["folder"] in seen:
                    continue
                seen.add(episode["folder"])
                listing = folders.get(episode["folder"]) or artwork.listing(episode["folder"])
                season_nfo = _first_existing(episode["folder"], listing, ["season.nfo"])
                if season_nfo:
                    folder = folder or episode["folder"]
                    break
        if not season_nfo:
            season_nfo = _first_existing(show, names, [f"season{season:02d}.nfo", f"season{season}.nfo"])
        season_ids[season] = _save_one_season(
            job, show, show_id, season, folder, season_nfo, names, folders, values, data,
        )
    _save_loose_seasons(job, show, show_id, names, folders, values, data, set(season_ids))
    known = store.known_episodes(show_id)
    claimed = {}
    for episode in episodes:
        units.append({"path": episode["path"], "show_id": show_id, "season_ids": season_ids, "known": known,
                      "known_files": known_files, "names": folders[episode["folder"]], "claimed": claimed,
                      **episode})
    return show_id


def _same_span(stored, span):
    def pair(item):
        if not isinstance(item, dict):
            return None
        try:
            return (int(item.get("season")), int(item.get("episode")))
        except (TypeError, ValueError):
            return None

    return [pair(item) for item in (stored or [])] == [pair(item) for item in (span or [])]


def _process_episode(job, unit):
    with activity.holding() as hold:
        _process_episode_held(job, unit, hold)


def _process_episode_held(job, unit, hold):
    parsed = unit["parsed"]
    keys = naming.episode_pairs(parsed)
    extras = []
    with job.seen:
        owned = []
        for key in keys:
            other = unit["claimed"].get(key)
            if other and other != unit["path"]:
                extras.append(key)
            else:
                unit["claimed"][key] = unit["path"]
                owned.append(key)
    for key in extras:
        job.note_extra(unit["show_id"], key[0], key[1], unit["path"])
        job.log(f"Extra copy of episode {key[1]}: {os.path.basename(unit['path'])}")
    if not owned:
        return
    for key in owned:
        previous = unit["known"].get(key)
        if previous:
            hold(previous["id"], unit["show_id"], unit["season_ids"].get(key[0]))
    file_id, file_changed = _probe_file(job, unit["path"], "episode", unit["known_files"], unit["names"])
    replaced_keys = {
        key for key in owned
        if files_replaced([(unit["known"].get(key) or {}).get("path")], [unit["path"]])
    }
    nfo_source = next((item.get("source") for item in unit["blocks"] if item.get("source")), None)
    if file_id and nfo_source and not replaced_keys:
        store.fill_empty_source(file_id, nfo_source)
    release_facts = probe.combined_release(unit["name"], "") if replaced_keys else None
    stem = os.path.splitext(unit["name"])[0]
    blocks = unit["blocks"]
    multi = len(keys) > 1
    span = [{"season": int(season), "episode": int(number)} for season, number in keys] if multi else []
    for index, key in enumerate(owned):
        nfo_path = (unit.get("nfo_paths") or {}).get(key)
        nfo_time = nfo.mtime(nfo_path) if nfo_path else None
        art = artwork.episode(unit["folder"], stem, cache={unit["folder"]: unit["names"]},
                              season=key[0], episode=key[1], multi=multi)
        previous = unit["known"].get(key)
        unchanged = (previous is not None and not file_changed and previous["path"] == unit["path"]
                     and previous["nfo_path"] == nfo_path and previous["nfo_mtime"] == nfo_time
                     and previous["file_id"] == file_id and _same_span(previous.get("file_span"), span))
        if job.mode == "incremental" and unchanged:
            if (previous["artwork"] or {}) != art:
                store.set_artwork("tv_episodes", previous["id"], art)
            job.count("unchanged")
            job.detail(f"Unchanged: {os.path.basename(unit['path'])}")
            continue
        block = next((item for item in blocks if item.get("season") == key[0] and item.get("episode") == key[1]), None)
        if block is None and index < len(blocks) and blocks[index].get("episode") is None:
            block = blocks[index]
        data = block or {}
        values = {
            "show_id": unit["show_id"], "season_id": unit["season_ids"][key[0]], "season_number": key[0],
            "episode_number": key[1], "path": unit["path"], "file_id": file_id,
            "title": data.get("title") or parsed.get("title"),
            "original_title": data.get("original_title"), "english_title": data.get("english_title"),
            "plot": data.get("plot"), "aired": data.get("aired"),
            "runtime_minutes": data.get("runtime"), "mpaa": data.get("mpaa"),
            "directors": data.get("directors") or [],
            "writers": data.get("writers") or [], "ids": data.get("ids") or {}, "ratings": data.get("ratings") or {},
            "rating": data.get("rating"), "votes": data.get("votes"), "user_rating": data.get("user_rating"),
            "display_season": data.get("display_season"), "display_episode": data.get("display_episode"),
            "resume_position": data.get("resume_position"), "resume_total": data.get("resume_total"),
            "playcount": data.get("playcount") or 0, "last_played": data.get("last_played"),
            "nfo_path": nfo_path, "nfo_mtime": nfo_time, "artwork": art,
            "file_span": span, "missing": False,
        }
        if data.get("certifications"):
            values["certifications"] = data["certifications"]
        if key in replaced_keys:
            kept_metadata(previous, values)
        episode_id, inserted = store.save_episode(values)
        hold(episode_id, unit["show_id"], unit["season_ids"].get(key[0]))
        if key in replaced_keys:
            job.note_replaced_episode(unit["show_id"], episode_id)
        job.note_changed(unit["show_id"])
        job.count("added" if inserted else "updated")
        if index == 0:
            verb = "Added" if inserted else "Updated"
            job.log(f"{verb} {os.path.basename(unit['path'])}")
    if replaced_keys and file_id and release_facts:
        store.apply_release_names(file_id, release_facts)


def _take_show(job, root, show, known_shows, known_files, episode_index, stream):
    """Leave an unchanged show listed, or parse it and hand its changed episodes to the workers."""
    previous = known_shows.get(show)
    file_list, empty_folders = _episode_files(job, show)
    if file_list is None:
        job.fail(show, "Could not read all episode files in show")
        return None, set()
    for folder in empty_folders:
        job.note_empty(folder)
    rows = (episode_index.get(str(previous["id"])) if previous else None) or []
    missing = _files_without_episodes(file_list, rows)
    if missing:
        job.log(f"{os.path.basename(show)}: {len(missing)} episode file{'s' if len(missing) != 1 else ''} on disk with no episode in the library")
    elif _show_can_skip(job, show, previous, file_list, known_files, rows):
        if not file_list or empty_folders:
            names = artwork.listing(show)
            occupied = {season for _folder, _name, season in file_list if season is not None}
            nfo_path = _first_existing(show, names, ["tvshow.nfo"])
            data = (nfo.read_show(nfo_path) if nfo_path else None) or {}
            _save_loose_seasons(
                job, show, previous["id"], names, {}, {"season_names": data.get("season_names") or {}}, data,
                occupied, only_changed=True,
            )
        seen = {os.path.join(folder, name) for folder, name, _season in file_list}
        keep = {(row["season_number"], row["episode_number"]) for row in rows if row.get("path") in seen}
        stream.skip(len(keep) or len(file_list))
        job.detail(f"Unchanged: {os.path.basename(show)}")
        return previous["id"], keep
    units = []
    show_id = _scan_show(job, root, show, known_shows, known_files, units, file_list)
    keep = {pair for unit in units for pair in naming.episode_pairs(unit["parsed"])}
    updated = previous.get("updated_at") if previous else None
    for unit in units:
        pairs = naming.episode_pairs(unit["parsed"])
        if _episode_needs_work(job, unit, updated):
            stream.submit(unit)
        else:
            stream.skip(len(pairs) or 1)
    return show_id, keep


def _prunable_tv_roots(job, walked):
    """The walked TV roots that may have their missing shows removed.

    The same limits as movies and music. A mount that would lose more than 20 % of what is
    indexed across all of its library paths is left alone, as is a single path that would lose
    more than 20 %, and a path that was readable but came back with no show in it.
    """
    from resonance.paths import mount_for
    from resonance.settings import prune_safety_on

    safety = prune_safety_on()
    measured = []
    for root, keep in walked:
        known = store.known_show_paths(root)
        measured.append((root, keep, len(known), len(known - set(keep))))
    mounts = {}
    for root, _keep, known, remove in measured:
        agg = mounts.setdefault(mount_for(root), {"known": 0, "remove": 0, "roots": []})
        agg["known"] += known
        agg["remove"] += remove
        agg["roots"].append(root)
    blocked = set()
    for mount, agg in mounts.items():
        if safety and mount and agg["known"] > 10 and agg["remove"] > agg["known"] * 0.20:
            blocked.add(mount)
            job.log(
                f"Prune safety: the mount {mount} would lose {agg['remove']}/{agg['known']} "
                f"shows ({100 * agg['remove'] // agg['known']}%) across {len(agg['roots'])} "
                f"library path(s), so none of them were pruned. Run a full scan if this is "
                f"expected."
            )
    allowed = []
    for root, keep, known, remove in measured:
        if mount_for(root) in blocked:
            store.mark_prune_held("tv", root, keep, True)
            continue
        if not keep:
            if known:
                job.log(
                    f"Prune safety: {root} is readable but no show was found in it, so none of "
                    f"its {known} indexed shows were removed. Remove the path in Settings and "
                    f"scan again if they should go."
                )
                store.mark_prune_held("tv", root, keep, True)
            continue
        if safety and known > 10 and remove > known * 0.20:
            job.log(
                f"Prune safety: would remove {remove}/{known} shows from {root} "
                f"({100 * remove // known}%) - skipping. Run a full scan if this is expected."
            )
            store.mark_prune_held("tv", root, keep, True)
            continue
        allowed.append(root)
    return allowed


def _scan_tv(job, roots):
    _drop_removed_paths("tv_paths", "shows")
    _count_for_deep(job, [(root, root) for root in roots], tv=True)
    known_shows = store.known_shows(roots)
    known_files = store.known_files(roots)
    episode_index = store.episode_index(roots)
    walked = []
    shows_by_id = {}
    stream = _Stream(job, lambda unit: _process_episode(job, unit), "Episodes")
    try:
        for root in roots:
            if not os.path.isdir(root) or not _has_entries(root):
                job.fail(root, "The folder is empty or not mounted")
                continue
            if job.cancelled:
                break
            seen = set()
            folders = _show_folders(root)
            if folders is None:
                job.fail(root, "The folder could not be read")
                continue
            stopped = False
            folder_total = len(folders) or 1
            for index, show in enumerate(folders, start=1):
                if job.cancelled:
                    stopped = True
                    break
                job.progress(
                    message=f"Reading shows {index}/{len(folders)}: {os.path.basename(show)}",
                    processed=index, total=folder_total, folders_done=index, folders_total=folder_total,
                )
                show_id, keep = _take_show(job, root, show, known_shows, known_files, episode_index, stream)
                seen.add(show)
                if show_id is not None:
                    shows_by_id[show_id] = keep
            if stopped:
                break
            walked.append((root, seen))
        stream.close_walk()
    finally:
        stream.finish()
    if not _pass_finished(job):
        if job.stopped:
            job.log("Stopped before every episode was saved, so seasons were left in place")
        return
    _keep_extra_copies(job, list(shows_by_id), known_files)
    job.progress(message="Checking for episodes that are gone", phase="cleanup", force=True)
    for show_id, keep in shows_by_id.items():
        removed = store.prune_show(show_id, keep)
        if removed:
            job.count("removed", removed)
            store.touch_show(show_id)
    for root in _prunable_tv_roots(job, walked):
        keep = dict(walked)[root]
        removed = store.prune_shows(root, keep)
        store.mark_prune_held("tv", root, keep, False)
        if removed:
            note_removed("tv", removed)
            job.log(f"Removed {len(removed)} shows that are no longer under {root}")
    _clear_removed_paths(job, "tv")
    store.drop_orphans()


def _scan_tv_targets(job, root, targets):
    if not _has_entries(root):
        job.fail(root, "The TV folder is empty or not mounted")
        return
    _count_for_deep(job, [(target, root) for target in targets if os.path.isdir(target)], tv=True)
    known_shows = store.known_shows([root])
    known_files = store.known_files([root])
    episode_index = store.episode_index([root])
    shows_by_id = {}
    stream = _Stream(job, lambda unit: _process_episode(job, unit), "Episodes")
    try:
        for target in targets:
            if job.cancelled:
                break
            if not os.path.isdir(target):
                removed = store.prune_show_path(root, target)
                if removed:
                    job.count("removed", len(removed))
                    note_removed("tv", removed)
                    job.log(f"Removed the show at {target}: the folder is gone")
                continue
            job.progress(message=f"Reading {os.path.basename(target)}", force=True)
            show_id, keep = _take_show(job, root, target, known_shows, known_files, episode_index, stream)
            if show_id is not None:
                shows_by_id[show_id] = keep
        stream.close_walk()
    finally:
        stream.finish()
    if not _pass_finished(job):
        if job.stopped:
            job.log("Stopped before every episode was saved, so seasons were left in place")
        return
    _keep_extra_copies(job, list(shows_by_id), known_files)
    job.progress(message="Checking for episodes that are gone", phase="cleanup", force=True)
    for show_id, keep in shows_by_id.items():
        removed = store.prune_show(show_id, keep)
        if removed:
            job.count("removed", removed)
            store.touch_show(show_id)
    store.drop_orphans()


def _scan_one_season(job, season_id):
    """Deep-read one season. Other seasons of the show are left as they are."""
    season = store.season_row(season_id)
    show = store.show_row(season["show_id"]) if season else None
    if not show or not show.get("path"):
        job.log("That season is not in the library")
        return
    number = int(season["season_number"])
    root = show["root"]
    if not _has_entries(root):
        job.fail(root, "The TV folder is empty or not mounted")
        return
    if not os.path.isdir(show["path"]):
        job.log(f"The show folder is not there: {show['path']}")
        return
    known_shows = store.known_shows([root])
    known_files = store.known_files([root])
    units = []
    label = "Specials" if number == 0 else f"season {number}"
    job.progress(message=f"Reading {os.path.basename(show['path'])} {label}", force=True)
    _scan_show(job, root, show["path"], known_shows, known_files, units)
    kept = [unit for unit in units if any(int(pair[0]) == number for pair in naming.episode_pairs(unit["parsed"]))]
    job.log(f"{job.mode.capitalize()} scan of {show['title']} {label}: {len(kept)} episode files")
    job.log("Reading every episode file in this season and filling blanks from its .nfo")
    _run_pool(job, kept, lambda unit: _process_episode(job, unit), "Episodes")


def _scan_one_episode(job, episode_id):
    """Deep-read the file for one episode. Other episodes in the show stay as they are."""
    episode = store.episode_detail(episode_id)
    show = store.show_row(episode["show_id"]) if episode else None
    if not show or not episode or not episode.get("path"):
        job.log("That episode is not in the library")
        return
    root = show["root"]
    if not _has_entries(root):
        job.fail(root, "The TV folder is empty or not mounted")
        return
    if not os.path.isdir(show["path"]):
        job.log(f"The show folder is not there: {show['path']}")
        return
    known_shows = store.known_shows([root])
    known_files = store.known_files([root])
    units = []
    code = f"S{int(episode['season_number']):02d}E{int(episode['episode_number']):02d}"
    job.progress(message=f"Reading {code}", force=True)
    _scan_show(job, root, show["path"], known_shows, known_files, units)
    path = os.path.normcase(episode["path"])
    kept = [unit for unit in units if os.path.normcase(unit["path"]) == path]
    job.log(f"{job.mode.capitalize()} scan of {show['title']} {code}: {os.path.basename(episode['path'])}")
    if not kept:
        job.log("That episode file is not in the show folder any more")
        return
    job.log("Reading this episode file and filling blanks from its .nfo")
    _run_pool(job, kept, lambda unit: _process_episode(job, unit), "Episodes")


def _keep_extra_copies(job, show_ids, known_files):
    """Remember a second file of the same episode instead of dropping it."""
    from curator.video import copies

    grouped = {}
    for item in job.extras:
        grouped.setdefault(item["show_id"], []).append(item)
    for show_id in show_ids:
        rows = []
        seen = set()
        for item in grouped.get(str(show_id), []):
            episode = db_episode(show_id, item["season"], item["episode"])
            if not episode:
                continue
            key = (str(episode["id"]), item["path"])
            if key in seen:
                continue
            seen.add(key)
            file_id = None
            try:
                file_id, _changed = _probe_file(
                    job, item["path"], "episode", known_files, artwork.listing(os.path.dirname(item["path"])),
                )
            except Exception as exc:
                job.log(f"Extra copy was not probed: {item['path']}: {exc}")
            rows.append({"episode_id": episode["id"], "path": item["path"], "file_id": file_id})
        try:
            copies.replace_show_copies(show_id, rows)
        except Exception as exc:
            job.log(f"Could not store extra episode copies: {exc}")


def db_episode(show_id, season, episode):
    from resonance import db

    return db.fetchone(
        """
        SELECT id FROM tv_episodes
        WHERE show_id = %s AND season_number = %s AND episode_number = %s
        """,
        (show_id, season, episode),
    )
