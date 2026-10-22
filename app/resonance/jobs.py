import logging
import os
import threading

from psycopg.types.json import Json

from resonance import db, scanner
from resonance.errors import AppError

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_cancel = threading.Event()
_prompt_guard = threading.Lock()
_prompt_event = threading.Event()
_prompt = None
_pause_guard = threading.Lock()
_pause = threading.Event()
_paused = threading.Event()
_resume = threading.Event()
_pause_owner = None
_pause_job = None
_importing = False
PAUSE_MESSAGE = "Paused for queued imports"


class ScanCancelled(Exception):
    """The user stopped a scan. Indexed folders stay; missing folders are not removed."""


def cancelled():
    return _cancel.is_set()


def bind_pause(job_id):
    """This thread is the library scan. Webhook work on another thread does not park here."""
    global _pause_owner, _pause_job
    with _pause_guard:
        _pause_owner = threading.current_thread()
        _pause_job = job_id


def unbind_pause():
    global _pause_owner, _pause_job, _importing
    with _pause_guard:
        _pause_owner = None
        _pause_job = None
        _importing = False
        _pause.clear()
        _paused.clear()
    _resume.set()


def library_active():
    with _pause_guard:
        owner = _pause_owner
    return owner is not None and owner.is_alive()


def request_pause():
    """Park the library scan at its next checkpoint. The job stays running."""
    with _pause_guard:
        owner = _pause_owner
        if owner is None or not owner.is_alive():
            return False
        _resume.clear()
        _pause.set()
    return True


def paused():
    return _paused.is_set()


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


def _announce_pause():
    if not _pause_job:
        return
    try:
        db.execute(
            """
            UPDATE scan_jobs
            SET message = %s
            WHERE id = %s AND status = 'running'
            """,
            (PAUSE_MESSAGE, _pause_job),
        )
    except Exception:
        logger.exception("could not mark the music scan as paused")


def _wait_if_paused():
    if not _pause.is_set():
        return
    _announce_pause()
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


def checkpoint():
    if threading.current_thread() is _pause_owner:
        _wait_if_paused()
        with _pause_guard:
            still_held = _importing and _pause.is_set()
        if _cancel.is_set() and not still_held:
            raise ScanCancelled()
        return
    with _pause_guard:
        owned = _pause_owner is not None and _importing
    if owned:
        return
    if _cancel.is_set():
        raise ScanCancelled()


def request_cancel():
    row = current_job()
    target = _pause_job or (row or {}).get("id")
    if not target:
        return False
    if (not row or row.get("status") != "running") and not _lock.locked():
        return False
    if not _lock.locked():
        _finish_cancelled(target)
        return True
    _cancel.set()
    _prompt_event.set()
    _resume.set()
    try:
        db.execute(
            """
            UPDATE scan_jobs
            SET message = 'Stopping scan'
            WHERE id = %s AND status = 'running'
            """,
            (target,),
        )
    except Exception:
        logger.exception("could not mark the scan as stopping")
    return True


def _finish_cancelled(job_id):
    note = "\nScan cancelled. Indexed music stays. Missing folders were not removed."
    try:
        db.execute(
            """
            UPDATE scan_jobs
            SET status = 'cancelled',
                message = 'Scan cancelled',
                log = CONCAT(COALESCE(log, ''), %s::text),
                finished_at = NOW()
            WHERE id = %s AND status = 'running'
            """,
            (note, job_id),
        )
    except Exception:
        logger.exception("could not append the cancel note")
        db.execute(
            """
            UPDATE scan_jobs
            SET status = 'cancelled', message = 'Scan cancelled', finished_at = NOW()
            WHERE id = %s AND status = 'running'
            """,
            (job_id,),
        )


def reset_prompt():
    global _prompt
    with _prompt_guard:
        _prompt = None
    _prompt_event.set()


def begin_prompt(job_id, payload):
    """Pause the scan until the browser chooses or skips."""
    global _prompt
    summary = {
        "kind": payload["kind"],
        "album_id": str(payload["album_id"]),
        "label": payload.get("label") or "",
    }
    message = payload.get("message") or "Waiting for a choice"
    _prompt_event.clear()
    with _prompt_guard:
        _prompt = {"summary": summary, "search": payload.get("search"), "decision": None}
    db.execute(
        """
        UPDATE scan_jobs
        SET message = %s,
            result = COALESCE(result, '{}'::jsonb) || %s::jsonb
        WHERE id = %s AND status = 'running'
        """,
        (message, Json({"wait": summary}), job_id),
    )
    while not _prompt_event.wait(0.4):
        checkpoint()
    checkpoint()
    with _prompt_guard:
        decision = dict((_prompt or {}).get("decision") or {"action": "skip"})
        _prompt = None
    db.execute(
        """
        UPDATE scan_jobs
        SET result = COALESCE(result, '{}'::jsonb) - 'wait'
        WHERE id = %s
        """,
        (job_id,),
    )
    return decision


