from resonance.sources.client import get_json


def fetch(artist, title, album, duration):
    params = {
        "artist_name": artist or "",
        "track_name": title or "",
        "album_name": album or "",
    }
    if duration:
        params["duration"] = int(duration)
    data = get_json("https://lrclib.net/api/get", params)
    if not data:
        return None
    return {
        "synced": data.get("syncedLyrics") or "",
        "plain": data.get("plainLyrics") or "",
        "instrumental": bool(data.get("instrumental")),
    }
