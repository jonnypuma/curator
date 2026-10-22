"""OFDb rating from the public search page. A blocked or empty page contributes nothing."""
from __future__ import annotations

import re
from urllib.parse import quote

from curator.scrapers.http import ScrapeError

_SEARCH = "https://www.ofdb.de/view.php?page=suchergebnis&Kat=DTitel&SText={query}"
_FILM = "https://www.ofdb.de/film/{fid},{slug}"
_LINK = re.compile(r"film/(\d+),([^\"'&< ]+)")
_NOTE = re.compile(r"Note:\s*([0-9]+(?:[.,][0-9]+)?)", re.I)
_YEAR = re.compile(r"\((\d{4})\)")


class Ofdb:
    def __init__(self, client):
        self.client = client

    async def movie(self, title, year=None):
        return await self._lookup(title, year)

    async def show(self, title, year=None):
        return await self._lookup(title, year)

    async def _lookup(self, title, year):
        if not title:
            return None
        _headers, html = await self.client.text(_SEARCH.format(query=quote(title)))
        chosen = None
        for fid, slug in _LINK.findall(html or ""):
            window = html[max(0, html.find(f"film/{fid}")): html.find(f"film/{fid}") + 400]
            found_year = _YEAR.search(window)
            if year and found_year and abs(int(found_year.group(1)) - int(year)) > 1:
                continue
            chosen = (fid, slug)
            break
        if not chosen:
            return None
        _headers, page = await self.client.text(_FILM.format(fid=chosen[0], slug=chosen[1]))
        match = _NOTE.search(page or "")
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        if value > 10:
            return None
        return {"source": "ofdb", "ids": {"ofdb": chosen[0]},
                "ratings": {"ofdb": {"value": round(value, 1), "votes": 0, "max": 10}}}
