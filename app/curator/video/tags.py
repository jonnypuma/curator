"""Tag manager for movies and TV shows: list, rename or merge, delete, add and remove, and fetch
TMDB keywords as tags.

Locked items are never changed. A changed item gets "tags" in its locked fields, the same as an
inline edit, so a later scrape keeps the tags. Fetching keywords adds to the tags and works on
items whose tags field is locked, because it is an explicit request.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from curator.scrapers.http import Client, ScrapeError
from curator.scrapers.tmdb import Tmdb
from curator.video import config, exports
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

TABLES = {"movies": "movies", "tv": "tv_shows", "movie": "movies", "show": "tv_shows",
          "episodes": "tv_episodes", "episode": "tv_episodes"}
MAX_TAG = 100


def _table(media):
    table = TABLES.get(media)
    if not table:
        raise AppError("Tags are kept for movies, shows and episodes", 400)
    return table


def clean_tag(value):
    text = " ".join(str(value or "").split())
    if not text:
        raise AppError("A tag cannot be empty", 400)
    return text[:MAX_TAG]


def clean_list(values):
    seen, found = set(), []
    for value in values or []:
        text = " ".join(str(value or "").split())[:MAX_TAG]
        if text and text.lower() not in seen:
            seen.add(text.lower())
            found.append(text)
    return found


def list_tags(media, ids=None):
    """Tags with use counts, over the whole library or only the given items."""
    table = _table(media)
    where, params = "", ()
    if ids is not None:
        where, params = "WHERE id = ANY(%s::uuid[]) ", (list(ids),)
    rows = db.fetchall(
        f"SELECT tag, count(*)::int AS count, count(*) FILTER (WHERE locked)::int AS locked "
        f"FROM {table}, unnest(tags) AS tag {where}GROUP BY tag ORDER BY lower(tag)",
        params,
    )
    return [dict(row) for row in rows]


_LOCK_TAGS = "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['tags'])))"


def rename(media, old, new):
    """Rename a tag everywhere, merging into an existing tag of the new name. Returns changed ids."""
    table = _table(media)
    old, new = clean_tag(old), clean_tag(new)
    rows = db.fetchall(
        f"""
        UPDATE {table} SET tags = ARRAY(
            SELECT DISTINCT ON (lower(value)) value FROM (
                SELECT CASE WHEN t = %s THEN %s ELSE t END AS value, n
                FROM unnest(tags) WITH ORDINALITY AS u(t, n)
            ) renamed ORDER BY lower(value), n
        ), {_LOCK_TAGS}, updated_at = NOW()
        WHERE %s = ANY(tags) AND NOT locked RETURNING id
        """,
        (old, new, old),
    )
    return [str(row["id"]) for row in rows]


def delete(media, tag):
    table = _table(media)
    tag = clean_tag(tag)
    rows = db.fetchall(
        f"UPDATE {table} SET tags = array_remove(tags, %s), {_LOCK_TAGS}, updated_at = NOW() "
        f"WHERE %s = ANY(tags) AND NOT locked RETURNING id",
        (tag, tag),
    )
    return [str(row["id"]) for row in rows]


def apply(kind, ids, add=(), remove=()):
    """Add and remove tags on picked items. Returns changed ids."""
    table = _table(kind)
    add, remove = clean_list(add), clean_list(remove)
    if not add and not remove:
        raise AppError("Name at least one tag to add or remove", 400)
    removing = [tag.lower() for tag in remove]
    rows = db.fetchall(
        f"""
        UPDATE {table} SET tags = ARRAY(
            SELECT value FROM (
                SELECT DISTINCT ON (lower(value)) value, n FROM (
                    SELECT t AS value, n FROM unnest(tags) WITH ORDINALITY AS u(t, n)
                    UNION ALL
                    SELECT a, 100000 + m FROM unnest(%s::text[]) WITH ORDINALITY AS v(a, m)
                ) combined
                WHERE NOT (lower(value) = ANY(%s::text[]))
                ORDER BY lower(value), n
            ) kept ORDER BY n
        ), {_LOCK_TAGS}, updated_at = NOW()
        WHERE id = ANY(%s::uuid[]) AND NOT locked RETURNING id
        """,
        (add, removing, list(ids)),
    )
    return [str(row["id"]) for row in rows]


async def _keywords(kind, rows, cfg):
    client = Client()
    try:
        scraper = Tmdb(client, cfg["tmdb_key"], cfg["language"], cfg["country"])
        found = {}
        for row in rows:
            ids = dict(row.get("ids") or {})
            for key in ("tmdb", "imdb", "tvdb"):
                if row.get(f"{key}_id") and not ids.get(key):
                    ids[key] = row[f"{key}_id"]
            try:
                if kind == "movie":
                    tmdb_id = await scraper.movie_id(ids, row.get("title"), row.get("year"))
                    data = await scraper._get(f"/movie/{tmdb_id}/keywords") if tmdb_id else {}
                    words = [item.get("name") for item in (data or {}).get("keywords") or []]
                elif kind == "episode" and row.get("show_tmdb") and row.get("season_number") is not None:
                    data = await scraper._get(
                        f"/tv/{row['show_tmdb']}/season/{row['season_number']}/episode/{row['episode_number']}/keywords"
                    )
                    words = [item.get("name") for item in (data or {}).get("results") or (data or {}).get("keywords") or []]
                else:
                    tmdb_id = await scraper.tv_id(ids, row.get("title"), row.get("year"))
                    data = await scraper._get(f"/tv/{tmdb_id}/keywords") if tmdb_id else {}
                    words = [item.get("name") for item in (data or {}).get("results") or []]
            except ScrapeError as exc:
                logger.warning("keywords for %s failed: %s", row.get("title"), exc)
                continue
            found[str(row["id"])] = clean_list(words)
        return found
    finally:
        await client.close()


def scrape(kind, ids):
    """Add TMDB keywords to the tags of picked items. Returns (changed ids, items without keywords)."""
    table = _table(kind)
    cfg = config.current()
    if not cfg.get("tmdb_key"):
        raise AppError("Add a TMDB key under Settings > General > API credentials first", 400)
    if table == "tv_episodes":
        rows = db.fetchall(
            """
            SELECT e.id, e.title, e.season_number, e.episode_number, e.ids, s.tmdb_id AS show_tmdb, s.year
            FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
            WHERE e.id = ANY(%s::uuid[]) AND NOT e.locked
            """,
            (list(ids),),
        )
        keyword_kind = "episode"
    else:
        id_columns = "tmdb_id, imdb_id" + (", tvdb_id" if table == "tv_shows" else "")
        rows = db.fetchall(f"SELECT id, title, year, ids, {id_columns} FROM {table} "
                           f"WHERE id = ANY(%s::uuid[]) AND NOT locked", (list(ids),))
        keyword_kind = "movie" if table == "movies" else "show"
    found = asyncio.run(_keywords(keyword_kind, rows, cfg))
    changed = []
    for row_id, words in found.items():
        if words:
            changed += apply(kind, [row_id], add=words)
    return changed, len(rows) - len([words for words in found.values() if words])


def write_nfos(kind, ids):
    """Rewrite the .nfo of changed items in the background when edits are written straight away."""
    cfg = config.current()
    if not ids or not cfg["write_on_edit"]:
        return False
    table = _table(kind)

    def work():
        for row_id in ids:
            try:
                if table == "movies":
                    exports.write_movie(row_id, cfg)
                elif table == "tv_episodes":
                    owner = db.fetchone("SELECT show_id FROM tv_episodes WHERE id = %s", (row_id,))
                    if owner:
                        exports.write_show(owner["show_id"], cfg, episode_ids=[str(row_id)])
                else:
                    exports.write_show(row_id, cfg)
            except Exception as exc:
                logger.warning("tag .nfo write failed for %s: %s", row_id, exc)

    threading.Thread(target=work, name="tag-nfo", daemon=True).start()
    return True
