from urllib.parse import quote, unquote, urlsplit

from resonance.sources.client import get_json


def from_url(url):
    """Summary of a Wikipedia page already linked to this artist."""
    if not url or "wikipedia.org" not in url:
        return None
    parts = urlsplit(url)
    marker = "/wiki/"
    if marker not in (parts.path or ""):
        return None
    title = unquote(parts.path.split(marker, 1)[1]).strip("/")
    if not title or title.lower().startswith("special:"):
        return None
    host = (parts.netloc or "en.wikipedia.org").lower()
    if host.startswith("www."):
        host = host[4:]
    page = get_json(f"https://{host}/api/rest_v1/page/summary/{quote(title)}")
    return usable(page)


def for_artist(name, url="", hint=""):
    """Summary for one artist. A MusicBrainz Wikipedia link wins over a name search."""
    linked = from_url(url) if url else None
    if linked:
        return linked
    query = " ".join(part for part in (str(name or "").strip(), str(hint or "").strip()) if part)
    return summary(query)


def summary(query):
    if not query:
        return None
    search = get_json(
        "https://en.wikipedia.org/w/api.php",
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
        },
    )
    hits = ((search or {}).get("query") or {}).get("search") or []
    for hit in hits:
        title = hit.get("title")
        if not title:
            continue
        page = get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}")
        text = usable(page)
        if text:
            return text
    return None


def usable(page):
    if not isinstance(page, dict):
        return None
    if str(page.get("type") or "").lower() == "disambiguation":
        return None
    extract = str(page.get("extract") or "").strip()
    if len(extract) < 80:
        return None
    from resonance.sources.lastfm import is_disambiguation

    if is_disambiguation(extract):
        return None
    return extract[:8000]
