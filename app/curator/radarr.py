"""Radarr v3 API: add missing set movies and start searches."""
import logging

from resonance.errors import AppError

logger = logging.getLogger(__name__)

AVAILABILITY = ("announced", "inCinemas", "released")


def _profile_name(value):
    text = str(value or "").strip()
    if not text or text.lower().startswith("profile ") and text[8:].strip().isdigit():
        return ""
    if "first" in text.lower() and "profile" in text.lower():
        return ""
    return text[:200]


def _profile_list(value):
    rows = []
    if not isinstance(value, list):
        return rows
    for item in value[:80]:
        if not isinstance(item, dict):
            continue
        try:
            ident = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        name = _profile_name(item.get("name"))
        if ident > 0 and name:
            rows.append({"id": ident, "name": name})
    return rows


def normalize(data):
    data = data if isinstance(data, dict) else {}
    try:
        profile = int(data.get("quality_profile") or 0)
    except (TypeError, ValueError):
        profile = 0
    availability = data.get("minimum_availability")
    return {
        "root_folder": str(data.get("root_folder") or "").strip(),
        "quality_profile": max(0, profile),
        "quality_profile_name": _profile_name(data.get("quality_profile_name")),
        "quality_profiles": _profile_list(data.get("quality_profiles")),
        "minimum_availability": availability if availability in AVAILABILITY else "released",
        "search": data.get("search", True) is not False,
    }


def _settings():
    from resonance import settings

    cfg = settings.load()
    url = str(cfg.get("radarr_url") or "").strip().rstrip("/")
    key = str(cfg.get("radarr_api_key") or "").strip()
    return url, key, cfg.get("radarr") or normalize({})


def _api(method, path, url, key, payload=None, params=None, timeout=20):
    import requests

    from resonance.connections import clear, note

    if not url or not key:
        message = "Radarr is not set up. Add its address and API key under Settings, Integrations."
        note("radarr", message)
        raise AppError(message, 400)
    try:
        response = requests.request(method, f"{url}/api/v3{path}", headers={"X-Api-Key": key},
                                    json=payload, params=params, timeout=timeout)
    except requests.Timeout as exc:
        message = f"Radarr did not answer in time: {exc}"
        note("radarr", message)
        raise AppError(message, 502) from exc
    except requests.RequestException as exc:
        message = f"Radarr could not be reached: {exc}"
        note("radarr", message)
        raise AppError(message, 502) from exc
    if response.status_code in (401, 403):
        note("radarr", "Radarr refused the API key")
        raise AppError("Radarr refused the API key", 502)
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, list) and body:
                detail = body[0].get("errorMessage") or ""
            elif isinstance(body, dict):
                detail = body.get("message") or body.get("title") or ""
        except ValueError:
            detail = response.text[:200]
        message = f"Radarr answered {response.status_code}{': ' + detail if detail else ''}"
        note("radarr", message)
        raise AppError(message, 502)
    clear("radarr")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def test(url=None, key=None):
    saved_url, saved_key, _cfg = _settings()
    status = _api("GET", "/system/status", (url or saved_url).rstrip("/"), key or saved_key)
    return f"Connected to Radarr {(status or {}).get('version') or ''}".strip()


def options(url=None, key=None):
    """Root folders and quality profiles for the settings form."""
    saved_url, saved_key, _cfg = _settings()
    url, key = (url or saved_url).rstrip("/"), key or saved_key
    roots = _api("GET", "/rootfolder", url, key) or []
    profiles = _api("GET", "/qualityprofile", url, key) or []
    return {
        "root_folders": [{"path": item.get("path"), "free": item.get("freeSpace")} for item in roots if item.get("path")],
        "quality_profiles": [{"id": item.get("id"), "name": item.get("name")} for item in profiles if item.get("id")],
    }


def find(tmdb_id):
    """The Radarr movie for a TMDB id, or None when Radarr does not have it."""
    url, key, _cfg = _settings()
    if not url or not key:
        raise AppError("Radarr is not set up. Add its address and API key under Settings, Integrations.", 400)
    return _existing(url, key, tmdb_id)


