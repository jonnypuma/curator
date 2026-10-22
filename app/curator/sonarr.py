"""Sonarr v3 API: search missing episodes, and add a show Sonarr does not have yet."""
import logging

from resonance.errors import AppError

logger = logging.getLogger(__name__)

MONITORS = ("all", "future", "missing", "existing", "firstSeason", "latestSeason", "pilot", "none")


def normalize(data):
    data = data if isinstance(data, dict) else {}
    try:
        profile = int(data.get("quality_profile") or 0)
    except (TypeError, ValueError):
        profile = 0
    monitor = data.get("monitor")
    from curator.radarr import _profile_list, _profile_name

    return {
        "root_folder": str(data.get("root_folder") or "").strip(),
        "quality_profile": max(0, profile),
        "quality_profile_name": _profile_name(data.get("quality_profile_name")),
        "quality_profiles": _profile_list(data.get("quality_profiles")),
        "monitor": monitor if monitor in MONITORS else "all",
        "search": data.get("search", True) is not False,
    }


def _config():
    from resonance import settings

    return normalize((settings.load() or {}).get("sonarr"))


def _settings():
    from resonance import settings

    cfg = settings.load()
    url = str(cfg.get("sonarr_url") or "").strip().rstrip("/")
    key = str(cfg.get("sonarr_api_key") or "").strip()
    return url, key


def _api(method, path, url, key, payload=None, params=None, timeout=30):
    import requests

    from resonance.connections import clear, note

    if not url or not key:
        message = "Sonarr is not set up. Add its address and API key under Settings, Integrations."
        note("sonarr", message)
        raise AppError(message, 400)
    try:
        response = requests.request(method, f"{url}/api/v3{path}", headers={"X-Api-Key": key},
                                    json=payload, params=params, timeout=timeout)
    except requests.Timeout as exc:
        message = f"Sonarr did not answer in time: {exc}"
        note("sonarr", message)
        raise AppError(message, 502) from exc
    except requests.RequestException as exc:
        message = f"Sonarr could not be reached: {exc}"
        note("sonarr", message)
        raise AppError(message, 502) from exc
    if response.status_code in (401, 403):
        note("sonarr", "Sonarr refused the API key")
        raise AppError("Sonarr refused the API key", 502)
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
        message = f"Sonarr answered {response.status_code}{': ' + detail if detail else ''}"
        note("sonarr", message)
        raise AppError(message, 502)
    clear("sonarr")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def options(url=None, key=None):
    """Root folders and quality profiles for the settings form."""
    saved_url, saved_key = _settings()
    url, key = (url or saved_url).rstrip("/"), key or saved_key
    roots = _api("GET", "/rootfolder", url, key) or []
    profiles = _api("GET", "/qualityprofile", url, key) or []
    return {
        "root_folders": [{"path": item.get("path"), "free": item.get("freeSpace")} for item in roots if item.get("path")],
        "quality_profiles": [{"id": item.get("id"), "name": item.get("name")} for item in profiles if item.get("id")],
    }


def test(url=None, key=None):
    saved_url, saved_key = _settings()
    status = _api("GET", "/system/status", (url or saved_url).rstrip("/"), key or saved_key)
    return f"Connected to Sonarr {(status or {}).get('version') or ''}".strip()


def series_by_tvdb(tvdb_id, url=None, key=None):
    saved_url, saved_key = _settings()
    url, key = (url or saved_url).rstrip("/"), key or saved_key
    found = _api("GET", "/series", url, key, params={"tvdbId": tvdb_id}) or []
    return found[0] if isinstance(found, list) and found else None


def tvdb_for_tmdb(tmdb_id):
    """Sonarr's lookup of a TMDB show id. Empty when Sonarr is off or the show has no TVDB id."""
    from curator.automation import integration_on

    if not integration_on("sonarr") or not str(tmdb_id or "").strip():
        return ""
    url, key = _settings()
    if not url or not key:
        return ""
    try:
        rows = _api("GET", "/series/lookup", url, key, params={"term": f"tmdb:{tmdb_id}"}, timeout=40) or []
    except AppError as exc:
        logger.info("Sonarr TMDB lookup failed: %s", exc)
        return ""
    if isinstance(rows, list) and rows and rows[0].get("tvdbId"):
        return str(rows[0]["tvdbId"])
    return ""


