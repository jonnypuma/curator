from resonance.sources.client import get_json

API = "https://www.theaudiodb.com/api/v1/json/2"


def artist_by_mbid(mbid):
    if not mbid:
        return None
    data = get_json(f"{API}/artist-mb.php", {"i": mbid})
    artists = (data or {}).get("artists") or []
    return artists[0] if artists else None


def album_by_mbid(release_group_id):
    if not release_group_id:
        return None
    data = get_json(f"{API}/album-mb.php", {"i": release_group_id})
    albums = (data or {}).get("album") or []
    return albums[0] if albums else None
