"""Upgrade comparison and duplicate groups for video. The artwork picker is in scrape.py."""

from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _uuid
from curator.video import copies
from resonance.errors import AppError

router = APIRouter()


@router.get("/copies/{kind}/{item_id}")
def list_copies(kind: str, item_id: str):
    if kind not in {"movie", "episode"}:
        raise AppError("Upgrades are shown for a movie or an episode", 400)
    return copies.copies_for(kind, _uuid(item_id))


class ReplaceBody(BaseModel):
    keep_id: str
    purge: bool = False


@router.post("/copies/{kind}/{item_id}/replace")
def replace_copy(kind: str, item_id: str, body: ReplaceBody):
    if kind not in {"movie", "episode"}:
        raise AppError("Upgrades are shown for a movie or an episode", 400)
    return copies.replace_copy(kind, _uuid(item_id), body.keep_id, body.purge)


@router.get("/video-duplicates")
def video_duplicates():
    return copies.duplicate_groups()


class DismissBody(BaseModel):
    kind: str
    left_id: str
    right_id: str


@router.post("/video-duplicates/dismiss")
def dismiss_video_duplicate(body: DismissBody):
    return copies.dismiss_pair(body.kind, _uuid(body.left_id), _uuid(body.right_id))


@router.post("/video-duplicates/restore")
def restore_video_duplicate(body: DismissBody):
    return copies.restore_pair(body.kind, _uuid(body.left_id), _uuid(body.right_id))
