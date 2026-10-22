"""Outbound notifications: Curator tells other apps what it did.

Targets are kept in Settings (a list). Each has a type, the details that type needs, and the events it wants.
Sending never raises and never blocks the work that caused it: each message goes out on its own thread, and a
target that fails is logged and skipped. Tokens and URLs are secrets: they are hidden when settings are read back
and kept when the form is saved with those boxes left empty.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime

import requests

logger = logging.getLogger(__name__)
TIMEOUT = 15
MAX_TARGETS = 20

EVENTS = [
    ("scan_finished", "A scan finished"),
    ("scan_failed", "A scan failed"),
    ("import_processed", "A Radarr, Sonarr, Lidarr or Bazarr import was processed"),
    ("job_failed", "A background job failed"),
    ("backup_completed", "A database backup finished"),
    ("backup_failed", "A database backup failed"),
    ("quota_low", "The OpenSubtitles download quota is nearly used"),
]
EVENT_IDS = {key for key, _ in EVENTS}
DEFAULT_EVENTS = ["scan_failed", "job_failed", "backup_failed", "quota_low"]

# type id -> (label, fields it needs: (key, label, secret?, placeholder))
TYPES = {
    "webhook": ("Webhook (JSON)", [("url", "Address", True, "https://example.com/hook"), ("token", "Bearer token (optional)", True, "")]),
    "discord": ("Discord", [("url", "Webhook address", True, "https://discord.com/api/webhooks/...")]),
    "slack": ("Slack", [("url", "Webhook address", True, "https://hooks.slack.com/services/...")]),
    "telegram": ("Telegram", [("token", "Bot token", True, "123456:ABC..."), ("chat_id", "Chat id", False, "-1001234567890")]),
    "pushover": ("Pushover", [("token", "Application token", True, ""), ("user_key", "User or group key", True, "")]),
    "ntfy": ("ntfy", [("url", "Topic address", True, "https://ntfy.sh/my-topic"), ("token", "Access token (optional)", True, "")]),
    "gotify": ("Gotify", [("url", "Server address", False, "http://192.168.1.10:8080"), ("token", "Application token", True, "")]),
    "apprise": ("Apprise API", [("url", "Notify address", True, "http://192.168.1.10:8000/notify/curator")]),
}
SECRET_KEYS = ("url", "token", "user_key")
_LEVEL = {"info": "info", "success": "success", "warning": "warning", "error": "failure"}
_COLOR = {"info": 0x3498DB, "success": 0x2ECC71, "warning": 0xF1C40F, "error": 0xE74C3C}

_recent = {}
_recent_lock = threading.Lock()
_quota_day = {"day": None}


def _text(value, limit=500):
    return str(value or "").strip()[:limit]


def normalize(items):
    """Clean the list from Settings. Unknown types and events are dropped."""
    found = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("type") not in TYPES:
            continue
        ident = _text(item.get("id"), 40) or uuid.uuid4().hex[:12]
        if ident in seen:
            ident = uuid.uuid4().hex[:12]
        seen.add(ident)
        events = [e for e in (item.get("events") if isinstance(item.get("events"), list) else DEFAULT_EVENTS) if e in EVENT_IDS]
        entry = {
            "id": ident,
            "type": item["type"],
            "name": _text(item.get("name"), 80) or TYPES[item["type"]][0],
            "enabled": item.get("enabled") is not False,
            "events": events,
        }
        for key, _label, _secret, _hint in TYPES[item["type"]][1]:
            entry[key] = _text(item.get(key), 1000)
        found.append(entry)
        if len(found) >= MAX_TARGETS:
            break
    return found


def keep_secrets(incoming, previous):
    """Blank or masked secret boxes keep what was saved before, matched by target id."""
    if incoming is None:
        return previous if isinstance(previous, list) else []
    old = {item.get("id"): item for item in previous or [] if isinstance(item, dict)}
    out = []
    for item in incoming if isinstance(incoming, list) else []:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        before = old.get(item.get("id")) or {}
        for key in SECRET_KEYS:
            value = str(item.get(key) or "").strip()
            if (not value or not (set(value) - {"*", "•"})) and not item.get(f"clear_{key}"):
                item[key] = before.get(key, "") if before.get("type") == item.get("type") else ""
        out.append(item)
    return out


def masked(items):
    """The list as the browser may see it: secrets replaced by a flag that says one is saved."""
    view = []
    for item in items or []:
        copy = dict(item)
        for key in SECRET_KEYS:
            copy[f"{key}_set"] = bool(copy.get(key))
            if key in copy:
                copy[key] = ""
        view.append(copy)
    return view


def catalog():
    return {
        "events": [{"id": key, "label": label} for key, label in EVENTS],
        "types": [{"id": key, "label": label, "fields": [{"key": k, "label": l, "secret": s, "hint": h} for k, l, s, h in fields]}
                  for key, (label, fields) in TYPES.items()],
        "default_events": DEFAULT_EVENTS,
    }


def _config():
    from resonance import settings

    return normalize(settings.load().get("outbound"))


def _post(url, **kwargs):
    response = requests.post(url, timeout=TIMEOUT, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {(response.text or '')[:160]}".strip())
    return response


def deliver(target, event, title, message, level="info"):
    """Send one message to one target. Raises RuntimeError with a readable reason."""
    kind = target.get("type")
    url = target.get("url", "")
    token = target.get("token", "")
    body = f"{message}".strip() or title
    try:
        if kind == "webhook":
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            _post(url, json={"app": "Curator", "event": event, "title": title, "message": message, "level": level,
                             "time": datetime.now().astimezone().isoformat(timespec="seconds")}, headers=headers)
        elif kind == "discord":
            _post(url, json={"username": "Curator", "embeds": [{"title": title[:250], "description": body[:3900], "color": _COLOR.get(level, _COLOR["info"])}]})
        elif kind == "slack":
            _post(url, json={"text": f"*{title}*\n{body}"})
        elif kind == "telegram":
            _post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": target.get("chat_id", ""), "text": f"{title}\n{body}"[:4000]})
        elif kind == "pushover":
            _post("https://api.pushover.net/1/messages.json", data={"token": token, "user": target.get("user_key", ""), "title": title[:250],
                                                                    "message": body[:1024], "priority": 1 if level == "error" else 0})
        elif kind == "ntfy":
            headers = {"Title": title.encode("utf-8"), "Priority": "4" if level == "error" else "3", "Tags": level}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            _post(url, data=body.encode("utf-8"), headers=headers)
        elif kind == "gotify":
            _post(f"{url.rstrip('/')}/message", params={"token": token}, json={"title": title, "message": body, "priority": 8 if level == "error" else 5})
        elif kind == "apprise":
            _post(url, json={"title": title, "body": body, "type": _LEVEL.get(level, "info")})
        else:
            raise RuntimeError("Unknown notification type")
    except requests.RequestException as exc:
        raise RuntimeError(str(exc).split("\n")[0][:200]) from exc


def test(target):
    """Used by the Test button. Returns a short message, or raises RuntimeError."""
    clean = (normalize([dict(target, type=target.get("type"))]) or [None])[0]
    if not clean:
        raise RuntimeError("Choose a type first")
    missing = [label for key, label, secret, _ in TYPES[clean["type"]][1] if not clean.get(key) and "optional" not in label]
    if missing:
        raise RuntimeError(f"Fill in: {', '.join(missing)}")
    deliver(clean, "test", "Curator test", "This is a test message from Curator.", "info")
    return f"Sent to {clean['name']}."


def send(event, title, message="", level="info"):
    """Tell every enabled target that wants this event. Fire and forget; safe to call from anywhere."""
    try:
        if event not in EVENT_IDS:
            return
        key = (event, title, message)
        now = time.monotonic()
        with _recent_lock:
            for old in [k for k, t in _recent.items() if now - t > 60]:
                _recent.pop(old, None)
            if key in _recent:
                return
            _recent[key] = now
        targets = [t for t in _config() if t["enabled"] and event in t["events"]]
        for target in targets:
            threading.Thread(target=_run, args=(target, event, title, message, level), daemon=True, name="outbound").start()
    except Exception:
        logger.exception("could not queue the %s notification", event)


def _run(target, event, title, message, level):
    try:
        deliver(target, event, title, message, level)
    except Exception as exc:
        logger.warning("notification %s to %s failed: %s", event, target.get("name"), exc)


def scan_done(media, status, message, origin="manual"):
    """A scan reached its end. A scan started by an ARR import is reported as an import; a cancelled one is not."""
    try:
        name = {"movies": "Movie", "tv": "TV", "music": "Music", "sets": "Movie set"}.get(media, "Library")
        if status == "failed":
            send("scan_failed", f"{name} scan failed", str(message or "")[:500], "error")
        elif status == "completed":
            if origin == "webhook":
                send("import_processed", f"{name} import processed", str(message or "")[:500], "success")
            else:
                send("scan_finished", f"{name} scan finished", str(message or "")[:500], "success")
    except Exception:
        logger.exception("could not report the finished scan")


def quota_low(remaining, limit_hint=None):
    """Called after a subtitle download with the downloads left today. Sends at most once a day."""
    try:
        if remaining is None or int(remaining) > 3:
            return
        today = datetime.now().date().isoformat()
        if _quota_day["day"] == today:
            return
        _quota_day["day"] = today
        send("quota_low", "OpenSubtitles quota nearly used", f"{int(remaining)} downloads are left today.", "warning")
    except Exception:
        logger.exception("could not check the subtitle quota for a notification")
