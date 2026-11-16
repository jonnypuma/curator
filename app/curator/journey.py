"""The path of each imported item, so the user can follow it: webhook, waiting, scan, scrape, file jobs, library update.

One row per item (an ingest queue key: the movie, show or album folder). The stages are a list in that row, each with a
status (waiting, running, done, failed, skipped), when it started and ended, and a line of detail. Each player's library
update is its own stage (library:kodi, library:plex ...). A row is done when no stage is waiting or running.

Recording a stage never raises: following an import must not stop the import. The webhook queue binds the rows it is
working on to its thread, so the library queue can carry them into the player jobs it queues (bound() and current()).
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from resonance import db

logger = logging.getLogger(__name__)
KEEP = 300
ORDER = ("received", "waiting", "scan", "scrape", "files", "library")
OPEN = {"waiting", "running"}
_lock = threading.Lock()
_bound = threading.local()


def _now():
    # With its offset, so a browser in another time zone reads the right moment.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _set(stages, name, status, detail=""):
    """The stage list with one stage set. A stage keeps its first start time; a finished stage gets an end time."""
    stages = [dict(item) for item in stages or []]
    if name.startswith("library:"):
        # A player's own stage replaces the stand-in that held the journey open until the players were known.
        stages = [item for item in stages if item.get("stage") != "library"]
    found = next((item for item in stages if item.get("stage") == name), None)
    if found is None:
        found = {"stage": name, "started": _now()}
        stages.append(found)
    elif status == "running" and found.get("status") != "running":
        found["started"] = _now()
    found["status"] = status
    if status in OPEN:
        found.pop("ended", None)
    else:
        found["ended"] = _now()
    if detail:
        found["detail"] = str(detail)[:500]
    rank = {item: index for index, item in enumerate(ORDER)}
    stages.sort(key=lambda item: (rank.get(str(item.get("stage")).split(":")[0], 99), str(item.get("stage"))))
    return stages


def overall(stages):
    """active while any stage is waiting or running, failed when one failed, else done."""
    states = [item.get("status") for item in stages or []]
    if any(state in OPEN for state in states):
        return "active"
    return "failed" if "failed" in states else "done"


def received(item, outcome="queued", detail=""):
    """A webhook item arrived. Another event for a folder already on its way joins that journey. Returns its id.

    outcome is queued, or unmapped for an item that could not be placed in the library (that journey ends there)."""
    try:
        key = str(item.get("key") or item.get("path") or "")
        label = f"{item.get('source') or ''} {item.get('event') or ''}".strip()
        with _lock:
            row = None
            if outcome == "queued":
                row = db.fetchone(
                    "SELECT id::text AS id, stages, events FROM ingest_journeys WHERE key = %s AND status = 'active' "
                    "ORDER BY created_at DESC LIMIT 1", (key,))
            if row:
                stages = _set(row["stages"], "received", "done", f"{int(row['events']) + 1} webhooks, the latest {label}")
                stages = _set(stages, "waiting", "waiting", detail or "Waiting for more webhooks for this folder")
                db.execute("UPDATE ingest_journeys SET stages = %s, events = events + 1, status = %s, updated_at = LOCALTIMESTAMP "
                           "WHERE id = %s", (Jsonb(stages), overall(stages), row["id"]))
                return row["id"]
            if outcome == "queued":
                stages = _set([], "received", "done", label)
                stages = _set(stages, "waiting", "waiting", detail or "Waiting for more webhooks for this folder")
            else:
                stages = _set([], "received", "failed", detail or outcome)
            found = db.fetchone(
                "INSERT INTO ingest_journeys (key, media, source, event_type, title, path, stages, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id::text AS id",
                (key, str(item.get("media") or "")[:10], str(item.get("source") or "")[:20], str(item.get("event") or ""),
                 str(item.get("title") or "")[:300], str(item.get("path") or ""), Jsonb(stages), overall(stages)))
            db.execute("DELETE FROM ingest_journeys WHERE id IN (SELECT id FROM ingest_journeys ORDER BY updated_at DESC OFFSET %s)",
                       (KEEP,))
            if overall(stages) == "failed":
                _announce(item.get("title"), item.get("path"), stages)
            return (found or {}).get("id")
    except Exception:
        logger.exception("could not record the webhook journey")
        return None


def requested(title, path, media, event="Update library"):
    """A library update the user started in Curator: no webhook, no scan, only the players. Returns its id."""
    try:
        stages = _set([], "received", "done", f"{event} from Curator")
        found = db.fetchone(
            "INSERT INTO ingest_journeys (key, media, source, event_type, title, path, stages, status) "
            "VALUES (%s, %s, 'curator', %s, %s, %s, %s, 'active') RETURNING id::text AS id",
            (f"manual:{path or title}", str(media or "")[:10], event, str(title or "")[:300], str(path or ""), Jsonb(stages)))
        return (found or {}).get("id")
    except Exception:
        logger.exception("could not record the library update")
        return None


def settle(ids):
    """A journey that ended up with nothing to wait for (no player took the job) is done."""
    try:
        _update(ids, lambda stages: stages if any(str(item.get("stage")).startswith("library") for item in stages)
                else _set(stages, "library", "skipped", "No player took this update"))
    except Exception:
        logger.exception("could not settle the library update")


def for_keys(keys):
    """The newest journey of each of these ingest queue keys: the one the queue is working on."""
    keys = [str(key) for key in keys or [] if key]
    if not keys:
        return []
    try:
        rows = db.fetchall("SELECT DISTINCT ON (key) id::text AS id FROM ingest_journeys WHERE key = ANY(%s) "
                           "ORDER BY key, created_at DESC", (keys,))
        return [row["id"] for row in rows]
    except Exception:
        logger.exception("could not find the webhook journeys")
        return []


def _announce(title, path, stages):
    """Tell the notification targets that want it that an import ended with a failed step. Never raises."""
    try:
        from curator import outbound

        lines = [f"{label(item.get('stage'))}: {item.get('detail') or 'failed'}"
                 for item in stages or [] if item.get("status") == "failed"]
        if path:
            lines.append(path)
        outbound.send("import_failed", f"Import failed: {title or path or 'an item'}", "\n".join(lines), "error")
    except Exception:
        logger.exception("could not send the failed import notification")


_LABELS = {"received": "Webhook", "waiting": "Waiting", "scan": "Scan", "scrape": "Scrape", "files": "File jobs", "library": "Library update"}


def label(stage):
    """Webhook, Scan ... and a player's library update by the player's name: Library update (kodi)."""
    base, _, player = str(stage or "").partition(":")
    name = _LABELS.get(base, base)
    return f"{name} ({player})" if player else name


def _update(ids, change):
    ids = [str(item) for item in ids or [] if item]
    if not ids:
        return
    with _lock:
        for row in db.fetchall("SELECT id::text AS id, title, path, status, stages FROM ingest_journeys WHERE id = ANY(%s::uuid[])", (ids,)):
            stages = change(row["stages"] or [])
            status = overall(stages)
            db.execute("UPDATE ingest_journeys SET stages = %s, status = %s, updated_at = LOCALTIMESTAMP WHERE id = %s",
                       (Jsonb(stages), status, row["id"]))
            if status == "failed" and row.get("status") != "failed":
                _announce(row.get("title"), row.get("path"), stages)


def stage(ids, name, status, detail=""):
    """Set one stage on these journeys and settle their overall status."""
    try:
        _update(ids, lambda stages: _set(stages, name, status, detail))
    except Exception:
        logger.exception("could not record the %s stage", name)


def fail_open(ids, detail):
    """A run that stopped: every stage still waiting or running on these journeys failed."""
    def change(stages):
        for item in [item for item in stages if item.get("status") in OPEN]:
            stages = _set(stages, item["stage"], "failed", detail)
        return stages

    try:
        _update(ids, change)
    except Exception:
        logger.exception("could not record the failed journey")


@contextmanager
def bound(ids):
    """While this block runs, library jobs queued on this thread carry these journeys."""
    previous = getattr(_bound, "ids", [])
    _bound.ids = [str(item) for item in ids or [] if item]
    try:
        yield
    finally:
        _bound.ids = previous


def current():
    return list(getattr(_bound, "ids", []) or [])


def recent(active_only=False, limit=100):
    where = "WHERE status = 'active'" if active_only else ""
    rows = db.fetchall(
        "SELECT id::text AS id, media, source, event_type, title, path, events, stages, status, created_at, updated_at "
        f"FROM ingest_journeys {where} ORDER BY updated_at DESC LIMIT %s", (int(limit),))
    return [dict(row, created_at=str(row["created_at"]), updated_at=str(row["updated_at"])) for row in rows]


def stamp():
    """Changes whenever a journey is added, moves a step or is removed: the newest update time and the count."""
    row = db.fetchone("SELECT max(updated_at) AS newest, count(*)::int AS n FROM ingest_journeys") or {}
    return f"{row.get('newest') or ''}|{row.get('n') or 0}"


def clear_finished():
    """Remove the journeys that are done or failed. Returns how many went."""
    rows = db.fetchall("SELECT id FROM ingest_journeys WHERE status <> 'active'")
    if rows:
        db.execute("DELETE FROM ingest_journeys WHERE status <> 'active'")
    return len(rows)
