"""The "Added to the library" notification: one message a day or a week listing what came in.

Settings, Notifications sets how often (off, every day, every week on a chosen day) and at which hour. Each target
ticks the event like any other. The message lists the movies, episodes (grouped per show), albums and music videos
added since the last digest was sent; when nothing was added, nothing is sent. The time of the last digest is kept in
the config folder, so a restart neither sends it twice nor loses the window.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from resonance import db

logger = logging.getLogger(__name__)

EVENT = "library_digest"
EVERY = ("off", "day", "week")
LIST_LIMIT = 15
DEFAULT = {"every": "off", "hour": 9, "weekday": 0}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def normalize(value):
    """The saved schedule, cleaned: every off/day/week, hour 0-23, weekday 0 (Monday) to 6."""
    value = value if isinstance(value, dict) else {}
    every = value.get("every") if value.get("every") in EVERY else "off"

    def number(key, low, high):
        try:
            return max(low, min(high, int(value.get(key, DEFAULT[key]))))
        except (TypeError, ValueError):
            return DEFAULT[key]

    return {"every": every, "hour": number("hour", 0, 23), "weekday": number("weekday", 0, 6)}


def _state_path():
    from resonance.paths import config_dir

    return os.path.join(config_dir(), "digest_state.json")


def _state():
    try:
        with open(_state_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def last_sent():
    """When the last digest was sent, on the database's clock (the one created_at is stamped with)."""
    try:
        text = _state().get("last_sent") or ""
        return datetime.fromisoformat(text) if text else None
    except (ValueError, TypeError):
        return None


def last_day():
    """The local date (schedule time zone) the last digest was sent on, as YYYY-MM-DD."""
    return str(_state().get("last_day") or "")


def _remember(moment, day):
    try:
        with open(_state_path(), "w", encoding="utf-8") as handle:
            json.dump({"last_sent": moment.isoformat(timespec="seconds"), "last_day": day}, handle)
    except OSError:
        logger.warning("could not save the time of the last library digest")


def _db_now():
    """The database's clock, so the window compares with created_at however the two containers' time zones differ."""
    row = db.fetchone("SELECT LOCALTIMESTAMP AS now")
    return row["now"] if row and row.get("now") else datetime.now()


def _local_now():
    from resonance import cron

    return datetime.now(cron.get_timezone())


def _names(items, limit=LIST_LIMIT):
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def collect(since, until):
    """What was added in the window, as lists of display names: {"movies", "episodes", "shows", "albums", "musicvideos"}."""
    window = (since, until)
    movies = db.fetchall(
        """
        SELECT title, year FROM movies
        WHERE created_at > %s AND created_at <= %s AND NOT COALESCE(wanted, FALSE) AND strpos(path, 'wanted://') <> 1
        ORDER BY created_at
        """,
        window,
    )
    episodes = db.fetchall(
        """
        SELECT s.title, s.year, e.season_number, e.episode_number
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
        WHERE e.created_at > %s AND e.created_at <= %s AND NOT e.missing AND strpos(e.path, 'missing://') <> 1
        ORDER BY lower(s.title), e.season_number, e.episode_number
        """,
        window,
    )
    albums = db.fetchall(
        """
        SELECT ar.name AS artist, al.title, al.release_year
        FROM albums al LEFT JOIN artists ar ON ar.id = al.artist_id
        WHERE al.created_at > %s AND al.created_at <= %s
        ORDER BY al.created_at
        """,
        window,
    )
    videos = db.fetchall(
        "SELECT artist, title FROM music_videos WHERE created_at > %s AND created_at <= %s ORDER BY created_at",
        window,
    )
    from curator.ingest import compact_episodes

    shows = {}
    for row in episodes:
        name = f"{row['title']} ({row['year']})" if row.get("year") else str(row.get("title") or "")
        if int(row.get("episode_number") or 0) < 0:
            continue
        shows.setdefault(name, []).append(f"S{int(row['season_number']):02d}E{int(row['episode_number']):02d}")
    return {
        "movies": [f"{row['title']} ({row['year']})" if row.get("year") else str(row["title"]) for row in movies],
        "episodes": len(episodes),
        "shows": [compact_episodes(f"{name} {', '.join(codes)}") for name, codes in shows.items()],
        "albums": [" — ".join(part for part in (row.get("artist"), row.get("title")) if part)
                   + (f" ({row['release_year']})" if row.get("release_year") else "") for row in albums],
        "musicvideos": [" — ".join(part for part in (row.get("artist"), row.get("title")) if part) for row in videos],
    }


def message(found, every="day"):
    """(title, body) for the notification, or None when nothing was added."""
    parts = []
    if found["movies"]:
        parts.append(f"Movies ({len(found['movies'])}): {_names(found['movies'])}")
    if found["shows"]:
        count = found["episodes"]
        parts.append(f"TV ({count} episode{'s' if count != 1 else ''}): {_names(found['shows'])}")
    if found["albums"]:
        parts.append(f"Albums ({len(found['albums'])}): {_names(found['albums'])}")
    if found["musicvideos"]:
        parts.append(f"Music videos ({len(found['musicvideos'])}): {_names(found['musicvideos'])}")
    if not parts:
        return None
    period = "this week" if every == "week" else "today" if every == "day" else "lately"
    return f"Added to the library {period}", "\n".join(parts)


def _window_start(every, now):
    previous = last_sent()
    if previous and previous < now:
        return previous
    return now - (timedelta(days=7) if every == "week" else timedelta(days=1))


def preview(cfg=None):
    """The digest as it would be sent now, without sending it or moving the window."""
    schedule = normalize(cfg)
    now = _db_now()
    found = collect(_window_start(schedule["every"], now), now)
    built = message(found, schedule["every"])
    return {"title": built[0] if built else "", "message": built[1] if built else "",
            "since": _window_start(schedule["every"], now).isoformat(timespec="minutes"), "empty": not built}


def send_now(cfg=None):
    """Send the digest for the time since the last one, and start the next window now. Returns what was sent."""
    from curator import outbound

    schedule = normalize(cfg)
    now = _db_now()
    built = message(collect(_window_start(schedule["every"], now), now), schedule["every"])
    _remember(now, _local_now().date().isoformat())
    if built:
        outbound.send(EVENT, built[0], built[1], "info")
    return {"sent": bool(built), "title": built[0] if built else "", "message": built[1] if built else ""}


def due(schedule, now, previous_day):
    """True when the schedule's hour has come today (and today is its weekday) and today's digest is not sent yet.

    now is local time in the schedule's time zone; previous_day the local date of the last digest (YYYY-MM-DD)."""
    if schedule["every"] == "off" or now.hour != schedule["hour"]:
        return False
    if schedule["every"] == "week" and now.weekday() != schedule["weekday"]:
        return False
    return previous_day != now.date().isoformat()


def tick(local_now=None):
    """Called by the scheduler every few seconds. Sends the digest once when it is due."""
    from resonance.settings import load

    schedule = normalize(load().get("outbound_digest"))
    if schedule["every"] == "off":
        return False
    now = local_now or _local_now()
    if not due(schedule, now, last_day()):
        return False
    try:
        send_now(schedule)
    except Exception:
        logger.exception("the library digest could not be sent")
        _remember(last_sent() or datetime.now(), now.date().isoformat())     # no retry every 15 s for the rest of the hour
    return True
