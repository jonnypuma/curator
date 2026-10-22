"""Bazarr API: ask it to search the subtitles it already lists as missing.

Bazarr only knows movies that are in Radarr and shows that are in Sonarr. Curator looks those up
and does not add anything.
"""
from resonance.errors import AppError


def _settings():
    from resonance import settings

    cfg = settings.load()
    url = str(cfg.get("bazarr_url") or "").strip().rstrip("/")
    key = str(cfg.get("bazarr_api_key") or "").strip()
    return url, key


def _api(method, path, url, key, params=None, timeout=30):
    import requests

    from resonance.connections import clear, note

    if not url or not key:
        message = "Bazarr is not set up. Add its address and API key under Settings, Integrations."
        note("bazarr", message)
        raise AppError(message, 400)
    try:
        response = requests.request(method, f"{url}/api/{path.lstrip('/')}", headers={"X-API-KEY": key},
                                    params=params, timeout=timeout)
    except requests.Timeout as exc:
        message = f"Bazarr did not answer in time: {exc}"
        note("bazarr", message)
        raise AppError(message, 502) from exc
    except requests.RequestException as exc:
        message = f"Bazarr could not be reached: {exc}"
        note("bazarr", message)
        raise AppError(message, 502) from exc
    if response.status_code in (401, 403):
        note("bazarr", "Bazarr refused the API key")
        raise AppError("Bazarr refused the API key", 502)
    if response.status_code >= 400:
        detail = (response.text or "").strip().splitlines()[0][:200] if response.text else ""
        message = f"Bazarr answered {response.status_code}{': ' + detail if detail else ''}"
        note("bazarr", message)
        raise AppError(message, 502)
    clear("bazarr")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def test(url=None, key=None):
    saved_url, saved_key = _settings()
    status = _api("GET", "system/status", (url or saved_url).rstrip("/"), key or saved_key)
    data = (status or {}).get("data") if isinstance(status, dict) else None
    version = (data or status or {}).get("version") if isinstance(data or status, dict) else ""
    return f"Connected to Bazarr {version or ''}".strip()


def _flag(value):
    return "true" if value in (True, "true", "True", "1", 1) else "false"


def missing_languages(raw):
    """(code, forced, hi) from a Bazarr missing_subtitles value."""
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    found = []
    for item in raw:
        if isinstance(item, str) and item:
            found.append((item, "false", "false"))
        elif isinstance(item, dict):
            code = item.get("code2") or item.get("language") or ""
            if code:
                found.append((str(code), _flag(item.get("forced")), _flag(item.get("hi"))))
    return found


def _known(rows):
    data = rows.get("data") if isinstance(rows, dict) else rows
    if isinstance(data, dict):
        data = [data]
    return bool(data)


def search_movie(tmdb_id):
    from curator import radarr
    from curator.automation import require_integration

    require_integration("bazarr")

    movie = radarr.find(tmdb_id)
    if not movie:
        raise AppError("This movie is not in Radarr, so Bazarr does not have it.", 404)
    url, key = _settings()
    radarr_id = int(movie["id"])
    known = _api("GET", "movies", url, key, params=[("radarrid[]", radarr_id), ("length", 1)])
    if not _known(known):
        raise AppError("Radarr has this movie, but Bazarr has not synced it yet.", 404)
    _api("PATCH", "movies", url, key, params={"radarrid": radarr_id, "action": "search-missing"})
    return {"title": movie.get("title") or "", "radarr_id": radarr_id}


def _series_id(tvdb_id):
    from curator import sonarr

    series = sonarr.series_by_tvdb(tvdb_id)
    if not series:
        raise AppError("This show is not in Sonarr, so Bazarr does not have it.", 404)
    return int(series["id"]), series.get("title") or ""


def search_series(tvdb_id):
    from curator.automation import require_integration

    require_integration("bazarr")
    series_id, title = _series_id(tvdb_id)
    url, key = _settings()
    known = _api("GET", "series", url, key, params=[("seriesid[]", series_id), ("length", 1)])
    if not _known(known):
        raise AppError("Sonarr has this show, but Bazarr has not synced it yet.", 404)
    _api("PATCH", "series", url, key, params={"seriesid": series_id, "action": "search-missing"})
    return {"title": title, "series_id": series_id}


