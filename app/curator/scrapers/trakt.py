"""Trakt community ratings. Only needs the app client id, not a signed-in account."""
from __future__ import annotations

import re

from curator.scrapers.http import ScrapeError

API = "https://api.trakt.tv"


class TraktRatings:
    name = "trakt"

    def __init__(self, client, client_id):
        self.client = client
        self.client_id = client_id

    def _headers(self):
        return {
            "Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": self.client_id,
        }

    async def _ratings(self, path):
        if not self.client_id:
            return {}
        data = await self.client.get(f"{API}{path}", headers=self._headers())
        if not isinstance(data, dict) or not data.get("votes"):
            return {}
        return {"trakt": {"value": round(float(data.get("rating") or 0), 1), "votes": int(data["votes"]), "max": 10}}

    async def _trakt_id(self, kind, key):
        if not self.client_id or not key:
            return None
        try:
            data = await self.client.get(f"{API}/{kind}/{key}", headers=self._headers())
        except ScrapeError:
            return None
        value = ((data or {}).get("ids") or {}).get("trakt") if isinstance(data, dict) else None
        return str(value) if value else None

    async def _bundle(self, kind, path, key, known):
        ratings = await self._ratings(path) if key else {}
        trakt_id = known or await self._trakt_id(kind, key)
        result = {"ratings": ratings}
        if trakt_id:
            result["ids"] = {"trakt": trakt_id}
        return result

    async def search(self, query, year=None, kind="movie"):
        """Title search. The hit id is the Trakt number, and ids also carries IMDb and TMDB when Trakt has them."""
        if not self.client_id:
            raise ScrapeError("No Trakt client id. Add one under Settings, Trakt.")
        params = {"query": query, "extended": "full"}
        if year:
            params["years"] = year
        path = "movie" if kind == "movie" else "show"
        data = await self.client.get(f"{API}/search/{path}", params=params, headers=self._headers())
        hits = []
        if not isinstance(data, list):
            return []
        for item in data:
            body = (item or {}).get(kind) or (item or {}).get("movie") or (item or {}).get("show") or {}
            found = body.get("ids") or {}
            trakt_id = found.get("trakt")
            if not trakt_id:
                continue
            ids = {"trakt": str(trakt_id)}
            if found.get("imdb"):
                ids["imdb"] = str(found["imdb"])
            if found.get("tmdb"):
                ids["tmdb"] = str(found["tmdb"])
            if found.get("tvdb"):
                ids["tvdb"] = str(found["tvdb"])
            hits.append({
                "source": "trakt", "id": str(trakt_id), "title": body.get("title") or "", "original_title": "",
                "year": body.get("year"), "overview": body.get("overview") or "", "poster": "", "popularity": 0,
                "ids": ids,
            })
        return hits

    async def movie(self, ids):
        key = ids.get("imdb") or ids.get("trakt")
        return await self._bundle("movies", f"/movies/{key}/ratings" if key else "", key, ids.get("trakt"))

    async def show(self, ids):
        key = ids.get("imdb") or ids.get("trakt")
        return await self._bundle("shows", f"/shows/{key}/ratings" if key else "", key, ids.get("trakt"))

    async def episode(self, ids, season, number):
        key = ids.get("imdb") or ids.get("trakt")
        if not key or season is None or number is None:
            return {"ratings": {}}
        path = f"/shows/{key}/seasons/{int(season)}/episodes/{int(number)}/ratings"
        return await self._bundle("shows", path, key, ids.get("trakt"))


def _youtube(url):
    found = re.search(r"(?:v=|youtu\.be/)([\w-]{6,})", str(url or ""))
    return f"plugin://plugin.video.youtube/play/?video_id={found.group(1)}" if found else None


def _names(people):
    seen = []
    for item in people or []:
        name = ((item or {}).get("person") or {}).get("name")
        if name and name not in seen:
            seen.append(name)
    return seen


