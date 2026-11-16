"""The Radarr and Sonarr orphan report: files the app and the library disagree about.

Three kinds of row:

- unused: Sonarr keeps a file record that no episode is attached to (two files for one episode, a file left from an
  old import). Radarr has one file per movie, so it has none of these.
- unknown: a video file in the library, inside a folder the app owns, that the app has no file record for (a second
  copy in a movie folder, an episode Sonarr never imported).
- missing: the app has a file record whose file is not on disk any more. A rescan in the app clears it.
- stray: a video or audio file in a library folder that neither Curator nor the app lists. These come from walking the
  folders, skipping extras, samples and the recycle bin.

Lidarr is checked too: its unmapped files are "unused", an album copy in a Lidarr artist folder with none of Lidarr's
files is "unknown", and a track file that is gone is "missing".

A delete goes through Curator's normal delete (the recycle bin, then a rescan in the app), or, for a file Curator does
not list, straight into the recycle bin.
"""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from curator.automation import map_path
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "processed": 0, "total": 0, "result": None}
# More than this share of an app's files missing means the path mappings are wrong, not that the files are gone.
MAPPING_DOUBT = 0.5


def _key(path):
    return os.path.normcase(os.path.normpath(str(path or ""))) if path else ""


def _under(path, folder):
    path, folder = _key(path), _key(folder)
    return bool(path and folder) and (path == folder or path.startswith(folder.rstrip(os.sep) + os.sep))


def _mappings():
    from curator import automation

    auto, _notify = automation.current()
    return auto.get("path_mappings") or []


def status():
    with _lock:
        return dict(_state)


def start():
    """Build the report in the background. False when one is already being built."""
    with _lock:
        if _state["status"] == "running":
            return False
        _state.update({"status": "running", "message": "Reading Radarr and Sonarr", "processed": 0, "total": 0})
    threading.Thread(target=_run, name="arr-orphans", daemon=True).start()
    return True


def _run():
    try:
        report = build()
        with _lock:
            _state.update({"status": "done", "message": _summary(report), "result": report})
    except Exception as exc:
        logger.exception("orphan report failed")
        with _lock:
            _state.update({"status": "failed", "message": str(exc)})


def _summary(report):
    items = report.get("items") or []
    if not items:
        return "Radarr, Sonarr, Lidarr and the library agree, and no stray files were found."
    counts = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    words = {"unused": "unused in the app", "unknown": "unknown to the app", "missing": "missing on disk",
             "stray": "stray in a library folder"}
    return ", ".join(f"{count} {words[kind]}" for kind, count in counts.items())


def _progress(step=1, total=None, message=None):
    with _lock:
        if total is not None:
            _state["total"] = total
        _state["processed"] += step
        if message:
            _state["message"] = message


