"""TheTVDB v4. Logs in with the project API key; supplies aired, DVD and absolute episode orders."""
from __future__ import annotations

import asyncio

from .http import ScrapeError
from .tmdb import _clean_ids, _unique, _year, pick

API = "https://api4.thetvdb.com/v4"
SEASON_TYPES = {"aired": "default", "dvd": "dvd", "absolute": "absolute"}
# /artwork/types ids for series and seasons.
SERIES_ART = {1: "banner", 2: "poster", 3: "fanart", 22: "clearart", 23: "clearlogo"}
SEASON_ART = {6: "banner", 7: "poster", 8: "fanart"}
LANGS = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "nl": "nld", "pt": "por", "sv": "swe",
         "da": "dan", "no": "nor", "fi": "fin", "pl": "pol", "ru": "rus", "ja": "jpn", "ko": "kor", "zh": "zho",
         "cs": "ces", "hu": "hun", "tr": "tur", "he": "heb", "el": "ell"}


class Tvdb:
    name = "tvdb"

    def __init__(self, client, key, language="en-US", pin=""):
        if not key:
            raise ScrapeError("No TVDB API key. Add one under Settings > General > API credentials.")
        self.client = client
        self.key = key
        self.pin = pin
        self.language = language
        self.lang = LANGS.get(language.split("-")[0], "eng")
        self.token = None
        self.lock = asyncio.Lock()

    def for_language(self, language):
        """A copy that asks TVDB in one item's language."""
        text = str(language or "").strip()
        if not text or text == self.language:
            return self
        return Tvdb(self.client, self.key, text, self.pin)

    async def _login(self):
        async with self.lock:
            if self.token:
                return
            body = {"apikey": self.key}
            if self.pin:
                body["pin"] = self.pin
            data = await self.client.json("POST", f"{API}/login", body=body, missing_ok=False)
            token = ((data or {}).get("data") or {}).get("token")
            if not token:
                raise ScrapeError("TVDB login failed. Check the API key.")
            self.token = token

    async def _get(self, path, params=None):
        await self._login()
        try:
            data = await self.client.get(f"{API}{path}", params=params,
                                         headers={"Authorization": f"Bearer {self.token}"})
        except ScrapeError as exc:
            if exc.status != 401:
                raise
            self.token = None
            await self._login()
            data = await self.client.get(f"{API}{path}", params=params,
                                         headers={"Authorization": f"Bearer {self.token}"})
        return (data or {}).get("data") if isinstance(data, dict) else None, data

    async def search_tv(self, query, year=None):
        return await self._search(query, year, "series")

    async def search_movie(self, query, year=None):
        return await self._search(query, year, "movie")

    async def _search(self, query, year, kind):
        params = {"query": query, "type": kind}
        if year:
            params["year"] = year
        rows, _ = await self._get("/search", params)
        prefix = "movie-" if kind == "movie" else "series-"
        hits = []
        for item in rows or []:
            translated = (item.get("translations") or {}).get(self.lang)
            raw = str(item.get("tvdb_id") or item.get("id") or "")
            tvdb_id = raw[len(prefix):] if raw.startswith(prefix) else raw
            ids = {"tvdb": tvdb_id} if tvdb_id else {}
            for remote in item.get("remote_ids") or []:
                source = str(remote.get("sourceName") or remote.get("source") or "").lower()
                value = str(remote.get("id") or "").strip()
                if not value:
                    continue
                if source == "imdb":
                    ids["imdb"] = value
                elif "moviedb" in source or source == "tmdb":
                    ids["tmdb"] = value
            hits.append({
                "source": "tvdb", "id": tvdb_id,
                "title": translated or item.get("name") or "", "original_title": item.get("name") or "",
                "year": _year(item.get("year") or item.get("first_air_time")),
                "overview": (item.get("overviews") or {}).get(self.lang) or item.get("overview") or "",
                "poster": item.get("image_url") or item.get("thumbnail") or "", "popularity": 0,
                "ids": ids,
            })
        return hits

    async def tv_id(self, ids, title=None, year=None):
        if ids.get("tvdb"):
            return str(ids["tvdb"])
        if ids.get("imdb"):
            rows, _ = await self._get(f"/search/remoteid/{ids['imdb']}")
            for item in rows or []:
                series = item.get("series")
                if series and series.get("id"):
                    return str(series["id"])
        if title:
            hits = await self.search_tv(title, year)
            best = pick(hits, title, year)
            if best:
                return best["id"]
        return None

    async def movie_id(self, ids, title=None, year=None):
        if ids.get("tvdb"):
            return str(ids["tvdb"])
        if ids.get("imdb"):
            rows, _ = await self._get(f"/search/remoteid/{ids['imdb']}")
            for item in rows or []:
                movie = item.get("movie")
                if movie and movie.get("id"):
                    return str(movie["id"])
        if title:
            hits = await self.search_movie(title, year)
            best = pick(hits, title, year)
            if best:
                return best["id"]
        return None

    async def movie(self, tvdb_id):
        """One movie, in the same shape as a TMDB movie result."""
        data, _ = await self._get(f"/movies/{tvdb_id}/extended", {"meta": "translations", "short": "false"})
        if not data:
            return None
        translations = data.get("translations") or {}
        name = _translation(translations.get("nameTranslations"), self.lang, "name") or data.get("name")
        overview = _translation(translations.get("overviewTranslations"), self.lang, "overview") or data.get("overview")
        remote = {}
        for item in data.get("remoteIds") or []:
            source = str(item.get("sourceName") or "").lower()
            if source == "imdb":
                remote["imdb"] = item.get("id")
            elif "moviedb" in source:
                remote["tmdb"] = item.get("id")
        actors = []
        for item in sorted(data.get("characters") or [], key=lambda row: row.get("sort") or 999):
            if item.get("type") != 3 or not item.get("personName"):
                continue
            actors.append({
                "name": item["personName"], "role": item.get("name") or "",
                "order": len(actors), "thumb": item.get("image") or item.get("personImgURL") or "",
            })
            if len(actors) >= 40:
                break
        art = []
        for item in data.get("artworks") or []:
            kind = SERIES_ART.get(item.get("type"))
            url = item.get("image") or ""
            if not kind or not url:
                continue
            art.append({
                "source": "tvdb", "kind": kind, "url": url, "lang": _short_lang(item.get("language")),
                "width": item.get("width") or 0, "height": item.get("height") or 0,
                "score": float(item.get("score") or 0) / 100000.0, "votes": 0,
            })
        year = _year(data.get("year"))
        premiered = _movie_premiered(data.get("releases"), year)
        studios = []
        for item in data.get("studios") or []:
            if isinstance(item, dict) and item.get("name"):
                studios.append(item["name"])
        country = _country(data.get("originalCountry"))
        return {
            "source": "tvdb",
            "ids": _clean_ids({"tvdb": str(data.get("id") or tvdb_id), **remote}),
            "title": name,
            "original_title": data.get("name") if name != data.get("name") else None,
            "year": year,
            "premiered": premiered,
            "plot": overview or None,
            "runtime_minutes": data.get("runtime") or None,
            "genres": [item["name"] for item in data.get("genres") or [] if isinstance(item, dict) and item.get("name")],
            "studios": _unique(studios),
            "original_language": _short_lang(data.get("originalLanguage")) or None,
            "countries": [country] if country else [],
            "actors": actors,
            "ratings": {},
            "art": art,
        } | _certificate(data.get("contentRatings"))

    async def series(self, tvdb_id):
        data, _ = await self._get(f"/series/{tvdb_id}/extended", {"meta": "translations", "short": "false"})
        if not data:
            return None
        translations = data.get("translations") or {}
        name = _translation(translations.get("nameTranslations"), self.lang, "name") or data.get("name")
        overview = _translation(translations.get("overviewTranslations"), self.lang, "overview") or data.get("overview")
        remote = {}
        for item in data.get("remoteIds") or []:
            source = str(item.get("sourceName") or "").lower()
            if source == "imdb":
                remote["imdb"] = item.get("id")
            elif "moviedb" in source:
                remote["tmdb"] = item.get("id")
        networks = [n.get("name") for n in (data.get("originalNetwork"), data.get("latestNetwork")) if n]
        actors = []
        for item in sorted(data.get("characters") or [], key=lambda c: c.get("sort") or 999):
            if item.get("type") != 3 or not item.get("personName"):
                continue
            actors.append({"name": item["personName"], "role": item.get("name") or "",
                           "order": len(actors), "thumb": item.get("image") or item.get("personImgURL") or ""})
            if len(actors) >= 40:
                break
        art, seasons = [], {}
        season_numbers = {}
        for item in data.get("seasons") or []:
            kind = ((item.get("type") or {}).get("type") or "official")
            if kind == "official" and item.get("number") is not None:
                season_numbers[item.get("id")] = item["number"]
                seasons.setdefault(item["number"], {
                    "title": item.get("name") or None, "plot": None, "premiered": None, "art": [],
                    "ids": _clean_ids({"tvdb": str(item.get("id") or "")}),
                })
        for item in data.get("artworks") or []:
            kind_id = item.get("type")
            candidate = {
                "source": "tvdb", "url": item.get("image") or "", "lang": _short_lang(item.get("language")),
                "width": item.get("width") or 0, "height": item.get("height") or 0,
                "score": float(item.get("score") or 0) / 100000.0, "votes": 0,
            }
            if not candidate["url"]:
                continue
            if kind_id in SERIES_ART:
                art.append({**candidate, "kind": SERIES_ART[kind_id]})
            elif kind_id in SEASON_ART and item.get("seasonId") in season_numbers:
                number = season_numbers[item["seasonId"]]
                seasons[number]["art"].append({**candidate, "kind": SEASON_ART[kind_id]})
        status = (data.get("status") or {}).get("name")
        return {
            "source": "tvdb",
            "ids": _clean_ids({"tvdb": str(data.get("id")), **remote}),
            "title": name,
            "original_title": data.get("name") if name != data.get("name") else None,
            "year": _year(data.get("firstAired") or data.get("year")),
            "premiered": data.get("firstAired") or None,
            "plot": overview or None,
            "tagline": data.get("tagline") or None,
            "show_status": {"Continuing": "Continuing", "Ended": "Ended", "Upcoming": "Upcoming"}.get(status, status),
            "runtime_minutes": data.get("averageRuntime") or None,
            "genres": [item["name"] for item in data.get("genres") or [] if item.get("name")],
            "studios": _unique(networks),
            "original_language": _short_lang(data.get("originalLanguage")) or None,
            "countries": [country] if (country := _country(data.get("originalCountry"))) else [],
            "actors": actors,
            "ratings": {},
            "seasons": seasons,
            "art": art,
        } | _certificate(data.get("contentRatings"))

    async def episodes(self, tvdb_id, order="aired"):
        season_type = SEASON_TYPES.get(order, "default")
        episodes, page = {}, 0
        while page is not None and page < 50:
            data, raw = await self._get(f"/series/{tvdb_id}/episodes/{season_type}/{self.lang}", {"page": page})
            for item in (data or {}).get("episodes") or []:
                season = item.get("seasonNumber")
                number = item.get("number")
                if order == "absolute":
                    season, number = 1, item.get("absoluteNumber") or number
                if season is None or number is None:
                    continue
                episodes[(int(season), int(number))] = {
                    "source": "tvdb",
                    "ids": _clean_ids({"tvdb": str(item.get("id") or "")}),
                    "title": item.get("name") or None,
                    "plot": item.get("overview") or None,
                    "aired": item.get("aired") or None,
                    "runtime_minutes": item.get("runtime") or None,
                    "ratings": {},
                    "art": [{"source": "tvdb", "kind": "thumb", "url": item["image"], "lang": "", "width": 0,
                             "height": 0, "score": 0.0, "votes": 0}] if item.get("image") else [],
                } | _certificate(item.get("contentRatings"))
            links = (raw or {}).get("links") or {}
            page = page + 1 if links.get("next") else None
        return episodes


