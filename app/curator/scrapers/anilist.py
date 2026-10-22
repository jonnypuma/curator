"""AniList ratings. The public GraphQL API needs no key."""
from __future__ import annotations

from curator.scrapers.http import ScrapeError

import re

_URL = "https://graphql.anilist.co"
_QUERY = """
query ($search: String, $type: MediaType) {
  Media(search: $search, type: $type) {
    id
    averageScore
    title { romaji english }
    startDate { year }
  }
}
"""


def _clean_title(text):
    return re.sub(r"[\s\W]+", "", str(text or "").lower())


class AniList:
    def __init__(self, client):
        self.client = client

    async def movie(self, title, year=None):
        return await self._lookup(title, year, "ANIME")

    async def show(self, title, year=None):
        return await self._lookup(title, year, "ANIME")

    async def _lookup(self, title, year, kind):
        if not title:
            return None
        data = await self.client.json("POST", _URL, body={"query": _QUERY, "variables": {"search": title, "type": kind}})
        media = ((data or {}).get("data") or {}).get("Media") or {}
        score = media.get("averageScore")
        if score in (None, ""):
            return None
        started = ((media.get("startDate") or {}).get("year"))
        if year and started and abs(int(started) - int(year)) > 1:
            return None
        media_titles = media.get("title") or {}
        candidates = [_clean_title(media_titles.get("romaji")), _clean_title(media_titles.get("english"))]
        target = _clean_title(title)
        if not target or not any(c and (c == target or target in c or c in target) for c in candidates):
            return None
        return {"source": "anilist", "ids": {"anilist": str(media.get("id") or "")},
                "ratings": {"anilist": {"value": round(float(score) / 10, 1), "votes": 0, "max": 10}}}
