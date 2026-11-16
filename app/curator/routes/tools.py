"""Library tools: bulk duplicate cleanup, activity history, integrity schedule, disk alert and the upgrade wishlist."""
from fastapi import APIRouter
from pydantic import BaseModel

from resonance.errors import AppError

router = APIRouter()


class CleanupPreview(BaseModel):
    media: list[str] = ["movies", "tv", "music"]
    include_upgrades: bool = False


class CleanupRun(BaseModel):
    token: str
    skip_groups: list[str] = []


@router.get("/cleanup")
def cleanup_status():
    from curator import bulk_cleanup

    return bulk_cleanup.status()


@router.post("/cleanup/preview")
def cleanup_preview(body: CleanupPreview):
    from curator import bulk_cleanup

    if not bulk_cleanup.start_preview(body.media, body.include_upgrades):
        raise AppError("A cleanup is already running", 409)
    return bulk_cleanup.status()


@router.post("/cleanup/run")
def cleanup_run(body: CleanupRun):
    from curator import bulk_cleanup

    bulk_cleanup.start_run(body.token, body.skip_groups)
    return bulk_cleanup.status()


@router.get("/history")
def activity_history(search: str = "", action: str = "", limit: int = 200, offset: int = 0):
    from resonance import history

    return history.entries(search, action, limit, offset)


class WishlistSearch(BaseModel):
    items: list[dict] = []


@router.get("/wishlist")
def wishlist_list():
    from curator import wishlist

    return wishlist.listing()


@router.post("/wishlist/search")
def wishlist_search(body: WishlistSearch):
    from curator import wishlist

    return wishlist.search(body.items)


class ShowPair(BaseModel):
    left_id: str
    right_id: str


@router.get("/twin-shows/{show_id}")
def twin_shows(show_id: str):
    from curator.routes.scrape import _uuid
    from curator.video import copies

    return {"shows": copies.twin_cards(str(_uuid(show_id)))}


@router.post("/twin-shows/dismiss")
def twin_shows_dismiss(body: ShowPair):
    from curator.routes.scrape import _uuid
    from curator.video import copies

    return copies.dismiss_shows(str(_uuid(body.left_id)), str(_uuid(body.right_id)))


@router.post("/twin-shows/restore")
def twin_shows_restore(body: ShowPair):
    from curator.routes.scrape import _uuid
    from curator.video import copies

    return copies.restore_shows(str(_uuid(body.left_id)), str(_uuid(body.right_id)))


@router.get("/twin-artists/{artist_id}")
def twin_artists(artist_id: str):
    from resonance import library

    return {"artists": library.artist_twin_cards(artist_id)}


@router.post("/twin-artists/dismiss")
def twin_artists_dismiss(body: ShowPair):
    from resonance import library

    return {"artists": library.dismiss_artist_twins(body.left_id, body.right_id)}


@router.post("/twin-artists/restore")
def twin_artists_restore(body: ShowPair):
    from resonance import library

    return {"artists": library.restore_artist_twins(body.left_id, body.right_id)}


@router.get("/journeys")
def journeys(active: bool = False, limit: int = 100, stamp: str = ""):
    """Each imported item's path from the webhook to the player library updates, newest first.

    stamp is the one the last answer carried: when nothing has moved since, the answer is only {"unchanged": true}, so
    the open window's 3-second refresh does not resend the whole list."""
    from curator import journey

    now = journey.stamp()
    if stamp and stamp == now:
        return {"unchanged": True, "stamp": now}
    return {"journeys": journey.recent(active_only=active, limit=max(1, min(int(limit), 300))), "stamp": now}


@router.post("/journeys/clear")
def journeys_clear():
    from curator import journey

    return {"removed": journey.clear_finished()}