def ensure_series(tvdb_id, search=None):
    """Add a show Sonarr lacks. A show already there is monitored and searched, not posted again.

    search is True or False for this call, or None to follow Start a search right away in Settings."""
    from curator.automation import require_integration

    require_integration("sonarr")
    url, key = _settings()
    cfg = _config()
    want = bool(cfg.get("search", True)) if search is None else bool(search)
    series = series_by_tvdb(tvdb_id, url, key)
    if series:
        try:
            if not series.get("monitored"):
                series = dict(series)
                series["monitored"] = True
                _api("PUT", f"/series/{series['id']}", url, key, payload=series)
            if want and series.get("id"):
                _api("POST", "/command", url, key, payload={"name": "SeriesSearch", "seriesId": series["id"]}, timeout=60)
        except AppError as exc:
            want = False
            logger.warning("Sonarr already has TVDB %s; search was not started: %s", tvdb_id, exc)
        return {"ok": True, "action": "present", "title": series.get("title") or "", "search": want}
    series = _add_series(url, key, tvdb_id, {**cfg, "search": want}, season=None)
    if not series.get("id"):
        raise AppError("Sonarr did not accept the show.", 502)
    return {"ok": True, "action": "added", "title": series.get("title") or "", "search": want}


def missing_episode_ids(episodes, season=None, episode_number=None):
    """Sonarr episode ids that are monitored and have no file. season and episode_number narrow the list."""
    ids = []
    skipped = 0
    for episode in episodes or []:
        number = int(episode.get("seasonNumber") if episode.get("seasonNumber") is not None else -1)
        if season is not None and number != int(season):
            continue
        shown = int(episode.get("episodeNumber") if episode.get("episodeNumber") is not None else -1)
        if episode_number is not None and shown != int(episode_number):
            continue
        if episode.get("hasFile"):
            continue
        if episode.get("monitored") is False:
            skipped += 1
            continue
        if episode.get("id"):
            ids.append(int(episode["id"]))
    return ids, skipped


def _defaults(url, key, cfg):
    root = cfg.get("root_folder")
    profile = cfg.get("quality_profile")
    if not root:
        roots = _api("GET", "/rootfolder", url, key) or []
        if not roots:
            raise AppError("Sonarr has no root folder. Add one in Sonarr first.", 400)
        root = roots[0]["path"]
    if not profile:
        profiles = _api("GET", "/qualityprofile", url, key) or []
        if not profiles:
            raise AppError("Sonarr has no quality profile", 400)
        profile = profiles[0]["id"]
    return root, profile


def _add_series(url, key, tvdb_id, cfg, season=None):
    lookup = _api("GET", "/series/lookup", url, key, params={"term": f"tvdb:{tvdb_id}"}, timeout=40) or []
    if not isinstance(lookup, list) or not lookup:
        raise AppError("Sonarr could not find this TVDB id", 404)
    root, profile = _defaults(url, key, cfg)
    body = {
        **lookup[0],
        "qualityProfileId": profile,
        "rootFolderPath": root,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "monitor": cfg.get("monitor") or "all",
            "searchForMissingEpisodes": bool(cfg.get("search", True) and season is None),
        },
    }
    try:
        added = _api("POST", "/series", url, key, payload=body, timeout=60)
    except AppError as exc:
        if "language" not in str(exc).lower():
            raise
        languages = _api("GET", "/languageprofile", url, key) or []
        if not languages:
            raise
        body["languageProfileId"] = languages[0].get("id")
        added = _api("POST", "/series", url, key, payload=body, timeout=60)
    return added or {}


