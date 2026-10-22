"""Recent Scan queue and ARR queue rows, kept the same way webhook history is kept."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
KEEP = 1000


def note(lane, source, event, title, path="", outcome="done", message=""):
    try:
        from resonance import db

        if db.pool is None:
            return
        db.execute(
            """
            INSERT INTO work_events (lane, source, event_type, title, path, outcome, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(lane or "")[:8],
                str(source or "")[:20],
                str(event or "")[:100],
                str(title or "")[:300],
                str(path or "")[:1000],
                str(outcome or "done")[:20],
                str(message or "")[:2000],
            ),
        )
        db.execute(
            """
            DELETE FROM work_events
            WHERE lane = %s AND id IN (
                SELECT id FROM work_events WHERE lane = %s ORDER BY received_at DESC OFFSET %s
            )
            """,
            (lane, lane, KEEP),
        )
    except Exception:
        logger.exception("could not record the %s queue event", lane)
    try:
        from curator import events

        events.emit(
            "WORK_EVENT",
            {
                "lane": lane,
                "source": source,
                "event": event,
                "title": title,
                "path": path,
                "outcome": outcome,
                "message": message,
            },
        )
    except Exception:
        logger.exception("could not emit the %s work event", lane)


def recent(lane, limit=60):
    from resonance import db

    if db.pool is None:
        return []
    rows = db.fetchall(
        """
        SELECT id::text AS id, received_at, source, event_type, title, path, outcome, message
        FROM work_events WHERE lane = %s
        ORDER BY received_at DESC LIMIT %s
        """,
        (lane, int(limit)),
    )
    return [dict(row) for row in rows]
