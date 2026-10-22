"""Whether a movie or show has a trailer and a theme song file on disk.

The library list cannot look at the disk for every row, so the answer is kept on the row (has_local_trailer and
has_local_theme). It is set after a scan, after a download or a file job, and once at startup for rows never checked.
NULL means not checked, or the folder could not be reached, so a drive that is offline never shows every title as
missing.
"""
from __future__ import annotations

import logging
import os

from resonance import db

logger = logging.getLogger(__name__)

KINDS = {"movies": "movies", "movie": "movies", "tv": "tv_shows", "show": "tv_shows"}
CHUNK = 200


def movie_flags(row):
    """(has a trailer, has a theme song) for a movie row, or None when its folder cannot be reached."""
    from curator.video import trailers

    folder = row.get("folder")
    if not folder or not row.get("path") or not os.path.isdir(folder):
        return None
    return bool(trailers.local_trailer(row)), bool(trailers.local_theme(folder))


def show_flags(row):
    """The same for a show row."""
    from curator.video import trailers

    folder = row.get("path")
    if not folder or not os.path.isdir(folder):
        return None
    return bool(trailers.show_trailer(row)), bool(trailers.local_theme(folder))


def _select(table, ids, targets, only_unchecked):
    if table == "movies":
        columns, place = "id, folder, path, parts, has_local_trailer, has_local_theme", "folder"
    else:
        columns, place = "id, title, path, has_local_trailer, has_local_theme", "path"
    where, params = ["COALESCE(wanted, false) = false"], []
    if ids is not None:
        where.append("id = ANY(%s::uuid[])")
        params.append([str(item) for item in ids])
    if targets:
        where.append(f"EXISTS (SELECT 1 FROM unnest(%s::text[]) AS t(p) WHERE {place} = t.p "
                     f"OR starts_with({place}, t.p || '/') OR starts_with(t.p, {place} || '/'))")
        params.append([str(item).rstrip("/") for item in targets])
    if only_unchecked:
        where.append("(has_local_trailer IS NULL OR has_local_theme IS NULL)")
    return f"SELECT {columns} FROM {table} WHERE {' AND '.join(where)}", params


def refresh(media, *, ids=None, targets=None, only_unchecked=False, touch=False):
    """Check the disk for the movies or shows chosen and store what is found. Returns how many rows changed.

    touch also moves updated_at, so an open library list picks the change up. A bulk check leaves it alone."""
    table = KINDS.get(media)
    if not table:
        return 0
    flags = movie_flags if table == "movies" else show_flags
    sql, params = _select(table, ids, targets, only_unchecked)
    stamp = ", updated_at = NOW()" if touch else ""
    update = f"UPDATE {table} SET has_local_trailer = %s, has_local_theme = %s{stamp} WHERE id = %s"
    changed = 0
    pending = []
    for row in db.fetchall(sql, params):
        row = dict(row)
        try:
            found = flags(row)
        except OSError:
            found = None
        if found is None or found == (row.get("has_local_trailer"), row.get("has_local_theme")):
            continue
        pending.append((found[0], found[1], row["id"]))
        if len(pending) >= CHUNK:
            changed += _write(update, pending)
            pending = []
    if pending:
        changed += _write(update, pending)
    return changed


def _write(update, rows):
    with db.transaction() as conn:
        for values in rows:
            conn.execute(update, values)
    return len(rows)


def refresh_item(kind, item_id):
    """After a download or a file job on one movie or show. A season or episode has no flag of its own."""
    if kind not in KINDS:
        return 0
    try:
        return refresh(kind, ids=[item_id], touch=True)
    except Exception:
        logger.exception("could not check the trailer and theme song of %s %s", kind, item_id)
        return 0


def backfill():
    """Fill in the rows that were never checked. This runs once in the background when the app starts."""
    total = 0
    for media in ("movies", "tv"):
        try:
            total += refresh(media, only_unchecked=True)
        except Exception:
            logger.exception("could not check trailers and theme songs for %s", media)
    if total:
        logger.info("trailer and theme song files checked for %d titles", total)
    return total
