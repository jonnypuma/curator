import base64
import hmac
import os

OPEN_PATHS = {"/api/health", "/api/v1/health", "/api/webhooks/lidarr", "/api/v1/trakt/callback"}
OPEN_PREFIXES = ("/api/v1/webhooks/",)


def _same(a, b):
    return hmac.compare_digest(str(a or "").encode(), str(b or "").encode())


def _credentials():
    configured = os.environ.get("BASIC_AUTH", "").strip()
    if not configured or ":" not in configured:
        return None
    return configured.split(":", 1)


def _authorized(headers, expected):
    raw = headers.get(b"authorization", b"").decode("latin-1")
    if not raw.lower().startswith("basic "):
        return False
    try:
        user, _, password = base64.b64decode(raw[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    return _same(user, expected[0]) and _same(password, expected[1])


class BasicAuthMiddleware:
    """Same BASIC_AUTH rule as the Flask app, applied to the FastAPI routes and websocket."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        expected = _credentials()
        if expected is None or path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        if _authorized(headers, expected):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", b'Basic realm="Curator"'),
                    (b"content-type", b"text/plain"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"Authentication required"})
