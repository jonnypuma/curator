"""TMDB v3 API. Accepts a v3 API key or a v4 read access token (sent as a bearer token)."""
from __future__ import annotations

import re

from .http import ScrapeError

API = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p/original"
PROFILE = "https://image.tmdb.org/t/p/h632"
WRITING_JOBS = {"screenplay", "writer", "story", "novel", "author", "teleplay", "characters", "adaptation"}


class Tmdb:
    name = "tmdb"

    def __init__(self, client, key, language="en-US", country="US"):
        if not key:
            raise ScrapeError("No TMDB API key. Add one under Settings > General > API credentials.")
        self.client = client
        self.key = key
        self.language = language
        self.lang = language.split("-")[0]
        self.country = country
        self.art_languages = []

    def for_language(self, language):
        """A copy that asks TMDB in one item's language. Artwork language order stays the same."""
        text = str(language or "").strip()
        if not text or text == self.language:
            return self
        other = Tmdb(self.client, self.key, text, self.country)
        other.art_languages = list(self.art_languages or [])
        return other

    def _auth(self, params):
        params = dict(params or {})
        headers = {"Accept": "application/json"}
        if len(self.key) > 40:
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        return params, headers

    async def _get(self, path, params=None):
        params, headers = self._auth(params)
        return await self.client.get(f"{API}{path}", params=params, headers=headers)

    # Search and lookup.

    async def search_movie(self, query, year=None):
        params = {"query": query, "language": self.language, "include_adult": "false"}
        if year:
            params["year"] = year
        data = await self._get("/search/movie", params) or {}
        return [_hit(item, "title", "release_date") for item in data.get("results") or []]

    async def search_tv(self, query, year=None):
        params = {"query": query, "language": self.language, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = await self._get("/search/tv", params) or {}
        return [_hit(item, "name", "first_air_date") for item in data.get("results") or []]

    async def search_collection(self, query):
        params = {"query": query, "language": self.language, "include_adult": "false"}
        data = await self._get("/search/collection", params) or {}
        return [_hit(item, "name", "release_date") for item in data.get("results") or []]

    async def find(self, external_id, source="imdb_id"):
        data = await self._get(f"/find/{external_id}", {"external_source": source}) or {}
        return data

    async def movie_id(self, ids, title=None, year=None):
        if ids.get("tmdb"):
            return str(ids["tmdb"])
        if ids.get("imdb"):
            found = (await self.find(ids["imdb"])).get("movie_results") or []
            if found:
                return str(found[0]["id"])
        if ids.get("tvdb"):
            found = (await self.find(ids["tvdb"], "tvdb_id")).get("movie_results") or []
            if found:
                return str(found[0]["id"])
        if title:
            hits = await self.search_movie(title, year)
            if not hits and year:
                hits = await self.search_movie(title)
            best = pick(hits, title, year)
            if best:
                return best["id"]
        return None

    async def tv_id(self, ids, title=None, year=None):
        if ids.get("tmdb"):
            return str(ids["tmdb"])
        for key, source in (("tvdb", "tvdb_id"), ("imdb", "imdb_id")):
            if ids.get(key):
                found = (await self.find(ids[key], source)).get("tv_results") or []
                if found:
                    return str(found[0]["id"])
        if title:
            hits = await self.search_tv(title, year)
            if not hits and year:
                hits = await self.search_tv(title)
            best = pick(hits, title, year)
            if best:
                return best["id"]
        return None

    # Details.

    def _image_params(self):
        codes = []
        for item in self.art_languages or []:
            text = str(item or "").strip().lower()
            if not text:
                continue
            token = "null" if text in {"none", "textless", "null"} else text.split("-")[0][:2]
            if token not in codes:
                codes.append(token)
        if not codes:
            return f"{self.lang},en,null"
        if "null" not in codes:
            codes.append("null")
        return ",".join(codes)

    async def movie(self, tmdb_id):
        data = await self._get(f"/movie/{tmdb_id}", {
            "language": self.language,
            "append_to_response": "credits,release_dates,external_ids,images,videos,keywords,translations",
            "include_image_language": self._image_params(),
            "include_video_language": f"{self.lang},en",
        })
        if not data:
            return None
        credits = data.get("credits") or {}
        crew = credits.get("crew") or []
        collection = data.get("belongs_to_collection") or None
        imdb = data.get("imdb_id") or (data.get("external_ids") or {}).get("imdb_id")
        result = {
            "source": "tmdb",
            "ids": _clean_ids({"tmdb": str(data["id"]), "imdb": imdb}),
            "title": data.get("title"),
            "original_title": data.get("original_title"),
            "english_title": _english_title(data, "title"),
            "year": _year(data.get("release_date")),
            "premiered": data.get("release_date") or None,
            "plot": data.get("overview") or None,
            "tagline": data.get("tagline") or None,
            "runtime_minutes": data.get("runtime") or None,
            "mpaa": self._movie_certification(data.get("release_dates") or {}),
            "certifications": self._movie_certifications(data.get("release_dates") or {}),
            "genres": [item["name"] for item in data.get("genres") or [] if item.get("name")],
            "countries": [item["name"] for item in data.get("production_countries") or [] if item.get("name")],
            "studios": _unique(item["name"] for item in data.get("production_companies") or [] if item.get("name")),
            "languages": [item.get("english_name") or item.get("name") for item in data.get("spoken_languages") or []
                          if item.get("english_name") or item.get("name")],
            "original_language": data.get("original_language") or None,
            "directors": _unique(item["name"] for item in crew if item.get("job") == "Director"),
            "writers": _unique(item["name"] for item in crew if str(item.get("job", "")).lower() in WRITING_JOBS),
            "producers": _unique(item["name"] for item in crew if item.get("job") == "Producer"),
            "actors": _cast(credits.get("cast") or []),
            "tags": [item["name"] for item in (data.get("keywords") or {}).get("keywords") or []],
            "trailer": _trailer((data.get("videos") or {}).get("results") or [], self.lang),
            "ratings": _rating("themoviedb", data.get("vote_average"), data.get("vote_count")),
            "set": {"name": collection["name"], "tmdb_id": str(collection["id"]), "overview": ""}
            if collection and collection.get("name") else None,
            "art": _art(data.get("images") or {}, {"posters": "poster", "backdrops": "fanart", "logos": "clearlogo"}),
        }
        return result

    def _movie_certification(self, block):
        for entry in block.get("results") or []:
            if entry.get("iso_3166_1") != self.country:
                continue
            dates = sorted(entry.get("release_dates") or [], key=lambda item: (item.get("type") != 3, item.get("type")))
            for item in dates:
                if item.get("certification"):
                    return _certification(self.country, item["certification"])
        return None

    def _movie_certifications(self, block):
        found = {}
        for entry in block.get("results") or []:
            code = (entry.get("iso_3166_1") or "").upper()
            dates = sorted(entry.get("release_dates") or [], key=lambda item: (item.get("type") != 3, item.get("type")))
            for item in dates:
                if code and item.get("certification"):
                    found[code] = str(item["certification"]).strip()
                    break
        return found

    async def collection(self, collection_id, images=False):
        data = await self._get(f"/collection/{collection_id}", {"language": self.language})
        if not data:
            return None
        found = {"name": data.get("name"), "overview": data.get("overview") or "", "tmdb_id": str(collection_id),
                 "parts": collection_parts(data)}
        if images:
            pictures = await self._get(f"/collection/{collection_id}/images",
                                       {"include_image_language": self._image_params()}) or {}
            found["art"] = _art(pictures, {"posters": "poster", "backdrops": "fanart"})
        return found

    async def tv(self, tmdb_id):
        data = await self._get(f"/tv/{tmdb_id}", {
            "language": self.language,
            "append_to_response": "aggregate_credits,external_ids,images,content_ratings,keywords,videos,translations",
            "include_image_language": self._image_params(),
            "include_video_language": f"{self.lang},en",
        })
        if not data:
            return None
        external = data.get("external_ids") or {}
        credits = data.get("aggregate_credits") or {}
        crew = credits.get("crew") or []
        directors = _unique(item["name"] for item in crew if item.get("job") == "Director")
        if not directors:
            directors = _unique(item["name"] for item in (data.get("created_by") or []) if item.get("name"))
        cast = []
        for item in credits.get("cast") or []:
            roles = item.get("roles") or [{}]
            cast.append({**item, "character": roles[0].get("character") or ""})
        seasons = {}
        for item in data.get("seasons") or []:
            number = item.get("season_number")
            if number is None:
                continue
            seasons[number] = {
                "title": item.get("name") or None, "plot": item.get("overview") or None,
                "premiered": item.get("air_date") or None,
                "episode_count": item.get("episode_count") or None,
                "ids": _clean_ids({"tmdb": str(item.get("id") or "")}),
                "art": [_candidate(item["poster_path"], "poster", None, None, None, 0, 0)]
                if item.get("poster_path") else [],
            }
        runtimes = data.get("episode_run_time") or []
        keywords = (data.get("keywords") or {}).get("results") or []
        return {
            "source": "tmdb",
            "ids": _clean_ids({"tmdb": str(data["id"]), "imdb": external.get("imdb_id"),
                               "tvdb": external.get("tvdb_id")}),
            "title": data.get("name"),
            "original_title": data.get("original_name"),
            "english_title": _english_title(data, "name", "title"),
            "year": _year(data.get("first_air_date")),
            "premiered": data.get("first_air_date") or None,
            "plot": data.get("overview") or None,
            "tagline": data.get("tagline") or None,
            "show_status": data.get("status") or None,
            "runtime_minutes": runtimes[0] if runtimes else None,
            "mpaa": self._tv_certification(data.get("content_ratings") or {}),
            "certifications": self._tv_certifications(data.get("content_ratings") or {}),
            "genres": [item["name"] for item in data.get("genres") or [] if item.get("name")],
            "studios": _unique(item["name"] for item in data.get("networks") or [] if item.get("name")),
            "countries": [item["name"] for item in data.get("production_countries") or [] if item.get("name")],
            "original_language": data.get("original_language") or None,
            "directors": directors,
            "actors": _cast(cast),
            "tags": [item["name"] for item in keywords if item.get("name")],
            "trailer": _trailer((data.get("videos") or {}).get("results") or [], self.lang),
            "ratings": _rating("themoviedb", data.get("vote_average"), data.get("vote_count")),
            "season_names": {str(number): info["title"] for number, info in seasons.items() if info["title"]},
            "seasons": seasons,
            "art": _art(data.get("images") or {}, {"posters": "poster", "backdrops": "fanart", "logos": "clearlogo"}),
        }

    def _tv_certification(self, block):
        for entry in block.get("results") or []:
            if entry.get("iso_3166_1") == self.country and entry.get("rating"):
                return _certification(self.country, entry["rating"])
        return None

    def _tv_certifications(self, block):
        found = {}
        for entry in block.get("results") or []:
            code = (entry.get("iso_3166_1") or "").upper()
            if code and entry.get("rating"):
                found[code] = str(entry["rating"]).strip()
        return found

    async def episode(self, tmdb_id, season, number):
        data = await self._get(f"/tv/{tmdb_id}/season/{season}/episode/{number}", {"language": self.language})
        return _episode(data) if data else None

    async def episode_stills(self, tmdb_id, season, episode):
        data = await self._get(f"/tv/{tmdb_id}/season/{season}/episode/{episode}/images")
        return _art(data or {}, {"stills": "thumb"})

    async def season(self, tmdb_id, number):
        data = await self._get(f"/tv/{tmdb_id}/season/{number}", {
            "language": self.language, "append_to_response": "images,videos",
            "include_image_language": self._image_params(),
        })
        if not data:
            return None
        episodes = {item.get("episode_number"): _episode(item) for item in data.get("episodes") or []
                    if item.get("episode_number") is not None}
        return {
            "title": data.get("name") or None, "plot": data.get("overview") or None,
            "premiered": data.get("air_date") or None,
            "ids": _clean_ids({"tmdb": str(data.get("id") or "")}),
            "episode_count": len(episodes) or None,
            "episode_numbers": sorted(episodes),
            "episodes": episodes,
            "trailer": _trailer((data.get("videos") or {}).get("results") or [], self.lang),
            "art": _art(data.get("images") or {}, {"posters": "poster"}),
        }

    async def season_images(self, tmdb_id, number):
        """Season posters only. Used when the full season payload is not being read."""
        data = await self._get(f"/tv/{tmdb_id}/season/{number}/images", {
            "include_image_language": self._image_params(),
        })
        return {"art": _art(data or {}, {"posters": "poster"})}

    async def episode_group(self, tmdb_id, order):
        """DVD or absolute numbering from a TMDB episode group, keyed (season, episode). None when TMDB has none.

        This is what lets DVD and absolute order work without a TheTVDB key.
        """
        kind = GROUP_TYPES.get(order)
        if not kind:
            return None
        listing = await self._get(f"/tv/{tmdb_id}/episode_groups") or {}
        groups = [item for item in listing.get("results") or [] if item.get("type") == kind and item.get("id")]
        if not groups:
            return None
        best = max(groups, key=lambda item: (item.get("episode_count") or 0, -(item.get("group_count") or 0)))
        data = await self._get(f"/tv/episode_group/{best['id']}", {"language": self.language})
        return group_numbers(data, order) if data else None


GROUP_TYPES = {"absolute": 2, "dvd": 3}
_GROUP_SEASON = re.compile(r"(?:season|series|volume|disc|staffel|saison|temporada)\s*(\d{1,3})", re.I)
_GROUP_SPECIALS = re.compile(r"special|extra|ova|bonus", re.I)


def group_numbers(data, order):
    """Map a TMDB episode group to {(season, episode): episode}. Absolute order is season 1, running numbers."""
    found = {}
    groups = sorted(data.get("groups") or [], key=lambda item: item.get("order") or 0)
    running = 0
    for group in groups:
        name = str(group.get("name") or "")
        episodes = sorted(group.get("episodes") or [], key=lambda item: item.get("order") or 0)
        if order == "absolute":
            if _GROUP_SPECIALS.search(name):
                continue
            for item in episodes:
                running += 1
                found[(1, running)] = _episode(item)
            continue
        match = _GROUP_SEASON.search(name)
        if match:
            season = int(match.group(1))
        elif _GROUP_SPECIALS.search(name):
            season = 0
        else:
            season = int(group.get("order") or 0)
        for index, item in enumerate(episodes, start=1):
            found[(season, index)] = _episode(item)
    return found


def _episode(item):
    crew = item.get("crew") or []
    return {
        "source": "tmdb",
        "ids": _clean_ids({"tmdb": str(item.get("id") or "")}),
        "title": item.get("name") or None,
        "original_title": item.get("original_name") or None,
        "english_title": _english_title(item, "name"),
        "plot": item.get("overview") or None,
        "aired": item.get("air_date") or None,
        "runtime_minutes": item.get("runtime") or None,
        "directors": _unique(c["name"] for c in crew if c.get("job") == "Director"),
        "writers": _unique(c["name"] for c in crew if str(c.get("job", "")).lower() in WRITING_JOBS),
        "guest_stars": _cast(item.get("guest_stars") or [], limit=20),
        "ratings": _rating("themoviedb", item.get("vote_average"), item.get("vote_count")),
        "art": [_candidate(item["still_path"], "thumb", None, None, None, 0, 0)]
        if item.get("still_path") else [],
    }


def _hit(item, title_key, date_key):
    poster = item.get("poster_path")
    return {
        "source": "tmdb", "id": str(item.get("id")), "title": item.get(title_key) or "",
        "original_title": item.get(f"original_{title_key}") or "",
        "year": _year(item.get(date_key)), "overview": item.get("overview") or "",
        "poster": f"https://image.tmdb.org/t/p/w185{poster}" if poster else "",
        "popularity": item.get("popularity") or 0,
        "ids": {"tmdb": str(item.get("id"))} if item.get("id") else {},
    }


def pick(hits, title, year):
    """The confident match, or None. Exact title plus a year within one wins; otherwise the top hit when alone."""
    wanted = _fold(title)
    for hit in hits:
        same = _fold(hit["title"]) == wanted or _fold(hit.get("original_title")) == wanted
        if same and (not year or not hit["year"] or abs(int(hit["year"]) - int(year)) <= 1):
            return hit
    if len(hits) == 1 and (not year or not hits[0]["year"] or abs(int(hits[0]["year"]) - int(year)) <= 1):
        return hits[0]
    return None


def _fold(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _year(date):
    text = str(date or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None


def _unique(names):
    seen = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


def _english_title(data, *keys):
    """English title when the source has one that is not the title already chosen."""
    current = ""
    for key in keys:
        current = str(data.get(key) or "").strip()
        if current:
            break
    for item in (data.get("translations") or {}).get("translations") or []:
        if item.get("iso_639_1") != "en":
            continue
        payload = item.get("data") or {}
        for key in keys:
            text = str(payload.get(key) or "").strip()
            if text and text != current:
                return text
    return None


def _clean_ids(ids):
    return {key: str(value) for key, value in ids.items() if value not in (None, "", "None")}


def _rating(name, value, votes):
    if not value or not votes:
        return {}
    return {name: {"value": round(float(value), 1), "votes": int(votes), "max": 10}}


def _cast(cast, limit=40):
    actors = []
    for index, item in enumerate(sorted(cast, key=lambda c: c.get("order", 999))[:limit]):
        if not item.get("name"):
            continue
        profile = item.get("profile_path")
        actors.append({
            "name": item["name"], "role": item.get("character") or "",
            "order": item.get("order", index), "thumb": f"{PROFILE}{profile}" if profile else "",
        })
    return actors


def _trailer(videos, lang):
    def rank(item):
        return (item.get("iso_639_1") != lang, not item.get("official"), item.get("type") != "Trailer")

    for item in sorted(videos, key=rank):
        if item.get("site") == "YouTube" and item.get("type") in {"Trailer", "Teaser"} and item.get("key"):
            return f"plugin://plugin.video.youtube/play/?video_id={item['key']}"
    return None


def _certification(country, value):
    value = str(value).strip()
    if not value:
        return None
    return f"Rated {value}" if country == "US" and not value.lower().startswith("rated") else value


def _candidate(path, kind, lang, width, height, score, votes):
    return {
        "source": "tmdb", "kind": kind, "url": f"{IMAGE}{path}", "lang": lang or "",
        "width": width or 0, "height": height or 0, "score": float(score or 0), "votes": int(votes or 0),
    }


def collection_parts(data):
    parts = []
    for item in (data or {}).get("parts") or []:
        if not item.get("id") or not item.get("title"):
            continue
        date = item.get("release_date") or ""
        parts.append({
            "tmdb_id": str(item["id"]),
            "title": item["title"],
            "year": int(date[:4]) if date[:4].isdigit() else None,
            "release_date": date,
            "overview": item.get("overview") or "",
            "poster": f"https://image.tmdb.org/t/p/w342{item['poster_path']}" if item.get("poster_path") else "",
        })
    parts.sort(key=lambda part: (part["release_date"] or "9999", part["title"].lower()))
    return parts


def _art(images, kinds):
    candidates = []
    for block, kind in kinds.items():
        for item in images.get(block) or []:
            if not item.get("file_path"):
                continue
            candidates.append(_candidate(item["file_path"], kind, item.get("iso_639_1"), item.get("width"),
                                         item.get("height"), item.get("vote_average"), item.get("vote_count")))
    return candidates
