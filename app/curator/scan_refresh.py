"""Tell the players about items a scan changed: new or replaced metadata, artwork or ratings.

A scan can fill in or overwrite metadata, artwork and ratings for items the players already hold. A plain folder
scan does not make Kodi or Plex read those again, so the last step of a scan refreshes each changed item: Kodi and
Plex per item, Emby and Jellyfin by marking the item folders modified. Music for Kodi and Navidrome is covered by the
music library update every music scan already sends.

Changes are found by comparing a digest of each item before and after the scan, so it does not matter which step
made the change or whether the scan was incremental, full or deep. An item the scan added counts as changed.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

CATEGORIES = ("metadata", "artwork", "ratings")

_RATING_COLUMNS = ("ratings", "rating", "votes", "rating_imdb", "rating_tmdb", "rating_rt", "rating_rt_audience",
                   "rating_metacritic", "rating_metacritic_user", "rating_trakt", "rating_anilist", "rating_ofdb",
                   "rating_tvdb")

# What each part of an item is made of. Columns a scan rewrites for other reasons (paths, file links, status, scrape
# bookkeeping, .nfo stamps) are left out so they do not count as a change.
_PARTS = {
    "movie": {
        "table": "movies",
        "metadata": ("title", "original_title", "sort_title", "year", "edition", "tagline", "outline", "plot",
                     "runtime_minutes", "mpaa", "premiered", "genres", "countries", "studios", "tags", "directors",
                     "writers", "actors", "ids", "imdb_id", "tmdb_id", "top250", "set_id", "trailer", "certifications",
                     "languages", "original_language", "producers", "english_title"),
        "artwork": ("artwork",),
        "ratings": _RATING_COLUMNS,
    },
    "show": {
        "table": "tv_shows",
        "metadata": ("title", "original_title", "sort_title", "year", "plot", "outline", "show_status", "premiered",
                     "mpaa", "runtime_minutes", "genres", "studios", "tags", "actors", "ids", "imdb_id", "tmdb_id",
                     "tvdb_id", "season_names", "tagline", "countries", "original_language", "directors",
                     "certifications", "trailer", "english_title", "top250"),
        "artwork": ("artwork",),
        "ratings": _RATING_COLUMNS,
    },
    "season": {
        "table": "tv_seasons",
        "metadata": ("title", "plot", "premiered", "year", "sort_title", "ids"),
        "artwork": ("artwork",),
        "ratings": (),
    },
    "episode": {
        "table": "tv_episodes",
        "metadata": ("title", "plot", "aired", "runtime_minutes", "directors", "writers", "ids", "mpaa",
                     "certifications", "tags", "guest_stars", "english_title", "original_title", "display_season",
                     "display_episode"),
        "artwork": ("artwork",),
        "ratings": ("ratings", "rating", "votes", "rating_imdb", "rating_tmdb", "rating_rt", "rating_rt_audience",
                    "rating_metacritic", "rating_metacritic_user", "rating_trakt", "rating_anilist", "rating_ofdb",
                    "rating_tvdb"),
    },
    "album": {
        "table": "albums",
        "metadata": ("title", "title_custom", "release_year", "original_year", "type", "edition", "review",
                     "musicbrainz_release_group_id", "musicbrainz_release_id", "mood", "style", "theme", "label",
                     "boxset", "country", "catalog", "barcode", "release_status", "release_group", "genres"),
        "artwork": ("has_artwork", "artwork_width", "artwork_height"),
        "ratings": (),
    },
    "artist": {
        "table": "artists",
        "metadata": ("name", "name_custom", "biography", "biography_custom", "genres", "genres_custom", "type",
                     "formed", "origin", "years_active", "website", "sortname", "gender", "disambiguation", "style",
                     "mood", "instruments", "died", "disbanded", "musicbrainz_artist_id"),
        "artwork": ("has_artwork", "artwork_width", "artwork_height"),
        "ratings": (),
    },
}

_KINDS = {"movies": ("movie",), "tv": ("show", "season", "episode"), "music": ("artist", "album")}


def wanted(media, video_cfg=None, music_cfg=None):
    """The categories switched on for this media type under During a scan."""
    if media == "music":
        cfg = music_cfg if music_cfg is not None else _music_settings()
        return {name for name in ("metadata", "artwork") if cfg.get(f"scan_refresh_{name}")}
    cfg = video_cfg if video_cfg is not None else _video_settings()
    suffix = "movies" if media == "movies" else "tv"
    return {name for name in CATEGORIES if cfg.get(f"scan_refresh_{name}_{suffix}")}


def dry_run(media, video_cfg=None, music_cfg=None):
    """True when the scan should only log what it would refresh, without queueing anything."""
    if media == "music":
        cfg = music_cfg if music_cfg is not None else _music_settings()
        return bool(cfg.get("scan_refresh_dry_run"))
    cfg = video_cfg if video_cfg is not None else _video_settings()
    return bool(cfg.get("scan_refresh_dry_" + ("movies" if media == "movies" else "tv")))


def active(media):
    """True when a scan needs the before-snapshot: a refresh is switched on, or a dry run is."""
    return bool(wanted(media)) or dry_run(media)


def _planned(media):
    """(categories, dry): the ticked categories, or every category a dry run with nothing ticked can report."""
    categories = wanted(media)
    dry = dry_run(media)
    if dry and not categories:
        categories = {"metadata", "artwork"} if media == "music" else set(CATEGORIES)
    return categories, dry


def _video_settings():
    from curator.video import config

    return config.current()


def _music_settings():
    from resonance.settings import load_settings

    return load_settings()


def _digest(columns, alias):
    if not columns:
        return "''"
    return "md5(jsonb_build_array(" + ", ".join(f"{alias}.{column}" for column in columns) + ")::text)"


def _query(kind, albums=False, folders=False):
    """The digest query for one kind. albums limits music to the albums at the given paths and their artists; folders
    limits movies and shows to the movie and show folders a scan of chosen folders (an import) reads."""
    parts = _PARTS[kind]
    table = parts["table"]
    digests = ", ".join(f"{_digest(parts[name], 't')} AS {name}" for name in CATEGORIES)
    if kind == "movie":
        return (f"SELECT t.id::text AS id, {digests} FROM movies t WHERE t.root = ANY(%s) AND NOT COALESCE(t.wanted, FALSE)"
                + (" AND (t.path = ANY(%s) OR t.folder = ANY(%s))" if folders else ""))
    show_in = " AND s.path = ANY(%s)" if folders else ""
    if kind == "show":
        return (f"SELECT t.id::text AS id, {digests} FROM tv_shows t WHERE t.root = ANY(%s) AND NOT COALESCE(t.wanted, FALSE)"
                + (" AND t.path = ANY(%s)" if folders else ""))
    if kind == "season":
        return (f"SELECT t.id::text AS id, {digests} FROM tv_seasons t JOIN tv_shows s ON s.id = t.show_id "
                "WHERE s.root = ANY(%s) AND NOT COALESCE(s.wanted, FALSE)" + show_in)
    if kind == "episode":
        return (f"SELECT t.id::text AS id, {digests} FROM tv_episodes t JOIN tv_shows s ON s.id = t.show_id "
                "WHERE s.root = ANY(%s) AND NOT t.missing AND NOT COALESCE(s.wanted, FALSE)" + show_in)
    if kind == "album":
        # Tags written into the tracks are album metadata too.
        meta = parts["metadata"]
        return (f"SELECT t.id::text AS id, md5(jsonb_build_array({', '.join('t.' + column for column in meta)}, "
                "(SELECT md5(string_agg(tr.tags::text, '|' ORDER BY tr.id)) FROM tracks tr WHERE tr.album_id = t.id))::text) AS metadata, "
                f"{_digest(parts['artwork'], 't')} AS artwork, '' AS ratings FROM {table} t"
                + (" WHERE t.path = ANY(%s)" if albums else ""))
    if kind == "artist" and albums:
        return (f"SELECT t.id::text AS id, {digests} FROM {table} t "
                "WHERE t.id IN (SELECT artist_id FROM albums WHERE path = ANY(%s))")
    return f"SELECT t.id::text AS id, {digests} FROM {table} t"


def snapshot(media, roots=None, albums=None, folders=None):
    """{"kind:id": {"metadata": digest, "artwork": digest, "ratings": digest}} for every item the scan can touch.

    albums (music) are the album folders of a scan of chosen albums: only they and their artists are read, not the
    whole library. Never raises: a failed snapshot only means no refresh is sent."""
    from resonance import db

    found = {}
    try:
        for kind in _KINDS.get(media, ()):
            narrow = bool(folders) and media != "music"
            if media != "music":
                params = (list(roots or []),)
                if narrow:
                    params += (list(folders),) * (2 if kind == "movie" else 1)
            else:
                params = (list(albums),) if albums else ()
            for row in db.fetchall(_query(kind, bool(albums) and media == "music", narrow), params):
                found[f"{kind}:{row['id']}"] = {name: row.get(name) or "" for name in CATEGORIES}
    except Exception:
        logger.exception("could not record the %s items before the scan", media)
        return None
    return found


# Folders a webhook import is scanning right now. The import sends its own library update as its last step, after the
# scrape has written the .nfo (with the stream details the players show as media flags). Refreshing an item the
# import's scan just added would make a player scan the folder at once and add the item from a half-finished folder;
# the later library update then finds it already there and does not read the .nfo again.
_importing = {}
_importing_lock = threading.Lock()


@contextmanager
def importing(folders):
    """Mark these folders as being scanned by an import for as long as the block runs."""
    paths = [str(folder) for folder in folders or [] if folder]
    with _importing_lock:
        for path in paths:
            _importing[path] = _importing.get(path, 0) + 1
    try:
        yield
    finally:
        with _importing_lock:
            for path in paths:
                left = _importing.get(path, 0) - 1
                if left > 0:
                    _importing[path] = left
                else:
                    _importing.pop(path, None)


def import_scan(folders):
    """True when this scan of chosen folders is an import's scan."""
    with _importing_lock:
        return any(str(folder) in _importing for folder in folders or [])


