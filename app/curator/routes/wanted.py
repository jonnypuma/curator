from fastapi import APIRouter
from pydantic import BaseModel

from curator.video import wanted, work_track
from resonance.errors import AppError

router = APIRouter()


@router.get("/add/options")
def add_options(media: str):
    if media not in {"movies", "tv"}:
        raise AppError("Add a movie or a TV show", 400)
    return wanted.options(media)


class AddBody(BaseModel):
    media: str
    source: str = "tmdb"
    id: str
    title: str
    year: int | None = None
    root: str = ""
    search: bool | None = None


@router.post("/add")
def add_title(body: AddBody):
    if body.media == "movies":
        if body.source != "tmdb":
            raise AppError("Movies are added from TMDB", 400)
        service = "Radarr"
    elif body.media == "tv":
        service = "Sonarr"
    else:
        raise AppError("Add a movie or a TV show", 400)
    name = f"{body.title} ({body.year})" if body.year else body.title
    # The request waits for Radarr or Sonarr, which can take several seconds, so it is shown in the Jobs list meanwhile.
    track = work_track.Tracked(f"{service.lower()}-add", f"Adding {name} to {service}", 1)
    try:
        if body.media == "movies":
            answer = wanted.add_movie(body.id, body.title, body.year, body.root, body.search)
        else:
            answer = wanted.add_show(body.source, body.id, body.title, body.year, body.root, body.search)
    except Exception as exc:
        track.finish("failed", f"{name}: {str(exc)[:200]}")
        raise
    track.finish("completed", f"{name}: {answer.get('message') or 'Added'}", 1)
    return answer
