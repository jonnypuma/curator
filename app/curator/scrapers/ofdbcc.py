"""Open Film Database (ofdb.cc): a free, open (ODbL) movie and TV database with a JSON:API and no key.

Not the German OFDb at ofdb.de, which has its own scraper and gives a score. This one has no scores. It is asked by the
ids a title already has (IMDb, then TMDB, then TheTVDB), never by title, so it cannot attach the wrong title."""
from __future__ import annotations

import re

from curator.scrapers.http import ScrapeError

API = "https://ofdb.cc/api/node"
_IMDB = re.compile(r"^tt\d{5,}$", re.I)


def _text(value):
    text = str(value or "").strip()
    return text or None


def _year(value):
    found = re.match(r"(\d{4})", str(value or ""))
    return int(found.group(1)) if found else None


def _names(included, kind):
    return [item["attributes"]["name"] for item in included
            if str(item.get("type", "")).endswith(f"--{kind}") and (item.get("attributes") or {}).get("name")]


def _runtime(included):
    for item in included:
        if str(item.get("type", "")).endswith("--runtime"):
            value = (item.get("attributes") or {}).get("field_runtime")
            try:
                minutes = int(value)
            except (TypeError, ValueError):
                continue
            if minutes > 0:
                return minutes
    return None


class OfdbCc:
    def __init__(self, client):
        self.client = client

    async def movie(self, ids):
        return await self._lookup("movie", ids, "field_genre,field_runtime")

    async def show(self, ids):
        return await self._lookup("tv_show", ids, "field_genre,field_network")

    async def _lookup(self, bundle, ids, include):
        ids = ids or {}
        tries = []
        if ids.get("imdb") and _IMDB.match(str(ids["imdb"])):
            tries.append(("field_imdb", str(ids["imdb"])))
        if str(ids.get("tmdb") or "").isdigit():
            tries.append(("field_tmdb", str(ids["tmdb"])))
        if bundle == "tv_show" and str(ids.get("tvdb") or "").isdigit():
            tries.append(("field_thetvdb", str(ids["tvdb"])))
        for field, value in tries:
            params = {f"filter[{field}]": value, "page[limit]": "1", "include": include}
            data = await self.client.get(f"{API}/{bundle}", params=params)
            items = (data or {}).get("data") if isinstance(data, dict) else None
            if items:
                return self._result(bundle, items[0], (data or {}).get("included") or [])
        return None

    def _result(self, bundle, item, included):
        attrs = item.get("attributes") or {}
        body = attrs.get("body")
        plot = _text(body.get("value") if isinstance(body, dict) else body)
        found_ids = {}
        for key, field in (("imdb", "field_imdb"), ("tmdb", "field_tmdb"), ("tvdb", "field_thetvdb")):
            value = _text(attrs.get(field))
            if value:
                found_ids[key] = value
        released = _text(attrs.get("field_release_date")) if bundle == "movie" else None
        result = {
            "source": "ofdbcc",
            "ids": found_ids,
            "title": _text(attrs.get("title")),
            "original_title": _text(attrs.get("field_original_title")),
            "year": _year(released),
            "premiered": released,
            "plot": plot,
            "tagline": _text(attrs.get("field_tagline")),
            "genres": _names(included, "genre"),
        }
        if bundle == "movie":
            result["runtime_minutes"] = _runtime(included)
        else:
            result["show_status"] = _text(attrs.get("field_status"))
            result["studios"] = _names(included, "network")
        return result
