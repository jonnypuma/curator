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

    from curator.video import mv_download

    # roots tells the page whether Add from YouTube has anywhere to save to.
    return {"items": musicvideos.list_items(), "scan": musicvideos.status(), "roots": mv_download.roots()}


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


class MusicVideoYoutube(BaseModel):
    id: str
    artist: str = ""
    title: str = ""
    year: str | int | None = None
    root: str | None = None


@router.get("/musicvideos/youtube/plan")
def musicvideos_youtube_plan(artist: str = "", title: str = "", year: str = "", root: str = ""):
    """Which artist the typed name is linked to and which folder the download would be saved in."""
    from curator.video import mv_download

    return mv_download.plan(artist, title, year, root or None)


@router.get("/musicvideos/artists")
def musicvideos_artists():
    """The artist names the library already has, for the artist box of Add from YouTube."""
    from curator.video import mv_download

    return {"artists": mv_download.known_artists()[:3000]}


@router.get("/musicvideos/youtube")
def musicvideos_youtube_search(q: str = ""):
    """Search YouTube for a music video to add."""
    from curator.video import mv_download

    return {"results": mv_download.search(q)}


@router.get("/musicvideos/youtube/status")
def musicvideos_youtube_status():
    from curator.video import mv_download

    return mv_download.status()


@router.post("/musicvideos/youtube")
def musicvideos_youtube_download(body: MusicVideoYoutube):
    """Download the picked video into the Music videos folder and add it to the library."""
    from curator.video import mv_download

    return mv_download.start(body.id, body.artist, body.title, body.year, body.root)


class MusicVideoLock(BaseModel):
    ids: list[str] = []
    locked: bool = True


@router.post("/musicvideos/lock")
def musicvideos_lock(body: MusicVideoLock):
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    return musicvideos.set_locked([str(_uuid(item)) for item in body.ids], body.locked)


class MusicVideoRename(BaseModel):
    ids: list[str] = []
    preview: bool = False


@router.post("/musicvideos/rename")
def musicvideos_rename(body: MusicVideoRename):
    """Rename the files to "Artist - Title (Year)". preview only says what would change."""
    from curator.routes.scrape import _uuid
    from curator.video import musicvideos

    ids = [str(_uuid(item)) for item in body.ids]
    if body.preview:
        return {"plan": musicvideos.rename_plan(ids)}
    return musicvideos.rename(ids)


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
