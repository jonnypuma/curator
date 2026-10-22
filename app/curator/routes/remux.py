"""Dolby Vision conversion and one-file track selection."""
from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _uuid
from curator.video import remux

router = APIRouter()


class ItemBody(BaseModel):
    kind: str
    id: str
    remove_original: bool = False


class KeepBody(BaseModel):
    kind: str
    id: str
    tracks: list[int]


@router.get("/remux/tracks")
def remux_tracks(kind: str, id: str):
    return remux.tracks_for(kind, str(_uuid(id)))


@router.post("/remux/tracks")
def remux_keep(body: KeepBody):
    return remux.keep(body.kind, str(_uuid(body.id)), body.tracks)


@router.post("/remux/dovi")
def remux_dovi(body: ItemBody):
    return remux.start_profile8(body.kind, str(_uuid(body.id)), body.remove_original)


@router.get("/remux/status")
def remux_status():
    return remux.status()