def _existing(url, key, tmdb_id):
    found = _api("GET", "/movie", url, key, params={"tmdbId": tmdb_id}) or []
    return found[0] if isinstance(found, list) and found else None


def states(tmdb_ids):
    """{tmdb_id: {monitored, has_file}} for movies Radarr already knows."""
    url, key, _cfg = _settings()
    if not url or not key:
        return {}
    found = {}
    for tmdb_id in tmdb_ids:
        try:
            movie = _existing(url, key, tmdb_id)
        except AppError:
            return found
        if movie:
            found[str(tmdb_id)] = {"monitored": bool(movie.get("monitored")), "has_file": bool(movie.get("hasFile"))}
    return found


def _defaults(url, key, cfg):
    root = cfg.get("root_folder")
    profile = cfg.get("quality_profile")
    if not root:
        roots = _api("GET", "/rootfolder", url, key) or []
        if not roots:
            raise AppError("Radarr has no root folder. Add one in Radarr first.", 400)
        root = roots[0]["path"]
    if not profile:
        profiles = _api("GET", "/qualityprofile", url, key) or []
        if not profiles:
            raise AppError("Radarr has no quality profile", 400)
        profile = profiles[0]["id"]
    return root, profile


def search(tmdb_ids, search=None):
    """Add each movie that Radarr lacks and, unless told otherwise, search for all of them.

    search is True or False for this call, or None to follow Start a search right away in Settings.
    Returns per-movie results."""
    from curator.automation import require_integration

    require_integration("radarr")
    url, key, cfg = _settings()
    want = bool(cfg.get("search", True)) if search is None else bool(search)
    results = []
    defaults = None
    for tmdb_id in dict.fromkeys(str(item) for item in tmdb_ids if str(item).strip()):
        try:
            movie = _existing(url, key, tmdb_id)
            if movie:
                if not movie.get("monitored"):
                    movie["monitored"] = True
                    _api("PUT", f"/movie/{movie['id']}", url, key, payload=movie)
                if want:
                    _api("POST", "/command", url, key, payload={"name": "MoviesSearch", "movieIds": [movie["id"]]})
                results.append({"tmdb_id": tmdb_id, "title": movie.get("title"), "ok": True,
                                "action": "searched" if want else "monitored", "search": want})
                continue
            lookup = _api("GET", "/movie/lookup/tmdb", url, key, params={"tmdbId": tmdb_id}, timeout=40)
            if not lookup:
                results.append({"tmdb_id": tmdb_id, "ok": False, "error": "Radarr could not find this TMDB id"})
                continue
            defaults = defaults or _defaults(url, key, cfg)
            body = {
                **lookup,
                "qualityProfileId": defaults[1],
                "rootFolderPath": defaults[0],
                "monitored": True,
                "minimumAvailability": cfg.get("minimum_availability") or "released",
                "addOptions": {"searchForMovie": want},
            }
            added = _api("POST", "/movie", url, key, payload=body, timeout=40) or {}
            results.append({"tmdb_id": tmdb_id, "title": added.get("title") or lookup.get("title"), "ok": True,
                            "action": "added", "search": want})
        except AppError as exc:
            if exc.status == 400 and "not set up" in str(exc):
                raise
            logger.warning("Radarr search for TMDB %s failed: %s", tmdb_id, exc)
            results.append({"tmdb_id": tmdb_id, "ok": False, "error": str(exc)})
    return results


def rescan_movie(tmdb_id=None, movie_id=None):
    """Tell Radarr to rescan the movie folder, updating the file path to any surviving copy."""
    url, key, _cfg = _settings()
    if not url or not key:
        return False
    try:
        target_id = movie_id
        if not target_id and tmdb_id:
            movie = _existing(url, key, tmdb_id)
            if movie and movie.get("id"):
                target_id = movie["id"]
        if not target_id:
            return False
        _api("POST", "/command", url, key, payload={"name": "RescanMovie", "movieId": int(target_id)})
        return True
    except Exception as exc:
        logger.warning("Radarr RescanMovie failed for tmdb=%s id=%s: %s", tmdb_id, movie_id, exc)
        return False

