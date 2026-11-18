"""Activity history: one searchable list of what Curator deleted, restored, renamed, moved or changed, and why.

record() never raises, because a failed history line must not stop the work it describes. A caller can name the reason
for everything underneath it with `with why("Bulk duplicate cleanup"):`, so a delete deep in a job is listed with the
job that asked for it. The newest KEEP rows are kept.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

KEEP = 20000
_PRUNE_EVERY = 500
_why = contextvars.ContextVar("history_why", default="")
_since_prune = {"count": 0}


@contextmanager
def why(reason):
    token = _why.set(str(reason or ""))
    try:
        yield
    finally:
        _why.reset(token)


def current_reason():
    """The reason named by why() around the running work, or ''."""
    return _why.get()


def record(action, title="", kind="", path="", detail=""):
    """Add one line. detail says what happened; the reason set by why() says what asked for it."""
    from resonance import db

    try:
        db.execute(
            "INSERT INTO activity_history (action, kind, title, path, detail, reason) VALUES (%s, %s, %s, %s, %s, %s)",
            (str(action)[:40], str(kind or "")[:20], str(title or "")[:300], str(path or ""), str(detail or "")[:1000],
             _why.get()[:200]),
        )
        _since_prune["count"] += 1
        if _since_prune["count"] >= _PRUNE_EVERY:
            _since_prune["count"] = 0
            db.execute("DELETE FROM activity_history WHERE id <= (SELECT id FROM activity_history ORDER BY id DESC OFFSET %s LIMIT 1)", (KEEP,))
    except Exception:
        logger.info("could not write an activity history line", exc_info=True)


def entries(search="", action="", limit=200, offset=0):
    """Newest first. Every word of search must appear in the title, path, detail or reason."""
    from resonance import db

    where, params = [], []
    for word in str(search or "").split():
        where.append("(title ILIKE %s OR path ILIKE %s OR detail ILIKE %s OR reason ILIKE %s)")
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like, like, like]
    if action:
        where.append("action = %s")
        params.append(action)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    limit = max(1, min(int(limit or 200), 1000))
    rows = db.fetchall(
        f"SELECT id, at, action, kind, title, path, detail, reason FROM activity_history {clause} "
        "ORDER BY id DESC LIMIT %s OFFSET %s",
        (*params, limit, max(0, int(offset or 0))),
    )
    actions = db.fetchall("SELECT DISTINCT action FROM activity_history ORDER BY action")
    return {
        "items": [{**dict(row), "at": row["at"].isoformat(timespec="seconds") if row.get("at") else None} for row in rows],
        "actions": [row["action"] for row in actions],
    }
