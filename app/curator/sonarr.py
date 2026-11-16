"""Sonarr API: search missing episodes, and add a show Sonarr does not have yet.

Sonarr 3 and 4 serve /api/v3. Sonarr 5 adds /api/v5, where a show can also be found by its TMDB id. The connection
test saves which one answers (curator.arr_versions) and every call uses it. A v5 call that answers 404 is tried again
on /api/v3, so a Sonarr 5 that drops or renames an endpoint keeps working.
"""
import logging

from curator.arr_client import NotFound as _NotFound  # Sonarr answered 404 for the whole endpoint
from resonance.errors import AppError

logger = logging.getLogger(__name__)

V3 = "/api/v3"
V5 = "/api/v5"


def _api_prefix(url):
    from curator import arr_versions

    return V5 if arr_versions.sonarr_entry(url).get("api") == "v5" else V3


def tmdb_ok(url=None):
    """True when Sonarr at this address (the saved one by default) can find a show by TMDB id: Sonarr 5 or newer."""
    from curator import arr_versions

    return arr_versions.sonarr_supports_tmdb(url)

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


def _api(method, path, url, key, payload=None, params=None, timeout=30, api=None):
    prefix = api or _api_prefix(url)
    try:
        return _call(method, prefix, path, url, key, payload, params, timeout)
    except _NotFound:
        if api or prefix != V5:
            raise
        logger.info("Sonarr /api/v5%s answered 404, trying /api/v3", path)
        return _call(method, V3, path, url, key, payload, params, timeout)


def _call(method, prefix, path, url, key, payload, params, timeout):
    from curator import arr_client

    # A 404 on /api/v5 is retried on /api/v3, so it does not mark the connection as failing.
    return arr_client.request("sonarr", method, url, key, f"{prefix}{path}", payload, params, timeout,
                              quiet_404=prefix == V5)


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
    """Check the address and key, then save the version and which API answers (v5 from Sonarr 5 on, else v3)."""
    from curator import arr_versions

    saved_url, saved_key = _settings()
    address, key = (url or saved_url).rstrip("/"), key or saved_key
    status, api = None, "v3"
    try:
        status = _api("GET", "/system/status", address, key, api=V3)
    except _NotFound:
        status = None            # a Sonarr that only serves /api/v5
    version = (status or {}).get("version") or ""
    if status is None or arr_versions.major_of(version) >= 5:
        try:
            newer = _api("GET", "/system/status", address, key, api=V5)
            version = (newer or {}).get("version") or version
            api = "v5"
        except AppError:
            if status is None:
                raise
    entry = arr_versions.record("sonarr", version, address, api)
    text = f"Connected to Sonarr {version}".strip() + f" (API {api})."
    return text + (" Shows with only a TMDB id can be looked up." if entry.get("major", 0) >= 5 else "")


def series_by_tvdb(tvdb_id, url=None, key=None):
    saved_url, saved_key = _settings()
    url, key = (url or saved_url).rstrip("/"), key or saved_key
    found = _api("GET", "/series", url, key, params={"tvdbId": tvdb_id}) or []
    return found[0] if isinstance(found, list) and found else None


def series_by_tmdb(tmdb_id, url=None, key=None):
    """The Sonarr series with this TMDB id. Sonarr 5 and newer only; None on older versions or when it is not there."""
    saved_url, saved_key = _settings()
    url, key = (url or saved_url).rstrip("/"), key or saved_key
    if not str(tmdb_id or "").strip() or not tmdb_ok(url):
        return None
    rows = _api("GET", "/series/lookup", url, key, params={"term": f"tmdb:{tmdb_id}"}, timeout=40) or []
    for row in rows if isinstance(rows, list) else []:
        if row.get("id") and str(row.get("tmdbId") or tmdb_id) == str(tmdb_id):
            return _api("GET", f"/series/{int(row['id'])}", url, key) or row
    listing = _api("GET", "/series", url, key) or []
    return next((row for row in listing if isinstance(row, dict) and str(row.get("tmdbId") or "") == str(tmdb_id)), None)