def current_prompt():
    with _prompt_guard:
        if not _prompt or _prompt.get("decision"):
            return None
        summary = _prompt.get("summary") or {}
        return {
            "kind": summary.get("kind"),
            "album_id": summary.get("album_id"),
            "label": summary.get("label") or "",
            "search": _prompt.get("search"),
        }


def resolve_prompt(decision):
    global _prompt
    with _prompt_guard:
        if not _prompt or _prompt.get("decision"):
            return False
        _prompt["decision"] = decision
    _prompt_event.set()
    return True


def try_lock():
    return _lock.acquire(blocking=False)


def acquire():
    _lock.acquire()


def locked():
    return _lock.locked()


def release_lock():
    try:
        _lock.release()
    except RuntimeError:
        return


def list_work():
    return db.fetchall(
        """
        SELECT * FROM work_jobs
        ORDER BY started_at DESC NULLS LAST
        LIMIT 20
        """
    )


def start_scan(force=False, mode="incremental", roots=None, verbose=False, albums=None, origin="manual"):
    from resonance.scanner import normalize_scan_mode

    mode = normalize_scan_mode(mode)
    if not _lock.acquire(blocking=False):
        return current_job(), False
    _cancel.clear()
    reset_prompt()
    try:
        row = db.fetchone(
            """
            INSERT INTO scan_jobs (status, message, processed, total, started_at, phase, mode, log, result)
            VALUES ('running', 'Starting scan', 0, 0, NOW(), 'directory', %s, '', %s)
            RETURNING *
            """,
            (mode, Json({"force": bool(force), "origin": origin or "manual"})),
        )
    except Exception:
        _lock.release()
        drain_lidarr()
        raise

    def run():
        bind_pause(row["id"])
        try:
            message = scanner.scan(row["id"], force=force, mode=mode, roots=roots, verbose=verbose, albums=albums)
            status = "cancelled" if message == "Scan cancelled" else "completed"
            from resonance import scan_pace

            scan_pace.finish(status == "completed")
            try:
                from curator import outbound

                outbound.scan_done("music", status, message, origin)
            except Exception:
                logger.exception("could not send the scan notification")
            if status == "completed":
                try:
                    from resonance.artwork import sweep_cache
                    sweep_cache()
                except Exception as _exc:
                    import logging as _logging
                    _logging.getLogger(__name__).warning("sweep_cache failed: %s", _exc)
            db.execute(
                """
                UPDATE scan_jobs
                SET status = %s, message = %s, finished_at = NOW()
                WHERE id = %s
                """,
                (status, message, row["id"]),
            )
        except ScanCancelled:
            from resonance import scan_pace

            scan_pace.finish(False)
            _finish_cancelled(row["id"])
        except AppError as exc:
            from resonance import scan_pace

            scan_pace.finish(False)
            logger.warning("scan failed: %s", exc)
            try:
                from curator import outbound

                outbound.scan_done("music", "failed", str(exc), origin)
            except Exception:
                logger.exception("could not send the scan notification")
            db.execute(
                """
                UPDATE scan_jobs
                SET status = 'failed', message = %s, finished_at = NOW()
                WHERE id = %s
                """,
                (str(exc), row["id"]),
            )
        except Exception as exc:
            logger.exception("scan failed")
            try:
                from curator import outbound

                outbound.scan_done("music", "failed", str(exc), origin)
            except Exception:
                logger.exception("could not send the scan notification")
            from resonance import scan_pace

            scan_pace.finish(False)
            db.execute(
                """
                UPDATE scan_jobs
                SET status = 'failed', message = %s, finished_at = NOW()
                WHERE id = %s
                """,
                (str(exc), row["id"]),
            )
        finally:
            unbind_pause()
            _cancel.clear()
            reset_prompt()
            _lock.release()
            if not drain_lidarr():
                from resonance import scan_queue

                scan_queue.finished()

    threading.Thread(target=run, name="library-scan", daemon=True).start()
    return row, True


_lidarr_queue = []
_lidarr_guard = threading.Lock()


def enqueue_lidarr(album_path, artist_path, label):
    """Queue one imported album. A running scan keeps the path until the lock is free."""
    key = os.path.normcase(os.path.normpath(album_path))
    with _lidarr_guard:
        duplicate = any(item["key"] == key for item in _lidarr_queue)
        if not duplicate:
            _lidarr_queue.append(
                {"key": key, "album": album_path, "artist": artist_path, "label": label or album_path}
            )
    return {"started": drain_lidarr(), "duplicate": duplicate}


def drain_lidarr():
    if not _lidarr_queue:
        return False
    if not _lock.acquire(blocking=False):
        return False
    _cancel.clear()
    reset_prompt()
    threading.Thread(target=_lidarr_worker, name="lidarr-scan", daemon=True).start()
    return True