def build():
    items, warnings = [], []
    tracked = set()
    for name, reader in (("Radarr", _radarr), ("Sonarr", _sonarr), ("Lidarr", _lidarr)):
        try:
            found, notes = reader()
            items += found
            warnings += notes
        except Exception as exc:
            logger.info("%s orphan check failed: %s", name, exc)
            warnings.append(f"{name}: {exc}")
    _progress(0, message="Looking for stray files in the library folders")
    try:
        tracked = {_key(item["path"]) for item in items}
        items += _stray(tracked)
    except Exception as exc:
        logger.exception("stray file check failed")
        warnings.append(f"Stray files: {exc}")
    return {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": items, "warnings": warnings}


def _library_rows(table):
    if table == "movies":
        return db.fetchall(
            "SELECT m.id::text AS id, m.title, m.year, f.path AS path FROM movies m JOIN video_files f ON f.id = m.file_id "
            "WHERE NOT COALESCE(m.wanted, FALSE) AND COALESCE(f.path, '') <> ''"
        )
    rows = db.fetchall(
        """
        SELECT e.id::text AS id, e.path, e.season_number, e.episode_number, s.title AS show_title
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
        WHERE NOT e.missing AND COALESCE(e.path, '') <> '' AND e.path NOT LIKE '%%://%%'
        """
    )
    copies = db.fetchall(
        """
        SELECT c.episode_id::text AS episode_id, c.path, e.season_number, e.episode_number, s.title AS show_title
        FROM episode_copies c JOIN tv_episodes e ON e.id = c.episode_id JOIN tv_shows s ON s.id = e.show_id
        """
    )
    found = [dict(row, kind="episode", item_id=row["id"]) for row in rows]
    found += [dict(row, kind="episode", item_id=f"file:{row['path']}") for row in copies]
    return found


def _episode_label(row):
    try:
        return f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"
    except (TypeError, ValueError, KeyError):
        return row.get("show_title") or ""


def _doubt(app, files):
    """A warning when most of an app's files look missing: the path mappings are the likely cause."""
    if len(files) < 20:
        return None
    gone = sum(1 for path in files if not os.path.exists(path))
    if gone / len(files) > MAPPING_DOUBT:
        return (f"{app}: {gone} of {len(files)} files were not found on disk. Check the remote path mappings under "
                "Settings, General before trusting this report. Missing files were left out.")
    return None


def _radarr():
    from curator import radarr

    url, key, _cfg = radarr._settings()
    if not url or not key:
        return [], []
    mappings = _mappings()
    movies = radarr._api("GET", "/movie", url, key, timeout=120) or []
    _progress(0, message="Comparing Radarr with the library")
    folders, files = {}, {}
    for movie in movies if isinstance(movies, list) else []:
        folder = map_path(movie.get("path") or "", mappings, "radarr")
        if folder:
            folders[_key(folder)] = movie
        movie_file = movie.get("movieFile") or {}
        local = map_path(movie_file.get("path") or "", mappings, "radarr")
        if local:
            files[_key(local)] = (local, movie)
    items, notes = [], []
    doubt = _doubt("Radarr", [local for local, _movie in files.values()])
    if doubt:
        notes.append(doubt)
    else:
        for local, movie in files.values():
            if not os.path.exists(local):
                items.append(_row("Radarr", "missing", local, movie.get("title") or "", arr_id=movie.get("id")))
    library = _library_rows("movies")
    by_folder = {}
    for row in library:
        by_folder.setdefault(_key(os.path.dirname(row["path"])), []).append(row)
    for row in library:
        if _key(row["path"]) in files:
            continue
        owner = folders.get(_key(os.path.dirname(row["path"])))
        if not owner:
            continue
        label = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        arr_file = map_path((owner.get("movieFile") or {}).get("path") or "", mappings, "radarr")
        other = bool(arr_file and os.path.exists(arr_file)) or any(
            peer is not row and os.path.exists(peer["path"]) for peer in by_folder.get(_key(os.path.dirname(row["path"])), []))
        items.append(_row("Radarr", "unknown", row["path"], label, arr_id=owner.get("id"), kind="movie", item_id=row["id"],
                          note=f"Radarr uses {os.path.basename((owner.get('movieFile') or {}).get('path') or '') or 'no file'}",
                          sole=not other))
    return items, notes


def _sonarr():
    from curator import sonarr

    url, key = sonarr._settings()
    if not url or not key:
        return [], []
    mappings = _mappings()
    series = sonarr._api("GET", "/series", url, key, timeout=120) or []
    series = [show for show in series if isinstance(show, dict) and show.get("id")] if isinstance(series, list) else []
    _progress(0, total=len(series), message="Reading Sonarr series")

    def read(show):
        try:
            records = sonarr._api("GET", "/episodefile", url, key, params={"seriesId": show["id"]}) or []
            episodes = sonarr._api("GET", "/episode", url, key, params={"seriesId": show["id"]}) or []
        except Exception as exc:
            logger.info("Sonarr series %s was not read: %s", show.get("title"), exc)
            records, episodes = None, []
        _progress(message=f"Read {show.get('title') or 'a series'}")
        return show, records, episodes

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, series))
    items, notes = [], []
    known, folders, everything = {}, {}, []
    attached_local = {}     # (Sonarr series id, season, episode) -> the file Sonarr attaches to that episode
    for show, records, episodes in results:
        if records is None:
            notes.append(f"Sonarr: {show.get('title')} could not be read")
            continue
        folder = map_path(show.get("path") or "", mappings, "sonarr")
        if folder:
            folders[_key(folder)] = show
        attached = {str(episode.get("episodeFileId")) for episode in episodes if isinstance(episode, dict)
                    and episode.get("episodeFileId")}
        for record in records if isinstance(records, list) else []:
            local = map_path(record.get("path") or "", mappings, "sonarr")
            if not local:
                continue
            known[_key(local)] = show
            everything.append((local, record, show, str(record.get("id")) in attached))
        by_file_id = {str(record.get("id")): map_path(record.get("path") or "", mappings, "sonarr")
                      for record in (records if isinstance(records, list) else []) if isinstance(record, dict)}
        for episode in episodes if isinstance(episodes, list) else []:
            if (isinstance(episode, dict) and episode.get("episodeFileId") and episode.get("seasonNumber") is not None
                    and episode.get("episodeNumber") is not None):
                path = by_file_id.get(str(episode["episodeFileId"]))
                if path:
                    attached_local[(show.get("id"), int(episode["seasonNumber"]), int(episode["episodeNumber"]))] = path
    doubt = _doubt("Sonarr", [local for local, _record, _show, _used in everything])
    if doubt:
        notes.append(doubt)
    library_rows = _library_rows("tv")
    library = {_key(row["path"]): row for row in library_rows}
    by_episode = {}
    for row in library_rows:
        by_episode.setdefault(_episode_key(row), []).append(row)
    for local, record, show, used in everything:
        present = os.path.exists(local)
        if not present and not doubt:
            items.append(_row("Sonarr", "missing", local, show.get("title") or "", arr_id=show.get("id"),
                              arr_file_id=record.get("id")))
        elif present and not used:
            row = library.get(_key(local))
            items.append(_row("Sonarr", "unused", local, _episode_label(row) if row else show.get("title") or "",
                              arr_id=show.get("id"), arr_file_id=record.get("id"),
                              kind=row["kind"] if row else "", item_id=row["item_id"] if row else "",
                              note="No episode in Sonarr uses this file",
                              sole=_sole_episode(row, local, show.get("id"), by_episode, attached_local)))
    for path_key, row in library.items():
        if path_key in known:
            continue
        owner = next((show for folder, show in folders.items() if _under(row["path"], folder)), None)
        if not owner:
            continue
        items.append(_row("Sonarr", "unknown", row["path"], _episode_label(row), arr_id=owner.get("id"),
                          kind=row["kind"], item_id=row["item_id"],
                          sole=_sole_episode(row, row["path"], owner.get("id"), by_episode, attached_local)))
    return items, notes


