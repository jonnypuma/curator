"""One ARR lane: Kodi library updates and Radarr, Sonarr, and Lidarr searches.

Webhook Kodi updates use priority 0, so they wait behind other webhook Kodi
rows and ahead of everything else. A rename or tag write uses priority 10.
Searches use priority 20. The row already running finishes before the next
starts. Identical Kodi folders that are still waiting collapse into one row.
"""
from __future__ import annotations

import logging
import threading
import uuid

from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

PRIORITY_FRONT = 0
PRIORITY_KODI = 10
PRIORITY_SEARCH = 20

_stop = threading.Event()
_wake = threading.Event()
_thread = None
_WHERE = {"kodi": "Kodi", "radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr"}


def ordered(rows):
    """Waiting order: lower priority first, then the time the row was added."""
    return sorted(rows, key=lambda row: (int(row.get("priority") or 0), row.get("created_at") or ""))


def kodi_merge_key(kind, folders):
    paths = sorted({str(folder).rstrip("/") for folder in (folders or []) if str(folder or "").strip()})
    return f"{kind}\n" + "\n".join(paths)


def enqueue_kodi(kind, folders=(), clean=False, message=None, front=False):
    """Queue one Kodi update. The same folders already waiting stay one row."""
    key = kodi_merge_key(kind, folders)
    priority = PRIORITY_FRONT if front else PRIORITY_KODI
    from resonance import db

    existing = db.fetchone(
        """
        SELECT id::text AS id, priority FROM work_queue
        WHERE lane = 'arr' AND status = 'queued' AND kind = 'kodi' AND payload->>'merge' = %s
        """,
        (key,),
    )
    if existing:
        if front and int(existing["priority"] or 0) > PRIORITY_FRONT:
            db.execute(
                """
                UPDATE work_queue
                SET priority = %s, payload = jsonb_set(payload, '{front}', 'true'::jsonb)
                WHERE id = %s
                """,
                (PRIORITY_FRONT, existing["id"]),
            )
        _wake.set()
        return existing["id"]
    paths = sorted({str(folder) for folder in (folders or []) if str(folder or "").strip()})
    noun = "video" if kind == "video" else "music"
    title = (message or "").strip() or f"Kodi {noun} library update"
    if paths and not message:
        title = f"Kodi {noun} update · {len(paths)} folder{'s' if len(paths) != 1 else ''}"
    return _insert("kodi", title, "kodi", priority, {
        "media": kind,
        "folders": paths,
        "clean": bool(clean),
        "message": message or "",
        "merge": key,
        "front": bool(front),
    })


def search_title(source, labels):
    """A queue title that names the movies or episodes, not only how many there were."""
    name = _WHERE.get(source, source.title() if source else "ARR")
    shown = [str(label).strip() for label in labels or [] if str(label or "").strip()]
    if not shown:
        return f"{name} search"
    text = ", ".join(shown[:4])
    extra = len(shown) - 4
    if extra > 0:
        text += f" and {extra} more"
    return f"{name} search · {text}"


def enqueue(kind, title, source, payload, priority=PRIORITY_SEARCH):
    return _insert(kind, title, source, priority, payload or {})


def _insert(kind, title, source, priority, payload):
    from resonance import db

    row_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO work_queue (id, lane, kind, title, source, priority, status, payload)
        VALUES (%s, 'arr', %s, %s, %s, %s, 'queued', %s)
        """,
        (row_id, kind, str(title or "")[:300], source, int(priority), Jsonb(payload)),
    )
    _wake.set()
    return row_id


def snapshot():
    from resonance import db

    if db.pool is None:
        return []
    rows = db.fetchall(
        """
        SELECT id::text AS id, kind, title, source, status, priority, payload, started_at
        FROM work_queue
        WHERE lane = 'arr' AND status IN ('queued', 'running')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, priority ASC, created_at ASC
        """
    )
    return [_public(row) for row in rows]


def _running_seconds(row):
    if (row.get("status") or "") != "running":
        return None
    from curator.queue_time import seconds_since

    return seconds_since(row.get("started_at"))


def _public(row):
    payload = row.get("payload") or {}
    source = row.get("source") or row.get("kind") or ""
    return {
        "id": str(row["id"]),
        "title": row.get("title") or "",
        "where": _WHERE.get(source, source),
        "source": source,
        "status": row.get("status") or "queued",
        "front": bool(payload.get("front")) or int(row.get("priority") or 0) == PRIORITY_FRONT,
        "kind": row.get("kind") or "",
        "running_seconds": _running_seconds(row),
    }


def drop(item_id):
    from resonance import db

    rows = db.fetchall(
        "DELETE FROM work_queue WHERE id = %s AND lane = 'arr' AND status = 'queued' RETURNING id",
        (str(item_id),),
    )
    return bool(rows)


def clear_waiting():
    from resonance import db

    rows = db.fetchall(
        "DELETE FROM work_queue WHERE lane = 'arr' AND status = 'queued' RETURNING id"
    )
    return len(rows)


def start():
    """Put a row left running back in line, then keep one worker going."""
    global _thread
    from resonance import db

    db.execute("UPDATE work_queue SET status = 'queued', started_at = NULL WHERE lane = 'arr' AND status = 'running'")
    if _thread and _thread.is_alive():
        _wake.set()
        return
    _stop.clear()
    _thread = threading.Thread(target=_worker, name="arr-queue", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    _wake.set()


def _worker():
    while not _stop.is_set():
        row = _claim()
        if not row:
            _wake.wait(5)
            _wake.clear()
            continue
        failed = None
        try:
            _execute(row)
        except Exception as exc:
            failed = exc
            logger.exception("ARR queue item failed: %s", row.get("title"))
        finally:
            try:
                from curator import work_log

                work_log.note(
                    "arr",
                    row.get("source") or row.get("kind") or "",
                    row.get("kind") or "",
                    row.get("title") or "",
                    "",
                    "error" if failed else "done",
                    "" if failed is None else str(failed),
                )
            except Exception:
                logger.exception("could not record the ARR queue item")
            try:
                from resonance import db

                db.execute("DELETE FROM work_queue WHERE id = %s", (row["id"],))
            except Exception:
                logger.exception("could not remove the finished ARR row")
            _wake.set()


def _claim():
    from resonance import db

    return db.fetchone(
        """
        WITH picked AS (
            SELECT id FROM work_queue
            WHERE lane = 'arr' AND status = 'queued'
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE work_queue SET status = 'running', started_at = LOCALTIMESTAMP
        FROM picked
        WHERE work_queue.id = picked.id
        RETURNING work_queue.id::text AS id, work_queue.kind, work_queue.title,
                  work_queue.source, work_queue.payload
        """
    )


def _execute(row):
    payload = row.get("payload") or {}
    kind = row.get("kind") or ""
    if kind == "kodi":
        from curator import notify

        notify.run_kodi(payload.get("media") or "video", payload.get("folders") or [], payload.get("clean"), payload.get("message"))
        return
    if kind == "radarr":
        from curator import radarr

        radarr.search(payload.get("tmdb_ids") or [])
        return
    if kind == "sonarr":
        from curator import sonarr

        if payload.get("episodes"):
            sonarr.search_episodes(payload["episodes"])
        else:
            sonarr.search_missing(payload.get("tvdb_id"), payload.get("season"), payload.get("episode"))
        return
    if kind == "lidarr":
        from resonance import lidarr

        lidarr.run_queued(payload)
        return
    logger.info("unknown ARR queue item %s", kind)
