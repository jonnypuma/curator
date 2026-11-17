"""What changed: one view of a period, built from what Curator already records.

Added items come from the same lists the daily digest sends (curator.digest.collect), deletes, renames, moves and
other changes from the activity history, replaced pictures from the kept copies of replaced artwork, and failed jobs
from the job history. Nothing new is stored for this window, so it also covers the days before it existed.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from resonance import db

logger = logging.getLogger(__name__)
PERIODS = (1, 7, 30, 90)
LIST_LIMIT = 200

_ART_SQL = """
    SELECT x.art_kind, x.kind, x.created_at,
           COALESCE(m.title, s.title, ss.title, es.title, st.name, '') AS title,
           sn.season_number AS season, e.season_number AS ep_season, e.episode_number AS episode
    FROM video_art_extra x
    LEFT JOIN movies m ON x.kind = 'movie' AND m.id = x.item_id
    LEFT JOIN tv_shows s ON x.kind = 'show' AND s.id = x.item_id
    LEFT JOIN tv_seasons sn ON x.kind = 'season' AND sn.id = x.item_id
    LEFT JOIN tv_shows ss ON ss.id = sn.show_id
    LEFT JOIN tv_episodes e ON x.kind = 'episode' AND e.id = x.item_id
    LEFT JOIN tv_shows es ON es.id = e.show_id
    LEFT JOIN movie_sets st ON x.kind = 'set' AND st.id = x.item_id
    WHERE x.origin = 'replaced' AND x.created_at > %s AND x.created_at <= %s
    ORDER BY x.created_at DESC LIMIT %s
"""


def _stamp(value):
    return value.isoformat(timespec="seconds") if hasattr(value, "isoformat") else (str(value) if value else None)


def _art_name(row):
    title = str(row.get("title") or "")
    if row.get("kind") == "season" and row.get("season") is not None:
        return f"{title} season {int(row['season'])}"
    if row.get("kind") == "episode" and row.get("episode") is not None:
        return f"{title} S{int(row.get('ep_season') or 0):02d}E{int(row['episode']):02d}"
    return title


def _section(name, read, fallback):
    """One part of the view. A part that cannot be read is left empty, so the rest still shows."""
    try:
        return read()
    except Exception:
        logger.exception("what changed: could not read %s", name)
        return fallback


def _activity(since, until):
    counts = db.fetchall(
        "SELECT action, COUNT(*) AS count FROM activity_history WHERE at > %s AND at <= %s GROUP BY action ORDER BY action",
        (since, until),
    )
    rows = db.fetchall(
        "SELECT at, action, kind, title, detail, reason FROM activity_history WHERE at > %s AND at <= %s "
        "ORDER BY id DESC LIMIT %s",
        (since, until, LIST_LIMIT),
    )
    return {
        "counts": {row["action"]: int(row["count"]) for row in counts},
        "items": [{**dict(row), "at": _stamp(row.get("at"))} for row in rows],
    }


def _artwork(since, until):
    total = db.fetchone(
        "SELECT COUNT(*) AS count FROM video_art_extra WHERE origin = 'replaced' AND created_at > %s AND created_at <= %s",
        (since, until),
    )
    rows = db.fetchall(_ART_SQL, (since, until, LIST_LIMIT))
    return {
        "count": int((total or {}).get("count") or 0),
        "items": [{"at": _stamp(row.get("created_at")), "art": row["art_kind"], "kind": row["kind"], "title": _art_name(row)}
                  for row in rows],
    }


def _jobs(since, until):
    from curator import job_history

    start = _stamp(since)
    end = _stamp(until)
    done = [row for row in job_history.recent(200)
            if start < str(row.get("finished_at") or row.get("started_at") or "").replace(" ", "T")[:19] <= end]
    failed = [row for row in done if str(row.get("status") or "").lower() in {"failed", "error"}]
    return {
        "finished": len(done),
        "failed": [{"at": str(row.get("finished_at") or ""), "label": row.get("label") or row.get("kind") or "",
                    "message": row.get("message") or "", "lane": row.get("lane") or ""} for row in failed],
    }


def collect(days=7):
    """Everything that changed in the last `days` days."""
    from curator import digest

    days = int(days or 7)
    if days not in PERIODS:
        days = min(PERIODS, key=lambda value: abs(value - days))
    until = digest._db_now()
    since = until - timedelta(days=days)
    empty_added = {"movies": [], "episodes": 0, "shows": [], "albums": [], "musicvideos": []}
    return {
        "days": days, "since": _stamp(since), "until": _stamp(until), "periods": list(PERIODS),
        "added": _section("added items", lambda: digest.collect(since, until), empty_added),
        "activity": _section("the activity history", lambda: _activity(since, until), {"counts": {}, "items": []}),
        "artwork": _section("replaced artwork", lambda: _artwork(since, until), {"count": 0, "items": []}),
        "jobs": _section("the job history", lambda: _jobs(since, until), {"finished": 0, "failed": []}),
    }
