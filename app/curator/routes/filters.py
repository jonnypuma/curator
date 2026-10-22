"""Saved library filters."""
from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _uuid
from curator.video import saved_filters

router = APIRouter()


@router.get("/filters")
def filters_list(media: str):
    return {"media": media, "filters": saved_filters.list_filters(media)}


class SaveFilter(BaseModel):
    media: str
    name: str
    payload: dict = {}
    tag: str | None = None


@router.post("/filters")
def filters_save(body: SaveFilter):
    return saved_filters.save_filter(body.media, body.name, body.payload, body.tag)


@router.delete("/filters/{filter_id}")
def filters_delete(filter_id: str):
    saved_filters.delete_filter(str(_uuid(filter_id)))
    return {"ok": True}
