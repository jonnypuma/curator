"""A saved movie or TV filter can run one action on a schedule: scrape what is missing, check file integrity, or
download trailers, for the items the filter matches at that moment.

The schedule is the one the "Added to the library" message uses: every day or every week on a chosen day, at an hour
in the schedule time zone (digest.due). The job goes through the shared queue, so it shows in the Jobs panel and waits
for a running scan. Only what the server can judge counts: the ribbons below and the column filters a scan tags with.
A filter with nothing the server can judge never runs, so an action can never fall back to the whole library.
"""
from __future__ import annotations

import logging

from curator.video import saved_filters
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

ACTIONS = {
    "scrape": "Scrape what is missing",
    "integrity": "Quick integrity check",
    "trailers": "Download trailers",
}
# Ribbons an action can judge on top of the ones a scan tags with. {a} is the movie (m) or show (s) alias.
ACTION_RIBBONS = {
    "new": "{a}.status = 'NEW'",
    "latest": "{a}.created_at >= LOCALTIMESTAMP - interval '30 days'",
    "unscraped": "{a}.scraped_at IS NULL",
    "scrapefail": "COALESCE({a}.scrape_error, '') <> ''",
    "nonfo": "{a}.nfo_path IS NULL",
    "noposter": "NOT (COALESCE({a}.artwork, '{{}}'::jsonb) ? 'poster')",
    "notrailer": "(COALESCE({a}.trailer, '') = '' AND {a}.has_local_trailer IS NOT TRUE)",
    "ignored": "{a}.status = 'IGNORED'",
}
MOVIE_RIBBONS = {
    "upgrade": "m.upgrade_source_id IS NOT NULL",
    "duplicate": "m.duplicate_release IS TRUE",
    "probefail": "COALESCE(f.probe_error, '') <> ''",
    "corrupt": "f.integrity = 'corrupt'",
}


def normalize(action, every, hour, weekday):
    """(action or None, every, hour, weekday) cleaned. No action means off."""
    from curator import digest

    action = action if action in ACTIONS else None
    schedule = digest.normalize({"every": every if action else "off", "hour": hour, "weekday": weekday})
    return action, schedule["every"], schedule["hour"], schedule["weekday"]


def clauses(payload, media):
    """SQL an action can match for this filter: the scan's tag clauses plus the action ribbons. ([], []) when none."""
    parts, params = saved_filters.tag_clauses(payload, media)
    alias = "m" if media == "movies" else "s"
    for key in saved_filters._payload(payload).get("ribbons") or []:
        key = str(key)
        if key in saved_filters.RIBBONS or key in saved_filters.OWN_RIBBONS:
            continue                      # already in the scan's clauses
        sql = ACTION_RIBBONS.get(key)
        if sql:
            parts.append(sql.format(a=alias))
        elif media == "movies" and key in MOVIE_RIBBONS:
            parts.append(MOVIE_RIBBONS[key])
    return parts, params


def unmatched_ribbons(payload, media):
    """Ribbons in the filter that the server cannot judge (they only work on the page)."""
    known = set(saved_filters.RIBBONS) | set(saved_filters.OWN_RIBBONS) | set(ACTION_RIBBONS)
    if media == "movies":
        known |= set(MOVIE_RIBBONS)
    return [str(key) for key in saved_filters._payload(payload).get("ribbons") or [] if str(key) not in known]


def matching_ids(media, payload):
    """The unlocked, not wanted movie or show ids the filter matches now. None when nothing can be matched."""
    where, params = clauses(payload, media)
    if not where:
        return None
    if media == "movies":
        sql = ("SELECT m.id FROM movies m LEFT JOIN video_files f ON f.id = m.file_id "
               f"WHERE NOT m.locked AND NOT COALESCE(m.wanted, FALSE) AND {' AND '.join(where)}")
    else:
        sql = ("SELECT DISTINCT s.id FROM tv_shows s LEFT JOIN tv_episodes e ON e.show_id = s.id "
               "LEFT JOIN video_files f ON f.id = e.file_id "
               f"WHERE NOT s.locked AND NOT COALESCE(s.wanted, FALSE) AND {' AND '.join(where)}")
    return [str(row["id"]) for row in db.fetchall(sql, tuple(params))]


def run(row):
    """Queue the filter's action for what it matches now. Returns a one-line result, also stored on the filter."""
    from resonance import scan_queue

    media = row["media"]
    action = row.get("action")
    if media not in ("movies", "tv") or action not in ACTIONS:
        raise AppError("Only a movie or TV filter with an action can run", 400)
    ids = matching_ids(media, row.get("payload"))
    if ids is None:
        result = "Nothing in this filter can be matched outside the page, so the action did not run."
    elif not ids:
        result = "Nothing matched, so the action did not run."
    else:
        label = f"Saved filter: {row['name']}"
        kind = "movie" if media == "movies" else "show"
        if action == "scrape":
            spec = {"kind": "scrape", "media": media, "scope": "selected", "ids": ids, "policy": "missing", "label": label}
        else:
            spec = {"kind": "files", "op": action, "media": kind, "ids": ids, "label": label}
        outcome = scan_queue.submit(spec)
        noun = "movie" if media == "movies" else "show"
        what = f"{ACTIONS[action]} for {len(ids)} {noun}{'s' if len(ids) != 1 else ''}"
        result = {"started": f"{what}: started", "queued": f"{what}: waiting in the queue",
                  "duplicate": f"{what}: the same job is already waiting"}.get(outcome, f"{what}: {outcome}")
    db.execute("UPDATE saved_filters SET action_last_result = %s WHERE id = %s", (result[:300], row["id"]))
    return result


def run_now(filter_id):
    row = db.fetchone("SELECT * FROM saved_filters WHERE id = %s", (str(filter_id),))
    if not row:
        raise AppError("That saved filter is gone", 404)
    return run(dict(row))


def tick(local_now=None):
    """Called by the scheduler every few seconds. Runs each filter action once when it is due. Returns how many ran."""
    from curator import digest

    rows = db.fetchall(
        "SELECT * FROM saved_filters WHERE action IS NOT NULL AND action_every <> 'off' AND media IN ('movies', 'tv')"
    )
    if not rows:
        return 0
    now = local_now or digest._local_now()
    ran = 0
    for row in rows:
        row = dict(row)
        schedule = {"every": row["action_every"], "hour": row["action_hour"], "weekday": row["action_weekday"]}
        if not digest.due(digest.normalize(schedule), now, row.get("action_last_day") or ""):
            continue
        db.execute("UPDATE saved_filters SET action_last_day = %s WHERE id = %s", (now.date().isoformat(), row["id"]))
        try:
            logger.info("saved filter %s: %s", row["name"], run(row))
            ran += 1
        except Exception:
            logger.exception("the action of saved filter %s failed", row.get("name"))
    return ran