def _episode_key(row):
    try:
        return (str(row.get("show_title") or "").lower(), int(row["season_number"]), int(row["episode_number"]))
    except (TypeError, ValueError, KeyError):
        return None


def _sole_episode(row, path, series_id, by_episode, attached_local):
    """True unless another copy of this episode is on disk. A file Curator does not list cannot be shown to have one."""
    key = _episode_key(row) if row else None
    if key is None:
        return True
    for other in by_episode.get(key, []):
        if _key(other["path"]) != _key(path) and os.path.exists(other["path"]):
            return False
    attached = attached_local.get((series_id, key[1], key[2]))
    return not (attached and _key(attached) != _key(path) and os.path.exists(attached))


def _lidarr():
    from resonance import lidarr

    url, key = lidarr._api_credentials()
    if not url or not key:
        return [], []
    mappings = _mappings()
    artists = lidarr._api("GET", "/api/v1/artist", url, key, timeout=120) or []
    artists = [artist for artist in artists if isinstance(artist, dict) and artist.get("id")]
    _progress(0, total=_state["total"] + len(artists), message="Reading Lidarr artists")

    def read(artist):
        try:
            rows = lidarr._api("GET", "/api/v1/trackfile", url, key, params={"artistId": artist["id"]}) or []
        except Exception as exc:
            logger.info("Lidarr artist %s was not read: %s", artist.get("artistName"), exc)
            rows = None
        _progress(message=f"Read {artist.get('artistName') or 'an artist'}")
        return artist, rows

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, artists))
    items, notes, everything, folders = [], [], [], {}
    for artist, rows in results:
        if rows is None:
            notes.append(f"Lidarr: {artist.get('artistName')} could not be read")
            continue
        folder = map_path(artist.get("path") or "", mappings, "lidarr")
        if folder:
            folders[_key(folder)] = artist
        for row in rows if isinstance(rows, list) else []:
            local = map_path(row.get("path") or "", mappings, "lidarr")
            if local:
                everything.append((local, artist))
    doubt = _doubt("Lidarr", [local for local, _artist in everything])
    if doubt:
        notes.append(doubt)
    else:
        for local, artist in everything:
            if not os.path.exists(local):
                items.append(_row("Lidarr", "missing", local, artist.get("artistName") or "", arr_id=artist.get("id")))
    try:
        unmapped = lidarr._api("GET", "/api/v1/trackfile", url, key, params={"unmapped": "true"}, timeout=120) or []
    except Exception as exc:
        unmapped = []
        notes.append(f"Lidarr: the unmapped files could not be read: {exc}")
    for row in unmapped if isinstance(unmapped, list) else []:
        local = map_path(row.get("path") or "", mappings, "lidarr")
        if local and os.path.exists(local):
            items.append(_row("Lidarr", "unused", local, os.path.basename(local), note="Lidarr has this file but no album for it",
                              sole=True))
    from resonance.fields import norm_name

    held = [_key(local) for local, _artist in everything]
    albums = db.fetchall(
        "SELECT al.id::text AS id, al.title, al.path, ar.name AS artist_name FROM albums al "
        "JOIN artists ar ON ar.id = al.artist_id WHERE COALESCE(al.path, '') <> ''"
    )
    by_name = {}
    for album in albums:
        by_name.setdefault((norm_name(album["artist_name"]), norm_name(album["title"])), []).append(album)
    for album in albums:
        owner = next((artist for folder, artist in folders.items() if _under(album["path"], folder)), None)
        if not owner or any(_under(path, album["path"]) for path in held):
            continue
        twins = [other for other in by_name[(norm_name(album["artist_name"]), norm_name(album["title"]))]
                 if other["id"] != album["id"] and os.path.isdir(other["path"])]
        items.append(_row("Lidarr", "unknown", album["path"], f"{album['artist_name']} — {album['title']}",
                          arr_id=owner.get("id"), kind="album", item_id=album["id"], note="Lidarr has no files in this folder",
                          sole=not twins))
    return items, notes


