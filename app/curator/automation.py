"""Webhook queue and downstream notification settings.

Stored under settings["automation"] and settings["notify"]. Values left empty fall back to docker-compose
(CMM_DEBOUNCE_MINUTES, KODI_HOST, KODI_LIBRARY_HOST, JELLYFIN_URL, PLEX_URL and friends).
"""
from __future__ import annotations

import os

SOURCES = ("any", "radarr", "sonarr", "bazarr", "lidarr")
LABELS = {"radarr": "Radarr", "sonarr": "Sonarr", "bazarr": "Bazarr", "lidarr": "Lidarr"}


def integration_on(source, scan=False):
    """Whether that app is enabled, or whether an import from it should be scanned.

    Radarr, Sonarr and Bazarr default to on. Lidarr defaults to off, matching its existing switches.
    """
    from resonance.settings import load

    key = f"{source}_import_scan" if scan else f"{source}_enabled"
    return load().get(key, source != "lidarr") is not False


def require_integration(source):
    from resonance.errors import AppError

    if not integration_on(source):
        raise AppError(f"{LABELS.get(source, source)} is turned off under Settings, Integrations.", 400)


def _flag(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(default)
        except (TypeError, ValueError):
            return low
    return max(low, min(number, high))


def _text(value, limit=500):
    return str(value or "").strip()[:limit]


def _env_defaults():
    from curator import env

    try:
        return env.load()
    except Exception:
        return env.EnvConfig.model_construct()


def clean_path(value):
    text = str(value or "").strip().replace("\\", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def _mappings(value):
    rows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        remote, local = clean_path(item.get("remote")), clean_path(item.get("local"))
        source = str(item.get("source") or "any").strip().lower()
        if remote and local:
            rows.append({"source": source if source in SOURCES else "any", "remote": remote, "local": local})
    return rows[:50]


def _path_pairs(value):
    """Curator path to the path another server uses for the same folder."""
    rows = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        local = clean_path(item.get("local"))
        remote = str(item.get("remote") or item.get("kodi") or "").strip()
        if local and remote:
            rows.append({"local": local, "remote": remote})
    return rows[:50]


def _kodi_paths(value):
    return [{"local": row["local"], "kodi": row["remote"]} for row in _path_pairs(value)]


def normalize(data):
    data = data if isinstance(data, dict) else {}
    defaults = _env_defaults()
    debounce = _int(data.get("debounce_minutes"), defaults.debounce_minutes, 0, 1440)
    postpone = _int(data.get("max_postpone_minutes"), defaults.max_postpone_minutes, 1, 10080)
    return {
        "enabled": _flag(data.get("enabled"), True),
        "debounce_minutes": debounce,
        "max_postpone_minutes": max(postpone, debounce),
        "music": _flag(data.get("music"), True),
        "scrape_movies": _flag(data.get("scrape_movies"), True),
        "scrape_tv": _flag(data.get("scrape_tv"), True),
        "path_mappings": _mappings(data.get("path_mappings")),
    }


def _split_enabled(data, video_key, music_key, legacy_key):
    """Video and music switches. A saved library that only has the old switch uses it for both."""
    legacy = _flag(data.get(legacy_key), True)
    video = _flag(data.get(video_key), legacy) if video_key in data else legacy
    music = _flag(data.get(music_key), legacy) if music_key in data else legacy
    return video, music


def normalize_notify(data):
    data = data if isinstance(data, dict) else {}
    kodi_video, kodi_music = _split_enabled(data, "kodi_video_enabled", "kodi_music_enabled", "kodi_library_enabled")
    emby_video, emby_music = _split_enabled(data, "emby_video_enabled", "emby_music_enabled", "emby_enabled")
    jellyfin_video, jellyfin_music = _split_enabled(data, "jellyfin_video_enabled", "jellyfin_music_enabled", "jellyfin_enabled")
    plex_video, plex_music = _split_enabled(data, "plex_video_enabled", "plex_music_enabled", "plex_enabled")
    return {
        "kodi_library_enabled": kodi_video or kodi_music,
        "kodi_video_enabled": kodi_video,
        "kodi_music_enabled": kodi_music,
        "kodi_library_host": _text(data.get("kodi_library_host")),
        "kodi_library_user": _text(data.get("kodi_library_user"), 200),
        "kodi_video_delay": _int(data.get("kodi_video_delay"), 60, 0, 86400),
        "kodi_music_delay": _int(data.get("kodi_music_delay"), 300, 0, 86400),
        "kodi_clean": _flag(data.get("kodi_clean"), True),
        "kodi_paths": _kodi_paths(data.get("kodi_paths")),
        "kodi_notify_enabled": _flag(data.get("kodi_notify_enabled"), True),
        "kodi_notify_host": _text(data.get("kodi_notify_host")),
        "kodi_notify_user": _text(data.get("kodi_notify_user"), 200),
        **_notice_flags(data, "kodi_notify"),
        **_notice_flags(data, "emby_notify"),
        **_notice_flags(data, "jellyfin_notify"),
        "jellyfin_enabled": jellyfin_video or jellyfin_music,
        "jellyfin_video_enabled": jellyfin_video,
        "jellyfin_music_enabled": jellyfin_music,
        "jellyfin_url": _text(data.get("jellyfin_url")),
        "plex_on": _flag(data.get("plex_on"), True),
        "plex_enabled": plex_video or plex_music,
        "plex_video_enabled": plex_video,
        "plex_music_enabled": plex_music,
        "plex_url": _text(data.get("plex_url")),
        "emby_on": _flag(data.get("emby_on"), True),
        "navidrome_on": _flag(data.get("navidrome_on"), True),
        "emby_enabled": emby_video or emby_music,
        "emby_video_enabled": emby_video,
        "emby_music_enabled": emby_music,
        "emby_url": _text(data.get("emby_url")),
        "emby_paths": _path_pairs(data.get("emby_paths")),
        "jellyfin_paths": _path_pairs(data.get("jellyfin_paths")),
        "plex_paths": _path_pairs(data.get("plex_paths")),
    }


def _notice_flags(data, prefix):
    """On-screen message switches. A missing switch follows the old single Kodi checkbox."""
    legacy = _flag(data.get("kodi_notify_enabled"), True) if prefix == "kodi_notify" else True
    flags = {}
    for kind in ("video", "removed", "music", "failed"):
        key = f"{prefix}_{kind}"
        flags[key] = _flag(data.get(key), legacy) if key not in data else _flag(data.get(key), False)
    return flags


def _env(*names):
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def current():
    """Settings with the docker-compose fallbacks filled in. Secrets included; never send this to the browser."""
    from resonance.settings import load

    data = load()
    auto = dict(data.get("automation") or normalize({}))
    notify = dict(data.get("notify") or normalize_notify({}))
    notify["kodi_notify_host"] = notify["kodi_notify_host"] or _env("KODI_HOST")
    notify["kodi_notify_user"] = notify["kodi_notify_user"] or _env("KODI_USERNAME")
    notify["kodi_notify_password"] = data.get("kodi_password") or ""
    notify["kodi_library_host"] = notify["kodi_library_host"] or _env("KODI_LIBRARY_HOST", "KODI_HOST")
    notify["kodi_library_user"] = notify["kodi_library_user"] or _env("KODI_LIBRARY_USERNAME", "KODI_USERNAME")
    notify["kodi_library_password"] = data.get("kodi_library_password") or data.get("kodi_password") or ""
    notify["jellyfin_url"] = notify["jellyfin_url"] or _env("JELLYFIN_URL", "JELLYFIN_HOST")
    notify["jellyfin_token"] = data.get("jellyfin_token") or ""
    notify["plex_url"] = notify["plex_url"] or _env("PLEX_URL", "PLEX_HOST")
    notify["plex_token"] = data.get("plex_token") or ""
    notify["emby_url"] = notify["emby_url"] or _env("EMBY_URL", "EMBY_HOST")
    notify["emby_token"] = data.get("emby_token") or ""
    return auto, notify


def env_hints():
    """Which notification hosts come from docker-compose, for the settings placeholders."""
    return {
        "kodi_notify_host": _env("KODI_HOST"),
        "kodi_notify_user": _env("KODI_USERNAME"),
        "kodi_library_host": _env("KODI_LIBRARY_HOST", "KODI_HOST"),
        "kodi_library_user": _env("KODI_LIBRARY_USERNAME", "KODI_USERNAME"),
        "jellyfin_url": _env("JELLYFIN_URL", "JELLYFIN_HOST"),
        "plex_url": _env("PLEX_URL", "PLEX_HOST"),
        "emby_url": _env("EMBY_URL", "EMBY_HOST"),
    }


def map_path(path, mappings, source):
    """Translate a path reported by Radarr, Sonarr, Bazarr or Lidarr into the container path.

    Rows for that source and rows for any source are tried longest remote prefix first. Unmapped paths
    come back unchanged.
    """
    text = clean_path(path)
    if not text:
        return ""
    ranked = [row for row in mappings or [] if row.get("source") in ("any", source)]
    ranked.sort(key=lambda row: (len(row["remote"]), row.get("source") != "any"), reverse=True)
    folded = text.lower() if _windows_style(text) else text
    for row in ranked:
        remote = row["remote"].lower() if _windows_style(row["remote"]) else row["remote"]
        if folded == remote or folded.startswith(remote + "/"):
            return row["local"] + text[len(remote):]
    return text


def _windows_style(path):
    return len(path) > 1 and path[1] == ":"
