"""OMDb ratings (IMDb, Rotten Tomatoes, Metacritic) and English movie metadata.

A free key stops for the rest of the UTC day once OMDb reports the daily quota.
An OMDb Patron key, switched on under Settings, keeps asking.
"""
from __future__ import annotations

import datetime as dt
import re

from .http import ScrapeError

API = "https://www.omdbapi.com/"
_quota = {"day": None}


def patron():
    try:
        from curator.video.config import current
    except Exception:
        return False
    return bool(current().get("omdb_patron"))


def exhausted():
    if patron():
        return False
    return _quota["day"] == dt.datetime.now(dt.timezone.utc).date()


class Omdb:
    name = "omdb"

    def __init__(self, client, key):
        if not key:
            raise ScrapeError("No OMDb API key")
        self.client = client
        self.key = key

    async def search(self, query, year=None, kind="movie"):
        """Title search. Each hit's id is the IMDb id."""
        if exhausted():
            raise ScrapeError("OMDb is out of requests for today")
        params = {"s": query, "type": "series" if kind == "series" else "movie", "apikey": self.key}
        if year:
            params["y"] = year
        data = await self.client.get(API, params=params)
        if not isinstance(data, dict):
            return []
        if data.get("Response") == "False":
            error = str(data.get("Error") or "")
            if "limit" in error.lower():
                if not patron():
                    _quota["day"] = dt.datetime.now(dt.timezone.utc).date()
                raise ScrapeError("OMDb is out of requests for today")
            if "invalid api key" in error.lower():
                raise ScrapeError("OMDb rejected the API key")
            return []
        hits = []
        for item in data.get("Search") or []:
            imdb_id = str(item.get("imdbID") or "").strip()
            if not imdb_id:
                continue
            poster = item.get("Poster") or ""
            hits.append({
                "source": "omdb", "id": imdb_id, "title": item.get("Title") or "", "original_title": "",
                "year": int(str(item.get("Year") or "")[:4]) if str(item.get("Year") or "")[:4].isdigit() else None,
                "overview": "", "poster": "" if poster == "N/A" else poster, "popularity": 0,
                "ids": {"imdb": imdb_id},
            })
        return hits

    async def ratings(self, imdb_id):
        """Returns {"ratings": {...}, "mpaa": ..., "top250": None} or None when OMDb has nothing or is out of quota."""
        if not imdb_id or exhausted():
            return None
        data = await self.client.get(API, params={"i": imdb_id, "apikey": self.key, "tomatoes": "true"})
        if not isinstance(data, dict):
            return None
        if data.get("Response") == "False":
            error = str(data.get("Error") or "")
            if "limit" in error.lower():
                if not patron():
                    _quota["day"] = dt.datetime.now(dt.timezone.utc).date()
                return None
            if "invalid api key" in error.lower():
                raise ScrapeError("OMDb rejected the API key")
            return None
        return parse(data)

    async def movie_base(self, ids):
        """A movie's English metadata and ratings from one OMDb request, in the shape the TMDB
        scraper returns. None when the movie has no IMDb id, OMDb does not know it, or the quota is used."""
        imdb_id = (ids or {}).get("imdb")
        if not imdb_id or exhausted():
            return None
        data = await self.client.get(API, params={"i": imdb_id, "plot": "full", "apikey": self.key, "tomatoes": "true"})
        if not isinstance(data, dict):
            return None
        if data.get("Response") == "False":
            error = str(data.get("Error") or "")
            if "limit" in error.lower():
                if not patron():
                    _quota["day"] = dt.datetime.now(dt.timezone.utc).date()
                return None
            if "invalid api key" in error.lower():
                raise ScrapeError("OMDb rejected the API key")
            return None
        return parse_movie(data)

    async def episode_ratings(self, imdb_id, season, number):
        if not imdb_id or season is None or number is None or exhausted():
            return None
        data = await self.client.get(API, params={
            "i": imdb_id, "Season": int(season), "Episode": int(number), "apikey": self.key,
        })
        if not isinstance(data, dict):
            return None
        if data.get("Response") == "False":
            error = str(data.get("Error") or "")
            if "limit" in error.lower():
                if not patron():
                    _quota["day"] = dt.datetime.now(dt.timezone.utc).date()
                return None
            if "invalid api key" in error.lower():
                raise ScrapeError("OMDb rejected the API key")
            return None
        return parse(data)


def parse(data):
    ratings = {}
    imdb = _number(data.get("imdbRating"))
    votes = _number(str(data.get("imdbVotes") or "").replace(",", ""))
    if imdb is not None:
        ratings["imdb"] = {"value": imdb, "votes": int(votes or 0), "max": 10}
    for item in data.get("Ratings") or []:
        source, value = item.get("Source"), str(item.get("Value") or "")
        if source == "Rotten Tomatoes" and value.endswith("%"):
            number = _number(value[:-1])
            if number is not None:
                ratings["tomatometerallcritics"] = {"value": number, "votes": 0, "max": 100}
        elif source == "Metacritic" and "/" in value:
            number = _number(value.split("/")[0])
            if number is not None:
                ratings["metacritic"] = {"value": number, "votes": 0, "max": 100}
    rated = data.get("Rated")
    certificate = f"Rated {rated}" if rated and rated not in {"N/A", "Not Rated", "Unrated"} else None
    return {
        "source": "omdb",
        "ratings": ratings,
        "mpaa": certificate,
        "mpaa_fallback": certificate,
        "awards": data.get("Awards") if data.get("Awards") not in (None, "N/A") else None,
    }


def _text(value):
    text = str(value or "").strip()
    return None if text in {"", "N/A"} else text


def _list(value):
    """OMDb joins names with commas. "Name (screenplay)" keeps only the name."""
    names = []
    for item in str(value or "").split(","):
        name = re.sub(r"\s*\([^)]*\)\s*$", "", item).strip()
        if name and name != "N/A" and name not in names:
            names.append(name)
    return names


def _released(value):
    text = _text(value)
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def parse_movie(data):
    """Ratings plus the movie fields OMDb has. Always English."""
    result = parse(data)
    year = str(data.get("Year") or "")[:4]
    runtime = re.match(r"\s*(\d+)\s*min", str(data.get("Runtime") or ""))
    imdb_id = _text(data.get("imdbID"))
    result.update({
        "ids": {"imdb": imdb_id} if imdb_id else {},
        "title": _text(data.get("Title")),
        "year": int(year) if year.isdigit() else None,
        "premiered": _released(data.get("Released")),
        "plot": _text(data.get("Plot")),
        "runtime_minutes": int(runtime.group(1)) if runtime else None,
        "genres": _list(data.get("Genre")),
        "countries": _list(data.get("Country")),
        "languages": _list(data.get("Language")),
        "directors": _list(data.get("Director")),
        "writers": _list(data.get("Writer")),
        "studios": _list(data.get("Production")),
        "actors": [{"name": name, "role": "", "order": index, "thumb": ""}
                   for index, name in enumerate(_list(data.get("Actors")))],
    })
    return result


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 1)
