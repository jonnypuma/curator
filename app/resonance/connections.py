"""The last connection error for each API. Settings shows it. A new error becomes an alert."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

_lock = threading.Lock()
_errors = {}
_notices = []
_notice_seq = 0

HOSTS = {
    "api.themoviedb.org": "tmdb",
    "api4.thetvdb.com": "tvdb",
    "www.omdbapi.com": "omdb",
    "api.trakt.tv": "trakt",
    "api.tvmaze.com": "tvmaze",
    "webservice.fanart.tv": "fanart",
    "graphql.anilist.co": "anilist",
    "musicbrainz.org": "musicbrainz",
    "ws.audioscrobbler.com": "lastfm",
    "api.acoustid.org": "acoustid",
}

LABELS = {
    "tmdb": "TMDB", "tvdb": "TheTVDB", "omdb": "OMDb", "trakt": "Trakt", "tvmaze": "TVMaze",
    "fanart": "Fanart.tv", "anilist": "AniList", "musicbrainz": "MusicBrainz", "lastfm": "Last.fm",
    "acoustid": "AcoustID", "radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr", "bazarr": "Bazarr",
    "kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex", "navidrome": "Navidrome",
}

PLAYERS = {
    "kodi_library": "kodi", "kodi_notify": "kodi", "kodi": "kodi",
    "emby": "emby", "emby_notify": "emby",
    "jellyfin": "jellyfin", "jellyfin_notify": "jellyfin",
    "plex": "plex", "navidrome": "navidrome",
}


def service_for_url(url):
    host = (urlsplit(str(url or "")).hostname or "").lower()
    if host in HOSTS:
        return HOSTS[host]
    if host.endswith(".musicbrainz.org"):
        return "musicbrainz"
    return ""


def label(name):
    return LABELS.get(name, name)


def _key(name):
    key = str(name or "").strip().lower()
    return {"last.fm": "lastfm"}.get(key, key)


def note(name, message):
    """Remember a connection failure. The same message does not raise another alert."""
    global _notice_seq
    key = _key(name)
    text = str(message or "").strip()
    if not key or not text:
        return
    with _lock:
        current = _errors.get(key) or {}
        if current.get("message") == text:
            return
        _errors[key] = {"message": text, "at": int(time.time())}
        _notice_seq += 1
        _notices.append({"id": _notice_seq, "name": key, "message": f"{label(key)}: {text}", "kind": "error"})
        del _notices[:-40]


def note_url(url, message):
    name = service_for_url(url)
    if name:
        note(name, message)


def clear(name):
    key = _key(name)
    if not key:
        return
    with _lock:
        _errors.pop(key, None)


def clear_url(url):
    name = service_for_url(url)
    if name:
        clear(name)


def snapshot():
    with _lock:
        out = {key: {"message": item["message"], "at": item["at"]} for key, item in _errors.items()}
    if "lastfm" in out:
        out["last.fm"] = out["lastfm"]
    return out


def notices():
    with _lock:
        return list(_notices)
