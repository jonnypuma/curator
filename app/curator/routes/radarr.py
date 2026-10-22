from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from curator import radarr

router = APIRouter()


class Connection(BaseModel):
    url: Optional[str] = None
    key: Optional[str] = None


class Search(BaseModel):
    tmdb_ids: List[str]


def _typed(value):
    text = str(value or "").strip()
    return text if text and set(text) - {"*", "•"} else None


@router.post("/radarr/test")
def radarr_test(body: Connection):
    return {"message": radarr.test(_typed(body.url), _typed(body.key))}


@router.post("/radarr/options")
def radarr_options(body: Connection):
    return radarr.options(_typed(body.url), _typed(body.key))


@router.post("/radarr/states")
def radarr_states(body: Search):
    return {"states": radarr.states(body.tmdb_ids[:50])}


@router.post("/radarr/search")
def radarr_search(body: Search):
    from resonance import db
    from curator.arr_queue import enqueue, search_title

    ids = [str(item).strip() for item in body.tmdb_ids[:100] if str(item).strip()]
    if not ids:
        return {"queued": False, "results": [], "ok": 0, "failed": [], "message": "Nothing to search."}
    rows = db.fetchall(
        """
        SELECT DISTINCT ON (tmdb_id) title, year, tmdb_id
        FROM movies WHERE tmdb_id = ANY(%s)
        ORDER BY tmdb_id, wanted
        """,
        (ids,),
    )
    by_id = {str(row["tmdb_id"]): row for row in rows}
    labels = []
    for tmdb in ids:
        row = by_id.get(tmdb)
        if row and row.get("title"):
            year = row.get("year")
            raw_title = str(row["title"]).strip()
            has_year = bool(year and raw_title.endswith(f"({year})"))
            labels.append(f"{raw_title} ({year})" if year and not has_year else raw_title)
        else:
            labels.append(f"TMDB {tmdb}")
    title = search_title("radarr", labels)
    enqueue("radarr", title, "radarr", {"tmdb_ids": ids})
    return {
        "queued": True,
        "results": [],
        "ok": 0,
        "failed": [],
        "message": f"Radarr search queued for {', '.join(labels[:4])}{' and more' if len(labels) > 4 else ''}.",
    }
