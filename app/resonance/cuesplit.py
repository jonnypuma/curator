import os
import re
import shutil
import subprocess

from resonance import db
from resonance.errors import AppError
from resonance.paths import assert_library_writable

_FILE = re.compile(r'^FILE\s+"([^"]+)"', re.IGNORECASE)
_TRACK = re.compile(r"^TRACK\s+(\d+)", re.IGNORECASE)
_TITLE = re.compile(r'^TITLE\s+"([^"]*)"', re.IGNORECASE)
_PERFORMER = re.compile(r'^PERFORMER\s+"([^"]*)"', re.IGNORECASE)
_INDEX = re.compile(r"^INDEX\s+01\s+(\d+):(\d+):(\d+)", re.IGNORECASE)


def parse_cue(text):
    tracks = []
    current = None
    for raw in str(text or "").splitlines():
        line = raw.strip()
        file_match = _FILE.match(line)
        if file_match and current is None:
            continue
        track_match = _TRACK.match(line)
        if track_match:
            current = {"number": int(track_match.group(1)), "title": "", "performer": "", "index_seconds": None}
            tracks.append(current)
            continue
        if current is None:
            continue
        title_match = _TITLE.match(line)
        if title_match and not current["title"]:
            current["title"] = title_match.group(1)
            continue
        performer_match = _PERFORMER.match(line)
        if performer_match and not current["performer"]:
            current["performer"] = performer_match.group(1)
            continue
        index_match = _INDEX.match(line)
        if index_match and current["index_seconds"] is None:
            minutes, seconds, frames = (int(part) for part in index_match.groups())
            current["index_seconds"] = minutes * 60 + seconds + frames / 75
    return [track for track in tracks if track["number"]]


def split_album(album_id, remove_image=False):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    assert_library_writable(album["path"])
    image, cue_path, tracks = _locate(album["path"])
    if not image or not cue_path:
        raise AppError("This folder does not have a single FLAC or WAV image and a cue sheet")
    if not shutil.which("shnsplit"):
        raise AppError("shnsplit is not installed in this image")
    temp = os.path.join(album["path"], ".resonance-split")
    if os.path.isdir(temp):
        shutil.rmtree(temp, ignore_errors=True)
    os.makedirs(temp, exist_ok=True)
    written = []
    try:
        completed = subprocess.run(
            ["shnsplit", "-O", "always", "-f", cue_path, "-o", "flac", "-d", temp, "-t", "%n", image],
            capture_output=True,
            text=True,
            check=False,
        )
        pieces = sorted(
            (
                os.path.join(temp, name)
                for name in os.listdir(temp)
                if name.lower().endswith(".flac")
            ),
            key=_piece_order,
        )
        if completed.returncode or not pieces:
            detail = (completed.stderr or completed.stdout or "shnsplit failed").strip()
            raise AppError(detail[-400:] or "shnsplit failed")
        if tracks and len(pieces) != len(tracks):
            raise AppError(f"shnsplit wrote {len(pieces)} files for {len(tracks)} cue tracks")
        cue_tracks = tracks or [{"number": index, "title": "", "performer": ""} for index in range(1, len(pieces) + 1)]
        for index, piece in enumerate(pieces):
            track = cue_tracks[index] if index < len(cue_tracks) else {"number": index + 1, "title": "", "performer": ""}
            title = track.get("title") or f"Track {track.get('number') or index + 1}"
            number = int(track.get("number") or index + 1)
            dest = os.path.join(album["path"], f"{number:02d} - {_safe(title)}.flac")
            if os.path.exists(dest):
                raise AppError(f"{os.path.basename(dest)} already exists")
            os.replace(piece, dest)
            written.append(dest)
            _tag(dest, title, track.get("performer") or "", number)
    except Exception:
        for path in written:
            if os.path.isfile(path):
                os.remove(path)
        shutil.rmtree(temp, ignore_errors=True)
        raise
    shutil.rmtree(temp, ignore_errors=True)
    from resonance.scanner import _scan_album
    from resonance.settings import load as load_settings

    _scan_album(album["artist_id"], os.path.dirname(album["path"]), album["path"], load_settings(), "incremental")
    refreshed = db.fetchone("SELECT musicbrainz_release_id FROM albums WHERE id = %s", (album_id,))
    if refreshed and refreshed.get("musicbrainz_release_id"):
        from resonance import match

        proposal = match.build_proposal(album_id, refreshed["musicbrainz_release_id"])
        match.apply(album_id, proposal["proposal"], notify=False)
    from resonance import lyrics

    try:
        lyrics.fetch_album(album_id)
    except Exception:
        pass
    if remove_image:
        for path in (image, cue_path):
            if os.path.isfile(path):
                os.remove(path)
        _scan_album(album["artist_id"], os.path.dirname(album["path"]), album["path"], load_settings(), "incremental")
    return {"tracks": len(written), "removed_image": bool(remove_image)}


def _locate(folder):
    try:
        entries = os.listdir(folder)
    except OSError as exc:
        raise AppError(f"Cannot read the album folder: {exc}") from exc
    cues = [os.path.join(folder, name) for name in entries if name.lower().endswith(".cue")]
    audio = [
        os.path.join(folder, name)
        for name in entries
        if os.path.isfile(os.path.join(folder, name)) and name.lower().endswith((".flac", ".wav"))
    ]
    if len(cues) != 1 or len(audio) != 1:
        return "", "", []
    try:
        with open(cues[0], encoding="utf-8", errors="replace") as handle:
            parsed = parse_cue(handle.read())
    except OSError as exc:
        raise AppError(f"Cannot read the cue sheet: {exc}") from exc
    return audio[0], cues[0], parsed


def _tag(path, title, artist, number):
    from resonance import tags

    payload = {"title": title, "tracknumber": str(number)}
    if artist:
        payload["artist"] = artist
    tags.write_easy(path, payload)


def _piece_order(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    digits = "".join(char for char in stem if char.isdigit())
    return int(digits) if digits else stem


def _safe(name):
    cleaned = "".join("-" if char in '\\/:*?"<>|' else char for char in str(name or "")).strip()
    return cleaned[:120] or "track"
