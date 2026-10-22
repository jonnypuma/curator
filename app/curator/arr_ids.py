"""Match library copies to the Radarr, Sonarr, or Lidarr item that already owns that file.

The duplicate and upgrade dialogs use this so a copy that is not in an *arr app is easy to see.
A missing app, or an app that does not answer, leaves the copies unmarked. A folder match is used
only when the app has no file yet and exactly one copy sits in that folder.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from curator.automation import clean_path, map_path

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_RADARR_CACHE: dict[str, tuple[float, dict | None]] = {}
_SONARR_CACHE: dict[str, tuple[float, dict | None]] = {}
_LIDARR_CACHE: dict[str, tuple[float, dict | None]] = {}
CACHE_TTL = 60.0


def clear_cache(app: str | None = None) -> None:
    """Clear cached lookup results for Radarr, Sonarr, or Lidarr."""
    with _CACHE_LOCK:
        name = (app or "").strip().lower()
        if not name or name == "radarr":
            _RADARR_CACHE.clear()
        if not name or name == "sonarr":
            _SONARR_CACHE.clear()
        if not name or name == "lidarr":
            _LIDARR_CACHE.clear()


def _get_cached(cache: dict, key: str):
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = cache.get(key)
        if entry:
            expire_at, val = entry
            if now < expire_at:
                return True, val
            cache.pop(key, None)
    return False, None


def _set_cached(cache: dict, key: str, value):
    now = time.monotonic()
    with _CACHE_LOCK:
        cache[key] = (now + CACHE_TTL, value)



def _same(left, right):
    a, b = clean_path(left).lower(), clean_path(right).lower()
    return bool(a) and a == b


def _inside(path, folder):
    """True when path is a file or folder underneath folder."""
    left, right = clean_path(path).lower(), clean_path(folder).lower()
    return bool(left and right) and left.startswith(right + "/")


def _copy_files(item):
    text = str((item or {}).get("file_path") or "").strip()
    return [text] if text else []


def _copy_places(item):
    places = _copy_files(item)
    folder = str((item or {}).get("path") or "").strip()
    if folder:
        places.append(folder)
    return places


def _item_inside(item, folder):
    for place in _copy_places(item):
        if _same(place, folder) or _inside(place, folder):
            return True
    return False


def label_copies(items, app, records):
    """Label each copy from the app record for that copy.

    records aligns with items. None means that copy's lookup did not finish.
    A record is {id, files, folders}. files are exact paths the app has.
    folders are used only when the app has no file and one copy is inside.
    """
    items = list(items or [])
    records = list(records or [])
    if len(records) < len(items):
        records = records + [None] * (len(items) - len(records))
    chosen = {}
    unknown = False
    for index, record in enumerate(records[:len(items)]):
        if record is None:
            unknown = True
            continue
        if not record.get("id"):
            continue
        for path in _copy_files(items[index]):
            if any(_same(path, owned) for owned in record.get("files") or []):
                chosen[index] = record["id"]
                break
    for index, record in enumerate(records[:len(items)]):
        if index in chosen or not record or not record.get("id") or record.get("files"):
            continue
        for folder in record.get("folders") or []:
            inside = [
                other for other, candidate in enumerate(items)
                if _item_inside(candidate, folder)
                and records[other]
                and records[other].get("id") == record["id"]
                and not records[other].get("files")
            ]
            if len(inside) == 1 and inside[0] == index:
                chosen[index] = record["id"]
    contain = _contain_winners(items, records)
    for index, ident in contain.items():
        chosen.setdefault(index, ident)
    if not chosen:
        return
    for index, item in enumerate(items):
        if index in chosen:
            item["arr"] = {"app": app, "id": chosen[index]}
        elif not unknown and records[index] is not None:
            item["arr"] = {"app": app, "id": ""}


def _contain_winners(items, records):
    """Give a Lidarr file to the one copy folder that actually contains it."""
    by_id = {}
    for index, record in enumerate(records[:len(items)]):
        if not record or record.get("match") != "contain" or not record.get("id") or not record.get("files"):
            continue
        bucket = by_id.setdefault(record["id"], set())
        bucket.update(record["files"])
    chosen = {}
    for ident, owned_files in by_id.items():
        winners = set()
        for owned in owned_files:
            best_index = None
            best_len = -1
            for index, item in enumerate(items):
                record = records[index] if index < len(records) else None
                if not record or record.get("id") != ident:
                    continue
                for place in _copy_places(item):
                    if _same(owned, place) or _inside(owned, place):
                        length = len(clean_path(place))
                        if length > best_len:
                            best_len = length
                            best_index = index
            if best_index is not None:
                winners.add(best_index)
        for index in winners:
            chosen[index] = ident
    return chosen


def _mapped(path, mappings, source):
    return map_path(path, mappings, source)


def _mappings():
    from curator import automation

    auto, _notify = automation.current()
    return auto.get("path_mappings") or []


def _groups(groups):
    return [list(items or []) for items in groups or [] if items]


def movie_groups(groups):
    """Label every movie duplicate group, asking Radarr once per TMDB id."""
    groups = _groups(groups)
    flat = [item for items in groups for item in items if isinstance(item, dict)]
    if not flat:
        return
    tmdb_ids = []
    for item in flat:
        tmdb = str(item.get("tmdb_id") or "").strip()
        if tmdb and tmdb not in tmdb_ids:
            tmdb_ids.append(tmdb)
    if not tmdb_ids:
        return
    try:
        from curator import radarr

        url, key, _cfg = radarr._settings()
        if not url or not key:
            return
        mappings = _mappings()
        known = {}
        missing_ids = []
        for tmdb_id in tmdb_ids:
            hit, val = _get_cached(_RADARR_CACHE, tmdb_id)
            if hit:
                known[tmdb_id] = val
            else:
                missing_ids.append(tmdb_id)

        def _fetch_movie(tmdb_id):
            try:
                movie = radarr._existing(url, key, tmdb_id)
            except Exception as exc:
                logger.info("Radarr lookup for %s did not finish: %s", tmdb_id, exc)
                return tmdb_id, None
            if not movie or not movie.get("id"):
                return tmdb_id, {"id": "", "files": [], "folders": []}
            ident = str(movie["id"])
            files, folders = [], []
            movie_file = movie.get("movieFile") if isinstance(movie.get("movieFile"), dict) else {}
            file_path = _mapped(movie_file.get("path") or "", mappings, "radarr")
            if file_path:
                files.append(file_path)
            elif _mapped(movie.get("path") or "", mappings, "radarr"):
                folders.append(_mapped(movie.get("path") or "", mappings, "radarr"))
            return tmdb_id, {"id": ident, "files": files, "folders": folders}

        if len(missing_ids) == 1:
            tid, record = _fetch_movie(missing_ids[0])
            known[tid] = record
            if record is not None:
                _set_cached(_RADARR_CACHE, tid, record)
        elif len(missing_ids) > 1:
            with ThreadPoolExecutor(max_workers=min(10, len(missing_ids))) as pool:
                for tid, record in pool.map(_fetch_movie, missing_ids):
                    known[tid] = record
                    if record is not None:
                        _set_cached(_RADARR_CACHE, tid, record)

        for items in groups:
            records = []
            for item in items:
                if not isinstance(item, dict):
                    records.append({"id": "", "files": [], "folders": []})
                    continue
                tmdb = str(item.get("tmdb_id") or "").strip()
                records.append(known.get(tmdb, {"id": "", "files": [], "folders": []}))
            label_copies(items, "Radarr", records)
    except Exception as exc:
        logger.info("Radarr ids were not added to the copies: %s", exc)


def movies(copies):
    movie_groups([copies])


def episode_groups(groups):
    """Label every episode duplicate group, asking Sonarr once per TVDB series."""
    groups = _groups(groups)
    flat = [item for items in groups for item in items if isinstance(item, dict)]
    tvdb_ids = []
    for item in flat:
        tvdb = str(item.get("tvdb_id") or "").strip()
        if tvdb and tvdb not in tvdb_ids:
            tvdb_ids.append(tvdb)
    if not tvdb_ids:
        return
    try:
        from curator import sonarr

        url, key = sonarr._settings()
        if not url or not key:
            return
        mappings = _mappings()
        known = {}
        missing_ids = []
        for tvdb_id in tvdb_ids:
            hit, val = _get_cached(_SONARR_CACHE, tvdb_id)
            if hit:
                known[tvdb_id] = val
            else:
                missing_ids.append(tvdb_id)

        def _fetch_series(tvdb_id):
            try:
                series = sonarr._api("GET", "/series", url, key, params={"tvdbId": tvdb_id}) or []
                if isinstance(series, dict):
                    series = [series]
                files = []
                for show in series if isinstance(series, list) else []:
                    if str(show.get("tvdbId") or "") != str(tvdb_id) or not show.get("id"):
                        continue
                    rows = sonarr._api("GET", "/episodefile", url, key, params={"seriesId": show["id"]}) or []
                    for episode_file in rows if isinstance(rows, list) else []:
                        local = _mapped(episode_file.get("path") or "", mappings, "sonarr")
                        if local and episode_file.get("id"):
                            files.append((local, str(episode_file["id"])))
                return tvdb_id, {"files": files}
            except Exception as exc:
                logger.info("Sonarr lookup for %s did not finish: %s", tvdb_id, exc)
                return tvdb_id, None

        if len(missing_ids) == 1:
            tid, record = _fetch_series(missing_ids[0])
            known[tid] = record
            if record is not None:
                _set_cached(_SONARR_CACHE, tid, record)
        elif len(missing_ids) > 1:
            with ThreadPoolExecutor(max_workers=min(10, len(missing_ids))) as pool:
                for tid, record in pool.map(_fetch_series, missing_ids):
                    known[tid] = record
                    if record is not None:
                        _set_cached(_SONARR_CACHE, tid, record)

        for items in groups:
            records = []
            for item in items:
                if not isinstance(item, dict):
                    records.append({"id": "", "files": [], "folders": []})
                    continue
                found = known.get(str(item.get("tvdb_id") or "").strip())
                if found is None:
                    records.append(None)
                    continue
                own = ""
                for path, ident in found["files"]:
                    if any(_same(path, candidate) for candidate in _copy_files(item)):
                        own = ident
                        break
                records.append({"id": own, "files": [path for path, ident in found["files"] if ident == own] if own else [], "folders": []})
            label_copies(items, "Sonarr", [
                {"id": (record or {}).get("id") or "", "files": (record or {}).get("files") or [], "folders": []}
                if record is not None else None
                for record in records
            ])
    except Exception as exc:
        logger.info("Sonarr ids were not added to the copies: %s", exc)


def episodes(copies):
    episode_groups([copies])


def album_groups(groups):
    """Label album copies from the Lidarr track files, not the shared release group id."""
    groups = _groups(groups)
    flat = [item for items in groups for item in items if isinstance(item, dict)]
    release_groups = []
    for item in flat:
        group = str(item.get("release_group") or item.get("musicbrainz_release_group_id") or "").strip()
        if group and group.lower() not in [item.lower() for item in release_groups]:
            release_groups.append(group)
    if not release_groups:
        return
    try:
        from resonance import lidarr

        url, key = lidarr._api_credentials()
        if not url or not key:
            return
        mappings = _mappings()
        known = {}
        missing_groups = []
        for group in release_groups:
            k = group.lower()
            hit, val = _get_cached(_LIDARR_CACHE, k)
            if hit:
                known[k] = val
            else:
                missing_groups.append(group)

        def _fetch_release_group(group):
            k = group.lower()
            try:
                rows = lidarr._lookup("/api/v1/album/lookup", url, key, params={"term": f"mbid:{group}"})
            except Exception as exc:
                logger.info("Lidarr lookup for %s did not finish: %s", group, exc)
                return k, None
            if rows is None:
                return k, None
            ident = ""
            for row in rows if isinstance(rows, list) else []:
                if str(row.get("foreignAlbumId") or "").lower() != k:
                    continue
                try:
                    value = int(row.get("id") or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > 0:
                    ident = str(value)
                    break
            if not ident:
                return k, {"id": "", "files": [], "folders": [], "match": "contain"}
            try:
                files = lidarr._api("GET", "/api/v1/trackfile", url, key, params={"albumId": ident}) or []
            except Exception as exc:
                logger.info("Lidarr files for album %s did not finish: %s", ident, exc)
                return k, None
            paths = []
            for row in files if isinstance(files, list) else []:
                local = _mapped(row.get("path") or "", mappings, "lidarr")
                if local:
                    paths.append(local)
            return k, {"id": ident, "files": paths, "folders": [], "match": "contain"}

        if len(missing_groups) == 1:
            k, record = _fetch_release_group(missing_groups[0])
            known[k] = record
            if record is not None:
                _set_cached(_LIDARR_CACHE, k, record)
        elif len(missing_groups) > 1:
            with ThreadPoolExecutor(max_workers=min(10, len(missing_groups))) as pool:
                for k, record in pool.map(_fetch_release_group, missing_groups):
                    known[k] = record
                    if record is not None:
                        _set_cached(_LIDARR_CACHE, k, record)

        for items in groups:
            records = []
            for item in items:
                if not isinstance(item, dict):
                    records.append({"id": "", "files": [], "folders": [], "match": "contain"})
                    continue
                group = str(item.get("release_group") or item.get("musicbrainz_release_group_id") or "").strip().lower()
                if not group:
                    records.append({"id": "", "files": [], "folders": [], "match": "contain"})
                    continue
                found = known.get(group)
                records.append(found if group in known else {"id": "", "files": [], "folders": [], "match": "contain"})
            label_copies(items, "Lidarr", records)
    except Exception as exc:
        logger.info("Lidarr ids were not added to the copies: %s", exc)


def albums(copies):
    album_groups([copies])