def find_series(tvdb_id=None, tmdb_id=None, url=None, key=None):
    """A show in Sonarr by TVDB id, or by TMDB id on Sonarr 5 and newer."""
    series = series_by_tvdb(tvdb_id, url, key) if str(tvdb_id or "").strip() else None
    return series or series_by_tmdb(tmdb_id, url, key)


def _show_term(tvdb_id=None, tmdb_id=None, url=None):
    """The lookup term for adding a show: tvdb:<id>, or tmdb:<id> on Sonarr 5 and newer."""
    if str(tvdb_id or "").strip():
        return f"tvdb:{tvdb_id}", f"TVDB id {tvdb_id}"
    if str(tmdb_id or "").strip() and tmdb_ok(url):
        return f"tmdb:{tmdb_id}", f"TMDB id {tmdb_id}"
    raise AppError("This show has no TVDB id. Scrape it first. Sonarr 5 and newer can also use the TMDB id.", 400)


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


def ensure_series(tvdb_id, search=None, tmdb_id=None):
    """Add a show Sonarr lacks. A show already there is monitored and searched, not posted again.

    search is True or False for this call, or None to follow Start a search right away in Settings.
    Without a TVDB id, Sonarr 5 and newer find the show by tmdb_id."""
    from curator.automation import require_integration

    require_integration("sonarr")
    url, key = _settings()
    cfg = _config()
    want = bool(cfg.get("search", True)) if search is None else bool(search)
    series = find_series(tvdb_id, tmdb_id, url, key)
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
            logger.warning("Sonarr already has TVDB %s / TMDB %s; search was not started: %s", tvdb_id, tmdb_id, exc)
        return {"ok": True, "action": "present", "title": series.get("title") or "", "search": want,
                "tvdb_id": _known_tvdb(series)}
    series = _add_series(url, key, tvdb_id, {**cfg, "search": want}, season=None, tmdb_id=tmdb_id)
    if not series.get("id"):
        raise AppError("Sonarr did not accept the show.", 502)
    return {"ok": True, "action": "added", "title": series.get("title") or "", "search": want,
            "tvdb_id": _known_tvdb(series)}


def _known_tvdb(series):
    """The TVDB id Sonarr has for a series, or "" (Sonarr 5 can hold a show that has none: tvdbId 0)."""
    value = (series or {}).get("tvdbId")
    return str(value) if value and str(value) != "0" else ""


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


def _add_series(url, key, tvdb_id, cfg, season=None, tmdb_id=None):
    term, named = _show_term(tvdb_id, tmdb_id, url)
    lookup = _api("GET", "/series/lookup", url, key, params={"term": term}, timeout=40) or []
    if not isinstance(lookup, list) or not lookup:
        raise AppError(f"Sonarr could not find {named}", 404)
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


def search_missing(tvdb_id, season=None, episode_number=None, tmdb_id=None):
    """Search missing monitored episodes. A show Sonarr does not have is added first.
    Without a TVDB id, Sonarr 5 and newer find the show by tmdb_id."""
    from curator.automation import require_integration

    require_integration("sonarr")
    url, key = _settings()
    series = find_series(tvdb_id, tmdb_id, url, key)
    added = False
    if not series:
        cfg = _config()
        series = _add_series(url, key, tvdb_id, cfg, season, tmdb_id=tmdb_id)
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
        series = find_series(row.get("tvdb_id"), row.get("tmdb_id"), url, key)
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


def rescan_series_command(tvdb_id=None, series_id=None):
    """Tell Sonarr to rescan the series folder. Returns the id of Sonarr's command, 0 when it cannot be tracked, None on failure."""
    url, key = _settings()
    if not url or not key:
        return None
    try:
        target_id = series_id
        if not target_id and tvdb_id:
            series = series_by_tvdb(tvdb_id, url, key)
            if series and series.get("id"):
                target_id = series["id"]
        if not target_id:
            return None
        reply = _api("POST", "/command", url, key, payload={"name": "RescanSeries", "seriesId": int(target_id)})
        return int((reply or {}).get("id") or 0)
    except Exception as exc:
        logger.warning("Sonarr RescanSeries failed for tvdb=%s id=%s: %s", tvdb_id, series_id, exc)
        return None


