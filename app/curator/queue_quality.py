"""Quality facts for the library queue: the same fields the info panel badges read, kept small.

The webhook queue works them out when it hands items to the library queue, so the queue
and its history can show resolution, codecs and HDR for video, or format and bit depth for music.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_VIDEO_FIELDS = (
    "resolution", "aspect_ratio", "hdr_format", "hdr_secondary", "dovi_profile", "dovi_el_type",
    "video_source", "source_format", "edition", "video_codec", "bit_depth", "container", "stereo_mode",
)
_VIDEO_COLUMNS = ", ".join(f"vf.{name}" for name in _VIDEO_FIELDS) + ", vf.is_3d, vf.audio_tracks"


def video_facts(row):
    """The badge fields of one video_files row. Empty when the file was not probed."""
    row = row or {}
    facts = {name: str(row[name]) for name in _VIDEO_FIELDS if row.get(name) not in (None, "")}
    if row.get("is_3d"):
        facts["is_3d"] = True
    tracks = row.get("audio_tracks") or []
    track = next((item for item in tracks if isinstance(item, dict) and item.get("default")), None)
    if track is None:
        track = next((item for item in tracks if isinstance(item, dict)), {})
    if track.get("codec"):
        facts["audio_codec"] = str(track["codec"])
    if track.get("channels"):
        facts["audio_channels"] = str(track["channels"])
    return {"kind": "video", **facts} if facts else {}


def music_facts(row):
    """The badge fields of one album row. Empty when the scanner has not worked them out."""
    row = row or {}
    facts = {}
    if row.get("audio_format"):
        facts["format"] = str(row["audio_format"])
    if row.get("audio_lossless") is not None:
        facts["lossless"] = bool(row["audio_lossless"])
    for key, name in (("audio_bit_depth", "bit_depth"), ("audio_sample_rate", "sample_rate"), ("audio_bitrate", "bitrate")):
        if row.get(key):
            facts[name] = int(row[key])
    return {"kind": "music", **facts} if facts.get("format") else {}


def for_ingest(media, rows):
    """Facts by item title for webhook rows that were just scanned. Never raises."""
    try:
        if media == "music":
            return _music_rows(rows)
        return _video_rows(media, rows)
    except Exception:
        logger.exception("could not read the quality of the queued items")
        return {}


def for_movies(ids):
    """Facts by movie title for a manual library update. Never raises."""
    from resonance import db

    try:
        found = db.fetchall(
            f"SELECT m.title, {_VIDEO_COLUMNS} FROM movies m JOIN video_files vf ON vf.id = m.file_id WHERE m.id = ANY(%s::uuid[])",
            (list(ids or []),),
        )
    except Exception:
        logger.exception("could not read the quality of the chosen movies")
        return {}
    result = {}
    for row in found:
        facts = video_facts(row)
        if facts and row.get("title") and row["title"] not in result:
            result[row["title"]] = facts
    return result


_CODE = re.compile(r"S(\d{1,3})E(\d{1,4})", re.IGNORECASE)


def episode_codes(title):
    """(season, episode) pairs named in a queue title such as "Show (2015) S03E10" or "Show S02E03, S02E07"."""
    return [(int(season), int(episode)) for season, episode in _CODE.findall(str(title or ""))]


def _video_rows(media, rows):
    """Facts by title. Every file the webhook named is looked up among the probed files, whichever item it belongs
    to (an upgrade can sit beside the old file as a second copy, a rename changes the name). A title none of whose
    files is found falls back to its movie folder, or to its show folder and the episode codes in the title."""
    from resonance import db

    wanted = {}
    for row in rows or []:
        title = row.get("title")
        if not title:
            continue
        entry = wanted.setdefault(title, {"files": [], "folder": row.get("path") or ""})
        # Files still on disk first: the list can also hold the file an upgrade replaced.
        named = [path for path in row.get("files") or [] if path]
        entry["files"].extend(sorted(named, key=lambda path: not os.path.isfile(path)))
    result = {}
    every = sorted({path for entry in wanted.values() for path in entry["files"]})
    if every:
        found = {row["path"]: video_facts(row) for row in db.fetchall(
            f"SELECT vf.path, {_VIDEO_COLUMNS} FROM video_files vf WHERE vf.path = ANY(%s)", (every,))}
        for title, entry in wanted.items():
            facts = next((found[path] for path in entry["files"] if found.get(path)), None)
            if facts:
                result[title] = facts
    missing = {title: entry for title, entry in wanted.items() if title not in result and entry["folder"]}
    if not missing:
        return result
    folders = sorted({entry["folder"] for entry in missing.values()})
    if media == "movies":
        by_folder = {}
        for row in db.fetchall(
            f"SELECT m.folder, {_VIDEO_COLUMNS} FROM movies m JOIN video_files vf ON vf.id = m.file_id WHERE m.folder = ANY(%s)",
            (folders,),
        ):
            facts = video_facts(row)
            if facts:
                by_folder.setdefault(row["folder"], facts)
        for title, entry in missing.items():
            if by_folder.get(entry["folder"]):
                result[title] = by_folder[entry["folder"]]
        return result
    by_code = {}
    for row in db.fetchall(
        f"""
        SELECT s.path AS show_path, e.season_number, e.episode_number, {_VIDEO_COLUMNS}
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id JOIN video_files vf ON vf.id = e.file_id
        WHERE s.path = ANY(%s) AND NOT e.missing
        """,
        (folders,),
    ):
        facts = video_facts(row)
        if facts:
            by_code.setdefault((row["show_path"], int(row["season_number"]), int(row["episode_number"])), facts)
    for title, entry in missing.items():
        facts = next((by_code[(entry["folder"], season, episode)] for season, episode in episode_codes(title)
                      if by_code.get((entry["folder"], season, episode))), None)
        if facts:
            result[title] = facts
    return result


def _music_rows(rows):
    from resonance import db

    paths = {}
    for row in rows or []:
        if row.get("title") and row.get("path") and not row.get("removed"):
            paths.setdefault(str(row["path"]).rstrip("/"), row["title"])
    if not paths:
        return {}
    found = db.fetchall(
        """
        SELECT path, audio_format, audio_lossless, audio_bit_depth, audio_sample_rate, audio_bitrate
        FROM albums WHERE rtrim(path, '/') = ANY(%s)
        """,
        (list(paths),),
    )
    result = {}
    for row in found:
        facts = music_facts(row)
        title = paths.get(str(row["path"]).rstrip("/"))
        if facts and title:
            result.setdefault(title, facts)
    return result


def pick(quality, labels):
    """The facts for these labels only, in label order, for the queue payload and the history row."""
    quality = quality or {}
    return [{"label": label, **quality[label]} for label in labels or [] if quality.get(label)]
