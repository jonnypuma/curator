"""Fanart.tv v3 movie and TV artwork. Fanart.tv publishes fixed sizes per type, so widths are known up front."""
from __future__ import annotations

API = "https://webservice.fanart.tv/v3"
MOVIE_TYPES = {
    "movieposter": ("poster", 1000, 1426), "moviebackground": ("fanart", 1920, 1080),
    "hdmovielogo": ("clearlogo", 800, 310), "movielogo": ("clearlogo", 400, 155),
    "hdmovieclearart": ("clearart", 1000, 562), "movieart": ("clearart", 500, 281),
    "moviedisc": ("discart", 1000, 1000), "moviebanner": ("banner", 1000, 185),
    "moviethumb": ("landscape", 1000, 562), "moviesquare": ("squareart", 1000, 1000),
}
TV_TYPES = {
    "tvposter": ("poster", 1000, 1426), "showbackground": ("fanart", 1920, 1080),
    "hdtvlogo": ("clearlogo", 800, 310), "clearlogo": ("clearlogo", 400, 155),
    "hdclearart": ("clearart", 1000, 562), "clearart": ("clearart", 500, 281),
    "tvbanner": ("banner", 1000, 185), "tvthumb": ("landscape", 1000, 562),
    "characterart": ("characterart", 512, 512), "tvsquare": ("squareart", 1000, 1000),
}
SEASON_TYPES = {
    "seasonposter": ("poster", 1000, 1426), "seasonbanner": ("banner", 1000, 185),
    "seasonthumb": ("landscape", 1000, 562),
}


class Fanart:
    name = "fanart"

    def __init__(self, client, key):
        self.client = client
        self.key = key

    async def movie(self, ids):
        key = ids.get("tmdb") or ids.get("imdb")
        if not self.key or not key:
            return []
        data = await self.client.get(f"{API}/movies/{key}", params={"api_key": self.key})
        return parse(data, MOVIE_TYPES)[0]

    async def collection(self, collection_id):
        """Fanart.tv files movie set art under the TMDB collection id on its movie endpoint."""
        if not self.key or not collection_id:
            return []
        data = await self.client.get(f"{API}/movies/{collection_id}", params={"api_key": self.key})
        return parse(data, MOVIE_TYPES)[0]

    async def tv(self, ids):
        if not self.key or not ids.get("tvdb"):
            return [], {}
        data = await self.client.get(f"{API}/tv/{ids['tvdb']}", params={"api_key": self.key})
        return parse(data, TV_TYPES, SEASON_TYPES)


def parse(data, types, season_types=None):
    show, seasons = [], {}
    if not isinstance(data, dict):
        return show, seasons
    for block, (kind, width, height) in {**types, **(season_types or {})}.items():
        for item in data.get(block) or []:
            if not item.get("url"):
                continue
            lang = item.get("lang") or ""
            candidate = {
                "source": "fanart", "kind": kind, "url": item["url"], "lang": "" if lang in {"00", "none"} else lang,
                "width": width, "height": height, "score": float(item.get("likes") or 0), "votes": 0,
            }
            if season_types and block in season_types:
                raw = str(item.get("season") or "")
                if raw == "all" or not raw.isdigit():
                    continue
                seasons.setdefault(int(raw), []).append(candidate)
            else:
                show.append(candidate)
    return show, seasons