def rescan_series(tvdb_id=None, series_id=None):
    """Tell Sonarr to rescan the series folder, updating episode file paths to any surviving copy."""
    return rescan_series_command(tvdb_id, series_id) is not None


def wait_for_command(command_id, timeout=180, step=3):
    """Wait until Sonarr has finished a command. True when it completed, False on failure or timeout."""
    import time

    url, key = _settings()
    if not url or not key or not command_id:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = (_api("GET", f"/command/{int(command_id)}", url, key) or {}).get("status")
        except Exception:
            return False
        if status == "completed":
            return True
        if status in ("failed", "aborted", "cancelled", "orphaned"):
            return False
        time.sleep(step)
    return False


# ---- Sonarr's own season and episode numbers ---------------------------------------------------------------
# A file can be named S04E01 while Sonarr and TheTVDB number it S03E01 (Lupin, for one). Sonarr is the one that
# knows, so a scan asks it which episodes each file holds and uses those numbers.

_NUMBER_TTL = 60
_numbers = {}          # series key -> (fetched at, {local path: [(season, episode), ...]})
_series_list = [0.0, []]


def _same_place(left, right):
    from curator.automation import clean_path

    return clean_path(left).rstrip("/").lower() == clean_path(right).rstrip("/").lower()


def _find_series(show_path, tvdb_id, url, key, mappings):
    import time
    from curator.automation import map_path

    if time.monotonic() - _series_list[0] > _NUMBER_TTL:
        listing = _api("GET", "/series", url, key) or []
        _series_list[:] = [time.monotonic(), listing if isinstance(listing, list) else []]
    for series in _series_list[1]:
        if tvdb_id and str(series.get("tvdbId") or "") == str(tvdb_id):
            return series
    for series in _series_list[1]:
        if show_path and _same_place(map_path(series.get("path") or "", mappings, "sonarr"), show_path):
            return series
    return None


def episode_numbers(show_path, tvdb_id=None):
    """{local file path: [(season, episode), ...]} as Sonarr numbers them. Empty when Sonarr is off or unsure."""
    import time
    from curator import automation
    from curator.automation import map_path

    try:
        url, key = _settings()
        if not url or not key:
            return {}
        url = url.rstrip("/")
        mappings = (automation.current()[0] or {}).get("path_mappings") or []
        series = _find_series(show_path, tvdb_id, url, key, mappings)
        if not series or not series.get("id"):
            return {}
        cached = _numbers.get(series["id"])
        if cached and time.monotonic() - cached[0] < _NUMBER_TTL:
            return cached[1]
        files = _api("GET", "/episodefile", url, key, params={"seriesId": series["id"]}) or []
        episodes = _api("GET", "/episode", url, key, params={"seriesId": series["id"]}) or []
        paths = {}
        for item in files if isinstance(files, list) else []:
            if item.get("id") and item.get("path"):
                paths[item["id"]] = map_path(item["path"], mappings, "sonarr")
        found = {}
        for episode in episodes if isinstance(episodes, list) else []:
            path = paths.get(episode.get("episodeFileId"))
            if not path or episode.get("seasonNumber") is None or episode.get("episodeNumber") is None:
                continue
            found.setdefault(path, []).append((int(episode["seasonNumber"]), int(episode["episodeNumber"])))
        for pairs in found.values():
            pairs.sort()
        _numbers[series["id"]] = (time.monotonic(), found)
        return found
    except Exception as exc:
        logger.info("Sonarr episode numbers were not used for %s: %s", show_path, exc)
        return {}


def known_seasons(show_path, tvdb_id=None):
    """Season numbers Sonarr lists for the show, or None when Sonarr is off or does not know the show."""
    from curator import automation

    try:
        url, key = _settings()
        if not url or not key:
            return None
        mappings = (automation.current()[0] or {}).get("path_mappings") or []
        series = _find_series(show_path, tvdb_id, url.rstrip("/"), key, mappings)
        numbers = {int(item["seasonNumber"]) for item in (series or {}).get("seasons") or [] if item.get("seasonNumber") is not None}
        return numbers or None
    except Exception as exc:
        logger.info("Sonarr seasons were not read for %s: %s", show_path, exc)
        return None


def clear_numbers():
    _numbers.clear()
    _series_list[:] = [0.0, []]
