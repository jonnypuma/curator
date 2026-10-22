"""Rename, tags, ReplayGain, duplicates, Lidarr, and artist merge."""

from __future__ import annotations

from fastapi import APIRouter, Query

from curator.routes.music_http import JsonBody, body_dict, cleaned, file_response, run
from resonance import library, lyrics, rename, settings
from resonance.paths import assert_readable

router = APIRouter()


def _move_folders(payload, artist_id):
    move_folders = payload.get("move_folders")
    if move_folders is None:
        move_folders = payload.get("keep_folders") is not True
    return bool(move_folders)


@router.post("/api/rename/example")
async def rename_example(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        cfg = settings.load()
        folder = payload.get("rename_folder_pattern") or cfg.get("rename_folder_pattern") or ""
        file = payload.get("rename_file_pattern") or cfg.get("rename_file_pattern") or ""
        return cleaned(rename.example(folder, file))

    return await run(work)


@router.post("/api/rename/preview")
async def rename_preview(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: cleaned(rename.preview(payload.get("album_ids") or [], payload, settings.load())))


@router.post("/api/tracks/save")
async def save_tracks(body: dict | None = JsonBody):
    tracks = body_dict(body).get("tracks") or []
    return await run(lambda: cleaned(library.save_track_edits(tracks)))


@router.post("/api/tracks/bulk")
async def bulk_tracks(body: dict | None = JsonBody):
    payload = body_dict(body)
    raw_fields = payload.get("fields")
    fields = raw_fields if isinstance(raw_fields, dict) else payload
    return await run(lambda: cleaned(library.update_tracks(payload.get("track_ids") or [], fields, payload.get("numbers"))))


@router.put("/api/tracks/{track_id}")
async def put_track(track_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(track_id)
        return cleaned(library.update_track(track_id, payload))

    return await run(work)


@router.get("/api/tracks/{track_id}/audio")
async def track_audio(track_id: str):
    def work():
        library.require_uuid(track_id)
        track = library.get_track(track_id)
        return assert_readable(track["file_path"])

    return file_response(await run(work))


@router.post("/api/albums/group-compilation")
async def group_albums(body: dict | None = JsonBody):
    ids = body_dict(body).get("album_ids") or []
    return await run(lambda: cleaned(library.group_compilation(ids)))


@router.post("/api/albums/{album_id}/profile")
async def save_album_profile(album_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(album_id)
        return cleaned(library.save_album_profile(album_id, payload))

    return await run(work)


@router.post("/api/albums/{album_id}/compilation")
async def album_compilation(album_id: str, body: dict | None = JsonBody):
    enabled = body_dict(body).get("enabled", True)

    def work():
        library.require_uuid(album_id)
        return cleaned(library.treat_compilation(album_id, enabled))

    return await run(work)


@router.post("/api/albums/{album_id}/replaygain")
async def album_gain(album_id: str):
    from resonance import gain

    def work():
        library.require_uuid(album_id)
        return cleaned({"lines": gain.album_lines(album_id)})

    return await run(work)


@router.post("/api/albums/{album_id}/audit")
async def album_audit(album_id: str):
    from resonance import audit

    def work():
        library.require_uuid(album_id)
        return cleaned(audit.album(album_id))

    return await run(work)


@router.get("/api/albums/{album_id}/upgrade")
async def album_upgrade(album_id: str):
    from resonance import upgrade

    def work():
        library.require_uuid(album_id)
        return cleaned(upgrade.compare(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/upgrade")
async def replace_album(album_id: str, body: dict | None = JsonBody):
    from resonance import upgrade

    payload = body_dict(body)

    def work():
        library.require_uuid(album_id)
        if payload.get("source_id"):
            library.require_uuid(payload["source_id"])
        return cleaned(upgrade.replace(album_id, payload.get("source_id"), bool(payload.get("purge"))))

    return await run(work)


@router.post("/api/albums/{album_id}/delete")
async def delete_album_files(album_id: str):
    from resonance import upgrade

    def work():
        library.require_uuid(album_id)
        return cleaned(upgrade.discard(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/gaps")
async def album_gaps(album_id: str):
    from resonance import gaps

    def work():
        library.require_uuid(album_id)
        return cleaned(gaps.refresh(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/split")
async def split_album(album_id: str, body: dict | None = JsonBody):
    from resonance import cuesplit

    remove_image = bool(body_dict(body).get("remove_image"))

    def work():
        library.require_uuid(album_id)
        return cleaned(cuesplit.split_album(album_id, remove_image))

    return await run(work)


@router.post("/api/albums/{album_id}/lyrics")
async def album_lyrics(album_id: str):
    def work():
        library.require_uuid(album_id)
        return lyrics.fetch_album(album_id)

    return await run(work)


@router.get("/api/duplicates")
async def list_duplicates(focus: str | None = None):
    from resonance import duplicates

    def work():
        if focus:
            library.require_uuid(focus)
        return cleaned(duplicates.groups(focus))

    return await run(work)


@router.post("/api/duplicates/scan")
async def scan_duplicates():
    from resonance import duplicates

    def work():
        job, started = duplicates.start_scan()
        return cleaned({"job": job, "started": started})

    return await run(work)


@router.post("/api/duplicates/dismiss")
async def dismiss_duplicate(body: dict | None = JsonBody):
    from resonance import duplicates

    payload = body_dict(body)
    return await run(lambda: cleaned(duplicates.dismiss(payload.get("left_id"), payload.get("right_id"), payload.get("pairs"))))


@router.post("/api/duplicates/restore")
async def restore_duplicate(body: dict | None = JsonBody):
    from resonance import duplicates

    payload = body_dict(body)
    return await run(lambda: cleaned(duplicates.restore(payload.get("pairs"))))


@router.get("/api/artists/{artist_id}/discography")
async def artist_discography(artist_id: str):
    from resonance import discography

    def work():
        library.require_uuid(artist_id)
        return cleaned(discography.cached(artist_id))

    return await run(work)


@router.post("/api/artists/{artist_id}/discography")
async def refresh_discography(artist_id: str):
    from resonance import discography

    def work():
        library.require_uuid(artist_id)
        return cleaned(discography.refresh(artist_id))

    return await run(work)


@router.post("/api/artists/{artist_id}/lidarr")
async def lidarr_search_release(artist_id: str, body: dict | None = JsonBody):
    from resonance import lidarr

    payload = body_dict(body)

    def work():
        library.require_uuid(artist_id)
        return cleaned(lidarr.queue_releases(artist_id, [payload]))

    return await run(work)


@router.post("/api/artists/{artist_id}/lidarr/missing")
async def lidarr_search_missing(artist_id: str):
    from resonance import lidarr

    def work():
        library.require_uuid(artist_id)
        return cleaned(lidarr.queue_missing_studio(artist_id))

    return await run(work)


@router.get("/api/artists/{artist_id}/candidates")
async def artist_candidates(artist_id: str, q: str = Query("")):
    def work():
        library.require_uuid(artist_id)
        return {"artists": library.artist_candidates(artist_id, q or "")}

    return await run(work)


@router.post("/api/artists/{artist_id}/merge-preview")
async def preview_artist_merge(artist_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(artist_id)
        return cleaned(library.merge_preview(
            payload.get("keep_id") or artist_id,
            payload.get("drop_id"),
            move_folders=_move_folders(payload, artist_id),
            remove_empty=payload.get("remove_empty") is True,
        ))

    return await run(work)


@router.post("/api/artists/{artist_id}/merge")
async def merge_artist(artist_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)
    choices = payload.get("folder_choices") or {}
    if not isinstance(choices, dict):
        choices = {}

    def work():
        library.require_uuid(artist_id)
        return cleaned(library.merge_artists(
            payload.get("keep_id") or artist_id,
            payload.get("drop_id"),
            move_folders=_move_folders(payload, artist_id),
            remove_empty=payload.get("remove_empty") is True,
            folder_choices=choices,
        ))

    return await run(work)


def _lrc_path(track_id):
    import os
    from resonance.errors import AppError

    library.require_uuid(track_id)
    track = library.get_track(track_id)
    if not track:
        raise AppError("Track not found", 404)
    return os.path.splitext(track["file_path"])[0] + ".lrc"


@router.get("/api/tracks/{track_id}/lyrics")
async def get_track_lyrics(track_id: str):
    import os
    from resonance.errors import AppError
    from curator.video import sync_marks

    def work():
        lrc_path = _lrc_path(track_id)
        if not os.path.isfile(lrc_path):
            raise AppError("No .lrc file for this track", 404)
        with open(lrc_path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return cleaned({"lyrics": content, "path": lrc_path,
                        "has_backup": os.path.isfile(lrc_path + ".sync-backup"),
                        "synced": sync_marks.status(lrc_path)})

    return await run(work)


@router.put("/api/tracks/{track_id}/lyrics")
async def put_track_lyrics(track_id: str, body: dict | None = JsonBody):
    import os
    import shutil
    from resonance.paths import atomic_write

    payload = body_dict(body)

    def work():
        lrc_path = _lrc_path(track_id)
        content = payload.get("lyrics", "")
        # One undo level: the file as it was before this save (kept until the next save).
        if os.path.isfile(lrc_path):
            with open(lrc_path, encoding="utf-8", errors="replace") as fh:
                same = fh.read() == (content if content.endswith("\n") else content + "\n")
            if not same:
                shutil.copy2(lrc_path, lrc_path + ".sync-backup")
        atomic_write(lrc_path, content if content.endswith("\n") else content + "\n")
        return cleaned({"ok": True, "has_backup": os.path.isfile(lrc_path + ".sync-backup")})

    return await run(work)


@router.post("/api/tracks/{track_id}/lyrics/revert")
async def revert_track_lyrics(track_id: str):
    """Put back the .lrc as it was before the last save."""
    import os
    import shutil
    from resonance.errors import AppError

    def work():
        lrc_path = _lrc_path(track_id)
        backup = lrc_path + ".sync-backup"
        if not os.path.isfile(backup):
            raise AppError("No backup is available for these lyrics", 404)
        shutil.copy2(backup, lrc_path)
        os.unlink(backup)
        with open(lrc_path, encoding="utf-8", errors="replace") as fh:
            return cleaned({"lyrics": fh.read(), "has_backup": False, "synced": None})

    return await run(work)


@router.post("/api/tracks/{track_id}/lyrics/synced")
async def mark_track_lyrics_synced(track_id: str):
    """Sync OK: remember that these lyrics were checked against the audio."""
    import os
    from resonance.errors import AppError
    from curator.video import sync_marks

    def work():
        lrc_path = _lrc_path(track_id)
        if not os.path.isfile(lrc_path):
            raise AppError("No .lrc file for this track", 404)
        sync_marks.mark(lrc_path)
        return cleaned({"synced": sync_marks.status(lrc_path)})

    return await run(work)
