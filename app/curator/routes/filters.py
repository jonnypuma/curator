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
    playlist: bool = False
    action: str | None = None
    action_every: str = "off"
    action_hour: int = 3
    action_weekday: int = 0


@router.post("/filters")
def filters_save(body: SaveFilter):
    return saved_filters.save_filter(body.media, body.name, body.payload, body.tag, body.playlist,
                                     body.action, body.action_every, body.action_hour, body.action_weekday)


@router.post("/filters/{filter_id}/run")
def filters_run(filter_id: str):
    """Run the filter's action now for what it matches (it still waits for a running scan in the queue)."""
    from curator.video import filter_actions

    return {"result": filter_actions.run_now(str(_uuid(filter_id)))}


@router.delete("/filters/{filter_id}")
def filters_delete(filter_id: str):
    saved_filters.delete_filter(str(_uuid(filter_id)))
    return {"ok": True}
