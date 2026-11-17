"""Add a music video from YouTube: search, pick one, download it into the Music videos folder.

The search and the download both use the yt-dlp that trailers use (curator.video.ytdlp_update.binary). The file is
saved as "Artist - Title (Year).mp4", in the artist's folder when the library already has one for that artist and
otherwise at the top of the Music videos folder, and a scan of that folder then adds it to the library and writes its
.nfo. One download runs at a time; it shows in the Jobs panel.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading

from resonance.errors import AppError

logger = logging.getLogger(__name__)
SEARCH_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 1800
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Words a YouTube title adds that are not part of the song's name.
_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*(official|video|audio|lyrics?|visuali[sz]er|remaster(ed)?|hd|hq|4k|mv|live|explicit|clean)[^\)\]]*[\)\]]",
    re.IGNORECASE)
_lock = threading.Lock()
_state = {"status": "idle", "message": "", "title": "", "path": ""}


def status():
    with _lock:
        return dict(_state)


def _binary():
    from curator.video import ytdlp_update

    binary = ytdlp_update.binary()
    if not binary:
        raise AppError("yt-dlp is not installed in the container", 500)
    return binary


def guess_names(title, channel=""):
    """{"artist", "title"} from a YouTube title such as "Adele - Hello (Official Music Video)". With no dash in it
    the channel is the artist (a "- Topic" or "VEVO" ending is dropped)."""
    text = _NOISE.sub("", str(title or "")).strip()
    parts = [part.strip(" .-") for part in re.split(r"\s+[-–—]\s+", text, maxsplit=1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return {"artist": " ".join(parts[0].split()), "title": " ".join(parts[1].split())}
    artist = re.sub(r"(\s*-\s*topic|\s*vevo)$", "", str(channel or ""), flags=re.IGNORECASE).strip()
    return {"artist": artist, "title": " ".join(text.split())}


def search(query, limit=10):
    """The first YouTube results for these words: id, title, channel, seconds, picture, and the guessed names."""
    words = " ".join(str(query or "").split())
    if len(words) < 2:
        raise AppError("Type an artist and a title to search for", 400)
    limit = max(1, min(20, int(limit or 10)))
    command = [_binary(), "--flat-playlist", "--dump-single-json", "--no-warnings", "--quiet", f"ytsearch{limit}:{words}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=SEARCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise AppError("YouTube did not answer the search in time", 504) from None
    if result.returncode != 0:
        raise AppError(f"The YouTube search failed: {(result.stderr or '').strip().splitlines()[-1:] or ['unknown error']}"[:300], 502)
    try:
        entries = (json.loads(result.stdout or "{}") or {}).get("entries") or []
    except ValueError:
        raise AppError("The YouTube search gave an answer that could not be read", 502) from None
    found = []
    for entry in entries:
        video_id = str((entry or {}).get("id") or "")
        if not _ID.match(video_id):
            continue
        channel = entry.get("channel") or entry.get("uploader") or ""
        thumbs = entry.get("thumbnails") or []
        found.append({
            "id": video_id, "title": entry.get("title") or "", "channel": channel,
            "seconds": int(entry.get("duration") or 0), "views": int(entry.get("view_count") or 0),
            "picture": (thumbs[-1] or {}).get("url") if thumbs else f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            **{f"guess_{key}": value for key, value in guess_names(entry.get("title"), channel).items()},
        })
    known = known_artists()
    for item in found:
        linked = link_artist(item.get("guess_artist"), known)
        item["guess_artist"], item["artist_known"] = linked["artist"], linked["known"]
    return found


def _roots():
    from curator import folders

    try:
        return [root for root in folders.choose("musicvideos", []) if root and os.path.isdir(root)]
    except AppError:
        return []


def roots():
    """The Music videos folders a download can go to. Empty when none is set under Settings, General."""
    return _roots()


def artist_key(name):
    """A name reduced to what makes two spellings the same artist: case, accents, punctuation and a leading The."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"^the ", "", text)
    return text or " ".join(str(name or "").lower().split())


def known_artists():
    """Artist names Curator already knows, each spelling once: music videos first, then the music library."""
    from resonance import db

    names = []
    try:
        names += [row["artist"] for row in db.fetchall(
            "SELECT artist, COUNT(*) AS n FROM music_videos WHERE COALESCE(artist, '') <> '' GROUP BY artist ORDER BY n DESC")]
        names += [row["name"] for row in db.fetchall("SELECT name FROM artists WHERE COALESCE(name, '') <> '' ORDER BY lower(name)")]
    except Exception:
        logger.info("could not read the known artists", exc_info=True)
    seen, found = set(), []
    for name in names:
        key = artist_key(name)
        if key and key not in seen:
            seen.add(key)
            found.append(name)
    return found


def link_artist(name, known=None):
    """{"artist", "known"}: the spelling the library already uses for this artist, or the name as typed."""
    text = " ".join(str(name or "").split())
    key = artist_key(text)
    if key:
        for item in (known_artists() if known is None else known):
            if artist_key(item) == key:
                return {"artist": item, "known": True}
    return {"artist": text, "known": False}


