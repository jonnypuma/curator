"""Music change notices. Navidrome is asked to scan. Emby, Jellyfin and Plex refresh from Integrations."""
import hashlib
import logging
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from resonance.settings import load as load_settings
from resonance.settings import webhook_parts

logger = logging.getLogger(__name__)

_MUSIC_LINES = {
    "tags": "Updated music tags",
    "rename": "Updated renamed music",
    "batch": "Updated a music batch",
    "scan": "Music scan finished",
}
_SUBSONIC_DROP = {"u", "p", "t", "s", "api_key", "apikey", "token"}


def fire(event, folders=(), items=()):
    try:
        from curator import notify

        notify.announce("music", _MUSIC_LINES.get(event) or "Updated music")
        notify.request("music", folders=tuple(folders or ()), items=tuple(items or ()))
    except Exception:
        logger.info("music update request failed for %s", event, exc_info=True)


def _navidrome_cfg(cfg):
    """Navidrome's address lives on the saved settings. A player config may only carry the on/off switch."""
    cfg = cfg or {}
    if cfg.get("webhook_navidrome"):
        return cfg
    stored = load_settings()
    merged = dict(stored)
    notify = stored.get("notify") if isinstance(stored.get("notify"), dict) else {}
    if "navidrome_on" in cfg:
        merged["navidrome_on"] = cfg["navidrome_on"]
    elif "navidrome_on" in notify:
        merged["navidrome_on"] = notify["navidrome_on"]
    return merged


def navidrome_ready(cfg):
    """True when Navidrome is enabled and a scan can be signed with a user name and password."""
    cfg = _navidrome_cfg(cfg)
    if cfg.get("navidrome_on") is False or cfg.get("webhook_navidrome_enabled") is False:
        return False
    _method, url, _headers = navidrome_target(cfg)
    return bool(url) and "u=" in url and "t=" in url


def send_navidrome_scan(cfg=None):
    """Ask Navidrome to scan and raise when the login or the request fails."""
    cfg = _navidrome_cfg(cfg if cfg is not None else load_settings())
    if cfg.get("navidrome_on") is False:
        raise RuntimeError("Navidrome is turned off under Settings, Integrations")
    if cfg.get("webhook_navidrome_enabled") is False:
        raise RuntimeError("Navidrome scans are turned off")
    method, url, headers = navidrome_target(cfg)
    if not url or "u=" not in url or "t=" not in url:
        raise RuntimeError("Set the Navidrome address, user name, and password")
    from resonance.connections import clear, note

    try:
        response = requests.request(method, url, headers=headers, timeout=20)
    except requests.RequestException as exc:
        message = f"Navidrome did not answer: {exc}"
        note("navidrome", message)
        raise RuntimeError(message) from exc
    if response.status_code >= 400:
        message = f"Navidrome answered HTTP {response.status_code}"
        note("navidrome", message)
        raise RuntimeError(message)
    problem = subsonic_error(response)
    if problem:
        note("navidrome", problem)
        raise RuntimeError(problem)
    clear("navidrome")
    return "Navidrome music library scan sent."


def scan_navidrome():
    """Ask Navidrome to scan. Emby, Jellyfin and Plex are updated from Integrations instead."""
    cfg = _navidrome_cfg(load_settings())
    if cfg.get("navidrome_on") is False or cfg.get("webhook_navidrome_enabled") is False:
        return
    try:
        send_navidrome_scan(cfg)
    except Exception:
        logger.info("navidrome scan failed", exc_info=True)


def target(name, cfg):
    """The request to send. The key is attached here and is not part of the stored address."""
    if name == "navidrome":
        return navidrome_target(cfg)
    url, embedded, found = webhook_parts(cfg.get(f"webhook_{name}"))
    key = str(cfg.get(f"webhook_{name}_key") or embedded or "").strip()
    param = str(cfg.get(f"webhook_{name}_param") or found or "").strip()
    if not url:
        return "", "", {}
    headers = {}
    if key and param:
        url = _with_query(url, param, key)
    elif key and name in {"emby", "jellyfin"}:
        headers["X-Emby-Token"] = key
    elif key and name == "plex":
        url = _with_query(url, "X-Plex-Token", key)
    elif key:
        url = _with_query(url, "api_key", key)
    method = "GET" if name == "plex" or "startscan" in url.lower() else "POST"
    return method, url, headers


def navidrome_target(cfg):
    """Subsonic startScan. Navidrome has no API key; each call uses md5(password + salt)."""
    url, _embedded, _param = webhook_parts(cfg.get("webhook_navidrome"))
    if not url:
        return "", "", {}
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in _SUBSONIC_DROP]
    user = str(cfg.get("webhook_navidrome_user") or "").strip()
    if not user:
        stored = dict(parse_qsl(parts.query, keep_blank_values=True))
        user = str(stored.get("u") or "").strip()
    password = str(cfg.get("webhook_navidrome_key") or "").strip()
    if user:
        query.append(("u", user))
    if password:
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{password}{salt}".encode("utf-8")).hexdigest()
        query.append(("t", token))
        query.append(("s", salt))
    query.extend([("v", "1.16.1"), ("c", "Curator"), ("f", "json")])
    path = parts.path if parts.path not in ("", "/") else "/rest/startScan"
    signed = urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))
    return "GET", signed, {}


def subsonic_error(response):
    """Navidrome reports a bad login as HTTP 200 with status failed."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    body = payload.get("subsonic-response") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or body.get("status") != "failed":
        return ""
    error = body.get("error") or {}
    return str(error.get("message") or "Navidrome refused the login")


def _send(name, cfg, event):
    method, url, headers = target(name, cfg)
    if not url:
        return
    try:
        response = requests.request(method, url, headers=headers, timeout=20)
        if response.status_code >= 400:
            logger.info("%s webhook for %s returned %s", name, event, response.status_code)
        elif name == "navidrome":
            problem = subsonic_error(response)
            if problem:
                logger.info("navidrome scan refused: %s", problem)
    except Exception:
        logger.info("%s webhook failed for %s", name, event, exc_info=True)


def _with_query(url, name, value):
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != name.lower()]
    query.append((name, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
