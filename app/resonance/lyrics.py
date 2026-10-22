import os

from resonance import db
from resonance.errors import AppError
from resonance.paths import atomic_write
from resonance.settings import load as load_settings
from resonance.sources import lrclib
from resonance.sources.client import host_down


def fetch_album(album_id, only_missing=False, on_progress=None):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    mode = load_settings()["lyrics_mode"]
    written = 0
    skipped = 0
    missing = 0
    unavailable = False
    total = len(tracks)
    for index, track in enumerate(tracks, start=1):
        if on_progress:
            on_progress(f"lyrics {index} of {total}: {track.get('title') or 'untitled'}")
        tags = track.get("tags") or {}
        if only_missing and track.get("lyrics_type") in {"lrc", "txt"}:
            skipped += 1
            continue
        if tags.get("_instrumental") is True or str(tags.get("_instrumental")).lower() == "true":
            skipped += 1
            continue
        result = lrclib.fetch(
            track.get("artist_name") or (artist["name"] if artist else ""),
            track.get("title"),
            track.get("album_name") or album["title"],
            track.get("duration_seconds"),
        )
        if not result or result.get("instrumental"):
            if not result and host_down("https://lrclib.net/"):
                unavailable = True
                break
            if result and result.get("instrumental"):
                tags = dict(tags)
                tags["_instrumental"] = True
                from psycopg.types.json import Json

                db.execute("UPDATE tracks SET tags = %s, lyrics_type = 'none' WHERE id = %s", (Json(tags), track["id"]))
                skipped += 1
            else:
                missing += 1
            continue
        stem = os.path.splitext(track["file_path"])[0]
        synced = (result.get("synced") or "").strip()
        plain = (result.get("plain") or "").strip()
        if mode == "lrc" and synced:
            atomic_write(stem + ".lrc", synced + "\n")
            lyrics_type = "lrc"
        elif plain or synced:
            atomic_write(stem + ".txt", (plain or synced) + "\n")
            lyrics_type = "txt"
        else:
            missing += 1
            continue
        db.execute("UPDATE tracks SET lyrics_type = %s WHERE id = %s", (lyrics_type, track["id"]))
        written += 1
    if unavailable:
        missing = max(0, len(tracks) - written - skipped)
    return {"written": written, "skipped_instrumental": skipped, "missing": missing, "unavailable": unavailable}
