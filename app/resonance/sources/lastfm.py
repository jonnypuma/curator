import re
from html import unescape

from resonance import settings
from resonance.sources.client import get_json

SIZES = [
    ("mega", 600),
    ("extralarge", 300),
    ("large", 174),
    ("medium", 64),
    ("small", 34),
]


def _largest(images):
    if not images:
        return None, None
    ranked = {item.get("size"): item.get("#text") for item in images if item.get("#text")}
    for name, edge in SIZES:
        if ranked.get(name):
            return ranked[name], edge
    return None, None


def album_image(artist, title):
    key = (settings.load().get("lastfm_key") or "").strip()
    if not key or not artist or not title:
        return None
    data = get_json(
        "https://ws.audioscrobbler.com/2.0/",
        {"method": "album.getinfo", "api_key": key, "artist": artist, "album": title, "format": "json"},
    )
    album = (data or {}).get("album") or {}
    url, edge = _largest(album.get("image"))
    if not url:
        return None
    return {"url": url, "edge": edge}


def album_text(artist, title):
    """Review and tags from album.getInfo. Empty when the API key is missing."""
    key = (settings.load().get("lastfm_key") or "").strip()
    if not key or not artist or not title:
        return {}
    data = get_json(
        "https://ws.audioscrobbler.com/2.0/",
        {"method": "album.getinfo", "api_key": key, "artist": artist, "album": title, "autocorrect": "1", "format": "json"},
    )
    album = (data or {}).get("album") or {}
    wiki = album.get("wiki") or {}
    review = formatted_bio(wiki.get("content") or wiki.get("summary") or "")
    return {"review": review or None, "tags": tag_names(album.get("tags"))}


def tag_names(payload):
    raw = payload.get("tag") if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw = [raw]
    names = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name and name.lower() not in {existing.lower() for existing in names}:
            names.append(name)
    return names[:12]


def artist_bio(name, mbid=None):
    artist = artist_info(name, mbid)
    bio = artist.get("bio") or {}
    return plain_bio(bio.get("content") or bio.get("summary") or "")


def artist_info(name, mbid=None):
    """Last.fm artist.getInfo payload, or an empty dict when the key is missing."""
    key = (settings.load().get("lastfm_key") or "").strip()
    if not key or not (mbid or name):
        return {}
    params = {"method": "artist.getinfo", "api_key": key, "format": "json"}
    if mbid:
        params["mbid"] = str(mbid)
    else:
        params["artist"] = name
        params["autocorrect"] = "1"
    data = get_json("https://ws.audioscrobbler.com/2.0/", params)
    return (data or {}).get("artist") or {}


def is_disambiguation(text):
    """True when the text lists several different artists that share a name."""
    sample = str(text or "").lower()
    if (
        "may refer to" in sample
        or "can refer to" in sample
        or "multiple artists" in sample
        or "there are several artists" in sample
        or "artists with this name" in sample
        or "artists that use this name" in sample
        or "artists who have used this name" in sample
        or "who have used this name" in sample
        or "have used this name" in sample
    ):
        return True
    return bool(re.search(
        r"there are (at least )?(?:\d+|two|three|four|five|six|seven|eight|nine|ten|several) artists",
        sample,
    ))


def plain_bio(html):
    text = formatted_bio(html)
    if is_disambiguation(text) or len(text) < 80:
        return None
    return text[:8000]


def formatted_bio(value):
    """Turn source HTML into paragraphs without flattening the line breaks."""
    text = str(value or "")
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|h[1-6]|li|tr)\s*>", "\n\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    text = re.split(r"User-contributed text is available", text, maxsplit=1)[0].strip()
    text = re.sub(r"\s*Read more on Last\.fm\.?\s*$", "", text, flags=re.IGNORECASE).strip()
    return text


def artist_image(name):
    key = (settings.load().get("lastfm_key") or "").strip()
    if not key or not name:
        return None
    data = get_json(
        "https://ws.audioscrobbler.com/2.0/",
        {"method": "artist.getinfo", "api_key": key, "artist": name, "format": "json"},
    )
    artist = (data or {}).get("artist") or {}
    url, edge = _largest(artist.get("image"))
    if not url:
        return None
    return {"url": url, "edge": edge}


def configured():
    return bool((settings.load().get("lastfm_key") or "").strip())