def artist_folder(root, artist):
    """The folder of this artist inside the Music videos folder, however it is spelled there, or None."""
    key = artist_key(artist)
    try:
        names = sorted(entry.name for entry in os.scandir(root) if entry.is_dir() and not entry.name.startswith("."))
    except OSError:
        return None
    for name in names:
        if artist_key(name) == key:
            return os.path.join(root, name)
    return None


def folder_for(root, artist, rule=None):
    """(folder, exists) the video is saved in under this rule. The folder is made later, by the download."""
    from curator.video import config, renamer

    rule = rule if rule in config.MV_FOLDER_RULES else config.current().get("mv_folder_rule", "artist")
    if rule == "flat":
        return root, True
    found = artist_folder(root, artist)
    if found:
        return found, True
    name = renamer.sanitize(artist).rstrip(". ")
    if rule == "existing" or not name:
        return root, True
    return os.path.join(root, name), False


def target_for(root, artist, title, year=None, rule=None):
    """Where the video goes (without its extension), by the folder rule under Settings, General."""
    from curator.video import musicvideos

    name = musicvideos.wanted_name({"artist": artist, "title": title, "year": year})
    if not name:
        raise AppError("A music video needs an artist and a title", 400)
    return os.path.join(folder_for(root, artist, rule)[0], name)


def plan(artist, title, year=None, root=None):
    """What a download with these names would do, for the window to show before it starts."""
    found = _roots()
    if not found:
        return {"ready": False, "roots": []}
    chosen = root if root in found else found[0]
    linked = link_artist(artist)
    folder, exists = folder_for(chosen, linked["artist"])
    return {"ready": True, "roots": found, "root": chosen, "artist": linked["artist"], "known": linked["known"],
            "folder": folder, "folder_exists": exists}


def start(video_id, artist, title, year=None, root=None):
    """Begin the download in the background. Returns the status; raises when one is already running."""
    if not _ID.match(str(video_id or "")):
        raise AppError("That is not a YouTube video", 400)
    roots = _roots()          # the local name hides roots() only inside this function
    if not roots:
        raise AppError("Add a folder with the media type Music videos under Settings, General, first", 400)
    chosen = os.path.realpath(root) if root else roots[0]
    if chosen not in [os.path.realpath(item) for item in roots]:
        raise AppError("That is not one of the Music videos folders", 400)
    artist = link_artist(artist)["artist"]
    text = str(year or "").strip()
    year = int(text) if text.isdigit() and 1900 < int(text) < 2200 else None
    target = target_for(chosen, artist, title, year)
    if any(os.path.exists(target + ext) for ext in (".mp4", ".mkv", ".webm")):
        raise AppError("A music video with that name is already there", 409)
    binary = _binary()
    with _lock:
        if _state["status"] == "running":
            raise AppError("A music video is already downloading", 409)
        _state.update({"status": "running", "message": "Downloading", "title": os.path.basename(target), "path": ""})
    threading.Thread(target=_run, args=(binary, video_id, target, chosen), name="mv-download", daemon=True).start()
    return status()


def _finish(state, message, path=""):
    with _lock:
        _state.update({"status": state, "message": message, "path": path})


def _run(binary, video_id, target, root):
    from curator.video import config, musicvideos, naming, trailers, work_track, writes

    label = os.path.basename(target)
    track = work_track.Tracked("mv-download", f"Downloading {label} from YouTube", 1)
    work = None
    try:
        folder = os.path.dirname(target)
        writes.ensure_dir(folder)
        writes.check(folder)
        work = tempfile.mkdtemp(prefix=".curator-mv-", dir=folder)
        command = [binary, "--no-playlist", "--no-progress", "--quiet", "--no-warnings",
                   "-f", trailers.format_selector(config.current().get("trailer_resolution", "1080p")),
                   "--merge-output-format", "mp4", "-o", os.path.join(work, "video.%(ext)s"),
                   f"https://www.youtube.com/watch?v={video_id}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise AppError(f"{label}: the download took longer than {DOWNLOAD_TIMEOUT // 60} minutes") from None
        if result.returncode != 0:
            raise AppError(trailers.ytdlp_failure(label, result, binary))
        files = [name for name in os.listdir(work) if naming.is_video(name)]
        if not files:
            raise AppError(f"{label}: yt-dlp did not produce a video file")
        final = target + os.path.splitext(files[0])[1].lower()
        if os.path.exists(final):
            raise AppError(f"{label}: a file with that name appeared meanwhile; nothing was overwritten")
        os.replace(os.path.join(work, files[0]), final)
        try:
            musicvideos.scan("incremental", [root])
        except Exception:
            logger.exception("the scan after the music video download failed")
        _finish("done", f"{label} was added.", final)
        track.finish("completed", f"Downloaded {os.path.basename(final)}", 1)
    except AppError as exc:
        _finish("failed", str(exc))
        track.finish("failed", str(exc))
    except Exception as exc:
        logger.exception("music video download failed")
        _finish("failed", f"{label}: {exc}")
        track.finish("failed", f"{label}: {exc}")
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
