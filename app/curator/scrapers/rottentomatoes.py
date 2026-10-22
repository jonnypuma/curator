"""Rotten Tomatoes Tomatometer and audience score for a movie or show already in the library.

The search feed is asked first. When that page has no scores, a Crawlbase JS token
loads the rendered title page. The public slots are criticsScore and audienceScore.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from .http import ScrapeError

SEARCH = "https://www.rottentomatoes.com/napi/search/all"
CRAWLBASE = "https://api.crawlbase.com/"
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class RottenTomatoes:
    name = "rottentomatoes"

    def __init__(self, client, token=""):
        self.client = client
        self.token = str(token or "").strip()

    async def movie(self, title, year=None):
        return await self._lookup("movie", title, year)

    async def show(self, title, year=None):
        return await self._lookup("tv", title, year)

    async def _lookup(self, kind, title, year):
        title = str(title or "").strip()
        if not title:
            return None
        hit = await self._search(kind, title, year)
        critics = hit.get("critics") if hit else None
        audience = hit.get("audience") if hit else None
        if critics is None and audience is None:
            url = (hit or {}).get("url") or _guess_url(kind, title)
            parsed = parse_page(await self._direct(url))
            if parsed.get("critics") is None and parsed.get("audience") is None and self.token:
                parsed = parse_page(await self._rendered(url))
            critics = parsed.get("critics")
            audience = parsed.get("audience")
        return ratings(critics, audience)


    async def _search(self, kind, title, year):
        try:
            data = await self.client.get(SEARCH, params={"searchQuery": title, "type": kind}, missing_ok=True)
        except ScrapeError:
            return None
        hits = search_hits(data, kind)
        return pick_hit(hits, title, year)

    async def _direct(self, url):
        if not url:
            return ""
        try:
            _headers, body = await self.client.text(url, headers={"User-Agent": BROWSER, "Accept": "text/html"})
            return body or ""
        except ScrapeError:
            if self.token:
                return ""
            raise

    async def _rendered(self, url):
        headers, body = await self.client.text(CRAWLBASE, params={
            "token": self.token, "url": url, "ajax_wait": "true", "page_wait": "5000",
        })
        status = str(headers.get("cb_status") or headers.get("pc_status") or "200")
        if status != "200":
            raise ScrapeError(f"Rotten Tomatoes page did not render ({status})")
        return body or ""


def ratings(critics, audience):
    found = {}
    if critics is not None:
        found["tomatometerallcritics"] = {"value": critics, "votes": 0, "max": 100}
    if audience is not None:
        found["tomatometeravguseraudience"] = {"value": audience, "votes": 0, "max": 100}
    if not found:
        return None
    return {"source": "rottentomatoes", "ratings": found}


def parse_page(html):
    return {
        "critics": _slot(html, "criticsScore"),
        "audience": _slot(html, "audienceScore"),
    }


def _slot(html, slot):
    match = re.search(rf'<rt-text[^>]*slot="{slot}"[^>]*>(.*?)</rt-text>', html or "", re.I | re.S)
    if not match:
        return None
    text = re.sub(r"<[^>]+>", "", match.group(1))
    return _percent(text)


def _percent(value):
    match = re.search(r"(\d{1,3})", str(value or ""))
    if not match:
        return None
    number = int(match.group(1))
    return number if 0 <= number <= 100 else None


def search_hits(data, kind):
    hits = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            name = node.get("name") or node.get("title")
            url = node.get("url") or node.get("path") or ""
            critics = _score(node.get("meterScore"), node.get("criticsScore"), node.get("meter"))
            audience = _score(node.get("audienceScore"), node.get("audience"))
            if name and (url or critics is not None or audience is not None):
                key = (str(name), str(url))
                if key not in seen:
                    seen.add(key)
                    hits.append({
                        "name": str(name), "url": _absolute(url), "critics": critics, "audience": audience,
                        "year": _year(node), "kind": str(node.get("type") or node.get("mediaType") or kind),
                    })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data or {})
    return hits


def pick_hit(hits, title, year):
    wanted = _slug(title)
    if not wanted:
        import unicodedata
        normalized = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode("ascii")
        wanted = _slug(normalized)
    if not wanted:
        cleaned = re.sub(r"[\s\W]+", "", str(title or "").lower())
        if not cleaned:
            return None
        pool = [hit for hit in hits if re.sub(r"[\s\W]+", "", str(hit.get("name") or "").lower()) == cleaned]
    else:
        pool = [hit for hit in hits if _slug(hit.get("name") or "") == wanted or (_slug(hit.get("name") or "") and wanted in _slug(hit.get("name") or ""))]
    if not pool:
        return None
    if year:
        dated = [hit for hit in pool if hit.get("year") in {int(year), str(year)}]
        if dated:
            pool = dated
    return pool[0] if pool else None


def _score(*values):
    for value in values:
        if isinstance(value, dict):
            value = value.get("score") or value.get("value")
        number = _percent(value) if value is not None and value != "" else None
        if number is not None:
            return number
    return None


def _year(node):
    for key in ("year", "releaseYear", "startYear"):
        if node.get(key):
            return node.get(key)
    date = str(node.get("releaseDate") or node.get("startDate") or "")
    return date[:4] if len(date) >= 4 and date[:4].isdigit() else None


def _absolute(url):
    text = str(url or "")
    if not text:
        return ""
    if text.startswith("http"):
        return text
    return "https://www.rottentomatoes.com" + (text if text.startswith("/") else f"/{text}")


def _guess_url(kind, title):
    folder = "tv" if kind == "tv" else "m"
    return f"https://www.rottentomatoes.com/{folder}/{_slug(title)}"


def _slug(title):
    text = re.sub(r"[^a-z0-9]+", "_", str(title or "").lower()).strip("_")
    return quote(text, safe="_")