def _listed_paths():
    """Every file the library lists, by key: movies with their parts, episodes, extra copies and tracks."""
    listed = set()
    for sql in ("SELECT path FROM movies", "SELECT path FROM tv_episodes", "SELECT path FROM episode_copies",
                "SELECT file_path AS path FROM tracks", "SELECT path FROM music_videos"):
        listed.update(_key(row["path"]) for row in db.fetchall(sql) if row.get("path"))
    for row in db.fetchall("SELECT parts FROM movies WHERE parts IS NOT NULL"):
        parts = row.get("parts")
        if isinstance(parts, list):
            listed.update(_key(part) for part in parts)
    return listed


def _stray(tracked):
    """Video and audio files in the library folders that nothing lists. Folders of extras are not walked."""
    from curator import folders
    from curator.video import naming
    from resonance.scanner import AUDIO_EXTS

    listed = _listed_paths() | set(tracked)
    found = []
    for kind in ("movies", "tv", "music"):
        for root in folders.included(kind):
            for folder, dirs, names in os.walk(root):
                dirs[:] = [name for name in dirs if not naming.skip_dir(name) and not naming.is_extra_dir(name, tv=kind == "tv")]
                for name in names:
                    wanted = os.path.splitext(name)[1].lower() in AUDIO_EXTS if kind == "music" else naming.is_video(name)
                    if not wanted or (kind != "music" and naming.is_extra_file(name)):
                        continue
                    path = os.path.join(folder, name)
                    if _key(path) not in listed:
                        found.append(_row("Library", "stray", path, name, note="Neither Curator nor the app lists this file"))
    return found


def _row(app, row_type, path, label, arr_id=None, arr_file_id=None, kind="", item_id="", note="", sole=False):
    """One report row. kind and item_id name the library item, for the library's own delete.

    sole is True unless another copy of the title is on disk: the report never offers Delete on a sole copy,
    because "the app does not use this file" is not the same as "nobody needs it"."""
    if sole:
        note = f"{note} · Only copy in the library" if note else "Only copy in the library"
    size = 0
    try:
        size = os.path.getsize(path) if row_type != "missing" else 0
    except OSError:
        pass
    return {
        "app": app, "type": row_type, "path": path, "label": label, "arr_id": arr_id, "arr_file_id": arr_file_id,
        "kind": kind or "", "item_id": item_id or "", "note": note, "size_bytes": size, "sole": bool(sole),
    }


