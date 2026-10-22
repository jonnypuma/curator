import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from curator import bazarr, sonarr
from resonance import db
from resonance.errors import AppError

router = APIRouter()


class Connection(BaseModel):
    url: str = ""
    key: str = ""


def _typed(value):
    text = str(value or "").strip()
    return text if text and set(text) - {"*", "•"} else None


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise AppError("Unknown item", 400) from exc


@router.post("/lidarr/test")
def lidarr_test(body: Connection):
    from resonance import lidarr

    return {"message": lidarr.test(_typed(body.url), _typed(body.key))}


@router.post("/lidarr/options")
def lidarr_options(body: Connection):
    from resonance import lidarr

    return lidarr.options(_typed(body.url), _typed(body.key))


@router.post("/sonarr/test")
def sonarr_test(body: Connection):
    return {"message": sonarr.test(_typed(body.url), _typed(body.key))}


@router.post("/sonarr/options")
def sonarr_options(body: Connection):
    return sonarr.options(_typed(body.url), _typed(body.key))


@router.post("/bazarr/test")
def bazarr_test(body: Connection):
    return {"message": bazarr.test(_typed(body.url), _typed(body.key))}


class SonarrSearch(BaseModel):
    show_id: str
    season_number: Optional[int] = None
    episode_number: Optional[int] = None


class SonarrEpisodes(BaseModel):
    episode_ids: list[str]


def _show(show_id):
    row = db.fetchone("SELECT title, tvdb_id FROM tv_shows WHERE id = %s", (_uuid(show_id),))
    if not row:
        raise AppError("That show is not in the library", 404)
    if not str(row["tvdb_id"] or "").strip():
        raise AppError(f"{row['title']} has no TVDB id. Scrape it first.", 400)
    return row


@router.post("/sonarr/missing")
def sonarr_missing(body: SonarrSearch):
    from curator.arr_queue import enqueue

    row = _show(body.show_id)
    title = row["title"] or "the show"
    if body.episode_number is not None and body.season_number is not None:
        label = f"{title} S{int(body.season_number):02d}E{int(body.episode_number):02d}"
    elif body.season_number is not None:
        label = f"{title} season {int(body.season_number)}"
    else:
        label = title
    enqueue("sonarr", f"Sonarr search · {label}", "sonarr", {
        "tvdb_id": str(row["tvdb_id"]),
        "season": body.season_number,
        "episode": body.episode_number,
    })
    return {"queued": True, "message": f"Sonarr search queued for {label}."}


@router.post("/sonarr/episodes")
def sonarr_episodes(body: SonarrEpisodes):
    from curator.arr_queue import enqueue, search_title

    ids = [_uuid(item) for item in body.episode_ids][:100]
    if not ids:
        raise AppError("Pick at least one episode", 400)
    rows = db.fetchall(
        """
        SELECT e.title, e.season_number, e.episode_number, sh.tvdb_id, sh.title AS show_title
        FROM tv_episodes e JOIN tv_shows sh ON sh.id = e.show_id
        WHERE e.id = ANY(%s::uuid[])
        """,
        (ids,),
    )
    if not rows:
        raise AppError("Those episodes are not in the library", 404)
    if any(not str(row["tvdb_id"] or "").strip() for row in rows):
        raise AppError("A show has no TVDB id. Scrape it first.", 400)
    payload = [dict(row) for row in rows]
    labels = []
    for row in payload:
        show = row.get("show_title") or "Show"
        season = row.get("season_number")
        episode = row.get("episode_number")
        if season is not None and episode is not None:
            labels.append(f"{show} S{int(season):02d}E{int(episode):02d}")
        else:
            labels.append(show)
    enqueue("sonarr", search_title("sonarr", labels), "sonarr", {"episodes": payload})
    shown = ", ".join(labels[:4]) + (" and more" if len(labels) > 4 else "")
    return {"queued": True, "message": f"Sonarr search queued for {shown}."}


class BazarrSearch(BaseModel):
    kind: str
    id: str


@router.post("/bazarr/missing")
def bazarr_missing(body: BazarrSearch):
    kind = body.kind
    if kind == "movie":
        row = db.fetchone("SELECT title, tmdb_id FROM movies WHERE id = %s", (_uuid(body.id),))
        if not row:
            raise AppError("That movie is not in the library", 404)
        if not str(row["tmdb_id"] or "").strip():
            raise AppError(f"{row['title']} has no TMDB id. Scrape it first.", 400)
        result = bazarr.search_movie(row["tmdb_id"])
        result["message"] = f"Bazarr is searching missing subtitles for {result['title'] or row['title']}."
        return result
    if kind == "show":
        row = _show(body.id)
        result = bazarr.search_series(row["tvdb_id"])
        result["message"] = f"Bazarr is searching missing subtitles for {result['title'] or row['title']}."
        return result
    if kind == "episode":
        row = db.fetchone(
            """
            SELECT e.season_number, e.episode_number, e.title, sh.title AS show_title, sh.tvdb_id
            FROM tv_episodes e JOIN tv_shows sh ON sh.id = e.show_id WHERE e.id = %s
            """,
            (_uuid(body.id),),
        )
        if not row:
            raise AppError("That episode is not in the library", 404)
        if not str(row["tvdb_id"] or "").strip():
            raise AppError(f"{row['show_title']} has no TVDB id. Scrape it first.", 400)
        result = bazarr.search_episode(row["tvdb_id"], row["season_number"], row["episode_number"])
        result["message"] = (f"Bazarr is searching {result['languages']} missing subtitle"
                             f"{'s' if result['languages'] != 1 else ''} for {row['show_title']} "
                             f"S{int(row['season_number']):02d}E{int(row['episode_number']):02d}.")
        return result
    raise AppError("Search subtitles for a movie, a show, or an episode", 400)
