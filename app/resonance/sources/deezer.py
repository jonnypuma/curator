from resonance.fields import norm_name
from resonance.sources.client import get_json


def lookup_album(artist, title):
    query = " ".join(part for part in (artist, title) if part)
    if not query:
        return None
    data = get_json("https://api.deezer.com/search/album", {"q": query})
    items = (data or {}).get("data") or []
    if not items:
        return None
    album = items[0]
    detail = get_json(f"https://api.deezer.com/album/{album.get('id')}") or album
    tracks = ((detail.get("tracks") or {}).get("data")) or []
    return {
        "id": album.get("id"),
        "title": detail.get("title") or album.get("title"),
        "artist": ((detail.get("artist") or album.get("artist") or {}).get("name")),
        "cover_url": detail.get("cover_xl") or album.get("cover_xl") or album.get("cover_big"),
        "track_count": detail.get("nb_tracks") or album.get("nb_tracks") or len(tracks),
        "tracks": [
            {"title": track.get("title") or "", "preview": track.get("preview") or ""}
            for track in tracks
        ],
    }


def compare(local_titles, remote):
    if not remote:
        return {"available": False, "matches": 0, "total": len(local_titles)}
    titles = [_track_title(item) for item in remote.get("tracks") or []]
    remote_keys = {norm_name(title) for title in titles if norm_name(title)}
    matches = sum(1 for title in local_titles if norm_name(title) and norm_name(title) in remote_keys)
    previews = []
    for item in remote.get("tracks") or []:
        if isinstance(item, dict) and item.get("preview"):
            previews.append({"title": item.get("title") or "", "preview": item.get("preview")})
    return {
        "available": True,
        "title": remote.get("title"),
        "artist": remote.get("artist"),
        "matches": matches,
        "total": len(local_titles),
        "cover_url": remote.get("cover_url"),
        "previews": previews,
    }


def _track_title(item):
    if isinstance(item, dict):
        return item.get("title") or ""
    return item or ""


def artist_image(name):
    if not name:
        return None
    data = get_json("https://api.deezer.com/search/artist", {"q": name})
    items = (data or {}).get("data") or []
    if not items:
        return None
    return items[0].get("picture_xl") or items[0].get("picture_big")
