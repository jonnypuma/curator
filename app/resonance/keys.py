import logging

from resonance import settings

logger = logging.getLogger(__name__)

LABELS = {
    "lastfm": "Last.fm",
    "fanart": "Fanart.tv",
    "acoustid": "AcoustID",
    "tmdb": "TMDB",
    "tvdb": "TheTVDB",
    "omdb": "OMDb",
}
_FIELDS = {
    "lastfm": "lastfm_key",
    "fanart": "fanart_key",
    "acoustid": "acoustid_key",
    "tmdb": "tmdb_key",
    "tvdb": "tvdb_key",
    "omdb": "omdb_key",
}
# A known MusicBrainz artist. The request only checks that Fanart.tv accepts the key.
_FANART_ARTIST = "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"


def chosen_key(typed, saved, cleared=False):
    text = str(typed or "").strip()
    if text and set(text) - {"*", "•"}:
        return text
    if cleared:
        return ""
    return str(saved or "").strip()


def lastfm_ok(status, body):
    if not isinstance(body, dict) or body.get("error"):
        return False
    return status < 400 and "artists" in body


def fanart_ok(status, body):
    if status in (401, 403):
        return False
    if isinstance(body, dict) and str(body.get("status") or "").lower() == "error":
        return False
    return 200 <= status < 300


def acoustid_ok(body):
    if not isinstance(body, dict):
        return False
    error = body.get("error") or {}
    code = error.get("code")
    if code in (4, 6):
        return False
    return body.get("status") == "ok" or code == 3


def omdb_ok(status, body):
    if not isinstance(body, dict):
        return False
    if str(body.get("Response") or "").lower() == "true":
        return True
    # A used-up daily quota still proves the key is real.
    return "limit" in str(body.get("Error") or "").lower()


def test_service(service, typed=None, cleared=False):
    label = LABELS.get(service)
    if not label:
        raise ValueError(service)
    saved = ""
    text = str(typed or "").strip()
    if not (text and set(text) - {"*", "•"}) and not cleared:
        saved = (settings.load().get(_FIELDS[service]) or "").strip()
    key = chosen_key(typed, saved, cleared)
    from resonance.connections import clear, note

    if not key:
        logger.info("connection test %s failed: no API key", label)
        note(service, f"{label} has no API key")
        return {"ok": False, "service": label}
    try:
        ok = _CHECK[service](key)
    except Exception as exc:
        logger.info("connection test %s failed: %s", label, type(exc).__name__)
        note(service, f"{label} connection test failed: {exc}")
        return {"ok": False, "service": label}
    if ok:
        logger.info("connection test %s successful", label)
        clear(service)
    else:
        logger.info("connection test %s failed: rejected", label)
        note(service, f"{label} rejected the API key")
    return {"ok": bool(ok), "service": label}


def _lastfm(key):
    status, body = _fetch(
        "get",
        "https://ws.audioscrobbler.com/2.0/",
        params={"method": "chart.gettopartists", "api_key": key, "format": "json", "limit": "1"},
    )
    return lastfm_ok(status, body)


def _fanart(key):
    status, body = _fetch(
        "get",
        f"https://webservice.fanart.tv/v3/music/{_FANART_ARTIST}",
        params={"api_key": key},
    )
    return fanart_ok(status, body)


def _acoustid(key):
    _status, body = _fetch(
        "post",
        "https://api.acoustid.org/v2/lookup",
        data={"format": "json", "client": key, "duration": "1", "fingerprint": "A", "meta": "recordings"},
    )
    return acoustid_ok(body)


def _tmdb(key):
    if len(key) > 40:
        status, _body = _fetch("get", "https://api.themoviedb.org/3/configuration",
                               headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    else:
        status, _body = _fetch("get", "https://api.themoviedb.org/3/configuration", params={"api_key": key})
    return 200 <= status < 300


def _tvdb(key):
    status, body = _fetch("post", "https://api4.thetvdb.com/v4/login", json={"apikey": key})
    return 200 <= status < 300 and bool((body.get("data") or {}).get("token"))


def _omdb(key):
    status, body = _fetch("get", "https://www.omdbapi.com/", params={"apikey": key, "i": "tt0111161"})
    return omdb_ok(status, body)


def _fetch(method, url, **kwargs):
    from resonance.sources.client import _call

    response = _call(url, lambda session: getattr(session, method)(url, timeout=20, **kwargs))
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return response.status_code, body


_CHECK = {
    "lastfm": _lastfm,
    "fanart": _fanart,
    "acoustid": _acoustid,
    "tmdb": _tmdb,
    "tvdb": _tvdb,
    "omdb": _omdb,
}
