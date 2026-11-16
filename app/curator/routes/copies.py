"""Upgrade comparison and duplicate groups for video. The artwork picker is in scrape.py."""

from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _uuid
from curator.video import copies
from resonance.errors import AppError

router = APIRouter()


@router.get("/copies/{kind}/{item_id}")
def list_copies(kind: str, item_id: str, arr: int = 1):
    """arr=0 answers from the database alone; the page then asks /arr for the Radarr or Sonarr lines."""
    if kind not in {"movie", "episode"}:
        raise AppError("Upgrades are shown for a movie or an episode", 400)
    return copies.copies_for(kind, _uuid(item_id), arr=bool(arr))


@router.get("/copies/{kind}/{item_id}/arr")
def copy_arr_labels(kind: str, item_id: str):
    """Which copy Radarr or Sonarr has, asked after the window opened."""
    if kind not in {"movie", "episode"}:
        raise AppError("Upgrades are shown for a movie or an episode", 400)
    return copies.copy_arr_labels(kind, _uuid(item_id))


class ReplaceBody(BaseModel):
    keep_id: str
    purge: bool = False


@router.post("/copies/{kind}/{item_id}/replace")
def replace_copy(kind: str, item_id: str, body: ReplaceBody):
    if kind not in {"movie", "episode"}:
        raise AppError("Upgrades are shown for a movie or an episode", 400)
    return copies.replace_copy(kind, _uuid(item_id), body.keep_id, body.purge)


def _duplicate_scope(media, focus):
    if media and media not in {"movies", "tv"}:
        raise AppError("Unknown library", 400)
    return (media or None), (_uuid(focus) if focus else None)


@router.get("/video-duplicates")
def video_duplicates(media: str = "", focus: str = "", arr: int = 1):
    """media and focus narrow the list to one library or to the copies of one item; arr=0 leaves out Radarr/Sonarr."""
    scope, item = _duplicate_scope(media, focus)
    return copies.duplicate_groups(scope, item, arr=bool(arr))


@router.get("/video-duplicates/arr")
def video_duplicate_arr_labels(media: str = "", focus: str = ""):
    scope, item = _duplicate_scope(media, focus)
    return copies.duplicate_arr_labels(scope, item)


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
