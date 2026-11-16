"""Read Radarr, Sonarr, Bazarr and Lidarr webhook payloads.

parse() turns one payload into queue items: which library, which folder (already mapped to the container
path), which files, and whether something was deleted. It does no I/O; the caller checks the folders.
"""
from __future__ import annotations

import posixpath
import re

from curator.automation import clean_path, map_path

RADARR_EVENTS = {"Download", "Rename", "MovieFileDelete", "MovieDelete"}
SONARR_EVENTS = {"Download", "Rename", "EpisodeFileDelete", "SeriesDelete"}
LIDARR_EVENTS = {"Download", "Rename", "Retag", "TrackRetag", "AlbumDownload", "AlbumDelete", "ArtistDelete", "TrackFileDelete"}
LIDARR_NOTES = {"Grab", "DownloadFailure", "ImportFailure"}
DELETES = {"MovieFileDelete", "MovieDelete", "EpisodeFileDelete", "SeriesDelete"}
# Event types only Lidarr sends: a call carrying one is Lidarr's even when the instance has another name.
LIDARR_ONLY_EVENTS = {"DownloadFailure", "ImportFailure", "AlbumDownload", "TrackRetag", "Retag", "AlbumDelete",
                      "ArtistDelete", "TrackFileDelete"}
# Lidarr's own deletes. An album or artist delete names the artist folder, not files; the album folder is looked up
# in the library when the webhook is queued (resonance.lidarr.locate_removed).
LIDARR_DELETES = {"AlbumDelete", "ArtistDelete", "TrackFileDelete"}

# Bazarr through Apprise's json:// sends only a message such as
# "Breaking Bad (2008) - S01E02 - Cat's in the Bag... : English subtitles downloaded from opensubtitles ..."
_BAZARR_EPISODE = re.compile(r"^(?P<title>.+?)(?:\s*\((?P<year>\d{4})\))?\s+-\s+S(?P<season>\d{1,4})E(?P<episode>\d{1,4})", re.I)
_BAZARR_MOVIE = re.compile(r"^(?P<title>.+?)(?:\s*\((?P<year>\d{4})\))?\s*:\s*[^:]*?subtitles?", re.I)


def detect(payload):
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("movie"), dict):
        return "radarr"
    if isinstance(payload.get("series"), dict):
        return "sonarr"
    if isinstance(payload.get("artist"), dict):
        return "lidarr"
    if isinstance(payload.get("subtitle"), dict) or payload.get("subtitles_path") or (
            payload.get("message") and not payload.get("eventType")):
        return "bazarr"
    event = str(payload.get("eventType") or "")
    if event:
        # Calls without a movie, series or artist block: Lidarr's DownloadFailure and ImportFailure, and Health,
        # HealthRestored and ApplicationUpdate from any of them. The instance name says which app sent it.
        instance = str(payload.get("instanceName") or "").lower()
        for name in ("radarr", "sonarr", "lidarr"):
            if name in instance:
                return name
        if event in LIDARR_ONLY_EVENTS:
            return "lidarr"
        if event == "Test":
            return "arr"
    return None


def _item(media, source, event, title, path, files=(), removed=False, **extra):
    return {"media": media, "source": source, "event": event, "title": title or "", "path": path or "",
            "files": [item for item in files if item], "removed": bool(removed), "extra": extra}


def _upgraded(payload, event):
    """True for an import that replaced a file. Radarr and Sonarr say so with isUpgrade, and list what they deleted.

    The delete that comes before it is ignored (see the deleteReason check below), so this is what lets the library
    clean run for the old file. A normal import returns False.
    """
    if event != "Download":
        return False
    if payload.get("isUpgrade") is True:
        return True
    return any(isinstance(item, (dict, str)) and item for item in (payload.get("deletedFiles") or []))


def _replaced(payload, event):
    """The extra field that marks an upgrade or a rename: the player keeps the old entry until it is cleaned. It is left
    out otherwise, so a later normal import of the same folder cannot overwrite it when queue rows merge."""
    return {"replaced": True} if _upgraded(payload, event) or event == "Rename" else {}


def _year_title(title, year):
    title = str(title or "").strip()
    if not title or not year:
        return title
    if re.search(rf"\(\s*{re.escape(str(year))}\s*\)\s*$", title):
        return title
    return f"{title} ({year})"


def _paths(values, mappings, source):
    return [map_path(value, mappings, source) for value in values if value]