def _sonarr_episode(tvdb_id, season, episode):
    from curator import sonarr

    series_id, title = _series_id(tvdb_id)
    url, key = sonarr._settings()
    rows = sonarr._api("GET", "/episode", url, key, params={"seriesId": series_id}, timeout=60) or []
    match = next((row for row in rows
                  if int(row.get("seasonNumber") or -1) == int(season)
                  and int(row.get("episodeNumber") or -1) == int(episode)), None)
    if not match:
        raise AppError(f"Sonarr has no S{int(season):02d}E{int(episode):02d} for {title}.", 404)
    return series_id, int(match["id"]), title


def search_episode(tvdb_id, season, episode):
    """Search each subtitle Bazarr lists as missing for one episode."""
    from curator.automation import require_integration

    require_integration("bazarr")
    series_id, episode_id, title = _sonarr_episode(tvdb_id, season, episode)
    url, key = _settings()
    rows = _api("GET", "episodes", url, key, params=[("episodeid[]", episode_id)])
    data = rows if isinstance(rows, list) else (rows or {}).get("data") or []
    if isinstance(data, dict):
        data = [data]
    if not data:
        raise AppError("Sonarr has this episode, but Bazarr has not synced it yet.", 404)
    languages = missing_languages(data[0].get("missing_subtitles"))
    if not languages:
        raise AppError("Bazarr is not missing any subtitles for this episode.", 404)
    for code, forced, hi in languages:
        _api("PATCH", "episodes/subtitles", url, key, params={
            "seriesid": series_id, "episodeid": episode_id, "language": code, "forced": forced, "hi": hi,
        }, timeout=60)
    return {"title": title, "series_id": series_id, "episode_id": episode_id, "languages": len(languages)}


def _library_item(sub_path):
    """("movie", tmdb_id) or ("show", tvdb_id) for the video that sits beside a subtitle file."""
    import os

    from curator.video import naming
    from resonance import db

    folder = os.path.dirname(os.path.realpath(sub_path))
    try:
        videos = [os.path.join(folder, n) for n in os.listdir(folder) if naming.is_video(n)]
    except OSError:
        return None, ""
    if videos:
        row = db.fetchone("""
            SELECT s.tvdb_id FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
            WHERE e.path = ANY(%s) AND COALESCE(s.tvdb_id, '') <> '' LIMIT 1""", (videos,))
        if row:
            return "show", str(row["tvdb_id"])
    row = db.fetchone("""
        SELECT tmdb_id FROM movies
        WHERE (folder = %s OR path = ANY(%s)) AND COALESCE(tmdb_id, '') <> '' LIMIT 1""", (folder, videos))
    if row:
        return "movie", str(row["tmdb_id"])
    return None, ""


def scan_subtitles(sub_path):
    """Ask Bazarr to re-read the subtitle files of the movie or show that owns `sub_path`.

    Only the Radarr movie id or Sonarr series id is needed (no path mapping): Bazarr already
    knows the folder and scans it. Returns a short message, or "" when there was nothing to do.
    """
    from curator.automation import integration_on

    if not integration_on("bazarr"):
        return ""
    kind, ident = _library_item(sub_path)
    if not kind:
        return ""
    url, key = _settings()
    if kind == "movie":
        from curator import radarr

        movie = radarr.find(ident)
        if not movie:
            return ""
        radarr_id = int(movie["id"])
        if not _known(_api("GET", "movies", url, key, params=[("radarrid[]", radarr_id), ("length", 1)])):
            return ""
        _api("PATCH", "movies", url, key, params={"radarrid": radarr_id, "action": "scan-disk"})
        return f"Bazarr is re-reading the subtitles of {movie.get('title') or 'the movie'}"
    series_id, title = _series_id(ident)
    if not _known(_api("GET", "series", url, key, params=[("seriesid[]", series_id), ("length", 1)])):
        return ""
    _api("PATCH", "series", url, key, params={"seriesid": series_id, "action": "scan-disk"})
    return f"Bazarr is re-reading the subtitles of {title or 'the show'}"