def search_missing(tvdb_id, season=None, episode_number=None):
    """Search missing monitored episodes. A show Sonarr does not have is added first."""
    from curator.automation import require_integration

    require_integration("sonarr")
    url, key = _settings()
    series = series_by_tvdb(tvdb_id, url, key)
    added = False
    if not series:
        cfg = _config()
        series = _add_series(url, key, tvdb_id, cfg, season)
        added = True
        if not series.get("id"):
            raise AppError("Sonarr did not accept the show.", 502)
        if cfg.get("search", True) and season is not None:
            _api("POST", "/command", url, key, payload={
                "name": "SeasonSearch", "seriesId": series["id"], "seasonNumber": int(season),
            }, timeout=60)
        return {"title": series.get("title") or "the show", "series_id": series["id"], "searched": 0,
                "unmonitored": 0, "action": "added", "search": bool(cfg.get("search", True)),
                "season": None if season is None else int(season),
                "episode": None if episode_number is None else int(episode_number)}
    episodes = _api("GET", "/episode", url, key, params={"seriesId": series["id"]}, timeout=60) or []
    ids, unmonitored = missing_episode_ids(episodes, season, episode_number)
    title = series.get("title") or "the show"
    if episode_number is not None and season is not None:
        where = f"S{int(season):02d}E{int(episode_number):02d}"
    elif season is not None:
        where = f"season {int(season)}"
    else:
        where = title
    if not ids:
        if unmonitored:
            raise AppError(f"Sonarr has {unmonitored} missing episode{'s' if unmonitored != 1 else ''} in {where}, "
                           "and none of them are monitored.", 404)
        raise AppError(f"Sonarr has no missing episodes in {where}.", 404)
    _api("POST", "/command", url, key, payload={"name": "EpisodeSearch", "episodeIds": ids}, timeout=60)
    return {"title": title, "series_id": series["id"], "searched": len(ids), "unmonitored": unmonitored,
            "action": "added" if added else "searched",
            "season": None if season is None else int(season),
            "episode": None if episode_number is None else int(episode_number)}


def search_episodes(rows):
    """Ask Sonarr to search these library episodes, whether or not it already has a file."""
    from curator.automation import require_integration

    require_integration("sonarr")
    url, key = _settings()
    found = []
    missing = []
    for row in rows or []:
        series = series_by_tvdb(row["tvdb_id"], url, key)
        if not series:
            missing.append(row.get("title") or "an episode")
            continue
        episodes = _api("GET", "/episode", url, key, params={"seriesId": series["id"]}, timeout=60) or []
        match = next((item for item in episodes
                      if int(item.get("seasonNumber") if item.get("seasonNumber") is not None else -1) == int(row["season_number"])
                      and int(item.get("episodeNumber") if item.get("episodeNumber") is not None else -1) == int(row["episode_number"])
                      and item.get("id")), None)
        if not match:
            missing.append(row.get("title") or f"S{row['season_number']}E{row['episode_number']}")
            continue
        found.append(int(match["id"]))
    if not found:
        raise AppError("Sonarr has none of these episodes." + (f" Missing: {', '.join(missing[:4])}." if missing else ""), 404)
    _api("POST", "/command", url, key, payload={"name": "EpisodeSearch", "episodeIds": found}, timeout=60)
    return {"searched": len(found), "missing": missing}


def rescan_series(tvdb_id=None, series_id=None):
    """Tell Sonarr to rescan the series folder, updating episode file paths to any surviving copy."""
    url, key = _settings()
    if not url or not key:
        return False
    try:
        target_id = series_id
        if not target_id and tvdb_id:
            series = series_by_tvdb(tvdb_id, url, key)
            if series and series.get("id"):
                target_id = series["id"]
        if not target_id:
            return False
        _api("POST", "/command", url, key, payload={"name": "RescanSeries", "seriesId": int(target_id)})
        return True
    except Exception as exc:
        logger.warning("Sonarr RescanSeries failed for tvdb=%s id=%s: %s", tvdb_id, series_id, exc)
        return False