def parse(payload, mappings, find=None):
    """Returns {"source", "event", "items", "note"}. note explains an ignored or test event.

    find(media, title, year) looks a Bazarr title up in the library and returns its folder, or None.
    """
    source = detect(payload)
    event = str((payload or {}).get("eventType") or "").strip() if isinstance(payload, dict) else ""
    result = {"source": source or "unknown", "event": event, "items": [], "note": ""}
    if source is None:
        result["note"] = "Not a Radarr, Sonarr, Bazarr or Lidarr payload"
        return result
    if event == "Test":
        result["note"] = "Test event received"
        return result
    handler = {"radarr": _radarr, "sonarr": _sonarr, "lidarr": _lidarr, "bazarr": _bazarr}.get(source)
    if handler is None:
        result["note"] = f"Unsupported event {event or 'without a type'}"
        return result
    return handler(payload, mappings, result, find)


def _radarr(payload, mappings, result, _find):
    event = result["event"]
    movie = payload.get("movie") or {}
    title = _year_title(movie.get("title"), movie.get("year"))
    if title:
        result["label"] = title
    if event not in RADARR_EVENTS:
        result["note"] = f"Radarr {event or 'event'} needs no scan"
        return result
    if event == "MovieFileDelete" and str(payload.get("deleteReason") or "").lower() == "upgrade":
        result["note"] = "File removed for an upgrade; the import that follows is queued instead"
        result["label"] = title
        return result
    files = []
    movie_file = payload.get("movieFile") or {}
    if movie_file.get("path"):
        files.append(movie_file["path"])
    for item in payload.get("renamedMovieFiles") or []:
        if isinstance(item, dict) and item.get("path"):
            files.append(item["path"])
    folder = movie.get("folderPath") or movie.get("path") or ""
    if not folder and files:
        folder = posixpath.dirname(clean_path(files[0]))
    if not folder:
        result["note"] = "Radarr did not send the movie folder"
        return result
    result["items"].append(_item(
        "movies", "radarr", event, title, map_path(folder, mappings, "radarr"), _paths(files, mappings, "radarr"),
        removed=event in DELETES, tmdb=str(movie.get("tmdbId") or ""), imdb=str(movie.get("imdbId") or ""),
        **_replaced(payload, event),
    ))
    return result


def _episode_codes(episodes):
    codes = []
    for item in episodes or []:
        if isinstance(item, dict) and item.get("seasonNumber") is not None and item.get("episodeNumber") is not None:
            codes.append(f"S{int(item['seasonNumber']):02d}E{int(item['episodeNumber']):02d}")
    return codes