async def movie_base(self, ids):
    """Movie metadata from Trakt alone, in the shape the TMDB scraper returns. Used when a movie
    exists on Trakt but not on TMDB (or TMDB has no usable entry). Trakt has no artwork."""
    key = ids.get("trakt") or ids.get("imdb")
    if not self.client_id or not key:
        return None
    data = await self.client.get(f"{API}/movies/{key}", params={"extended": "full"}, headers=self._headers())
    if not isinstance(data, dict) or not data.get("title"):
        return None
    found = data.get("ids") or {}
    result_ids = {"trakt": str(found["trakt"])} if found.get("trakt") else {}
    if found.get("imdb"):
        result_ids["imdb"] = str(found["imdb"])
    if found.get("tmdb"):
        result_ids["tmdb"] = str(found["tmdb"])       # only a candidate: TMDB must confirm it
    people = {}
    try:
        people = await self.client.get(f"{API}/movies/{key}/people", headers=self._headers()) or {}
    except ScrapeError:
        people = {}
    crew = people.get("crew") or {}
    cast = [{"name": (item.get("person") or {}).get("name") or "", "role": ", ".join(item.get("characters") or []) or item.get("character") or "",
             "order": index, "thumb": ""} for index, item in enumerate((people.get("cast") or [])[:40])]
    ratings = {}
    if data.get("votes"):
        ratings = {"trakt": {"value": round(float(data.get("rating") or 0), 1), "votes": int(data["votes"]), "max": 10}}
    country = str(data.get("country") or "").upper()
    return {
        "source": "trakt",
        "ids": result_ids,
        "title": data.get("title"),
        "original_title": None,
        "year": data.get("year"),
        "premiered": data.get("released") or None,
        "plot": data.get("overview") or None,
        "tagline": data.get("tagline") or None,
        "runtime_minutes": data.get("runtime") or None,
        "mpaa": data.get("certification") or None,
        "genres": [str(g).replace("-", " ").title() for g in data.get("genres") or []],
        "countries": [country] if country else [],
        "languages": [str(data["language"])] if data.get("language") else [],
        "directors": _names([i for i in crew.get("directing") or [] if str(i.get("job", "")).lower() == "director"]),
        "writers": _names(crew.get("writing")),
        "producers": _names([i for i in crew.get("production") or [] if "producer" in str(i.get("job", "")).lower()]),
        "actors": [a for a in cast if a["name"]],
        "trailer": _youtube(data.get("trailer")),
        "ratings": ratings,
        "set": None,
        "art": [],
    }


_SHOW_STATUS = {
    "returning series": "Continuing", "continuing": "Continuing", "in production": "Upcoming",
    "planned": "Upcoming", "upcoming": "Upcoming", "pilot": "Upcoming",
    "ended": "Ended", "canceled": "Ended", "cancelled": "Ended",
}


async def show_base(self, ids):
    """Show metadata from Trakt alone, in the shape the TMDB scraper returns. English only.
    Trakt has no artwork, and its season and episode lists are left to TMDB, TheTVDB and TVMaze."""
    key = ids.get("trakt") or ids.get("imdb")
    if not self.client_id or not key:
        return None
    data = await self.client.get(f"{API}/shows/{key}", params={"extended": "full"}, headers=self._headers())
    if not isinstance(data, dict) or not data.get("title"):
        return None
    found = data.get("ids") or {}
    result_ids = {name: str(found[name]) for name in ("trakt", "imdb", "tvdb", "tmdb") if found.get(name)}
    people = {}
    try:
        people = await self.client.get(f"{API}/shows/{key}/people", headers=self._headers()) or {}
    except ScrapeError:
        people = {}
    crew = people.get("crew") or {}
    cast = [{"name": (item.get("person") or {}).get("name") or "", "role": ", ".join(item.get("characters") or []) or item.get("character") or "",
             "order": index, "thumb": ""} for index, item in enumerate((people.get("cast") or [])[:40])]
    ratings = {}
    if data.get("votes"):
        ratings = {"trakt": {"value": round(float(data.get("rating") or 0), 1), "votes": int(data["votes"]), "max": 10}}
    country = str(data.get("country") or "").upper()
    premiered = str(data.get("first_aired") or "")[:10] or None
    year = data.get("year")
    network = str(data.get("network") or "").strip()
    return {
        "source": "trakt",
        "ids": result_ids,
        "title": data.get("title"),
        "original_title": None,
        "year": year,
        "premiered": premiered,
        "plot": data.get("overview") or None,
        "tagline": data.get("tagline") or None,
        "show_status": _SHOW_STATUS.get(str(data.get("status") or "").strip().lower()),
        "runtime_minutes": data.get("runtime") or None,
        "mpaa": data.get("certification") or None,
        "genres": [str(g).replace("-", " ").title() for g in data.get("genres") or []],
        "studios": [network] if network else [],
        "countries": [country] if country else [],
        "original_language": str(data["language"]) if data.get("language") else None,
        "directors": _names(crew.get("created by")),
        "actors": [a for a in cast if a["name"]],
        "trailer": _youtube(data.get("trailer")),
        "ratings": ratings,
        "seasons": {},
        "art": [],
    }


async def show_details(self, ids):
    """The show's full Trakt metadata, or the ratings bundle when the full lookup finds nothing."""
    try:
        full = await self.show_base(ids)
    except ScrapeError:
        full = None
    return full or await self.show(ids)


TraktRatings.movie_base = movie_base
TraktRatings.show_base = show_base
TraktRatings.show_details = show_details
