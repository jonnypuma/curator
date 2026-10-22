import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class Broadcaster:
    """Fan-out of JSON events to every connected /ws/events client."""

    def __init__(self):
        self._clients = {}
        self._lock = asyncio.Lock()

    @property
    def count(self):
        return len(self._clients)

    async def connect(self, websocket):
        await websocket.accept()
        async with self._lock:
            self._clients[websocket] = asyncio.Lock()

    async def disconnect(self, websocket):
        async with self._lock:
            self._clients.pop(websocket, None)

    async def broadcast(self, kind, data=None):
        if not self._clients:
            return
        payload = json.dumps({"type": kind, "data": data or {}}, default=str)
        async with self._lock:
            items = list(self._clients.items())
        dead = []
        for client, lock in items:
            try:
                async with lock:
                    await client.send_text(payload)
            except Exception:
                dead.append(client)
        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.pop(client, None)


broadcaster = Broadcaster()
_loop = None


def set_loop(loop):
    global _loop
    _loop = loop


def emit(kind, data=None):
    if _loop and not _loop.is_closed() and broadcaster.count:
        try:
            asyncio.run_coroutine_threadsafe(broadcaster.broadcast(kind, data), _loop)
        except Exception:
            logger.exception("could not broadcast %s", kind)


async def ticker(status_fn, interval=1.0):
    """Push QUEUE_TICK once per interval while any client is connected."""
    while True:
        try:
            if broadcaster.count:
                if asyncio.iscoroutinefunction(status_fn):
                    data = await status_fn()
                else:
                    data = await asyncio.to_thread(status_fn)
                await broadcaster.broadcast("QUEUE_TICK", data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("queue ticker failed")
        await asyncio.sleep(interval)