def discard(path, app="", arr_id=None):
    """Delete one row of the stored report. Only a row in the report can be deleted, and never a title's only copy.

    The app and arr_id the caller sends are ignored: the report knows them. A library item goes through the library
    delete (the recycle bin, then a rescan in the app); a file nothing lists goes into the recycle bin."""
    from curator import bulk_cleanup, radarr, sonarr
    from resonance import lidarr, trash

    with _lock:
        report = _state.get("result") or {}
        item = next((row for row in report.get("items") or [] if _key(row.get("path")) == _key(path)), None)
    if not item:
        raise AppError("That file is not in the report any more. Check again.", 404)
    if item["type"] == "missing":
        raise AppError("The app has a record for this file, but the file is gone. Rescan in the app instead.", 400)
    if item.get("sole"):
        raise AppError("This is the only copy of the title in the library, so it is not deleted from here.", 409)
    if item.get("kind") and item.get("item_id"):
        error = bulk_cleanup._delete_one({"kind": item["kind"], "id": item["item_id"]})
        if error:
            raise AppError(error, 409)
    else:
        if not os.path.isfile(item["path"]):
            raise AppError("That file is not on disk", 404)
        if not trash.root_for(item["path"]):
            raise AppError("The file is not inside a library folder", 400)
        listed = db.fetchone(
            """
            SELECT 1 AS hit FROM movies WHERE path = %s
            UNION ALL SELECT 1 FROM video_files f JOIN movies m ON m.file_id = f.id WHERE f.path = %s
            UNION ALL SELECT 1 FROM tv_episodes WHERE path = %s
            UNION ALL SELECT 1 FROM episode_copies WHERE path = %s
            UNION ALL SELECT 1 FROM tracks WHERE file_path = %s
            LIMIT 1
            """,
            (item["path"],) * 5,
        )
        if listed:
            raise AppError("The library lists this file now. Check again.", 409)
        trash.discard(item["path"], label=os.path.basename(item["path"]), kind="orphan")
        if item.get("arr_id"):
            if item["app"] == "Sonarr":
                sonarr.rescan_series(series_id=item["arr_id"])
            elif item["app"] == "Radarr":
                radarr.rescan_movie(movie_id=item["arr_id"])
            elif item["app"] == "Lidarr":
                lidarr.rescan_artist(artist_id=item["arr_id"])
    forget([item["path"]])
    return True


def rescan(app, arr_id):
    """Ask the app to rescan, which clears records whose file is gone."""
    from curator import radarr, sonarr
    from resonance import lidarr

    if not arr_id:
        raise AppError("No item to rescan", 400)
    if app == "Lidarr":
        done = lidarr.rescan_artist(artist_id=arr_id)
    else:
        done = sonarr.rescan_series(series_id=arr_id) if app == "Sonarr" else radarr.rescan_movie(movie_id=arr_id)
    if not done:
        raise AppError(f"{app} did not accept the rescan", 502)
    return True


def forget(paths):
    """Drop rows from the stored report after the front end deleted them through the library delete."""
    wanted = {_key(path) for path in paths or []}
    with _lock:
        report = _state.get("result") or {}
        report["items"] = [item for item in report.get("items") or [] if _key(item.get("path")) not in wanted]
        if _state.get("result") and _state["status"] != "running":
            _state["message"] = _summary(report)


def test_connections():
    """Ask each app the same questions the report asks. One line per app, with what came back or what failed."""
    from curator import radarr, sonarr
    from resonance import lidarr

    lines = []

    def attempt(name, configured, question):
        if not configured:
            lines.append({"app": name, "ok": None, "message": "Not set up"})
            return
        try:
            lines.append({"app": name, "ok": True, "message": question()})
        except Exception as exc:
            lines.append({"app": name, "ok": False, "message": str(exc)})

    r_url, r_key, _cfg = radarr._settings()
    s_url, s_key = sonarr._settings()
    l_url, l_key = lidarr._api_credentials()
    attempt("Radarr", r_url and r_key, lambda: f"{len(radarr._api('GET', '/movie', r_url, r_key, timeout=120) or [])} movies")
    attempt("Sonarr", s_url and s_key, lambda: f"{len(sonarr._api('GET', '/series', s_url, s_key, timeout=120) or [])} series")

    def lidarr_question():
        artists = lidarr._api("GET", "/api/v1/artist", l_url, l_key, timeout=120) or []
        row = db.fetchone("SELECT musicbrainz_release_group_id::text AS mbid FROM albums "
                          "WHERE musicbrainz_release_group_id IS NOT NULL LIMIT 1")
        albums = "no album to try"
        if row and row.get("mbid"):
            found = lidarr._api("GET", "/api/v1/album", l_url, l_key, params={"foreignAlbumId": row["mbid"]})
            albums = f"album lookup answered with {len(found or [])} row(s)"
        return f"{len(artists)} artists, {albums}"

    attempt("Lidarr", l_url and l_key, lidarr_question)
    return lines