_COUNTRIES = {
    "usa": "US", "gbr": "GB", "deu": "DE", "aus": "AU", "can": "CA", "fra": "FR",
    "nld": "NL", "jpn": "JP", "kor": "KR", "bra": "BR", "che": "CH", "irl": "IE",
    "nzl": "NZ", "swe": "SE", "nor": "NO", "dnk": "DK", "fin": "FI", "esp": "ES",
    "ita": "IT", "pol": "PL", "mex": "MX",
}


def _country(value):
    if isinstance(value, dict):
        value = value.get("name") or value.get("code") or value.get("id") or ""
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null"}:
        return ""
    mapped = _COUNTRIES.get(text.lower())
    if mapped:
        return mapped
    return text.upper() if len(text) <= 8 else ""


def _movie_premiered(releases, year):
    """A release date from the movie's own year. An unrelated first date is left out."""
    dates = []
    for item in releases or []:
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "").strip()
        if date:
            dates.append(date)
    if year:
        for date in dates:
            if date.startswith(str(year)):
                return date
    return None


def _certificate(items):
    """TVDB contentRatings into mpaa plus a country map. US wins the single mpaa line."""
    found = {}
    for item in items or []:
        name = str(item.get("name") or "").strip()
        country = _COUNTRIES.get(str(item.get("country") or "").lower())
        if not country:
            raw = str(item.get("country") or "").strip().upper()
            country = raw if len(raw) == 2 else ""
        if name and country:
            found.setdefault(country, name)
    if not found:
        return {}
    return {"mpaa": found.get("US") or next(iter(found.values())), "certifications": found}


def _translation(items, lang, key):
    for item in items or []:
        if item.get("language") == lang and item.get(key):
            return item[key]
    return None


def _short_lang(code):
    code = str(code or "").lower()
    for short, long in LANGS.items():
        if long == code:
            return short
    return code[:2] if code else ""
