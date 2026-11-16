"""Music videos: a fourth video library for Kodi's music video section.

Each video file under a music video folder is one music video. Artist, title and year come from the Kodi .nfo
(<musicvideo>) beside the file when there is one, otherwise from the file name ("Artist - Title (Year)"), with the
parent folder as the artist when the name has no dash. The file is probed like a movie, so it gets the same quality
badges. Curator writes a <musicvideo> .nfo for Kodi when one is missing or when asked to.

An incremental scan reads only new and changed files (size or mtime); a full scan reads every file again. Files that
are gone are removed from the library (rows only, never files).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from xml.sax.saxutils import escape

import psycopg

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "processed": 0, "total": 0, "result": {}}
_log = deque(maxlen=1000)
_YEAR = re.compile(r"[\(\[]((?:19|20)\d{2})[\)\]]")
_NOISE = re.compile(r"\b(official\s+(music\s+)?video|official|hd|4k|1080p|720p|2160p|lyrics?)\b", re.I)


def status():
    with _lock:
        return {**_state, "log": "\n".join(_log)}


def _say(line, **progress):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        _state["message"] = line
        _state.update(progress)


def parse_name(path):
    """{"artist", "title", "year"} from a file name like "Artist - Title (2014) [1080p].mkv"."""
    stem = os.path.splitext(os.path.basename(path))[0]
    year_match = _YEAR.search(stem)
    year = int(year_match.group(1)) if year_match else None
    text = _YEAR.sub(" ", stem)
    text = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", text)
    text = _NOISE.sub(" ", text).replace("_", " ")
    parts = [part.strip(" .-") for part in re.split(r"\s+-\s+|\s+–\s+", text, maxsplit=1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        artist, title = parts
    else:
        artist = os.path.basename(os.path.dirname(path))
        title = parts[0] if parts and parts[0] else stem
    return {"artist": " ".join(artist.split()), "title": " ".join(title.split()), "year": year}


def nfo_path(path):
    return os.path.splitext(path)[0] + ".nfo"


def read_nfo(path):
    """Facts from a Kodi <musicvideo> .nfo, or {} when there is none or it is not one."""
    target = nfo_path(path)
    if not os.path.isfile(target):
        return {}
    try:
        root = ET.parse(target).getroot()
    except (ET.ParseError, OSError):
        return {}
    if root.tag != "musicvideo":
        return {}

    def text(tag):
        node = root.find(tag)
        return " ".join((node.text or "").split()) if node is not None and node.text else ""

    year = text("year") or text("premiered")[:4]
    return {
        "title": text("title"), "artist": text("artist"), "album": text("album"), "plot": text("plot"),
        "year": int(year) if year[:4].isdigit() else None,
        "genres": [" ".join((node.text or "").split()) for node in root.findall("genre") if node.text],
        "director": text("director"),
    }


def nfo_text(row):
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', "<musicvideo>"]
    for tag, key in (("title", "title"), ("artist", "artist"), ("album", "album"), ("plot", "plot"),
                     ("director", "director")):
        if row.get(key):
            lines.append(f"    <{tag}>{escape(str(row[key]))}</{tag}>")
    if row.get("year"):
        lines.append(f"    <year>{int(row['year'])}</year>")
    for genre in row.get("genres") or []:
        lines.append(f"    <genre>{escape(str(genre))}</genre>")
    if row.get("playcount"):
        lines.append(f"    <playcount>{int(row['playcount'])}</playcount>")
    if row.get("last_played"):
        lines.append(f"    <lastplayed>{escape(str(row['last_played']))}</lastplayed>")
    lines.append("</musicvideo>")
    return "\n".join(lines) + "\n"


def write_nfo(row, overwrite=False):
    """Write the .nfo. Returns True when a file was written. A file that already holds the same text stays."""
    target = nfo_path(row["path"])
    text = nfo_text(row)
    if os.path.isfile(target):
        if not overwrite:
            return False
        try:
            with open(target, encoding="utf-8") as handle:
                if handle.read() == text:
                    return False
        except OSError:
            pass
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    db.execute("UPDATE music_videos SET nfo_path = %s, updated_at = NOW() WHERE id = %s", (target, row["id"]))
    return True


def _walk(root):
    from curator.video import naming

    for folder, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if not naming.skip_dir(name)]
        for name in names:
            if naming.is_video(name) and not naming.is_extra_file(name):
                yield os.path.join(folder, name)


def scan(mode="incremental", roots=None, write_nfos=True):
    """Index the music video folders. Returns counts."""
    from curator import folders
    from curator.video import probe, store

    chosen = folders.choose("musicvideos", roots or [])
    from resonance.settings import take_path_removals

    for removed in take_path_removals("musicvideos"):
        db.execute("DELETE FROM music_videos WHERE root = %s", (os.path.realpath(removed),))
    known = {row["path"]: row for row in db.fetchall(
        "SELECT mv.id::text AS id, mv.path, f.size_bytes, f.mtime FROM music_videos mv "
        "LEFT JOIN video_files f ON f.id = mv.file_id WHERE mv.root = ANY(%s)", (chosen,))}
    files = [(root, path) for root in chosen for path in _walk(root)]
    _say(f"Found {len(files)} music video files", total=len(files), processed=0)
    added = changed = written = 0
    seen = set()
    for index, (root, path) in enumerate(files, start=1):
        seen.add(path)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        old = known.get(path)
        same = old and old.get("size_bytes") == stat.st_size and abs(float(old.get("mtime") or 0) - stat.st_mtime) < 1
        if mode == "incremental" and same:
            continue
        _say(f"Reading {os.path.basename(path)}", processed=index)
        try:
            summary = probe.analyze(path)
        except Exception as exc:
            summary = {"probe_error": str(exc)}
        facts = {**parse_name(path), **{key: value for key, value in read_nfo(path).items() if value}}
        row = None
        for _attempt in range(3):
            file_id = store.save_file(path, "musicvideo", stat.st_size, stat.st_mtime, summary)
            try:
                row = db.fetchone(
                    """
                    INSERT INTO music_videos (path, root, folder, title, artist, album, year, genres, plot, director,
                                              file_id, nfo_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (path) DO UPDATE SET root = EXCLUDED.root, folder = EXCLUDED.folder, title = EXCLUDED.title,
                        artist = EXCLUDED.artist, album = EXCLUDED.album, year = EXCLUDED.year, genres = EXCLUDED.genres,
                        plot = EXCLUDED.plot, director = EXCLUDED.director, file_id = EXCLUDED.file_id,
                        nfo_path = EXCLUDED.nfo_path, updated_at = NOW()
                    WHERE NOT music_videos.locked
                    RETURNING id::text AS id, path, title, artist, album, year, genres, plot, director, playcount, last_played
                    """,  # a locked music video keeps what you typed
                    (path, root, os.path.dirname(path), facts.get("title") or os.path.basename(path), facts.get("artist") or "",
                     facts.get("album") or "", facts.get("year"), facts.get("genres") or [], facts.get("plot") or "",
                     facts.get("director") or "", file_id, nfo_path(path) if os.path.isfile(nfo_path(path)) else None),
                )
                break
            except psycopg.errors.ForeignKeyViolation:
                continue    # a movie or TV scan cleaned up the file row between the two statements: save it again
        else:
            raise RuntimeError(f"{os.path.basename(path)}: the file row kept disappearing while it was being linked")
        if old:
            changed += 1
        else:
            added += 1
        _note_thumb(path)
        if row and write_nfos:
            try:
                written += 1 if write_nfo(dict(row)) else 0
            except OSError as exc:
                _say(f"Could not write the .nfo of {os.path.basename(path)}: {exc}")
    gone = [row["id"] for path, row in known.items() if path not in seen and not os.path.exists(path)]
    if gone:
        db.execute("DELETE FROM music_videos WHERE id = ANY(%s::uuid[])", (gone,))
    if added or changed or gone:
        try:
            from curator import notify

            notify.request("video", folders=sorted({os.path.dirname(path) for _root, path in files if path in seen})
                           if mode == "incremental" else chosen, clean=bool(gone))
        except Exception:
            logger.info("music video library update was not sent", exc_info=True)
    return {"added": added, "changed": changed, "removed": len(gone), "nfo": written, "files": len(files)}


def start(mode="incremental", roots=None):
    with _lock:
        if _state["status"] == "running":
            return False
        _log.clear()
        _state.update({"status": "running", "message": "Starting", "processed": 0, "total": 0, "result": {}})
    threading.Thread(target=_run, args=(mode, roots), name="musicvideo-scan", daemon=True).start()
    return True


def _run(mode, roots):
    try:
        result = scan(mode, roots)
        final = "done"
        message = (f"Music videos: {result['added']} added, {result['changed']} read again, {result['removed']} removed, "
                   f"{result['nfo']} .nfo written")
    except AppError as exc:
        result, final, message = {}, "failed", str(exc)
    except Exception as exc:
        logger.exception("music video scan failed")
        result, final, message = {}, "failed", str(exc)
    _say(message)
    with _lock:
        _state.update({"status": final, "message": message, "result": result})
    try:
        from curator import outbound

        outbound.scan_done("musicvideos", "completed" if final == "done" else "failed", message)
    except Exception:
        logger.exception("could not report the music video scan")


def list_items():
    from curator.video import store

    rows = db.fetchall(
        f"""
        SELECT mv.id::text AS id, mv.path, mv.root, mv.title, mv.artist, mv.album, mv.year, mv.genres, mv.locked,
               mv.nfo_path, mv.playcount, mv.last_played, mv.plot, mv.director, mv.thumb_path, mv.created_at,
               f.path AS file_path, {store.FILE_BRIEF}
        FROM music_videos mv LEFT JOIN video_files f ON f.id = mv.file_id
        ORDER BY lower(mv.artist), lower(mv.title)
        """
    )
    items = [dict(row) for row in rows]
    copy_marks(items)
    return [db.clean(store.brief_file(item)) for item in items]


def copy_marks(items):
    """Duplicate and Upgrade for music videos, with the movie rules (copies.assign_marks).

    Copies are videos with the same artist and title. Two copies are duplicates when they are the same release (same
    source, resolution and about the same size); a better file is an upgrade for the weaker copy, never across 3D and
    flat. Sets on each item: duplicate, copies (same-release copies, itself included), upgrade and upgrade_path. Needs
    the joined video_files columns."""
    from curator.video import copies
    from resonance.fields import norm_name

    prepared = []
    for item in items:
        key = (norm_name(item.get("artist")), norm_name(item.get("title")))
        prepared.append({
            "id": str(item["id"]), "key": key if key[0] and key[1] else None, "score": copies.score(item),
            "path": item.get("path") or "", "height": item.get("height"), "size_bytes": item.get("size_bytes"),
            "source_format": item.get("source_format") or "", "video_source": item.get("video_source") or "",
            "hdr_format": item.get("hdr_format") or "", "is_3d": bool(item.get("is_3d")),
            "stereo_mode": item.get("stereo_mode") or "", "copies": [],
        })
    marks = copies.assign_marks(prepared)
    by_id = {row["id"]: row for row in prepared}
    paths = {row["id"]: row["path"] for row in prepared}
    for item in items:
        mark = marks.get(str(item["id"])) or {}
        mine = by_id[str(item["id"])]
        same = [row for row in prepared if row is not mine and mine["key"] and row["key"] == mine["key"]
                and copies.same_release(mine, row)]
        item["duplicate"] = bool(mark.get("duplicate"))
        item["copies"] = 1 + len(same) if item["duplicate"] else 1
        upgrade_id = mark.get("upgrade_id")
        item["upgrade"] = bool(upgrade_id or mark.get("upgrade_path"))
        item["upgrade_path"] = paths.get(str(upgrade_id), "") if upgrade_id else (mark.get("upgrade_path") or "")
    return items


def write_all(ids=None, overwrite=True):
    rows = db.fetchall(
        "SELECT id::text AS id, path, title, artist, album, year, genres, plot, director, playcount, last_played "
        "FROM music_videos WHERE NOT locked" + (" AND id = ANY(%s::uuid[])" if ids else ""),
        (list(ids),) if ids else (),
    )
    return sum(1 for row in rows if write_nfo(dict(row), overwrite=overwrite))


# Editing one music video, its picture, delete, and looking up what is blank.

THUMB_SUFFIXES = ("-thumb.jpg", "-poster.jpg", "-thumb.png", "-poster.png")
EDITABLE = ("title", "artist", "album", "year", "plot", "director", "genres")


def _note_thumb(path):
    stem = os.path.splitext(path)[0]
    found = next((stem + suffix for suffix in THUMB_SUFFIXES if os.path.isfile(stem + suffix)), None)
    db.execute("UPDATE music_videos SET thumb_path = %s WHERE path = %s", (found, path))


def _row(item_id):
    row = db.fetchone(
        "SELECT id::text AS id, path, root, title, artist, album, year, genres, plot, director, playcount, last_played, "
        "locked, thumb_path FROM music_videos WHERE id = %s", (item_id,))
    if not row:
        raise AppError("That music video is gone", 404)
    return dict(row)


def update(item_id, fields, locked=None):
    """Save typed values, then rewrite the .nfo. Saving locks the item if asked, so a scan keeps them."""
    row = _row(item_id)
    values = {key: fields[key] for key in EDITABLE if key in (fields or {})}
    if "year" in values:
        text = str(values["year"] or "").strip()
        values["year"] = int(text) if text.isdigit() and 1800 < int(text) < 2200 else None
    if "genres" in values and not isinstance(values["genres"], list):
        values["genres"] = [part.strip() for part in str(values["genres"] or "").split(",") if part.strip()]
    for key in ("title", "artist", "album", "plot", "director"):
        if key in values:
            values[key] = " ".join(str(values[key] or "").split()) if key != "plot" else str(values[key] or "").strip()
    if "title" in values and not values["title"]:
        raise AppError("A music video needs a title", 400)
    if locked is not None:
        values["locked"] = bool(locked)
    if values:
        sets = ", ".join(f"{key} = %s" for key in values)
        db.execute(f"UPDATE music_videos SET {sets}, updated_at = NOW() WHERE id = %s", (*values.values(), item_id))
    row = _row(item_id)
    try:
        write_nfo(row, overwrite=True)
    except OSError as exc:
        raise AppError(f"Saved, but the .nfo could not be written: {exc}", 500) from exc
    return row


def make_thumb(item_id):
    """Save a still from the video as <video>-thumb.jpg, where Kodi looks for it."""
    from curator.video import framegrab

    row = _row(item_id)
    target = os.path.splitext(row["path"])[0] + "-thumb.jpg"
    if not os.path.isfile(row["path"]):
        raise AppError("The video file is not on disk", 404)
    if framegrab.probe(row["path"])["duration"] < 30:
        raise AppError("This video is shorter than 30 seconds, too short to take a picture from", 400)
    if not framegrab.grab(row["path"], target):
        raise AppError(framegrab.last_error or "No usable frame was found", 500)
    _note_thumb(row["path"])
    return target


def thumb_file(item_id):
    path = _row(item_id).get("thumb_path")
    if not path or not os.path.isfile(path):
        raise AppError("This music video has no picture", 404)
    return path


def delete(ids):
    """Delete the video and its .nfo and pictures from disk (to the recycle bin when it is on). Returns titles and errors."""
    from curator import notify
    from resonance import trash

    from curator.video import delete as video_delete

    deleted, errors, folders_changed = [], [], set()
    for item_id in ids or []:
        try:
            row = _row(item_id)
            if os.path.exists(row["path"]):
                # The same guards as a movie delete: a mounted Music videos folder, writable, never the folder itself.
                video_delete._guard(row["path"], row["root"], "musicvideos")
            stem = os.path.splitext(row["path"])[0]
            for path in [stem + ".nfo", stem + ".cmm_mediainfo.xml", *(stem + suffix for suffix in THUMB_SUFFIXES)]:
                if os.path.isfile(path):
                    trash.discard(path, kind="musicvideo")
            trash.discard(row["path"], label=f"{row['artist']} — {row['title']}", kind="musicvideo")
            db.execute("DELETE FROM music_videos WHERE id = %s", (item_id,))
            deleted.append(row["title"])
            folders_changed.add(os.path.dirname(row["path"]))
        except (AppError, OSError) as exc:
            errors.append(f"{item_id}: {exc}")
    if folders_changed:
        notify.request("video", folders=sorted(folders_changed), clean=True)
    return {"deleted": deleted, "errors": errors}


def forget(ids):
    """Remove music videos from the library only. The files stay, and the next scan adds them back."""
    from resonance import history

    removed = []
    for item_id in ids or []:
        try:
            row = _row(item_id)
        except AppError:
            continue
        db.execute("DELETE FROM music_videos WHERE id = %s", (item_id,))
        history.record("removed", f"{row['artist']} — {row['title']}", "musicvideo", row["path"],
                       "Removed from the library. The files stay on disk.")
        removed.append(row["title"])
    return {"removed": removed}


def _audiodb_track(artist, title):
    from resonance.sources import audiodb
    from resonance.sources.client import get_json

    data = get_json(f"{audiodb.API}/searchtrack.php", {"s": artist, "t": title})
    tracks = (data or {}).get("track") or []
    return tracks[0] if tracks else None


def fill_blanks(row):
    """Fill a blank album, genre, or plot from TheAudioDB. What is already there stays. Returns True when a field was filled."""
    if row.get("locked") or not row.get("artist") or not row.get("title"):
        return False
    track = _audiodb_track(row["artist"], row["title"])
    if not track:
        return False
    fields = {}
    if not row.get("album") and track.get("strAlbum"):
        fields["album"] = track["strAlbum"]
    if not row.get("plot") and track.get("strDescriptionEN"):
        fields["plot"] = track["strDescriptionEN"]
    if not row.get("genres") and track.get("strGenre"):
        fields["genres"] = [track["strGenre"]]
    if not fields:
        return False
    update(row["id"], fields)
    return True


def _run_fill():
    rows = db.fetchall("SELECT id::text AS id, title, artist, album, plot, genres, locked FROM music_videos "
                       "WHERE NOT locked AND (album = '' OR plot = '' OR genres = ARRAY[]::text[])")
    filled = 0
    try:
        for index, row in enumerate(rows, start=1):
            _say(f"Looking up {row['artist']} - {row['title']}", processed=index, total=len(rows))
            try:
                filled += 1 if fill_blanks(dict(row)) else 0
            except Exception as exc:
                logger.info("music video lookup failed for %s: %s", row["title"], exc)
        final, message = "done", f"Filled in {filled} of {len(rows)} music videos from TheAudioDB"
    except Exception as exc:
        logger.exception("music video lookup failed")
        final, message = "failed", str(exc)
    _say(message)
    with _lock:
        _state.update({"status": final, "message": message})


def start_fill():
    with _lock:
        if _state["status"] == "running":
            return False
        _log.clear()
        _state.update({"status": "running", "message": "Starting", "processed": 0, "total": 0, "result": {}})
    threading.Thread(target=_run_fill, name="musicvideo-lookup", daemon=True).start()
    return True
