"""Finished jobs for the Jobs panel's Recent section: what ran, how it ended, and its log.

File jobs (rename, subtitles, Clean artwork and the rest) keep their log only in memory while they run, so they are
recorded here when they end. Scans, scrapes and background work jobs already have their own tables; recent() reads
those too, so every kind of job shows in one list.
"""
from __future__ import annotations

import logging

from resonance import db

logger = logging.getLogger(__name__)
KEEP = 300
LOG_LIMIT = 400_000
ITEMS_KEPT = 25


def items_result(names, count=None):
    """The names a job worked on, for its result: the first ITEMS_KEPT (no repeats) and how many there were.

    count: how many items there were when only the first ones were named. When they all fit, the count is the number
    of different names, so two copies of one movie do not read as "and 1 more"."""
    seen = []
    for name in names or ():
        text = str(name or "").strip()
        if text and text not in seen:
            seen.append(text)
    count = int(count or 0)
    return {"items": seen[:ITEMS_KEPT], "item_count": max(len(seen), count) if count > ITEMS_KEPT else len(seen)}


def names_text(names, count=None, shown=3):
    """'Heat (1995), Alien (1979) and 4 more' for a message."""
    names = [str(name) for name in names or () if str(name or "").strip()]
    count = max(int(count or 0), len(names))
    if not names:
        return ""
    head = ", ".join(names[:shown])
    rest = count - min(shown, len(names))
    return f"{head} and {rest} more" if rest > 0 else head


def record(kind, label, status, message="", result=None, log="", started_at=None, finished_at=None, lane="Files"):
    """Keep a finished job (and its log, cut to LOG_LIMIT characters). Never raises."""
    from psycopg.types.json import Jsonb

    try:
        text = str(log or "")
        if len(text) > LOG_LIMIT:
            text = "… (the start of the log was cut)\n" + text[-LOG_LIMIT:]
        db.execute(
            """
            INSERT INTO job_history (lane, kind, label, status, message, result, log, started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, LOCALTIMESTAMP))
            """,
            (lane, str(kind or "")[:60], str(label or "")[:200], str(status or "")[:20], str(message or "")[:2000],
             Jsonb(result or {}), text, started_at, finished_at),
        )
        db.execute("DELETE FROM job_history WHERE id IN (SELECT id FROM job_history ORDER BY finished_at DESC OFFSET %s)",
                   (KEEP,))
    except Exception:
        logger.exception("could not record the finished job")


def recent(limit=30):
    """The newest finished jobs of every kind, newest first: file jobs, work jobs, music scans, video scans, scrapes."""
    limit = max(1, min(200, int(limit or 30)))
    rows = []
    queries = (
        ("files", """SELECT id::text AS id, lane, kind, label, status, message, result, started_at, finished_at,
                            (COALESCE(log, '') <> '') AS has_log FROM job_history"""),
        ("work", """SELECT id::text AS id, 'Job' AS lane, kind, '' AS label, status, message, NULL::jsonb AS result,
                           started_at, finished_at, (COALESCE(log, '') <> '') AS has_log
                    FROM work_jobs WHERE status NOT IN ('running', 'queued', 'idle')"""),
        ("music-scan", """SELECT id::text AS id, 'Scan' AS lane, 'music-scan' AS kind,
                                 'Music scan' || COALESCE(' (' || mode || ')', '') AS label, status, message, result,
                                 started_at, finished_at, (COALESCE(log, '') <> '') AS has_log
                          FROM scan_jobs WHERE status NOT IN ('running', 'queued', 'idle')"""),
        ("video-scan", """SELECT id::text AS id, 'Scan' AS lane, 'video-scan' AS kind,
                                 CASE media WHEN 'tv' THEN 'TV' WHEN 'movies' THEN 'Movie' ELSE initcap(media) END
                                     || ' scan (' || mode || ')' AS label,
                                 status, message, result, started_at, finished_at, FALSE AS has_log
                          FROM video_scan_jobs WHERE status NOT IN ('running', 'queued', 'idle')"""),
        ("scrape", """SELECT id::text AS id, 'Scrape' AS lane, 'scrape' AS kind,
                             CASE media WHEN 'tv' THEN 'TV' WHEN 'movies' THEN 'Movie' WHEN 'sets' THEN 'Movie set'
                                  ELSE initcap(media) END || ' scrape' || COALESCE(' · ' || NULLIF(scope, ''), '') AS label,
                             status, message, result, started_at, finished_at, FALSE AS has_log
                      FROM video_scrape_jobs WHERE status NOT IN ('running', 'queued', 'idle')"""),
    )
    for source, sql in queries:
        try:
            for row in db.fetchall(f"{sql} ORDER BY finished_at DESC NULLS LAST LIMIT %s", (limit,)):
                item = db.clean(dict(row))
                item["source"] = source
                result = item.get("result") if isinstance(item.get("result"), dict) else {}
                item["items"] = [str(name) for name in (result.get("items") or [])][:ITEMS_KEPT]
                item["item_count"] = int(result.get("item_count") or len(item["items"]))
                rows.append(item)
        except Exception:
            logger.exception("could not read recent %s jobs", source)
    rows.sort(key=lambda item: str(item.get("finished_at") or item.get("started_at") or ""), reverse=True)
    return rows[:limit]


_LOG_SQL = {
    "files": "SELECT log FROM job_history WHERE id = %s",
    "work": "SELECT log FROM work_jobs WHERE id = %s",
    "music-scan": "SELECT log FROM scan_jobs WHERE id = %s",
}


def log_of(source, job_id):
    """The log of one finished job, or "" when that kind keeps none here (video scans: Scan history)."""
    sql = _LOG_SQL.get(source)
    if not sql:
        return ""
    row = db.fetchone(sql, (job_id,))
    return str((row or {}).get("log") or "")
