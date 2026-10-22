"""Trakt sign-in with the device code.

Curator asks Trakt for a short code, you approve it at trakt.tv/activate, and Curator collects the
token from Trakt. Nothing calls back into the house. The client id and client secret stay in
config/trakt.json. Tokens are kept there too and are never sent to the browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from urllib.parse import urlencode, urlparse

import httpx

from resonance.errors import AppError
from resonance.paths import config_dir

logger = logging.getLogger(__name__)

AUTH_HOST = "https://trakt.tv"
API_HOST = "https://api.trakt.tv"
CALLBACK_PATH = "/api/v1/trakt/callback"
PENDING_SECONDS = 600
REFRESH_MARGIN = 24 * 3600

_lock = threading.Lock()
_pending = {}
_device = {}


def _path():
    return os.path.join(config_dir(), "trakt.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)


def client_id():
    return (_load().get("client_id") or os.environ.get("TRAKT_CLIENT_ID") or "").strip()


def client_secret():
    return (_load().get("client_secret") or os.environ.get("TRAKT_CLIENT_SECRET") or "").strip()


def client_source():
    if (_load().get("client_id") or "").strip():
        return "saved"
    return "environment" if (os.environ.get("TRAKT_CLIENT_ID") or "").strip() else ""


def redirect_uri(base_url):
    override = (os.environ.get("TRAKT_REDIRECT_URI") or "").strip()
    if override:
        return override
    return base_url.rstrip("/") + CALLBACK_PATH


def _refresh_redirect(value):
    """A redirect Trakt will accept on a token refresh. Device sign-in has none."""
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    return ""


def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _credential(value, label):
    value = str(value or "").strip()
    if value and (len(value) > 128 or not value.replace("-", "").replace("_", "").isalnum()):
        raise AppError(f"That does not look like a Trakt {label}", 400)
    return value


def save_client(client_id_value, client_secret_value=""):
    """Store the app credentials. A blank secret leaves the saved secret in place."""
    cid = _credential(client_id_value, "client ID")
    secret = _credential(client_secret_value, "client secret")
    data = _load()
    if cid != (data.get("client_id") or ""):
        data = {"client_id": cid} if cid else {}
    else:
        data["client_id"] = cid
    if secret:
        data["client_secret"] = secret
    elif not cid:
        data.pop("client_secret", None)
    _save(data)
    return status()


def save_client_id(value):
    return save_client(value, "")


def authorize_url(base_url, signup=False, force_login=False):
    cid = client_id()
    if not cid:
        raise AppError("Add the client ID of your Trakt app first", 400)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    uri = redirect_uri(base_url)
    now = time.time()
    with _lock:
        for key in [key for key, item in _pending.items() if now - item["at"] > PENDING_SECONDS]:
            _pending.pop(key, None)
        _pending[state] = {"verifier": verifier, "redirect_uri": uri, "client_id": cid, "at": now}
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if signup:
        params["signup"] = "true"
    if force_login:
        params["prompt"] = "login"
    return {"url": f"{AUTH_HOST}/oauth/authorize?{urlencode(params)}", "redirect_uri": uri}


def _post(path, body):
    try:
        response = httpx.post(f"{API_HOST}{path}", json=body, timeout=20,
                              headers={"Content-Type": "application/json", "User-Agent": "Curator"})
    except httpx.HTTPError as exc:
        message = f"Trakt could not be reached: {exc}"
        from resonance.connections import note

        note("trakt", message)
        raise AppError(message, 502) from exc
    if response.status_code >= 400:
        detail = ""
        try:
            detail = response.json().get("error_description") or response.json().get("error") or ""
        except ValueError:
            detail = response.text[:200]
        message = f"Trakt refused the request ({response.status_code}). {detail}".strip()
        from resonance.connections import note

        note("trakt", message)
        raise AppError(message, 502)
    from resonance.connections import clear

    clear("trakt")
    return response.json() if response.content else {}


def _api_json(path, body, cid):
    """POST to api.trakt.tv and return the status code plus the JSON object."""
    try:
        response = httpx.post(f"{API_HOST}{path}", json=body, timeout=20, headers={
            "Content-Type": "application/json", "User-Agent": "Curator",
            "trakt-api-version": "2", "trakt-api-key": cid,
        })
    except httpx.HTTPError as exc:
        raise AppError(f"Trakt could not be reached: {exc}", 502) from exc
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    return response.status_code, payload if isinstance(payload, dict) else {}


def _device_public(item):
    item = item or {}
    return {
        "status": item.get("status") or "idle",
        "user_code": item.get("user_code") or "",
        "verification_url": item.get("verification_url") or "",
        "interval": int(item.get("interval") or 5),
        "message": item.get("message") or "",
    }


def _user_code(payload):
    code = str(payload.get("user_code") or payload.get("userCode") or "").strip()
    if code:
        return code
    url = str(payload.get("verification_url") or "")
    marker = "/activate/"
    if marker in url:
        return url.split(marker, 1)[1].split("?", 1)[0].strip()
    return ""


def _remember_device(item):
    data = _load()
    data["device"] = {
        "device_code": item.get("device_code") or "",
        "user_code": item.get("user_code") or "",
        "verification_url": item.get("verification_url") or "",
        "expires_at": item.get("expires_at") or 0,
        "interval": item.get("interval") or 5,
        "next_poll": item.get("next_poll") or 0,
        "client_id": item.get("client_id") or "",
        "code_verifier": item.get("code_verifier") or "",
        "status": "waiting",
        "message": item.get("message") or "",
    }
    _save(data)


def _saved_device():
    item = _load().get("device") or {}
    if not isinstance(item, dict) or not item.get("device_code") or not item.get("user_code"):
        return {}
    if time.time() > float(item.get("expires_at") or 0):
        return {}
    return item


def _clear_saved_device():
    data = _load()
    if "device" not in data:
        return
    data.pop("device", None)
    _save(data)


def _active_device():
    with _lock:
        if _device.get("device_code") and _device.get("status") == "waiting":
            return dict(_device)
    return _saved_device()


def start_device():
    """Ask Trakt for a code the user types at trakt.tv/activate."""
    cid = client_id()
    if not cid:
        raise AppError("Add the client ID from your existing Trakt app first", 400)
    verifier, challenge = pkce_pair()
    status_code, payload = _api_json("/oauth/device/code", {
        "client_id": cid,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }, cid)
    user_code = _user_code(payload)
    if status_code >= 400 or not payload.get("device_code") or not user_code:
        detail = payload.get("error_description") or payload.get("error") or ""
        raise AppError(f"Trakt did not give a sign-in code ({status_code}). {detail}".strip(), 502)
    now = time.time()
    interval = max(5, int(payload.get("interval") or 5))
    item = {
        "device_code": payload["device_code"],
        "user_code": user_code,
        "verification_url": payload.get("verification_url") or "https://trakt.tv/activate",
        "expires_at": now + int(payload.get("expires_in") or 600),
        "interval": interval,
        "next_poll": now + interval,
        "client_id": cid,
        "code_verifier": verifier,
        "status": "waiting",
        "message": "Enter this code on the Trakt page.",
    }
    with _lock:
        _device.clear()
        _device.update(item)
    _remember_device(item)
    return _device_public(item)


def poll_device():
    """One check with Trakt. Waiting, connected, expired, or denied."""
    with _lock:
        if not _device.get("device_code"):
            saved = _saved_device()
            if saved:
                _device.update(saved)
        if not _device:
            return _device_public({})
        if _device.get("status") != "waiting":
            return _device_public(_device)
        now = time.time()
        if now > _device["expires_at"]:
            _device["status"] = "expired"
            _device["message"] = "That Trakt code expired. Press Connect again."
            return _device_public(_device)
        if now < _device["next_poll"]:
            return _device_public(_device)
        _device["next_poll"] = now + _device["interval"]
        snapshot = dict(_device)
    token_body = {
        "code": snapshot["device_code"],
        "client_id": snapshot["client_id"],
        "code_verifier": snapshot.get("code_verifier") or "",
    }
    status_code, payload = _api_json("/oauth/device/token", token_body, snapshot["client_id"])
    error = str(payload.get("error") or "")
    if status_code < 400 and payload.get("access_token"):
        stored = _store_tokens(snapshot["client_id"], payload, _load())
        stored["username"] = _username(snapshot["client_id"], stored.get("access_token"))
        _save(stored)
        with _lock:
            if _device.get("device_code") == snapshot["device_code"]:
                _device.clear()
                _device.update({"status": "connected", "message": "Trakt is connected."})
            _clear_saved_device()
            return _device_public(_device)
    with _lock:
        if _device.get("device_code") != snapshot["device_code"]:
            return _device_public(_device)
        if error in ("authorization_pending", "slow_down"):
            if error == "slow_down":
                _device["interval"] = int(_device.get("interval") or 5) + 5
                _device["next_poll"] = time.time() + _device["interval"]
            return _device_public(_device)
        if error == "expired_token" or status_code == 410:
            _device["status"] = "expired"
            _device["message"] = "That Trakt code expired. Press Connect again."
            _clear_saved_device()
            return _device_public(_device)
        if error == "access_denied":
            _device["status"] = "denied"
            _device["message"] = "Trakt sign-in was cancelled."
            _clear_saved_device()
            return _device_public(_device)
        if status_code == 404:
            _device["status"] = "expired"
            _device["message"] = "That Trakt code was already used. Press Connect again."
            _clear_saved_device()
            return _device_public(_device)
        if error and error not in ("authorization_pending", "slow_down"):
            _device["message"] = f"Still waiting for Trakt. {error}".strip()
        return _device_public(_device)


def cancel_device():
    with _lock:
        _device.clear()
    _clear_saved_device()
    return _device_public({})


def _store_tokens(cid, tokens, previous=None):
    data = dict(previous or _load())
    data["client_id"] = data.get("client_id") or ""
    created = int(tokens.get("created_at") or time.time())
    data.update({
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": created + int(tokens.get("expires_in") or 0),
        "scope": tokens.get("scope") or "",
        "token_client_id": cid,
    })
    _save(data)
    return data


def finish(state, code):
    """Exchange the code from the Trakt redirect for tokens."""
    with _lock:
        pending = _pending.pop(state or "", None)
    if not pending or time.time() - pending["at"] > PENDING_SECONDS:
        raise AppError("This Trakt sign-in expired or was not started here. Start it again from Settings.", 400)
    if not code:
        raise AppError("Trakt did not send an authorization code", 400)
    tokens = _post("/oauth/token", {
        "code": code,
        "client_id": pending["client_id"],
        "redirect_uri": pending["redirect_uri"],
        "grant_type": "authorization_code",
        "code_verifier": pending["verifier"],
    })
    data = _store_tokens(pending["client_id"], tokens)
    data["redirect_uri"] = pending["redirect_uri"]
    data["username"] = _username(pending["client_id"], data.get("access_token"))
    _save(data)
    return status()


def _username(cid, token):
    if not token:
        return ""
    try:
        response = httpx.get(f"{API_HOST}/users/settings", timeout=20, headers={
            "Authorization": f"Bearer {token}", "trakt-api-key": cid, "trakt-api-version": "2",
            "Content-Type": "application/json", "User-Agent": "Curator",
        })
        if response.status_code == 200:
            user = (response.json() or {}).get("user") or {}
            return user.get("username") or user.get("name") or ""
    except (httpx.HTTPError, ValueError):
        pass
    return ""


def access_token():
    """A valid access token, refreshed when it expires within a day. None when not connected."""
    data = _load()
    token = data.get("access_token")
    if not token:
        return None
    if int(data.get("expires_at") or 0) - time.time() > REFRESH_MARGIN:
        return token
    cid = data.get("token_client_id") or client_id()
    if not data.get("refresh_token") or not cid:
        return token
    body = {"refresh_token": data["refresh_token"], "client_id": cid, "grant_type": "refresh_token"}
    secret = client_secret()
    if secret:
        body["client_secret"] = secret
    uri = _refresh_redirect(data.get("redirect_uri") or os.environ.get("TRAKT_REDIRECT_URI"))
    if uri:
        body["redirect_uri"] = uri
    tokens = _post("/oauth/token", body)
    return _store_tokens(cid, tokens, data).get("access_token")


def disconnect():
    data = _load()
    token = data.get("access_token")
    cid = data.get("token_client_id") or client_id()
    if token and cid:
        try:
            _post("/oauth/revoke", {"token": token, "client_id": cid})
        except AppError as exc:
            logger.warning("Trakt token revoke failed: %s", exc)
    kept = {}
    if data.get("client_id"):
        kept["client_id"] = data["client_id"]
    if data.get("client_secret"):
        kept["client_secret"] = data["client_secret"]
    _save(kept)
    return status()


def mark_synced():
    data = _load()
    data["last_sync"] = int(time.time())
    _save(data)


def last_synced():
    return int(_load().get("last_sync") or 0)


def status():
    data = _load()
    connected = bool(data.get("access_token"))
    pending = _active_device()
    return {
        "client_id": client_id(),
        "client_secret_set": bool(client_secret()),
        "client_source": client_source(),
        "connected": connected,
        "username": (data.get("username") or "") if connected else "",
        "expires_at": data.get("expires_at") if connected else None,
        "last_sync": data.get("last_sync") if connected else None,
        "user_code": pending.get("user_code") or "",
        "verification_url": pending.get("verification_url") or "",
        "device_status": "waiting" if pending.get("user_code") else "",
        "device_message": pending.get("message") or "",
    }
