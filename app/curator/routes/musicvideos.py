"""The Music videos tab: list, scan, .nfo, delete and remove, lookups, edits and thumbnails (/api/v1/musicvideos)."""
from fastapi import APIRouter
from pydantic import BaseModel

from resonance.errors import AppError

router = APIRouter()


class MusicVideoScan(BaseModel):
    mode: str = "incremental"
    roots: list[str] = []


class MusicVideoIds(BaseModel):
    ids: list[str] = []


@router.get("/musicvideos")
def musicvideos_list():
    from curator.video import musicvideos

    return {"items": musicvideos.list_items(), "scan": musicvideos.status()}


@router.get("/musicvideos/scan")
def musicvideos_scan_status():
    from curator.video import musicvideos

    return musicvideos.status()


@router.post("/musicvideos/scan")
def musicvideos_scan(body: MusicVideoScan):
    from curator.video import musicvideos

    if body.mode not in ("incremental", "full"):
        raise AppError("Choose an incremental or full scan", 400)
    if not musicvideos.start(body.mode, body.roots):
        raise AppError("A music video scan is already running", 409)
    return musicvideos.status()


@router.post("/musicvideos/nfo")
def musicvideos_nfo(body: MusicVideoIds):
    from curator.video import musicvideos

    return {"written": musicvideos.write_all(body.ids or None)}


class MusicVideoEdit(BaseModel):
    fields: dict = {}
    locked: bool | None = None


@router.post("/musicvideos/delete")
def musicvideos_delete(body: MusicVideoIds):
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return musicvideos.delete([str(_uuid(item)) for item in body.ids])


@router.post("/musicvideos/remove")
def musicvideos_remove(body: MusicVideoIds):
    """Remove from the library only; the files stay."""
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return musicvideos.forget([str(_uuid(item)) for item in body.ids])


@router.post("/musicvideos/lookup")
def musicvideos_lookup():
    from curator.video import musicvideos

    if not musicvideos.start_fill():
        raise AppError("A music video job is already running", 409)
    return musicvideos.status()


@router.post("/musicvideos/{item_id}")
def musicvideos_edit(item_id: str, body: MusicVideoEdit):
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return musicvideos.update(str(_uuid(item_id)), body.fields, body.locked)


@router.post("/musicvideos/{item_id}/thumb")
def musicvideos_make_thumb(item_id: str):
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return {"path": musicvideos.make_thumb(str(_uuid(item_id)))}


@router.get("/musicvideos/{item_id}/thumb")
def musicvideos_thumb(item_id: str):
    from fastapi.responses import FileResponse

    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return FileResponse(musicvideos.thumb_file(str(_uuid(item_id))))
