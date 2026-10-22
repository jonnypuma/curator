"""TVMaze's free REST API. No key. Show metadata, episode lists, and images."""
from __future__ import annotations

import re

from .tmdb import _clean_ids

API = "https://api.tvmaze.com"
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_IMAGE_KINDS = {"poster": "poster", "banner": "banner", "background": "fanart", "typography": "clearlogo"}


class Tvmaze:
    name = "tvmaze"

    def __init__(self, client):
        self.client = client

    async def show(self, ids, title, year=None):
        """One show in the same shape as the other scrapers, plus an episode map."""
        found = await self._find(ids, title, year)
        if not found or not found.get("id"):
            return None
        show_id = found["id"]
        episodes, seasons, cast, images = await self._extras(show_id)
        return _shape(found, episodes, seasons, cast, images)

    async def _find(self, ids, title, year):
        ids = ids or {}
        if ids.get("tvmaze"):
            row = await self.client.get(f"{API}/shows/{ids['tvmaze']}")
            if row:
                return row
        if ids.get("imdb"):
            row = await self.client.get(f"{API}/lookup/shows", params={"imdb": ids["imdb"]})
            if row:
                return row
        if ids.get("tvdb"):
            row = await self.client.get(f"{API}/lookup/shows", params={"thetvdb": ids["tvdb"]})
            if row:
                return row
        if not title:
            return None
        hits = await self.client.get(f"{API}/search/shows", params={"q": title}) or []
        wanted = str(year) if year else ""
        best = None
        for hit in hits:
            show = hit.get("show") or {}
            premiered = str(show.get("premiered") or "")
            if wanted and premiered[:4] == wanted:
                return show
            if best is None:
                best = show
        return best

    async def _extras(self, show_id):
        episodes = await self.client.get(f"{API}/shows/{show_id}/episodes") or []
        seasons = await self.client.get(f"{API}/shows/{show_id}/seasons") or []
        cast = await self.client.get(f"{API}/shows/{show_id}/cast") or []
        images = await self.client.get(f"{API}/shows/{show_id}/images") or []
        return episodes, seasons, cast, images


def _plain(html):
    text = _SPACE.sub(" ", _TAGS.sub(" ", str(html or ""))).strip()
    return text or None


def _image(block):
    if isinstance(block, str):
        return block.strip()
    if not isinstance(block, dict):
        return ""
    original = block.get("original")
    if isinstance(original, dict):
        return str(original.get("url") or "").strip()
    if isinstance(original, str) and original.strip():
        return original.strip()
    medium = block.get("medium")
    if isinstance(medium, str) and medium.strip():
        return medium.strip()
    return str(block.get("url") or "").strip()


def _art(url, kind):
    if not url:
        return None
    return {
        "source": "tvmaze", "kind": kind, "url": url, "lang": "",
        "width": 0, "height": 0, "score": 1, "votes": 0,
    }


def _rating(average):
    try:
        value = float(average)
    except (TypeError, ValueError):
        return {}
    if value <= 0:
        return {}
    return {"tvmaze": {"value": round(value, 1), "votes": None, "max": 10}}


def _shape(show, episodes, seasons, cast, images):
    externals = show.get("externals") or {}
    network = (show.get("network") or {}).get("name") or (show.get("webChannel") or {}).get("name")
    country = ((show.get("network") or {}).get("country") or {}).get("name")
    poster = _image(show.get("image"))
    art = [item for item in (_art(poster, "poster"),) if item]
    for image in images or []:
        kind = _IMAGE_KINDS.get(str(image.get("type") or ""))
        url = _image((image.get("resolutions") or {}).get("original")) or _image(image)
        candidate = _art(url, kind) if kind else None
        if candidate:
            art.append(candidate)
    season_rows = {}
    names = {}
    for item in seasons or []:
        number = item.get("number")
        if number is None:
            continue
        name = item.get("name") or None
        if name:
            names[str(number)] = name
        picture = _art(_image(item.get("image")), "poster")
        season_rows[number] = {
            "title": name,
            "plot": _plain(item.get("summary")),
            "premiered": item.get("premiereDate") or None,
            "episode_count": item.get("episodeOrder") or None,
            "ids": _clean_ids({"tvmaze": str(item.get("id") or "")}),
            "art": [picture] if picture else [],
        }
    episode_rows = {}
    for item in episodes or []:
        season = item.get("season")
        number = item.get("number")
        if season is None or number is None:
            continue
        still = _art(_image(item.get("image")), "thumb")
        episode_rows[(int(season), int(number))] = {
            "source": "tvmaze",
            "ids": _clean_ids({"tvmaze": str(item.get("id") or "")}),
            "title": item.get("name") or None,
            "plot": _plain(item.get("summary")),
            "aired": item.get("airdate") or None,
            "runtime_minutes": item.get("runtime") or None,
            "ratings": _rating((item.get("rating") or {}).get("average")),
            "art": [still] if still else [],
        }
    actors = []
    for index, item in enumerate(cast or []):
        person = item.get("person") or {}
        character = item.get("character") or {}
        if not person.get("name"):
            continue
        actors.append({
            "name": person["name"],
            "role": character.get("name") or "",
            "order": index,
            "thumb": _image(person.get("image")),
        })
        if len(actors) >= 40:
            break
    return {
        "source": "tvmaze",
        "ids": _clean_ids({
            "tvmaze": str(show.get("id") or ""),
            "imdb": externals.get("imdb"),
            "tvdb": externals.get("thetvdb"),
            "tvrage": externals.get("tvrage"),
        }),
        "title": show.get("name"),
        "year": int(str(show.get("premiered") or "")[:4]) if str(show.get("premiered") or "")[:4].isdigit() else None,
        "premiered": show.get("premiered") or None,
        "plot": _plain(show.get("summary")),
        "show_status": show.get("status") or None,
        "runtime_minutes": show.get("averageRuntime") or show.get("runtime"),
        "genres": [name for name in show.get("genres") or [] if name],
        "studios": [network] if network else [],
        "countries": [country] if country else [],
        "original_language": str(show.get("language") or "").split("-")[0].lower() or None,
        "actors": actors,
        "ratings": _rating((show.get("rating") or {}).get("average")),
        "season_names": names,
        "seasons": season_rows,
        "episodes": episode_rows,
        "art": art,
    }
