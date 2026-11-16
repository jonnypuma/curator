"""The version each ARR app reported at its last connection test, kept in config/arr_versions.json.

Sonarr 5 brings a new API (/api/v5) and lets a show be found by its TMDB id as well as its TVDB id. The Sonarr
client reads the saved version to pick the API, and the page reads it to decide whether a show with only a TMDB id
can be looked up.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

APPS = ("radarr", "sonarr", "lidarr", "bazarr")
_LABELS = {"radarr": "Radarr", "sonarr": "Sonarr", "lidarr": "Lidarr", "bazarr": "Bazarr"}
_lock = threading.Lock()


def _path():
    from resonance.paths import config_dir

    return os.path.join(config_dir(), "arr_versions.json")


def _read():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def major_of(version):
    """5 for "5.0.1.2345", 0 when there is no number."""
    head = str(version or "").strip().lstrip("vV").split(".", 1)[0]
    return int(head) if head.isdigit() else 0


def same_url(left, right):
    return str(left or "").strip().rstrip("/").lower() == str(right or "").strip().rstrip("/").lower()


def record(app, version, url="", api=""):
    """Save and log what a connection test found. Returns the saved entry."""
    if app not in APPS:
        return {}
    entry = {
        "version": str(version or "").strip(),
        "major": major_of(version),
        "api": str(api or "").strip(),
        "url": str(url or "").strip().rstrip("/"),
        "tested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with _lock:
        data = _read()
        data[app] = entry
        try:
            os.makedirs(os.path.dirname(_path()), exist_ok=True)
            temp = f"{_path()}.tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
            os.replace(temp, _path())
        except OSError as exc:
            logger.warning("could not save the %s version: %s", _LABELS[app], exc)
    api_note = f", API {entry['api']}" if entry["api"] else ""
    logger.info("%s connection test: version %s%s at %s", _LABELS[app], entry["version"] or "unknown", api_note, entry["url"] or "the saved address")
    return entry


def get(app):
    return dict(_read().get(app) or {})


def all_versions():
    data = _read()
    return {app: dict(data[app]) for app in APPS if isinstance(data.get(app), dict)}


def sonarr_entry(url=None):
    """The saved Sonarr entry when it belongs to this address (the saved one when url is None), else {}."""
    entry = get("sonarr")
    if not entry:
        return {}
    if url is None:
        from resonance import settings

        url = (settings.load() or {}).get("sonarr_url") or ""
    return entry if not entry.get("url") or same_url(entry.get("url"), url) else {}


def sonarr_supports_tmdb(url=None):
    """True when the last test found Sonarr 5 or newer at this address. Sonarr 5 finds shows by TMDB id too."""
    return int(sonarr_entry(url).get("major") or 0) >= 5
