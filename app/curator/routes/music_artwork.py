"""Music artwork lookup, files, and uploads."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile

from curator.routes.music_http import JsonBody, body_dict, cleaned, error, image_response, run
from resonance import artwork, db, jobs, library, settings
from resonance.errors import AppError

router = APIRouter()


def _tracked_work(kind, message, action):
    job = jobs.begin_work(kind, message, 1)
    try:
        payload = action()
    except Exception as exc:
        jobs.finish_work(job["id"], "failed", str(exc)[:300], log=str(exc)[:1000])
        raise
    warnings = payload.get("warnings") if isinstance(payload, dict) else []
    log = "\n".join(str(item) for item in (warnings or []))
    note = message if not warnings else f"{message}. {len(warnings)} notes"
    jobs.finish_work(job["id"], "completed", note, 1, log)
    return payload


async def _read_upload(upload: UploadFile, asset_type: str | None):
    if upload is None or not upload.filename:
        raise AppError("Choose an image file", 400)
    data = await upload.read(artwork.MAX_UPLOAD_BYTES + 1)
    return data, asset_type


@router.post("/api/artwork/deploy-missing")
async def queue_missing_artwork(body: dict | None = JsonBody):
    ids = body_dict(body).get("album_ids") or []

    def work():
        job, started = artwork.start_missing(ids)
        return cleaned({**job, "started": started})

    return await run(work)


@router.post("/api/artwork/deploy-missing-artists")
async def queue_missing_artist_artwork(body: dict | None = JsonBody):
    ids = body_dict(body).get("artist_ids") or []

    def work():
        job, started = artwork.start_missing_artists(ids)
        return cleaned({**job, "started": started})

    return await run(work)


@router.post("/api/artwork/{art_id}/select")
async def select_artwork(art_id: str):
    def work():
        library.require_uuid(art_id)
        return cleaned({"artwork": artwork.select(art_id)})

    return await run(work)


@router.delete("/api/artwork/{art_id}")
async def delete_artwork(art_id: str):
    def work():
        library.require_uuid(art_id)
        return cleaned(artwork.remove(art_id))

    return await run(work)


@router.get("/api/artwork/additional")
async def additional_artwork_info():
    return await run(artwork.additional_stats)


@router.post("/api/artwork/additional/purge")
async def purge_additional_artwork():
    return await run(artwork.purge_additional)


@router.get("/api/artwork/{art_id}/preview")
async def preview_artwork(art_id: str, w: int = Query(0)):
    def work():
        library.require_uuid(art_id)
        return artwork.preview_path(art_id)

    path = await run(work)
    return image_response(path, w, max_age=3600)


@router.get("/api/artists/{artist_id}/fanart/{index}")
async def artist_fanart_file(artist_id: str, index: int, w: int = Query(0)):
    def work():
        library.require_uuid(artist_id)
        return artwork.fanart_file(artist_id, index)

    path = await run(work)
    if not path:
        return error("No artwork", 404)
    return image_response(path, w)


@router.get("/api/artists/{artist_id}/art/{asset_type}")
async def artist_art(artist_id: str, asset_type: str, w: int = Query(0)):
    def work():
        library.require_uuid(artist_id)
        return artwork.artist_image(artist_id, asset_type)

    path = await run(work)
    if not path:
        return error("No artwork", 404)
    return image_response(path, w)


@router.post("/api/artists/{artist_id}/artwork/deploy-missing")
async def deploy_missing_artist_artwork(artist_id: str):
    def work():
        library.require_uuid(artist_id)
        job, started = artwork.start_missing_artist(artist_id)
        return cleaned({**job, "started": started})

    return await run(work)


@router.get("/api/artists/{artist_id}/artwork")
async def get_artist_artwork(artist_id: str, harvest: str = Query(""), q: str = Query("")):
    def work():
        library.require_uuid(artist_id)
        if harvest == "1":
            payload = _tracked_work(
                "artwork",
                "Looking up artist artwork",
                lambda: artwork.harvest_artist(artist_id, respect_enabled=False, query=q),
            )
        else:
            cfg = settings.load()
            row = db.fetchone("SELECT name FROM artists WHERE id = %s", (artist_id,))
            payload = {
                "album": [],
                "artist": artwork._annotate(artwork.list_for_artist(artist_id), cfg),
                "warnings": [],
                "query": (row or {}).get("name") or "",
            }
        payload["undo"] = artwork.undo_status("artist", artist_id)
        return cleaned(payload)

    return await run(work)


@router.post("/api/artists/{artist_id}/artwork/undo")
async def undo_artist_artwork(artist_id: str):
    def work():
        library.require_uuid(artist_id)
        return cleaned(artwork.restore_artwork("artist", artist_id))

    return await run(work)


@router.post("/api/artists/{artist_id}/artwork/upload")
async def upload_artist_artwork(artist_id: str, file: UploadFile = File(...), asset_type: str | None = Form(None)):
    data, kind = await _read_upload(file, asset_type)

    def work():
        library.require_uuid(artist_id)
        row = artwork.store_upload(kind, data, artist_id=artist_id)
        return cleaned({"artwork": row})

    return await run(work)


@router.get("/api/albums/{album_id}/cover")
async def album_cover(album_id: str, w: int = Query(0)):
    def work():
        library.require_uuid(album_id)
        return artwork.cover_path(album_id)

    path = await run(work)
    if not path:
        return error("No cover", 404)
    return image_response(path, w)


@router.get("/api/albums/{album_id}/art/{asset_type}")
async def album_art(album_id: str, asset_type: str, w: int = Query(0)):
    def work():
        library.require_uuid(album_id)
        return artwork.album_image(album_id, asset_type)

    path = await run(work)
    if not path:
        return error("No artwork", 404)
    return image_response(path, w)


@router.get("/api/albums/{album_id}/artwork")
async def get_artwork(album_id: str, harvest: str = Query(""), scope: str = Query("album"), q: str = Query("")):
    def work():
        library.require_uuid(album_id)
        if harvest == "1":
            chosen = scope if scope in {"album", "artist", "both"} else "album"
            payload = _tracked_work(
                "artwork",
                "Looking up artwork",
                lambda: artwork.harvest(album_id, scope=chosen, respect_enabled=False, query=q),
            )
        else:
            album = library.album_detail(album_id)
            cfg = settings.load()
            payload = {
                "album": artwork._annotate(artwork.list_for_album(album_id), cfg),
                "artist": artwork._annotate(artwork.list_for_artist(album["artist"]["id"]), cfg) if album.get("artist") else [],
                "warnings": [],
                "query": artwork.artwork_query(
                    (album.get("artist") or {}).get("name"),
                    (album.get("album") or {}).get("title"),
                ),
            }
        payload["undo"] = artwork.undo_status("album", album_id)
        return cleaned(payload)

    return await run(work)


@router.post("/api/albums/{album_id}/artwork/undo")
async def undo_album_artwork(album_id: str):
    def work():
        library.require_uuid(album_id)
        return cleaned(artwork.restore_artwork("album", album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/artwork/deploy-missing")
async def deploy_missing_artwork(album_id: str):
    def work():
        library.require_uuid(album_id)
        payload = artwork.deploy_missing(album_id)
        detail = library.album_detail(album_id)
        return cleaned({**payload, **detail})

    return await run(work)


@router.post("/api/albums/{album_id}/artwork/upload")
async def upload_album_artwork(album_id: str, file: UploadFile = File(...), asset_type: str | None = Form(None)):
    data, kind = await _read_upload(file, asset_type)

    def work():
        library.require_uuid(album_id)
        row = artwork.store_upload(kind, data, album_id=album_id)
        return cleaned({"artwork": row})

    return await run(work)
