import platform
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from curator import env
from curator.video import store, ytdlp_update
from resonance import db, library

router = APIRouter()

TOOLS = ("ffprobe", "ffmpeg", "mediainfo", "dovi_tool", "mkvpropedit", "mkvmerge", "yt-dlp", "tesseract", "alass")


def _db_ok():
    try:
        db.fetchone("SELECT 1 AS ok")
        return True
    except Exception:
        return False


@router.get("/health")
async def health():
    ok = await run_in_threadpool(_db_ok)
    body = {
        "status": "ok" if ok else "error",
        "database": "connected" if ok else "unavailable",
        "tools": {name: bool(shutil.which(name)) for name in TOOLS},
    }
    return JSONResponse(body, status_code=200 if ok else 503)


_TOOL_VERSION_ARGS = {
    "ffprobe": ["-version"], "ffmpeg": ["-version"], "mediainfo": ["--Version"], "dovi_tool": ["--version"],
    "mkvpropedit": ["--version"], "mkvmerge": ["--version"], "yt-dlp": ["--version"], "tesseract": ["--version"],
    "alass": ["--version"],
}
_tool_versions = {}
_STARTED = time.time()


def _tool_version(name):
    """First line of a tool's version output; cached, since it never changes while the app runs.

    yt-dlp is the exception: it can be updated from the About window, so it is asked every time (the answer
    is remembered per file by the trailer code)."""
    if name == "yt-dlp":
        path = ytdlp_update.binary()
        if not path:
            return ""
        from curator.video import trailers

        return trailers.ytdlp_version(path) or "installed"
    if name in _tool_versions:
        return _tool_versions[name]
    path = shutil.which(name)
    text = ""
    if path:
        try:
            result = subprocess.run([path, *_TOOL_VERSION_ARGS.get(name, ["--version"])], capture_output=True,
                                    text=True, timeout=5, check=False)
            lines = [line.strip() for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines() if line.strip()]
            text = lines[0] if lines else "installed"
        except (OSError, subprocess.SubprocessError):
            text = "installed"
    _tool_versions[name] = text
    return text


def _about():
    version = ""
    try:
        version = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    database = ""
    try:
        database = str((db.fetchone("SHOW server_version") or {}).get("server_version") or "")
    except Exception:
        pass
    return {
        "version": version or "dev",
        "python": platform.python_version(),
        "database": database,
        "uptime_seconds": int(time.time() - _STARTED),
        "tools": [_tool_entry(name) for name in TOOLS],
    }


def _tool_entry(name):
    entry = {"name": name, "version": _tool_version(name)}
    if name == "yt-dlp" and entry["version"]:
        info = ytdlp_update.status()
        entry.update(age_days=info["age_days"], stale=info["stale"], updated=info["updated"])
    return entry


@router.get("/about")
async def about():
    return await run_in_threadpool(_about)


@router.get("/ytdlp")
async def ytdlp_status(check: bool = False):
    """The yt-dlp in use. With check=1 it also asks GitHub for the newest release (remembered for six hours)."""
    return await run_in_threadpool(ytdlp_update.status, check)


@router.post("/ytdlp/update")
async def ytdlp_install_update():
    """Download the newest yt-dlp into the cache folder, after checking it against the published checksum."""
    return await run_in_threadpool(ytdlp_update.update)


