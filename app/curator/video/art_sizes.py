"""Width and height of each artwork file, kept in the item's artwork map so checks read the database, not the files.

The map gets "_sizes": {path: [width, height, mtime, bytes]}. It is filled whenever an artwork map is saved (a scan, a
pick, a download): a file is opened only when it is new, or its modification time or size changed; otherwise the
stored entry is kept. Files that are gone lose their entry. A check that finds no entry reads the file once and
writes what it learned back (remember()).
"""
from __future__ import annotations

import logging
import os

from curator.video import naming

logger = logging.getLogger(__name__)
KEY = "_sizes"


def _stamp(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return int(stat.st_mtime), int(stat.st_size)


def entry(path, size=None):
    """[width, height, mtime, bytes] for a file, reading its size when not given. None when it cannot be read."""
    stamp = _stamp(path)
    if not stamp:
        return None
    if size is None:
        from curator.video.art_fetch import image_size

        size = image_size(path)
    if not size or not size[0] or not size[1]:
        return None
    return [int(size[0]), int(size[1]), stamp[0], stamp[1]]


def _artwork_paths(art):
    for key, value in (art or {}).items():
        if str(key).startswith("_") or not isinstance(value, str) or not value:
            continue
        if os.path.splitext(value)[1].lower() in naming.IMAGE_EXTS:
            yield value


def with_sizes(old, new):
    """The new artwork map with a "_sizes" entry for each image file in it. Entries of the old map (or the new one)
    are kept while the file's modification time and size are the same. Never raises."""
    if not isinstance(new, dict):
        return new
    try:
        known = {**(((old or {}) if isinstance(old, dict) else {}).get(KEY) or {}), **(new.get(KEY) or {})}
        sizes = {}
        for path in dict.fromkeys(_artwork_paths(new)):
            stamp = _stamp(path)
            if not stamp:
                continue
            previous = known.get(path)
            if isinstance(previous, list) and len(previous) >= 4 and [previous[2], previous[3]] == list(stamp):
                sizes[path] = previous
                continue
            found = entry(path)
            if found:
                sizes[path] = found
        out = {key: value for key, value in new.items() if key != KEY}
        if sizes:
            out[KEY] = sizes
        return out
    except Exception:
        logger.debug("artwork sizes could not be recorded", exc_info=True)
        return new


def size_of(art, path):
    """(width, height) from the map's "_sizes", or None when it has no entry for that path."""
    found = ((art or {}).get(KEY) or {}).get(path)
    if isinstance(found, list) and len(found) >= 2 and found[0] and found[1]:
        return int(found[0]), int(found[1])
    return None


TABLES = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes", "set": "movie_sets"}


def remember(kind, row_id, learned):
    """Add sizes a check read from the files to the row's artwork map. Never raises."""
    table = TABLES.get(kind)
    if not table or not learned:
        return
    try:
        from psycopg.types.json import Jsonb

        from resonance import db

        db.execute(
            f"UPDATE {table} SET artwork = jsonb_set(artwork, '{{{KEY}}}', COALESCE(artwork->'{KEY}', '{{}}'::jsonb) || %s::jsonb) "
            "WHERE id = %s",
            (Jsonb(learned), row_id),
        )
    except Exception:
        logger.debug("artwork sizes could not be saved", exc_info=True)
