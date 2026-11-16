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


def download_summary(written, albums, counts):
    """The closing line of a lyrics download, shown in the Jobs panel and as the notice on the page."""
    noun = "album" if albums == 1 else "albums"
    parts = [f"Lyrics: saved {written} for {albums} {noun}"]
    if counts.get("missing"):
        parts.append(f"{counts['missing']} track{'s' if counts['missing'] != 1 else ''} not found on LRCLIB")
    if counts.get("complete"):
        parts.append(f"{counts['complete']} {'album' if counts['complete'] == 1 else 'albums'} already had lyrics")
    if counts.get("failed"):
        parts.append(f"{counts['failed']} failed" + (" (LRCLIB could not be reached)" if counts.get("unreachable") else ""))
    return ", ".join(parts)


def start_download(album_ids=None, artist_ids=None):
    """Queue a lyrics-only search and download for albums (and every album of the artists). Tracks that already have
    lyrics are skipped. Returns (job, started); started is False when a lyrics download is already running."""
    import threading

    from resonance import artwork, jobs, library

    ids = []
    seen = set()

    def add(value):
        album_id = str(library.require_uuid(value))
        if album_id not in seen:
            seen.add(album_id)
            ids.append(album_id)

    for item in album_ids or []:
        add(item)
    artists = [str(library.require_uuid(item)) for item in (artist_ids or [])]
    if artists:
        for row in db.fetchall(
            "SELECT id FROM albums WHERE artist_id = ANY(%s::uuid[]) ORDER BY title", (db.uuid_array(artists),)
        ):
            add(row["id"])
    if not ids:
        raise AppError("Select at least one album or artist")
    running = db.fetchone(
        "SELECT * FROM work_jobs WHERE kind = 'missing-lyrics' AND status = 'running' ORDER BY started_at DESC LIMIT 1"
    )
    if running:
        return running, False
    row = jobs.begin_work("missing-lyrics", f"Searching and downloading lyrics for {len(ids)} albums", len(ids))

    def run():
        labels = artwork._labels_for(ids, "albums")
        order = [labels.get(album_id, "Album") for album_id in ids]
        done = []
        written = 0
        counts = {"missing": 0, "complete": 0, "failed": 0, "unreachable": False}
        try:
            for index, album_id in enumerate(ids, start=1):
                label = order[index - 1]
                queued = order[index:]
                working = f"Working — {label} ({index} of {len(ids)})"
                jobs.touch_work(row["id"], index - 1, working, artwork._queue_log(working, done, queued))
                try:
                    result = fetch_album(album_id, only_missing=True)
                    written += int(result.get("written") or 0)
                    counts["missing"] += int(result.get("missing") or 0)
                    if result.get("unavailable"):
                        counts["unreachable"] = True
                        counts["failed"] += 1
                        done.insert(0, f"Failed — {label} — LRCLIB is not reachable")
                    elif result.get("written"):
                        done.insert(0, f"Saved — {label} — {result['written']} lyrics, {result.get('missing') or 0} not found")
                    elif result.get("missing"):
                        done.insert(0, f"No lyrics — {label} — {result['missing']} not found")
                    else:
                        counts["complete"] += 1
                        done.insert(0, f"Already complete — {label}")
                except Exception as exc:
                    counts["failed"] += 1
                    done.insert(0, f"Failed — {label} — {exc}")
                jobs.touch_work(row["id"], index, f"Finished {index} of {len(ids)}", artwork._queue_log("", done, queued))
            jobs.finish_work(
                row["id"], "completed", download_summary(written, len(ids), counts), len(ids),
                artwork._queue_log("", done, []),
            )
        except Exception as exc:
            jobs.finish_work(row["id"], "failed", str(exc)[:300], log=artwork._queue_log("", done, []))

    threading.Thread(target=run, name="missing-lyrics", daemon=True).start()
    return row, True