def _health():
    """Quick local checks for the About window. Nothing here calls out to another service."""
    from resonance import paths

    checks = []

    def add(name, state, detail=""):
        checks.append({"name": name, "state": state, "detail": detail})

    try:
        db.fetchone("SELECT 1 AS ok")
        add("Database", "ok", "Reachable")
    except Exception as error:
        add("Database", "bad", str(error)[:120])
    for kind, label in (("music", "Music"), ("movies", "Movies"), ("tv", "TV Shows")):
        try:
            folders = paths.configured_library_paths(kind) or []
        except Exception:
            folders = []
        for folder in folders:
            folder = folder.get("path") if isinstance(folder, dict) else folder
            if not folder:
                continue
            if not paths.readable_dir(folder):
                add(f"{label} folder", "bad", f"{folder} cannot be read")
                continue
            try:
                usage = shutil.disk_usage(folder)
                free = usage.free / (1024 ** 3)
                pct = usage.free * 100 / usage.total if usage.total else 100
                add(f"{label} folder", "warn" if pct < 5 else "ok", f"{folder}: {free:,.0f} GB free ({pct:.0f}%)")
            except OSError:
                add(f"{label} folder", "ok", folder)
    try:
        info = ytdlp_update.status()
        if info["installed"] and info["version"]:
            if info["stale"]:
                add("yt-dlp", "warn", f"{info['version']} is {info['age_days'] // 30} months old; YouTube downloads may fail. Press Update yt-dlp above")
            elif info["age_days"] is not None:
                add("yt-dlp", "ok", f"{info['version']}, {info['age_days']} days old")
        elif not info["installed"]:
            add("yt-dlp", "warn", "Not installed; trailer and theme song downloads will fail")
    except Exception:
        pass
    missing = [tool for tool in ("ffprobe", "ffmpeg") if not _tool_version(tool)]
    if missing:
        add("Tools", "bad", f"{', '.join(missing)} not installed")
    try:
        row = db.fetchone(
            "SELECT status, finished_at FROM scan_jobs WHERE status <> 'running' AND finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1"
        ) or {}
        if row:
            add("Last scan", "ok", f"{row.get('status')}, {row.get('finished_at'):%Y-%m-%d %H:%M}")
        else:
            add("Last scan", "warn", "No scan has finished yet")
    except Exception:
        pass
    try:
        failed = db.fetchone(
            "SELECT COUNT(*) AS n FROM work_jobs WHERE status IN ('failed', 'error') AND finished_at > NOW() - INTERVAL '7 days'"
        ) or {}
        n = int(failed.get("n") or 0)
        add("Jobs, last 7 days", "warn" if n else "ok", f"{n} failed" if n else "None failed")
    except Exception:
        pass
    return {"checks": checks}


@router.get("/about/health")
async def about_health():
    return await run_in_threadpool(_health)


@router.get("/totals")
async def totals():
    music = await run_in_threadpool(library.totals)
    video = await run_in_threadpool(store.totals)
    return {
        "music": music,
        "movies": {
            "movies": int(video.get("movies") or 0),
            "bytes": int(video.get("movie_bytes") or 0),
            "seconds": int(video.get("movie_seconds") or 0),
        },
        "sets": {
            "sets": int(video.get("sets") or 0),
            "movies": int(video.get("set_movies") or 0),
        },
        "tv": {
            "shows": int(video.get("shows") or 0),
            "seasons": int(video.get("seasons") or 0),
            "episodes": int(video.get("episodes") or 0),
            "bytes": int(video.get("episode_bytes") or 0),
            "seconds": int(video.get("episode_seconds") or 0),
        },
    }


@router.get("/config")
async def config():
    cfg = env.load()
    return {
        "port": cfg.port,
        "debounce_minutes": cfg.debounce_minutes,
        "max_postpone_minutes": cfg.max_postpone_minutes,
        "overwrite_all": cfg.overwrite_all,
        "webhook_key_set": bool(cfg.api_key),
    }


_client_log_window = {"minute": 0, "count": 0}


@router.post("/client-log")
async def client_log(body: dict | None = None):
    """The browser reports startup progress and script errors so they appear in `docker logs`.

    Rate limited (40 a minute) and truncated; newlines are removed so a message cannot fake log lines.
    """
    import logging
    import time

    now = int(time.time() // 60)
    if _client_log_window["minute"] != now:
        _client_log_window.update(minute=now, count=0)
    _client_log_window["count"] += 1
    if _client_log_window["count"] > 40:
        return {"ok": False}
    data = body if isinstance(body, dict) else {}
    level = {"error": logging.ERROR, "warn": logging.WARNING}.get(str(data.get("level")), logging.INFO)
    text = " ".join(str(data.get("message") or "").split())[:600]
    where = " ".join(str(data.get("where") or "").split())[:200]
    logging.getLogger("curator.client").log(level, "browser: %s%s", text, f" [{where}]" if where else "")
    return {"ok": True}


@router.get("/ui-state")
def ui_state_get():
    """Saved layout choices (columns, column order and widths, pane widths, sort)."""
    from curator import ui_state

    return {"state": ui_state.load()}


@router.put("/ui-state")
def ui_state_put(body: dict | None = None):
    from curator import ui_state

    values = (body or {}).get("values") if isinstance(body, dict) else None
    return {"state": ui_state.update(values)}
