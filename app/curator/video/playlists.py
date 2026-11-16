"""Kodi smart playlists (.xsp) from saved filters.

A saved movie or TV filter with "Kodi smart playlist" on is written as an .xsp file whose rule lists the file names
that match the filter now (Kodi's filename field). Kodi needs no tags for that. The files are rewritten after every
movie or TV scan and whenever a saved filter is saved or removed, so the playlist follows the library.

The playlists go to the folder set under Settings, Files (default <config>/playlists/video). Point Kodi's
special://profile/playlists/video at that folder (a network share or a bind mount), or copy the files there.
Only files Curator wrote (they start with "Curator - ") are ever removed from that folder.
"""
from __future__ import annotations

import logging
import os
import re
from xml.sax.saxutils import escape

from resonance import db

logger = logging.getLogger(__name__)

PREFIX = "Curator - "
NO_MATCH = "curator-no-matching-file"


def folder():
    from curator.video import config
    from resonance.paths import config_dir

    chosen = str(config.current().get("kodi_playlist_dir") or "").strip()
    return chosen or os.path.join(config_dir(), "playlists", "video")


def music_folder():
    """Beside the video folder: Kodi keeps music playlists in playlists/music."""
    video = folder().rstrip("/\\")
    parent, base = os.path.split(video)
    return os.path.join(parent, "music") if base.lower() == "video" else os.path.join(video, "music")


def file_name(name):
    clean = re.sub(r'[\\/:*?"<>|]+', " ", str(name or "")).strip() or "Filter"
    return f"{PREFIX}{' '.join(clean.split())}.xsp"


def matching_files(media, payload):
    """File names of the movies, or episodes, that match the filter's ribbons and column filters now."""
    from curator.video.saved_filters import tag_clauses

    if media == "music":
        return matching_albums(payload)
    clauses, params = tag_clauses(payload, media)
    title = "m.title" if media == "movies" else "s.title"
    for word in str((payload or {}).get("search") or "").split():
        clauses.append(f"{title} ILIKE %s")
        params.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if not clauses:
        return None
    where = " AND ".join(clauses)
    from curator.video import store

    if media == "movies":
        sql = (f"SELECT f.path AS file_path, m.parts AS parts FROM movies m LEFT JOIN video_files f ON f.id = m.file_id "
               f"WHERE NOT COALESCE(m.wanted, FALSE) AND {where}")
        rows = [store.movie_file_paths(row) for row in db.fetchall(sql, tuple(params))]
    else:
        sql = (f"SELECT e.path AS file_path FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id "
               f"LEFT JOIN video_files f ON f.id = e.file_id WHERE NOT e.missing AND {where}")
        rows = [store.movie_file_paths(row) for row in db.fetchall(sql, tuple(params))]
    names = {os.path.basename(str(path)) for paths in rows for path in paths}
    return sorted(name for name in names if name and "://" not in name)


# Music presets a scan can read from the database. The others depend on the page, so they make no playlist.
MUSIC_PRESETS = {
    "all": "TRUE",
    "type-album": "lower(COALESCE(al.type::text, '')) = 'album'",
    "type-ep": "lower(COALESCE(al.type::text, '')) = 'ep'",
    "type-single": "lower(COALESCE(al.type::text, '')) = 'single'",
    "type-live": "lower(COALESCE(al.type::text, '')) = 'live'",
    "type-compilation": "lower(COALESCE(al.type::text, '')) = 'compilation'",
    "new": "al.status = 'NEW'",
    "missing-art": "NOT COALESCE(al.has_artwork, FALSE)",
    "missing-nfo": "NOT COALESCE(al.has_nfo, FALSE)",
    "duplicates": "al.duplicate_release",
    "upgrade": "al.upgrade_source_id IS NOT NULL",
    "locked": "al.locked",
}


def matching_albums(payload):
    """Album titles for a saved music preset, or None when that preset cannot be read from the database."""
    sql = MUSIC_PRESETS.get(str((payload or {}).get("preset") or "all"))
    if not sql:
        return None
    rows = db.fetchall(f"SELECT DISTINCT al.title FROM albums al WHERE {sql}")
    return sorted(row["title"] for row in rows if row.get("title"))


def xsp(name, media, files):
    """The playlist text. An empty match lists one name that no file has, so Kodi shows an empty playlist."""
    if media == "music":
        values = "".join(f"<value>{escape(item)}</value>" for item in (files or [NO_MATCH]))
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            '<smartplaylist type="albums">\n'
            f"    <name>{escape(name)}</name>\n"
            "    <match>one</match>\n"
            f'    <rule field="album" operator="is">{values}</rule>\n'
            '    <order direction="ascending">album</order>\n'
            "</smartplaylist>\n"
        )
    kind = "movies" if media == "movies" else "episodes"
    values = "".join(f"<value>{escape(item)}</value>" for item in (files or [NO_MATCH]))
    order = "sorttitle" if media == "movies" else "tvshow"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
        f'<smartplaylist type="{kind}">\n'
        f"    <name>{escape(name)}</name>\n"
        "    <match>one</match>\n"
        f'    <rule field="filename" operator="is">{values}</rule>\n'
        f'    <order direction="ascending">{order}</order>\n'
        "</smartplaylist>\n"
    )


def refresh(log=None, media=None):
    """Write every playlist, and remove Curator's playlists whose saved filter is gone or switched off.

    media (music, or movies / tv) refreshes only that side's playlist folder: a movie scan cannot change a music
    playlist. Returns the number written. Never raises: a scan must not fail on a playlist."""
    try:
        rows = db.fetchall(
            "SELECT name, media, payload FROM saved_filters WHERE media IN ('movies', 'tv', 'music') AND COALESCE(playlist, FALSE) "
            "ORDER BY name"
        )
        written = 0
        for target, group, side in ((folder(), [row for row in rows if row["media"] != "music"], "video"),
                                    (music_folder(), [row for row in rows if row["media"] == "music"], "music")):
            if media and side != ("music" if media == "music" else "video"):
                continue
            written += _write_folder(target, group, log)
        return written
    except Exception as exc:
        logger.exception("could not write the Kodi smart playlists")
        if log:
            log(f"Kodi smart playlists were not written: {exc}")
        return 0


def _write_folder(target, rows, log):
    if not rows and not os.path.isdir(target):
        return 0
    os.makedirs(target, exist_ok=True)
    keep, written = set(), 0
    for row in rows:
        files = matching_files(row["media"], row.get("payload") or {})
        if files is None:
            if log:
                log(f"Playlist {row['name']}: nothing in this filter can be matched, so no playlist was written.")
            continue
        title = f"{row['name']} (episodes)" if row["media"] == "tv" else row["name"]
        name = file_name(title)
        keep.add(name)
        path = os.path.join(target, name)
        text = xsp(title, row["media"], files)
        try:
            with open(path, encoding="utf-8") as handle:
                if handle.read() == text:
                    continue
        except OSError:
            pass
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written += 1
    for entry in os.listdir(target):
        if entry.startswith(PREFIX) and entry.endswith(".xsp") and entry not in keep:
            os.remove(os.path.join(target, entry))
    if log and written:
        log(f"Kodi smart playlists: {written} written to {target}.")
    return written
