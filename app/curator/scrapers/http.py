"""Async HTTP for the video scrapers: one pacing gate per host, 429 back-off and plain errors."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import httpx

USER_AGENT = "Curator/1.0"
# Seconds between request starts. TMDB allows ~40/s, TVDB and Fanart are friendlier when spaced.
SPACING = {
    "api.themoviedb.org": 0.03,
    "api4.thetvdb.com": 0.1,
    "www.omdbapi.com": 0.2,
    "api.trakt.tv": 0.35,
    "api.tvmaze.com": 0.25,
    "webservice.fanart.tv": 0.1,
    "www.rottentomatoes.com": 3.0,
    "www.metacritic.com": 3.0,
    "api.crawlbase.com": 3.0,
    "graphql.anilist.co": 1.0,
    "www.ofdb.de": 2.0,
}


class ScrapeError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Gate:
    def __init__(self, spacing):
        self.spacing = spacing
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self):
        async with self.lock:
            delay = self.next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = time.monotonic() + self.spacing

    def hold(self, seconds):
        self.next_at = max(self.next_at, time.monotonic() + seconds)


class Client:
    """Owned by one scrape job and one event loop. Gates are per host so sources run in parallel."""

    def __init__(self, timeout=20.0):
        self.http = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self.gates = {}

    async def close(self):
        await self.http.aclose()

    def gate(self, url):
        host = urlsplit(url).hostname or ""
        if host not in self.gates:
            self.gates[host] = Gate(SPACING.get(host, 0.1))
        return self.gates[host]

    async def json(self, method, url, *, params=None, headers=None, body=None, retries=2, missing_ok=True):
        gate = self.gate(url)
        for attempt in range(retries + 1):
            await gate.wait()
            try:
                response = await self.http.request(method, url, params=params, headers=headers, json=body)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    message = f"{urlsplit(url).hostname}: {exc.__class__.__name__}"
                    _connection(url, message)
                    raise ScrapeError(message) from exc
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= retries:
                    message = f"{urlsplit(url).hostname} answered {response.status_code}"
                    _connection(url, message)
                    raise ScrapeError(message, response.status_code)
                wait = _retry_after(response.headers.get("Retry-After"), 2.0 * (attempt + 1))
                gate.hold(wait)
                continue
            if response.status_code == 404 and missing_ok:
                return None
            if response.status_code in (401, 403):
                _connection(url, _message(response))
                raise ScrapeError(_message(response), response.status_code)
            if response.status_code >= 400:
                raise ScrapeError(_message(response), response.status_code)
            _connection(url, "", ok=True)
            try:
                return response.json()
            except ValueError as exc:
                raise ScrapeError(f"{urlsplit(url).hostname} sent something that is not JSON") from exc
        return None

    async def get(self, url, **kwargs):
        return await self.json("GET", url, **kwargs)

    async def text(self, url, *, params=None, headers=None, timeout=10.0):
        """GET a page as text. Returns (headers, body). Used for public rating pages."""
        gate = self.gate(url)
        for attempt in range(2):
            await gate.wait()
            try:
                response = await self.http.get(url, params=params, headers=headers, timeout=timeout)
            except httpx.HTTPError as exc:
                if attempt >= 1:
                    raise ScrapeError(f"{urlsplit(url).hostname}: {exc.__class__.__name__}") from exc
                await asyncio.sleep(1.0)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= 1:
                    raise ScrapeError(f"{urlsplit(url).hostname} answered {response.status_code}", response.status_code)
                gate.hold(_retry_after(response.headers.get("Retry-After"), 2.0 * (attempt + 1)))
                continue
            if response.status_code >= 400:
                raise ScrapeError(f"{urlsplit(url).hostname} answered {response.status_code}", response.status_code)
            return response.headers, response.text
        raise ScrapeError(f"{urlsplit(url).hostname} kept failing")

    async def download(self, url, limit=40 * 1024 * 1024):
        from resonance.memory import wait as wait_for_memory

        await asyncio.to_thread(wait_for_memory)
        gate = self.gate(url)
        for attempt in range(3):
            await gate.wait()
            try:
                async with self.http.stream("GET", url) as response:
                    if response.status_code == 429:
                        gate.hold(_retry_after(response.headers.get("Retry-After"), 3.0))
                        continue
                    if response.status_code >= 400:
                        raise ScrapeError(f"Image download failed ({response.status_code})", response.status_code)
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ScrapeError("Image is larger than 40 MB")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.HTTPError as exc:
                if attempt >= 2:
                    raise ScrapeError(f"Image download failed: {exc.__class__.__name__}") from exc
                await asyncio.sleep(1.5 * (attempt + 1))
        raise ScrapeError("Image download kept getting rate limited")


def _connection(url, message, ok=False):
    from resonance.connections import clear_url, note_url

    if ok:
        clear_url(url)
    else:
        note_url(url, message)


def _retry_after(value, default):
    try:
        return max(0.5, min(float(value), 30.0))
    except (TypeError, ValueError):
        return default


def _message(response):
    host = urlsplit(str(response.request.url)).hostname
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        text = data.get("status_message") or data.get("message") or data.get("Error") or data.get("error")
        if text:
            return f"{host}: {text}"
    if response.status_code == 401:
        return f"{host} rejected the API key"
    return f"{host} answered {response.status_code}"
