"""One HTTP client for Radarr, Sonarr, Lidarr and Bazarr.

Each app module keeps its own _api() with its own address and API base (/api/v3, /api/v5, /api/v1, /api/), and calls
request() here for the part they share: the "not set up" check, the API key header, timeouts, refused keys, the error
text an app sends back, and the connection note shown under Settings, Integrations.
"""
from __future__ import annotations

import logging

from resonance.errors import AppError

logger = logging.getLogger(__name__)

APPS = {
    "radarr": {"label": "Radarr", "header": "X-Api-Key"},
    "sonarr": {"label": "Sonarr", "header": "X-Api-Key"},
    "lidarr": {"label": "Lidarr", "header": "X-Api-Key"},
    "bazarr": {"label": "Bazarr", "header": "X-API-KEY"},
}


class NotFound(AppError):
    """The app answered 404 with no message: the endpoint itself is not there (an API version it does not serve)."""


def label(app):
    return APPS[app]["label"]


def error_detail(response):
    """The reason an app gives with an error: the first errorMessage of a list, a message or title, or the text."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return str(body[0].get("errorMessage") or "").strip()
    if isinstance(body, dict):
        return str(body.get("message") or body.get("title") or "").strip()
    text = (getattr(response, "text", "") or "").strip()
    return text.splitlines()[0][:200] if text else ""


def request(app, method, url, key, path, payload=None, params=None, timeout=30, quiet_404=False):
    """Call one ARR app. Returns the JSON answer, or None for an empty or non-JSON answer. Raises AppError.

    url is the app's address, path everything after it (including the API base). quiet_404 leaves the connection
    note alone for a 404 the caller will try elsewhere (Sonarr probing /api/v5).
    """
    import requests

    from resonance.connections import clear, note

    name = label(app)
    if not url or not key:
        message = f"{name} is not set up. Add its address and API key under Settings, Integrations."
        note(app, message)
        raise AppError(message, 400)
    try:
        response = requests.request(method, f"{url.rstrip('/')}{path}", headers={APPS[app]["header"]: key},
                                    json=payload, params=params, timeout=timeout)
    except requests.Timeout as exc:
        message = f"{name} did not answer in time: {exc}"
        note(app, message)
        raise AppError(message, 502) from exc
    except requests.RequestException as exc:
        message = f"{name} could not be reached: {exc}"
        note(app, message)
        raise AppError(message, 502) from exc
    if response.status_code in (401, 403):
        note(app, f"{name} refused the API key")
        raise AppError(f"{name} refused the API key", 502)
    if response.status_code >= 400:
        detail = error_detail(response)
        message = f"{name} answered {response.status_code}{': ' + detail if detail else ''}"
        if response.status_code == 404 and not detail:
            if not quiet_404:
                note(app, message)
            raise NotFound(message, 502)
        note(app, message)
        raise AppError(message, 502)
    clear(app)
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None