def _sonarr(payload, mappings, result, _find):
    event = result["event"]
    series = payload.get("series") or {}
    codes = _episode_codes(payload.get("episodes"))
    title = _year_title(series.get("title"), series.get("year"))
    if codes:
        title = f"{title} {codes[0]}" + (f"–{codes[-1]}" if len(codes) > 1 else "")
    if title.strip():
        result["label"] = title.strip()
    if event not in SONARR_EVENTS:
        result["note"] = f"Sonarr {event or 'event'} needs no scan"
        return result
    if event == "EpisodeFileDelete" and str(payload.get("deleteReason") or "").lower() == "upgrade":
        result["note"] = "File removed for an upgrade; the import that follows is queued instead"
        result["label"] = title
        return result
    files = []
    for key in ("episodeFile",):
        if isinstance(payload.get(key), dict) and payload[key].get("path"):
            files.append(payload[key]["path"])
    for key in ("episodeFiles", "renamedEpisodeFiles"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get("path"):
                files.append(item["path"])
    folder = series.get("path") or ""
    if not folder:
        result["note"] = "Sonarr did not send the series folder"
        return result
    result["items"].append(_item(
        "tv", "sonarr", event, title, map_path(folder, mappings, "sonarr"), _paths(files, mappings, "sonarr"),
        removed=event in DELETES, tvdb=str(series.get("tvdbId") or ""), tmdb=str(series.get("tmdbId") or ""),
        **_replaced(payload, event),
    ))
    return result


def _import_retag(payload):
    """True for a Retag Lidarr sends while it imports: it writes the tags into each new file before saving the file, so
    the file id is still 0. Lidarr's Download call for the album follows and covers it. A retag of a file Lidarr
    already had carries that file's id."""
    files = [payload.get("trackFile")] + list(payload.get("trackFiles") or [])
    ids = [item.get("id") for item in files if isinstance(item, dict) and "id" in item]
    return bool(ids) and all(str(value).strip() in ("0", "") for value in ids)


def _lidarr(payload, mappings, result, _find):
    event = result["event"]
    if event in LIDARR_NOTES:
        result["note"] = "lidarr-note"
        return result
    if event not in LIDARR_EVENTS:
        result["note"] = f"Lidarr {event or 'event'} needs no scan"
        return result
    artist = (payload.get("artist") or {}).get("name") or ""
    album = (payload.get("album") or {}).get("title") or ""
    if artist or album:
        result["label"] = " — ".join(part for part in (artist, album) if part)
    if event in ("Retag", "TrackRetag") and _import_retag(payload):
        result["note"] = ("Lidarr tagged this file while importing it (On Track Retag). "
                          "The Download call for the album covers it, so no scan is queued")
        return result
    if event in ("AlbumDelete", "ArtistDelete"):
        artist_path = str((payload.get("artist") or {}).get("path") or "").strip()
        if not artist_path:
            result["note"] = f"Lidarr {event} did not include the artist folder"
            return result
        artist_folder = map_path(artist_path, mappings, "lidarr")
        scope = "artist" if event == "ArtistDelete" else "album"
        title = artist if scope == "artist" else " — ".join(part for part in (artist, album) if part)
        result["items"].append(_item(
            "music", "lidarr", event, title or posixpath.basename(artist_folder.rstrip("/")), artist_folder, (),
            removed=True, artist=artist_folder, scope=scope, album_title=album,
            release_group=str((payload.get("album") or {}).get("foreignAlbumId") or ""),
            deleted_files=bool(payload.get("deletedFiles")),
        ))
        return result
    files = []
    # Download and Rename send trackFiles. Retag sends one trackFile: the file whose tags Lidarr rewrote.
    single = payload.get("trackFile")
    for item in [single] if isinstance(single, dict) else []:
        if item.get("path"):
            files.append(item["path"])
    for key in ("trackFiles", "tracks"):
        for item in payload.get(key) or []:
            path = item if isinstance(item, str) else (item.get("path") if isinstance(item, dict) else "")
            if path:
                files.append(path)
    if not files:
        result["note"] = "Lidarr did not include any imported file paths"
        return result
    mapped = _paths(files, mappings, "lidarr")
    try:
        folder = posixpath.commonpath([posixpath.dirname(path) for path in mapped])
    except ValueError:
        folder = posixpath.dirname(mapped[0])
    if not album:
        # Retag does not name the album: its folder does.
        album = posixpath.basename(folder.rstrip("/"))
    title = " — ".join(part for part in (artist, album) if part)
    artist_path = (payload.get("artist") or {}).get("path") or ""
    if artist_path:
        artist_folder = map_path(artist_path, mappings, "lidarr")
    else:
        artist_folder = posixpath.dirname(folder)
    result["items"].append(_item("music", "lidarr", event, title, folder, mapped,
                                 removed=event in LIDARR_DELETES, artist=artist_folder))
    return result


def _bazarr(payload, mappings, result, find):
    result["event"] = result["event"] or "SubtitleDownload"
    subtitle = payload.get("subtitle") if isinstance(payload.get("subtitle"), dict) else {}
    path = subtitle.get("path") or payload.get("subtitles_path") or payload.get("path") or ""
    media_hint = "tv" if payload.get("series") or payload.get("episode") else ""
    if path:
        local = map_path(path, mappings, "bazarr")
        title = str(payload.get("title") or "").strip()
        if not title or title.lower().startswith("bazarr"):
            title = posixpath.basename(local)
        result["items"].append(_item(media_hint or "auto", "bazarr", result["event"], title,
                                     posixpath.dirname(local), [local]))
        return result
    message = str(payload.get("message") or "").strip()
    match = _BAZARR_EPISODE.match(message)
    media = "tv"
    if not match:
        match = _BAZARR_MOVIE.match(message)
        media = "movies"
    if not match:
        result["note"] = "Bazarr message without a title or path"
        return result
    title = match.group("title").strip()
    year = int(match.group("year")) if match.group("year") else None
    folder = find(media, title, year) if find else None
    if not folder:
        result["note"] = f"Bazarr subtitle for {title} does not match anything in the library"
        return result
    label = _year_title(title, year)
    if media == "tv":
        label = f"{label} S{int(match.group('season')):02d}E{int(match.group('episode')):02d}"
    result["items"].append(_item(media, "bazarr", result["event"], label, folder))
    return result