def changed(before, after, categories):
    """Item keys whose chosen categories differ. An item that was not there before counts as changed."""
    keys = []
    for key, now in (after or {}).items():
        then = (before or {}).get(key)
        if then is None or any(now.get(name) != then.get(name) for name in categories):
            keys.append(key)
    return keys


def targets(keys):
    """What each player needs for the changed items: kind, file or folder, and a label. A season becomes its show."""
    from resonance import db

    grouped = {}
    for key in keys or []:
        kind, _sep, item_id = key.partition(":")
        grouped.setdefault(kind, []).append(item_id)
    items = {}

    def add(item):
        items.setdefault((item["kind"], item.get("path") or item.get("folder")), item)

    if grouped.get("movie"):
        for row in db.fetchall(
            "SELECT m.id, m.title, m.year, COALESCE(f.path, m.path) AS path, m.folder FROM movies m "
            "LEFT JOIN video_files f ON f.id = m.file_id WHERE m.id = ANY(%s::uuid[])", (grouped["movie"],)):
            label = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
            add({"kind": "movie", "path": row["path"], "folder": row["folder"] or os.path.dirname(row["path"]), "label": label,
                 "id": str(row["id"])})
    show_ids = list(grouped.get("show") or [])
    if grouped.get("season"):
        show_ids += [str(row["show_id"]) for row in db.fetchall(
            "SELECT DISTINCT show_id FROM tv_seasons WHERE id = ANY(%s::uuid[])", (grouped["season"],))]
    if show_ids:
        for row in db.fetchall("SELECT id, title, year, path FROM tv_shows WHERE id = ANY(%s::uuid[])", (list(set(show_ids)),)):
            label = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
            add({"kind": "show", "path": "", "folder": row["path"], "label": label, "id": str(row["id"])})
    if grouped.get("episode"):
        for row in db.fetchall(
            """
            SELECT e.path, e.season_number, e.episode_number, s.title AS show_title
            FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE e.id = ANY(%s::uuid[]) AND NOT e.missing
            """,
            (grouped["episode"],),
        ):
            if not row.get("path") or str(row["path"]).startswith(("wanted://", "missing://")):
                continue
            label = f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"
            add({"kind": "episode", "path": row["path"], "folder": os.path.dirname(row["path"]), "label": label})
    if grouped.get("album"):
        for row in db.fetchall(
            "SELECT al.title, al.path, ar.name FROM albums al LEFT JOIN artists ar ON ar.id = al.artist_id WHERE al.id = ANY(%s::uuid[])",
            (grouped["album"],),
        ):
            label = f"{row['name']} — {row['title']}" if row.get("name") else row["title"]
            add({"kind": "album", "path": "", "folder": row["path"], "label": label})
    if grouped.get("artist"):
        for row in db.fetchall("SELECT name, path FROM artists WHERE id = ANY(%s::uuid[])", (grouped["artist"],)):
            if row.get("path"):
                add({"kind": "artist", "path": "", "folder": row["path"], "label": row["name"]})
    return [item for item in items.values() if item.get("folder") or item.get("path")]


