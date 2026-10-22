"""Whether a stored video NFO still matches the database fields it was written from.

The first time a file is seen, the current database is stored as the baseline so the
library does not all turn purple. A later edit that is not written back shows as a change.
"""
import hashlib
import json
import logging
import time

from curator.scrapers.merge import unique_names
from resonance import db

logger = logging.getLogger(__name__)

# Rows whose .nfo was read and really differs from the database. The list is loaded on every
# start and refresh; without this the same .nfo files (often on a network share) were read and
# compared again each time. An entry holds while the stored and current fingerprints are unchanged.
_CONFIRM_SECONDS = 600
_confirmed = {}

FIELDS = {
    "movies": (
        "title", "original_title", "sort_title", "year", "edition", "tagline", "outline", "plot",
        "runtime_minutes", "mpaa", "premiered", "genres", "countries", "studios", "tags",
        "directors", "writers", "rating", "imdb_id", "tmdb_id", "trailer", "playcount",
    ),
    "movie_sets": ("name", "overview", "tmdb_collection_id"),
    "tv_shows": (
        "title", "original_title", "sort_title", "year", "plot", "outline", "tagline",
        "runtime_minutes", "mpaa", "premiered", "genres", "countries", "studios", "tags",
        "directors", "show_status", "rating", "imdb_id", "tvdb_id", "tmdb_id", "trailer",
    ),
    "tv_seasons": ("title", "plot", "premiered", "year", "season_number"),
    "tv_episodes": (
        "title", "plot", "aired", "season_number", "episode_number", "rating", "directors", "playcount",
    ),
}
# Added after the first episode fingerprints. Empty values stay out of the hash so an
# existing library does not all turn purple. A set value changes the fingerprint.
_EPISODE_EXTRA = (
    "user_rating", "display_season", "display_episode", "resume_position", "resume_total",
    "mpaa", "certifications", "original_title", "english_title",
)
_SHOW_EXTRA = ("user_rating", "top250", "playcount", "last_played", "original_language", "english_title")
_MOVIE_EXTRA = ("english_title",)
_SEASON_EXTRA = ("sort_title", "ids")
_EXTRA = {
    "tv_episodes": _EPISODE_EXTRA, "tv_shows": _SHOW_EXTRA, "movies": _MOVIE_EXTRA, "tv_seasons": _SEASON_EXTRA,
}


