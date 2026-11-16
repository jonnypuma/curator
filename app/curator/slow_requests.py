"""Requests that took a long time, kept in memory and listed in About.

Several routes already log their own steps when they take more than three seconds. This keeps the last ones of every
route in one place, so a slow window on the real library can be named without reading the logs. Nothing is stored on
disk and a restart starts the list again.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

SLOW_SECONDS = 2.0
KEEP = 50
# Long by design: a video stream, live events, an upload, a download of a backup or an export.
_SKIP = ("/stream", "/ws", "/events", "/upload", "/download", "/export")

_lock = threading.Lock()
_rows: deque = deque(maxlen=KEEP)


def note(method, path, status, seconds):
    if seconds < SLOW_SECONDS or any(part in path for part in _SKIP):
        return
    with _lock:
        _rows.appendleft({
            "method": method, "path": path, "status": int(status or 0), "seconds": round(seconds, 2),
            "at": datetime.now().isoformat(timespec="seconds"),
        })


def recent():
    with _lock:
        return list(_rows)


class SlowRequestMiddleware:
    """Times each HTTP request from its start to the end of its body. The query string is left out."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status = {"code": 0}

        async def timed_send(message):
            if message["type"] == "http.response.start":
                status["code"] = message.get("status", 0)
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                note(scope.get("method", ""), scope.get("path", ""), status["code"], time.monotonic() - started)

        return await self.app(scope, receive, timed_send)