def _lidarr_worker():
    try:
        while True:
            with _lidarr_guard:
                item = _lidarr_queue.pop(0) if _lidarr_queue else None
            if not item:
                break
            _run_lidarr_item(item, notify_players=True)
    finally:
        _cancel.clear()
        reset_prompt()
        _lock.release()
        from resonance import scan_queue

        if not (_lidarr_queue and drain_lidarr()):
            scan_queue.finished()


def _run_lidarr_item(item, notify_players=False):
    label = item.get("label") or item["album"]
    try:
        row = db.fetchone(
            """
            INSERT INTO scan_jobs (status, message, processed, total, started_at, phase, mode, log, result)
            VALUES ('running', %s, 0, 1, NOW(), 'directory', 'incremental', '', '{"origin": "webhook"}'::jsonb)
            RETURNING *
            """,
            (f"Lidarr: {label}",),
        )
    except Exception:
        logger.exception("could not start Lidarr scan for %s", label)
        return
    try:
        message = scanner.scan_release(row["id"], item["album"], item.get("artist"))
        status = "cancelled" if message == "Scan cancelled" else "completed"
        db.execute(
            """
            UPDATE scan_jobs
            SET status = %s, message = %s, finished_at = NOW()
            WHERE id = %s
            """,
            (status, message, row["id"]),
        )
        try:
            from curator import outbound

            outbound.scan_done("music", status, message, "webhook")
        except Exception:
            logger.exception("could not send the scan notification")
        if notify_players and status == "completed":
            try:
                from curator import notify

                artist = item.get("artist")
                album = item.get("album")
                folder = artist or album
                folders = [folder] if folder else []
                items = [label] if label else []
                notify.request("music", folders=folders, items=items, message=f"Updated: {label}")
            except Exception:
                logger.info("player notify failed after Lidarr scan for %s", label, exc_info=True)
    except ScanCancelled:
        db.execute(
            """
            UPDATE scan_jobs
            SET status = 'cancelled', message = 'Scan cancelled', finished_at = NOW()
            WHERE id = %s AND status = 'running'
            """,
            (row["id"],),
        )
    except Exception as exc:
        logger.exception("lidarr scan failed")
        db.execute(
            """
            UPDATE scan_jobs
            SET status = 'failed', message = %s, finished_at = NOW()
            WHERE id = %s
            """,
            (str(exc), row["id"]),
        )


def scan_lidarr_now(album_path, artist_path, label):
    """Index one imported album on this thread. The paused library scan keeps its lock."""
    _run_lidarr_item({"album": album_path, "artist": artist_path, "label": label or album_path})


def current_job():
    row = db.fetchone(
        """
        SELECT * FROM scan_jobs
        WHERE status = 'running'
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
        """
    )
    if not row:
        row = db.fetchone(
            """
            SELECT * FROM scan_jobs
            ORDER BY started_at DESC NULLS LAST
            LIMIT 1
            """
        )
    if not row:
        return {
            "status": "idle",
            "message": "Idle",
            "processed": 0,
            "total": 0,
            "phase": None,
            "mode": None,
            "log": "",
        }
    if row.get("status") == "running":
        from resonance import scan_pace

        row = dict(row)
        row["pace"] = scan_pace.snapshot()
    return row


def queue_work(kind, message, total=0):
    row = db.fetchone(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
        VALUES (%s, 'queued', %s, 0, %s, '', NOW())
        RETURNING *
        """,
        (kind, message, total),
    )
    return row


def claim_work(job_id):
    db.execute(
        """
        UPDATE work_jobs
        SET status = 'running', started_at = NOW()
        WHERE id = %s AND status = 'queued'
        """,
        (job_id,),
    )


def begin_work(kind, message, total=0):
    from resonance.settings import vlog

    row = db.fetchone(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
        VALUES (%s, 'running', %s, 0, %s, '', NOW())
        RETURNING *
        """,
        (kind, message, total),
    )
    vlog(logger, "job started: %s — %s", kind, message)
    return row


def touch_work(job_id, processed, message, log):
    db.execute(
        """
        UPDATE work_jobs
        SET processed = %s, message = %s, log = %s
        WHERE id = %s
        """,
        (processed, message, log, job_id),
    )


def finish_work(job_id, status, message, processed=None, log=None):
    if str(status).lower() in {"failed", "error"}:
        try:
            from curator import outbound

            outbound.send("job_failed", "A job failed", str(message or "")[:500], "error")
        except Exception:
            logger.exception("could not send the job notification")
    db.execute(
        """
        UPDATE work_jobs
        SET status = %s,
            message = %s,
            processed = COALESCE(%s, processed),
            log = COALESCE(%s, log),
            finished_at = NOW()
        WHERE id = %s
        """,
        (status, message, processed, log, job_id),
    )
