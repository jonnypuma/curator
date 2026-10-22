import asyncio
import json
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from curator import arr_queue, boot_status, env, events, ingest, library_queue, queue_state, trakt_sync
from curator.auth import BasicAuthMiddleware
from curator.routes import router as v1_router
from curator.routes import music_artwork, music_jobs, music_library, music_match, music_scan, music_system
from curator.video import files, scanner, scrape, store
from resonance.errors import AppError

logger = logging.getLogger("curator")

env.load()


def _move_old_cache():
    """Move files left in the old artwork folders. It runs beside startup because a large cache takes a while."""
    try:
        from resonance import cache_migrate

        cache_migrate.run()
    except Exception:
        logger.exception("the old cache folder could not be moved")


def _check_local_extras():
    """Find out which movies and shows have a trailer and a theme song file. It runs beside startup."""
    try:
        from curator.video import local_extras

        local_extras.backfill()
    except Exception:
        logger.exception("trailer and theme song files could not be checked")


def _boot_music():
    """Database, settings, and the music scheduler. These used to start with the Flask app."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)
    from resonance import backup, db, schedule, settings
    from curator import curator_schedule

    db.init_db()
    settings.ensure()
    threading.Thread(target=_move_old_cache, name="cache-migration", daemon=True).start()
    schedule.start()
    curator_schedule.start()
    backup.start()
    threading.Thread(target=db.maintain_catalog, name="catalogue-maintenance", daemon=True).start()
    threading.Thread(target=_check_local_extras, name="local-extras", daemon=True).start()


async def _startup(loop):
    """Database and workers. The page is already being served so the loading screen can show."""
    try:
        events.set_loop(loop)
        boot_status.advance(0.04)
        await run_in_threadpool(_boot_music)
        boot_status.advance(0.62)
        try:
            await run_in_threadpool(store.interrupt_running)
        except Exception:
            logger.exception("could not mark interrupted video scans")
        scanner.add_listener(
            lambda snapshot: asyncio.run_coroutine_threadsafe(events.broadcaster.broadcast("SCAN_PROGRESS", snapshot), loop)
        )
        scrape.add_listener(
            lambda snapshot: asyncio.run_coroutine_threadsafe(events.broadcaster.broadcast("SCRAPE_PROGRESS", snapshot), loop)
        )
        files.add_listener(
            lambda snapshot: asyncio.run_coroutine_threadsafe(events.broadcaster.broadcast("FILES_PROGRESS", snapshot), loop)
        )
        ingest.set_emitter(
            lambda kind, data: asyncio.run_coroutine_threadsafe(events.broadcaster.broadcast(kind, data), loop)
        )
        boot_status.advance(0.68)
        try:
            await run_in_threadpool(ingest.start)
        except Exception:
            logger.exception("the webhook queue could not start")
        boot_status.advance(0.72)
        try:
            await run_in_threadpool(library_queue.start)
        except Exception:
            logger.exception("the library queue could not start")
        boot_status.advance(0.76)
        try:
            await run_in_threadpool(arr_queue.start)
        except Exception:
            logger.exception("the ARR queue could not start")
        try:
            from resonance import scan_queue

            await run_in_threadpool(scan_queue.restore)
        except Exception:
            logger.exception("the scan queue could not resume")
        trakt_sync.start_timer()
        boot_status.mark_ready()
        logger.info("Curator ready")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Curator could not start")
        boot_status.fail(str(exc) or "Curator could not start.")


@asynccontextmanager
async def lifespan(_app):
    loop = asyncio.get_running_loop()
    events.set_loop(loop)
    startup = asyncio.create_task(_startup(loop))
    tick = asyncio.create_task(events.ticker(queue_state.snapshot))
    try:
        yield
    finally:
        startup.cancel()
        ingest.stop()
        arr_queue.stop()
        library_queue.stop()
        tick.cancel()
        for task in (startup, tick):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


class _StartingGate:
    """Other requests wait until the database and workers are up. The loading page does not."""

    # /api/v1/ui-state only reads and writes one small file in the config folder; the page needs it
    # before it draws anything, which can be while the database is still starting.
    _OPEN = {"/", "/favicon.ico", "/api/boot", "/api/health", "/api/v1/health", "/api/v1/ui-state"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or boot_status.snapshot()["ready"]:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path in self._OPEN or path.startswith("/static/") or path.startswith("/media/"):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013})
            return
        body = b'{"error":"Curator is still starting."}'
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


app = FastAPI(title="Curator", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json", lifespan=lifespan)
app.add_middleware(_StartingGate)
app.add_middleware(BasicAuthMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(v1_router)
app.include_router(music_library.router)
app.include_router(music_scan.router)
app.include_router(music_match.router)
app.include_router(music_artwork.router)
app.include_router(music_jobs.router)
app.include_router(music_system.router)

templates = Jinja2Templates(directory=str(ROOT / "templates"))


# Content-hash fingerprints for static files: computed once at startup.
# Browsers can cache static assets for a long time; a changed file gets a new
# hash in the query string so the browser fetches the updated version.
import hashlib as _hashlib

_STATIC_DIR = ROOT / "static"
_static_hashes: dict = {}
_static_mtimes: dict = {}
_build = {"label": ""}


def _build_static_hashes() -> None:
    global _static_hashes, _static_mtimes
    hashes: dict = {}
    mtimes: dict = {}
    try:
        for entry in _STATIC_DIR.rglob("*"):
            if entry.is_file():
                rel = entry.relative_to(_STATIC_DIR).as_posix()
                try:
                    mtimes[rel] = entry.stat().st_mtime_ns
                    digest = _hashlib.sha256(entry.read_bytes()).hexdigest()[:12]
                    hashes[rel] = digest
                except OSError:
                    pass
    except OSError:
        pass
    _static_hashes = hashes
    _static_mtimes = mtimes
    _build["label"] = _build_label(hashes)


def _build_label(hashes) -> str:
    """Version shown beside the logo: the number in the VERSION file next to this file, for example 1.0.0.

    Every update bumps the last digit; a digit that passes 9 rolls over into the one before it
    (1.0.9 is followed by 1.1.0, and 1.9.9 by 2.0.0). Static files are cache-busted by their own hash,
    so a changed file is picked up whatever this says."""
    try:
        text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    return text or "dev"


# Build hashes in a background thread so the event loop isn't blocked at startup.
# The Jinja helper returns no query-string for any file not yet hashed; once
# the thread finishes (usually < 1 s) the dict is populated atomically.
threading.Thread(target=_build_static_hashes, name="static-hashes", daemon=True).start()


def _url_for(endpoint, **kwargs):
    """Static URL carrying its own cache-buster.

    The template used to append `?v={{ ui }}` after each `url_for` call. That worked when
    this function returned a bare URL, but once per-file content hashes were added here the
    two concatenated as `?v=HASH?v=UI`: a single `?` with everything after it as one query
    value, which Flask served as a 404 or an unexpected version. Every static tag on the
    page was broken that way, which is why `window.state`, `openScanModal` and friends
    came back undefined.

    The fix is to return a correctly-formed URL from here and strip the manual suffix from
    the template. During the first second of startup, before the hash cache has populated,
    the URL falls back to the APP_VERSION so the asset is still bustable.
    """
    if endpoint == "static":
        rel = str(kwargs.get("filename") or "").lstrip("/")
        try:
            entry = _STATIC_DIR / rel
            mtime = entry.stat().st_mtime_ns
            if _static_mtimes.get(rel) != mtime:
                _static_mtimes[rel] = mtime
                _static_hashes[rel] = _hashlib.sha256(entry.read_bytes()).hexdigest()[:12]
        except OSError:
            pass
        token = _static_hashes.get(rel) or os.environ.get("APP_VERSION", "1")
        return f"/static/{rel}?v={token}"
    return "/"


templates.env.globals["url_for"] = _url_for


@app.get("/api/boot")
def boot():
    """Startup progress for the loading screen. Stays available before the database is ready."""
    state = boot_status.snapshot()
    return {"ready": state["ready"], "progress": state["progress"], "error": state["error"]}


@app.get("/")
def index(request: Request):
    context = {"version": _build["label"] or os.environ.get("APP_VERSION", "1")}
    try:
        return templates.TemplateResponse(request, "index.html", context)
    except TypeError:
        return templates.TemplateResponse("index.html", {"request": request, **context})


@app.get("/favicon.ico")
def favicon():
    return FileResponse(ROOT / "static" / "favicon.png", media_type="image/png")


@app.exception_handler(AppError)
async def app_error(_request: Request, exc: AppError):
    payload = {"error": str(exc)}
    extra = getattr(exc, "conflict", None)
    if isinstance(extra, dict):
        payload.update(extra)
    return JSONResponse(payload, status_code=exc.status)


# Allowed WebSocket origins: comma-separated list in CMM_ALLOWED_ORIGINS.
# Defaults to permissive (any origin) when the variable is not set so that
# docker-compose deployments work out of the box without extra config.
_ALLOWED_ORIGINS: set | None = None
_raw_origins = os.environ.get("CMM_ALLOWED_ORIGINS", "").strip()
if _raw_origins:
    _ALLOWED_ORIGINS = {o.strip().rstrip("/").lower() for o in _raw_origins.split(",") if o.strip()}


def _ws_origin_ok(websocket: WebSocket) -> bool:
    """Return True when the WebSocket Origin header is acceptable."""
    if _ALLOWED_ORIGINS is None:
        return True  # permissive mode: no restriction configured
    origin = websocket.headers.get("origin", "").strip().rstrip("/").lower()
    return not origin or origin in _ALLOWED_ORIGINS


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    if not _ws_origin_ok(websocket):
        await websocket.close(code=4403)
        return
    await events.broadcaster.connect(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "QUEUE_TICK", "data": queue_state.snapshot()}))
        while True:
            message = await websocket.receive_text()
            try:
                action = (json.loads(message) or {}).get("action")
            except (ValueError, AttributeError):
                action = None
            if action == "PING":
                await websocket.send_text(json.dumps({"type": "PONG", "data": {}}))
            elif action == "FORCE_FLUSH":
                ingest.force_flush()
            elif action == "CLEAR_QUEUE":
                await run_in_threadpool(ingest.clear)
    except WebSocketDisconnect:
        pass
    finally:
        await events.broadcaster.disconnect(websocket)


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/media/{folder}/{filename}")
async def media_logo(folder: str, filename: str):
    """A logo you added in Settings → Files wins over a shipped logo with the same name."""
    from fastapi.responses import FileResponse

    from curator.video import brands

    path = brands.custom_file(folder, filename)
    if path:
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    shipped = (ROOT / "media" / folder / filename).resolve()
    base = (ROOT / "media").resolve()
    if base in shipped.parents and shipped.is_file():
        return FileResponse(shipped)
    raise HTTPException(status_code=404)


app.mount("/media", StaticFiles(directory=str(ROOT / "media")), name="media-badges")