def after_scan(media, roots, before, log, albums=None, folders=None):
    """The last step of a scan: queue a refresh of the changed items on every player. Never raises."""
    try:
        categories, dry = _planned(media)
        if not categories or before is None:
            return 0
        if albums:
            after = snapshot(media, roots, albums=albums)
        elif folders:
            after = snapshot(media, roots, folders=folders)
        else:
            after = snapshot(media, roots)
        if after is None:
            return 0
        keys = changed(before, after, categories)
        if keys and import_scan(folders):
            added = [key for key in keys if key not in before]
            if added:
                keys = [key for key in keys if key in before]
                noun = "item" if len(added) == 1 else "items"
                log(f"Client libraries: {len(added)} new {noun} of this import {'goes' if len(added) == 1 else 'go'} to the "
                    "players with the import's library update, after the scrape and the .nfo")
                if not keys:
                    return 0
        if not keys:
            log("Client libraries: no item got new " + _names(categories))
            return 0
        items = targets(keys)
        if not items:
            return 0
        if "artwork" in categories:
            _with_new_art(items, [key for key in keys if (before.get(key) or {}).get("artwork") != after[key].get("artwork")])
        if dry:
            noun = "item" if len(items) == 1 else "items"
            shown = ", ".join(item["label"] for item in items[:10] if item.get("label"))
            more = f" and {len(items) - 10} more" if len(items) > 10 else ""
            log(f"Client libraries (dry run): would refresh {len(items)} {noun} with new {_names(categories)}"
                + (f": {shown}{more}" if shown else "") + ". Nothing was sent.")
            return 0
        from curator.library_queue import queue_refresh

        queued, skipped = queue_refresh(media, items)
        noun = "item" if len(items) == 1 else "items"
        if queued:
            log(f"Client libraries: {len(items)} {noun} with new {_names(categories)} queued for {', '.join(queued)}")
        for line in skipped:
            log(f"Client libraries: {line}")
        return len(items) if queued else 0
    except Exception as exc:
        logger.exception("client library refresh after the %s scan failed", media)
        log(f"Client libraries: the update was not queued: {exc}")
        return 0


def _with_new_art(items, art_keys):
    """A movie or show whose artwork changed also has Kodi drop its cached pictures (same file name, new picture), as
    well as the full refresh. art: every Kodi artwork type the item has on disk."""
    from curator.video import art_pick, store

    wanted = {key.partition(":")[2] for key in art_keys if key.split(":", 1)[0] in ("movie", "show")}
    for item in items:
        if item.get("id") not in wanted or item.get("kind") not in ("movie", "show"):
            continue
        row = (store.movie_row(item["id"]) if item["kind"] == "movie" else store.show_row(item["id"])) or {}
        art = {key: value for key, value in (row.get("artwork") or {}).items()
               if key in art_pick.PLAYER_ART and isinstance(value, str) and os.path.isfile(value)}
        if art:
            item["art"] = art
            item["full"] = True


def _names(categories):
    ordered = [name for name in CATEGORIES if name in categories]
    if len(ordered) <= 1:
        return ordered[0] if ordered else ""
    return ", ".join(ordered[:-1]) + " or " + ordered[-1]
