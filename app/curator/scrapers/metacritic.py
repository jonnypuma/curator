"""Metascore and user score for a movie or show already in the library.

Reads the public title page. When that HTML has no scores, a Crawlbase JS token
loads the rendered page. The fields kept are the critic Metascore and the user score.
"""
from __future__ import annotations

import re

from .http import ScrapeError

CRAWLBASE = "https://api.crawlbase.com/"
BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class Metacritic:
    name = "metacritic"

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
        for slug in _slugs(title, year):
            url = f"https://www.metacritic.com/{kind}/{slug}/"
            parsed = parse_page(await self._direct(url))
            if not parsed and self.token:
                parsed = parse_page(await self._rendered(url))
            if parsed:
                return parsed
        return None

    async def _direct(self, url):
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
            raise ScrapeError(f"Metacritic page did not render ({status})")
        return body or ""


def parse_page(html):
    text = html or ""
    critics = _group(r'"metascore"\s*:\s*\{[^}]{0,200}"score"\s*:\s*(\d{1,3})', text)
    if critics is None:
        critics = _group(r'Metascore[^0-9]{0,40}(\d{1,3})', text)
    user = _group(r'"user_score"\s*:\s*\{[^}]{0,200}"score"\s*:\s*(\d+(?:\.\d+)?)', text)
    if user is None:
        user = _group(r'"userScore"\s*:\s*"?(\d+(?:\.\d+)?)', text)
    ratings = {}
    if critics is not None and 0 <= critics <= 100:
        ratings["metacritic"] = {"value": int(critics), "votes": 0, "max": 100}
    if user is not None and 0 <= user <= 10:
        ratings["metacriticuser"] = {"value": round(float(user), 1), "votes": 0, "max": 10}
    if not ratings:
        return None
    return {"source": "metacritic", "ratings": ratings}


def _group(pattern, text):
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _slugs(title, year):
    base = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
    found = []
    if base:
        found.append(base)
    if base and year:
        found.append(f"{base}-{int(year)}")
    return found