def _part(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "|".join(_part(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "1" if value else ""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if number == int(number) and "e" not in text.lower():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _extra_part(field, value):
    """A zero play count is the unset value, so it does not change an older fingerprint."""
    if field == "playcount" and value in (None, "", 0, "0"):
        return ""
    if field == "ids" and not value:
        return ""
    return _part(value)


def fingerprint(table, row):
    fields = list(FIELDS.get(table) or ())
    parts = [_part((row or {}).get(field)) for field in fields]
    extra_fields = _EXTRA.get(table) or ()
    extra = [_extra_part(field, (row or {}).get(field)) for field in extra_fields]
    if any(extra):
        parts.extend(extra)
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def changed(row, table):
    """True when this row has an NFO and the database no longer matches the stored fingerprint."""
    if not row or not row.get("nfo_path"):
        return False
    stored = row.get("nfo_digest") or ""
    if not stored:
        return False
    return stored != fingerprint(table, row)


def remember(table, row_id, row=None):
    """Store the fingerprint of the saved row, including columns this scan did not touch."""
    del row
    if table not in FIELDS or not row_id:
        return
    stored = db.fetchone(f"SELECT * FROM {table} WHERE id = %s", (row_id,))
    if not stored or not stored.get("nfo_path"):
        return
    stored = db.clean(dict(stored))
    if collapse_studios(table, stored):
        db.execute(f"UPDATE {table} SET studios = %s WHERE id = %s", (stored["studios"], row_id))
    db.execute(
        f"UPDATE {table} SET nfo_digest = %s WHERE id = %s",
        (fingerprint(table, stored), row_id),
    )


def collapse_studios(table, row):
    """Drop repeated studio names on the row. Returns True when the list changed."""
    if table not in {"movies", "tv_shows"} or not isinstance(row, dict):
        return False
    current = row.get("studios")
    if not isinstance(current, list):
        return False
    cleaned = unique_names(current)
    if cleaned == current:
        return False
    row["studios"] = cleaned
    return True


def apply(table, rows):
    """Set nfo_stale on each row. A file with no fingerprint yet is recorded and left clear."""
    pending = []
    repairs = []
    for row in rows or []:
        if collapse_studios(table, row) and row.get("id"):
            repairs.append((row["studios"], row["id"]))
        if not row.get("nfo_path"):
            row["nfo_stale"] = False
            continue
        current = fingerprint(table, row)
        stored = row.get("nfo_digest") or ""
        if not stored:
            pending.append((current, row["id"]))
            row["nfo_stale"] = False
            row["nfo_digest"] = current
            continue
        row["nfo_stale"] = stored != current
    cleared = _clear_hidden_changes(table, rows)
    if db.pool is None or not (pending or repairs or cleared):
        return
    with db.transaction() as conn:
        for studios, row_id in repairs:
            conn.execute(f"UPDATE {table} SET studios = %s WHERE id = %s", (studios, row_id))
        for digest, row_id in pending:
            conn.execute(f"UPDATE {table} SET nfo_digest = %s WHERE id = %s AND nfo_digest IS NULL", (digest, row_id))
        for digest, row_id in cleared:
            conn.execute(f"UPDATE {table} SET nfo_digest = %s WHERE id = %s", (digest, row_id))


_KIND = {
    "movies": "movie",
    "movie_sets": "set",
    "tv_shows": "show",
    "tv_seasons": "season",
    "tv_episodes": "episode",
}
def _clear_hidden_changes(table, rows):
    """A fingerprint can move when the comparison shows no field. Keep that file clear."""
    kind = _KIND.get(table)
    cleared = []
    if not kind:
        return cleared
    from curator.video import nfo as video_nfo

    now = time.monotonic()
    reads = skipped = 0
    started = time.monotonic()
    for row in rows or []:
        if not row.get("nfo_stale") or not row.get("id"):
            continue
        key = (table, str(row["id"]))
        current = fingerprint(table, row)
        signature = (row.get("nfo_digest") or "", current)
        held = _confirmed.get(key)
        if held and held[0] == signature and now - held[1] < _CONFIRM_SECONDS:
            skipped += 1
            continue
        reads += 1
        text = video_nfo._read_text(row.get("nfo_path") or "")
        if not text:
            _confirmed[key] = (signature, now)
            continue
        seasons = _show_seasons(table, row)
        diff = video_nfo.changes(kind, row, text, seasons)
        if diff.get("notes") or diff.get("changes"):
            _confirmed[key] = (signature, now)
            continue
        _confirmed.pop(key, None)
        row["nfo_stale"] = False
        row["nfo_digest"] = current
        cleared.append((current, row["id"]))
    elapsed = time.monotonic() - started
    if reads and elapsed > 1.0:
        logger.info("nfo check (%s): read %d .nfo files in %.1fs (%d skipped as already checked)",
                    table, reads, elapsed, skipped)
    return cleared
    from curator.video import nfo as video_nfo

    for row in rows or []:
        if not row.get("nfo_stale") or not row.get("id"):
            continue
        text = video_nfo._read_text(row.get("nfo_path") or "")
        if not text:
            continue
        seasons = _show_seasons(table, row)
        diff = video_nfo.changes(kind, row, text, seasons)
        if diff.get("notes") or diff.get("changes"):
            continue
        current = fingerprint(table, row)
        row["nfo_stale"] = False
        row["nfo_digest"] = current
        cleared.append((current, row["id"]))
    return cleared


def _show_seasons(table, row):
    if table != "tv_shows" or not row.get("id") or db.pool is None:
        return None
    return db.fetchall(
        "SELECT id, season_number, plot FROM tv_seasons WHERE show_id = %s ORDER BY season_number",
        (row["id"],),
    )
