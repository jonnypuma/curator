"""Kodi 22 NFO writer for movies, shows, seasons and (stacked) episodes, plus the Emby/Jellyfin and Plex dialects."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET

from . import nfo as nfo_read
from curator.video.sources import canonical_edition

VIDEO_CODECS = {
    "HEVC": "hevc", "H.264": "h264", "AV1": "av1", "VVC": "vvc", "VC-1": "vc1", "MPEG-2": "mpeg2video",
    "MPEG-1": "mpeg1video", "MPEG-4": "mpeg4", "VP9": "vp9", "VP8": "vp8", "WMV3": "wmv3",
}
AUDIO_CODECS = (
    ("truehd", "truehd"), ("dts:x", "dtshd_ma"), ("dts-hd ma", "dtshd_ma"), ("dts-hd hra", "dtshd_hra"),
    ("dts", "dca"), ("e-ac3", "eac3"), ("eac3", "eac3"), ("dd+", "eac3"), ("ac3", "ac3"), ("dolby digital", "ac3"),
    ("aac", "aac"), ("flac", "flac"), ("opus", "opus"), ("vorbis", "vorbis"), ("mp3", "mp3"), ("mp2", "mp2"),
    ("pcm", "pcm"), ("lpcm", "pcm"), ("atmos", "truehd"),
)
HDR_TYPES = {"dovi": "dolbyvision", "hdr10": "hdr10", "hdr10plus": "hdr10", "hlg": "hlg"}
# Kodi's built-in version types. Their ids are the string numbers. Names a library adds itself
# start at 40801 and differ per library, so a custom cut is written by title only.
_VERSION_TYPES = {
    "standard edition": 40400,
    "extended edition": 40401,
    "unrated version": 40402,
    "uncut version": 40403,
    "remastered version": 40404,
    "4k": 40405,
    "theatrical cut": 40406,
    "director's cut": 40407,
    "directors cut": 40407,
    "special edition": 40408,
    "limited edition": 40409,
}


_XML_INVALID_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _clean_xml(val):
    if val is None:
        return None
    return _XML_INVALID_CONTROL_CHARS.sub("", str(val))


def _add(parent, tag, value=None, **attrs):
    node = ET.SubElement(parent, tag, {key: _clean_xml(item) for key, item in attrs.items() if item is not None})
    if value is not None:
        node.text = _clean_xml(value)
    return node


def _season_year(premiered):
    text = str(premiered or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


_BOARDS = {"US": "MPAA", "DE": "FSK", "GB": "BBFC", "AU": "ACB", "CA": "CHVRS", "FR": "CNC", "NL": "Kijkwijzer"}


def _certifications(parent, items):
    for country, value in sorted((items or {}).items()):
        code = str(country or "").upper()
        if not code or not value:
            continue
        node = _add(parent, "certification", country=code.lower())
        _add(node, "country", code)
        _add(node, "name", _BOARDS.get(code, code))
        _add(node, "value", value)


def _text(parent, tag, value):
    if value is None or value == "" or value == []:
        return None
    return _add(parent, tag, value)


def _many(parent, tag, values):
    items = values or []
    if tag == "studio":
        from curator.scrapers.merge import unique_names

        items = unique_names(list(items))
    for value in items:
        if value not in (None, ""):
            _add(parent, tag, value)


def _number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 1)


def _ratings(parent, ratings, default_name):
    if not ratings:
        return
    holder = _add(parent, "ratings")
    default = default_name if default_name in ratings else next(iter(ratings))
    for name, item in ratings.items():
        node = _add(holder, "rating", name=name, max=item.get("max") or 10,
                    default="true" if name == default else "false")
        _add(node, "value", _number(item.get("value")))
        if item.get("votes"):
            _add(node, "votes", int(item["votes"]))


def _uniqueids(parent, ids, default_kind):
    default = default_kind if ids.get(default_kind) else next(iter(ids), None)
    for kind in sorted(ids, key=lambda key: (key != default, key)):
        _add(parent, "uniqueid", ids[kind], type=kind, default="true" if kind == default else "false")


def _actors(parent, actors, thumbs=True):
    for index, actor in enumerate(actors or []):
        if not actor.get("name"):
            continue
        node = _add(parent, "actor")
        _add(node, "name", actor["name"])
        _text(node, "role", actor.get("role"))
        _add(node, "order", actor.get("order") if actor.get("order") is not None else index)
        if thumbs:
            _text(node, "thumb", actor.get("thumb"))


def channels(layout):
    text = str(layout or "").strip()
    match = re.match(r"^(\d+)\.(\d+)", text)
    if match:
        return int(match.group(1)) + int(match.group(2))
    return int(text) if text.isdigit() else None


def audio_codec(label):
    lowered = str(label or "").lower()
    for key, name in AUDIO_CODECS:
        if key in lowered:
            return name
    return lowered.replace(" ", "") or None


def hdr_detail(file):
    if file.get("hdr_format") != "dovi" or not file.get("dovi_profile"):
        return None
    profile = str(file["dovi_profile"]).strip()
    if profile.startswith("7") and file.get("dovi_el_type") in {"FEL", "MEL"}:
        return f"7{file['dovi_el_type']}"
    if profile.startswith("8") and file.get("dovi_bl_compat") not in (None, ""):
        return f"8.{file['dovi_bl_compat']}"
    return profile


def _streamdetails(parent, file):
    if not file or not file.get("video_codec"):
        return
    details = _add(_add(parent, "fileinfo"), "streamdetails")
    video = _add(details, "video")
    _add(video, "codec", VIDEO_CODECS.get(file["video_codec"], str(file["video_codec"]).lower()))
    _text(video, "aspect", file.get("aspect_ratio"))
    _text(video, "width", file.get("width"))
    _text(video, "height", file.get("height"))
    _text(video, "durationinseconds", file.get("duration_seconds"))
    stereo = {"HSBS": "left_right", "SBS": "left_right", "HOU": "top_bottom", "OU": "top_bottom",
              "MVC": "mvc", "3D": "left_right"}.get(file.get("stereo_mode"))
    if stereo:
        _add(video, "stereomode", stereo)
    elif file.get("is_3d"):
        _add(video, "stereomode", "left_right")
    hdr = HDR_TYPES.get(file.get("hdr_format"))
    if hdr:
        _add(video, "hdrtype", hdr)
        _text(video, "hdrdetail", hdr_detail(file))
    for track in file.get("audio_tracks") or []:
        audio = _add(details, "audio")
        _text(audio, "codec", audio_codec(track.get("codec")))
        _text(audio, "language", track.get("lang"))
        _text(audio, "channels", channels(track.get("channels")))
    subs = list(file.get("subtitle_tracks") or []) + list(file.get("external_subtitles") or [])
    for track in subs:
        if not track.get("lang"):
            continue
        sub = _add(details, "subtitle")
        _add(sub, "language", track["lang"])
        flags = track.get("flags") or []
        flags = [flags] if isinstance(flags, str) else flags
        names = {str(flag).lower() for flag in flags}
        if track.get("forced") or "forced" in names:
            _add(sub, "forced", 1)
        if "sdh" in names or "hi" in names:
            _add(sub, "hearingimpaired", 1)


def _remote_art(parent, art_urls, kinds):
    for kind in kinds:
        url = (art_urls or {}).get(kind)
        if url:
            _add(parent, "thumb", url, aspect=kind)
    if (art_urls or {}).get("fanart"):
        _add(_add(parent, "fanart"), "thumb", art_urls["fanart"])


def _dialect(root, item, dialect, ids, default_rating):
    if dialect == "emby":
        holder = root.find("ratings")
        ratings = item.get("ratings") or {}
        if holder is not None:
            root.remove(holder)
        main = ratings.get(default_rating) or (next(iter(ratings.values())) if ratings else None)
        if main and main.get("value") is not None:
            _add(root, "rating", _number(main["value"]))
            if main.get("votes"):
                _add(root, "votes", int(main["votes"]))
        critic = ratings.get("tomatometerallcritics")
        if critic and critic.get("value") is not None:
            _add(root, "criticrating", _number(critic["value"]))
        for kind in ("imdb", "tmdb", "tvdb"):
            if ids.get(kind):
                _add(root, f"{kind}id", ids[kind])
        _add(root, "lockdata", "true" if item.get("locked") else "false")
    elif dialect == "plex":
        for kind in ("imdb", "tmdb", "tvdb"):
            if ids.get(kind):
                _add(root, "guid", f"{kind}://{ids[kind]}")


def _ids(item):
    ids = dict(item.get("ids") or {})
    for kind in ("imdb", "tmdb", "tvdb"):
        if item.get(f"{kind}_id"):
            ids.setdefault(kind, str(item[f"{kind}_id"]))
    return {key: value for key, value in ids.items() if value}


def _serialize(roots):
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    for root in roots:
        ET.indent(root, space="    ")
        parts.append(ET.tostring(root, encoding="unicode"))
    return "\n".join(parts) + "\n"


def movie_xml(movie, *, dialect="kodi", default_rating="themoviedb", actor_thumbs=True, art_urls=None, versions=None):
    root = ET.Element("movie")
    ids = _ids(movie)
    _text(root, "title", movie.get("title"))
    _text(root, "originaltitle", movie.get("original_title"))
    _text(root, "englishtitle", movie.get("english_title"))
    _text(root, "sorttitle", movie.get("sort_title"))
    _ratings(root, movie.get("ratings") or {}, default_rating)
    _text(root, "top250", movie.get("top250"))
    _text(root, "outline", movie.get("outline"))
    _text(root, "plot", movie.get("plot"))
    _text(root, "tagline", movie.get("tagline"))
    _text(root, "runtime", movie.get("runtime_minutes"))
    _remote_art(root, art_urls, ("poster", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart"))
    _text(root, "mpaa", movie.get("mpaa"))
    _certifications(root, movie.get("certifications"))
    _add(root, "playcount", movie.get("playcount") or 0)
    _text(root, "lastplayed", movie.get("last_played"))
    _uniqueids(root, ids, "tmdb")
    _many(root, "genre", movie.get("genres"))
    _many(root, "country", movie.get("countries"))
    if movie.get("set_name"):
        node = _add(root, "set")
        _add(node, "name", movie["set_name"])
        _text(node, "overview", movie.get("set_overview"))
    _many(root, "tag", movie.get("tags"))
    _many(root, "credits", movie.get("writers"))
    _many(root, "director", movie.get("directors"))
    _text(root, "premiered", movie.get("premiered"))
    _text(root, "releasedate", movie.get("premiered"))
    _text(root, "year", movie.get("year"))
    _many(root, "studio", movie.get("studios"))
    _text(root, "trailer", movie.get("trailer"))
    _text(root, "edition", canonical_edition(movie.get("edition")))
    _video_version(root, movie, versions)
    _text(root, "source", (movie.get("file") or {}).get("source_format"))
    _streamdetails(root, movie.get("file"))
    _actors(root, movie.get("actors"), actor_thumbs)
    _text(root, "dateadded", _added(movie))
    _dialect(root, movie, dialect, ids, default_rating)
    return _serialize([root])


def show_xml(show, *, dialect="kodi", default_rating="themoviedb", actor_thumbs=True, art_urls=None,
             seasons=None, episode_count=None):
    root = ET.Element("tvshow")
    ids = _ids(show)
    _text(root, "title", show.get("title"))
    _text(root, "originaltitle", show.get("original_title"))
    _text(root, "englishtitle", show.get("english_title"))
    _text(root, "showtitle", show.get("title"))
    _text(root, "sorttitle", show.get("sort_title"))
    _ratings(root, show.get("ratings") or {}, default_rating)
    _text(root, "userrating", _number(show.get("user_rating")))
    _text(root, "top250", show.get("top250"))
    if seasons is not None:
        _text(root, "season", len(seasons))
    if episode_count is not None:
        _text(root, "episode", episode_count)
    _text(root, "outline", show.get("outline"))
    _text(root, "plot", show.get("plot"))
    _text(root, "tagline", show.get("tagline"))
    _text(root, "runtime", show.get("runtime_minutes"))
    _remote_art(root, art_urls, ("poster", "clearlogo", "clearart", "banner", "landscape", "characterart", "squareart"))
    _text(root, "mpaa", show.get("mpaa"))
    _add(root, "playcount", show.get("playcount") or 0)
    _text(root, "lastplayed", show.get("last_played"))
    _certifications(root, show.get("certifications"))
    default_id = "tvdb" if show.get("scrape_source") == "tvdb" else "tmdb"
    _uniqueids(root, ids, default_id)
    guide = {kind: str(ids[kind]) for kind in ("tvmaze", "tvrage", "tvdb", "tmdb", "imdb") if ids.get(kind)}
    if guide:
        _add(root, "episodeguide", json.dumps(guide, separators=(",", ":")))
    _many(root, "genre", show.get("genres"))
    _many(root, "country", show.get("countries"))
    _many(root, "tag", show.get("tags"))
    _text(root, "premiered", show.get("premiered"))
    _text(root, "year", show.get("year"))
    _text(root, "status", show.get("show_status"))
    _text(root, "originallanguage", show.get("original_language"))
    _many(root, "studio", show.get("studios"))
    _many(root, "director", show.get("directors"))
    _text(root, "trailer", show.get("trailer"))
    names = show.get("season_names") or {}
    for number in sorted(names, key=lambda key: int(key) if str(key).lstrip("-").isdigit() else 0):
        if names[number]:
            _add(root, "namedseason", names[number], number=number)
    for season in seasons or []:
        plot = str(season.get("plot") or "").strip()
        if plot and season.get("season_number") is not None:
            _add(root, "seasonplot", plot, number=season["season_number"])
    _actors(root, show.get("actors"), actor_thumbs)
    _text(root, "dateadded", _added(show))
    _dialect(root, show, dialect, ids, default_rating)
    return _serialize([root])


def season_xml(season, show_title=None, dialect="kodi"):
    root = ET.Element("season")
    _text(root, "title", season.get("title") or (f"Season {season['season_number']}" if season.get("season_number")
                                                  else "Specials"))
    _text(root, "showtitle", show_title)
    _text(root, "sorttitle", season.get("sort_title"))
    _text(root, "plot", season.get("plot"))
    _text(root, "premiered", season.get("premiered"))
    _text(root, "year", season.get("year") or _season_year(season.get("premiered")))
    _add(root, "seasonnumber", season.get("season_number") or 0)
    _uniqueids(root, season.get("ids") or {}, "tmdb")
    if dialect == "emby":
        _add(root, "lockdata", "true" if season.get("locked") else "false")
    return _serialize([root])


def set_xml(movie_set):
    """Kodi v22 set.nfo: title, original title, and overview."""
    root = ET.Element("set")
    _text(root, "title", movie_set.get("name"))
    if movie_set.get("original_title"):
        _text(root, "originaltitle", movie_set.get("original_title"))
    _text(root, "overview", movie_set.get("overview"))
    return _serialize([root])


def episodes_xml(episodes, show, file=None, *, dialect="kodi", default_rating="themoviedb", actor_thumbs=True):
    """<episodedetails> blocks, in episode order.

    Kodi v22 reads one block per file. A multi-episode video gets a separate NFO for each
    episode; this still serializes every block it is given so an older combined file can be rebuilt.
    Each block includes <fileinfo><streamdetails> when the shared video file has been probed.
    """
    roots = []
    for episode in sorted(episodes, key=lambda item: (item["season_number"], item["episode_number"])):
        root = ET.Element("episodedetails")
        ids = {key: value for key, value in (episode.get("ids") or {}).items() if value}
        _text(root, "title", episode.get("title"))
        _text(root, "originaltitle", episode.get("original_title"))
        _text(root, "englishtitle", episode.get("english_title"))
        _text(root, "showtitle", show.get("title"))
        _ratings(root, episode.get("ratings") or {}, default_rating)
        _text(root, "userrating", _number(episode.get("user_rating")))
        _add(root, "season", episode["season_number"])
        _add(root, "episode", episode["episode_number"])
        _text(root, "displayseason", episode.get("display_season"))
        _text(root, "displayepisode", episode.get("display_episode"))
        _text(root, "plot", episode.get("plot"))
        _text(root, "mpaa", episode.get("mpaa"))
        _certifications(root, episode.get("certifications"))
        _text(root, "runtime", episode.get("runtime_minutes"))
        _add(root, "playcount", episode.get("playcount") or 0)
        _text(root, "lastplayed", episode.get("last_played"))
        if ids:
            _uniqueids(root, ids, "tvdb" if ids.get("tvdb") else "tmdb")
        _many(root, "tag", episode.get("tags"))
        _many(root, "credits", episode.get("writers"))
        _many(root, "director", episode.get("directors"))
        _text(root, "aired", episode.get("aired"))
        _text(root, "premiered", episode.get("aired"))
        _text(root, "source", (file or {}).get("source_format"))
        _streamdetails(root, file)
        _actors(root, episode.get("guest_stars"), actor_thumbs)
        _resume(root, episode)
        _text(root, "dateadded", _added(episode))
        _dialect(root, episode, dialect, ids, default_rating)
        roots.append(root)
    return _serialize(roots)


def _asset_title(movie):
    edition = canonical_edition(movie.get("edition") or (movie.get("file") or {}).get("edition"))
    return edition or "Standard Edition"


def _version_key(name):
    return re.sub(r"\s+", " ", str(name or "").replace("’", "'").strip().lower())


def _default_version(peers):
    """The highest-resolution copy. Bitrate, then id, breaks a tie."""
    def rank(item):
        try:
            height = float(item.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        try:
            bitrate = float(item.get("bitrate_mbps") or 0)
        except (TypeError, ValueError):
            bitrate = 0
        return (height, bitrate, str(item.get("id") or ""))

    return max(peers, key=rank).get("id") if peers else None


def _video_version(root, movie, versions):
    """Kodi version tags on this file's own movie NFO.

    One NFO still describes one file. hasvideoversions says other copies of the same movie exist.
    Kodi v21 does not yet attach those copies from the tags; the version manager does that.
    """
    peers = list(versions) if versions else [{"id": movie.get("id")}]
    title = _asset_title(movie)
    _add(root, "videoassettitle", title)
    asset_id = _VERSION_TYPES.get(_version_key(title))
    if asset_id:
        _add(root, "videoassetid", asset_id)
    _add(root, "videoassettype", 0)
    multiple = len(peers) > 1
    _add(root, "hasvideoversions", "true" if multiple else "false")
    _add(root, "hasvideoextras", "false")
    chosen = _default_version(peers)
    is_default = not multiple or str(movie.get("id")) == str(chosen)
    _add(root, "isdefaultvideoversion", "true" if is_default else "false")


def _resume(root, episode):
    position = episode.get("resume_position")
    total = episode.get("resume_total")
    if position in (None, "") and total in (None, ""):
        return
    node = _add(root, "resume")
    if position not in (None, ""):
        _add(node, "position", _number(position))
    if total not in (None, ""):
        _add(node, "total", _number(total))


def _added(item):
    """The first-seen date, so rewriting an unchanged item produces identical bytes."""
    if item.get("date_added"):
        return item["date_added"]
    created = item.get("created_at")
    if isinstance(created, dt.datetime):
        return created.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(created, str) and created:
        return created.replace("T", " ")[:19]
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def same_text(path, text):
    """True when the file already holds exactly this text, so the database and the file agree."""
    try:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", "replace").replace("\r\n", "\n") == (text or "").replace("\r\n", "\n")
    except OSError:
        return False


def write(path, text, *, policy="merge", backup=True):
    """Atomic write next to the target. Returns (written, mtime). missing never touches an existing file."""
    from . import writes

    exists = os.path.exists(path)
    if exists and policy == "missing":
        return False, nfo_read.mtime(path)
    if exists:
        try:
            with open(path, "rb") as handle:
                if handle.read().decode("utf-8", "replace").replace("\r\n", "\n") == (text or "").replace("\r\n", "\n"):
                    return False, nfo_read.mtime(path)
        except OSError:
            pass
        if backup and policy == "overwrite":
            writes.check(path)
            shutil.copy2(path, f"{path}.bak")
    writes.atomic_write(path, text.encode("utf-8"))
    return True, nfo_read.mtime(path)
