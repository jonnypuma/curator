"""Settings, backup, health, and the system snapshot."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from curator import env
from curator.routes.music_http import JsonBody, body_dict, cleaned, run
from resonance import artwork, backup, batch, db, jobs, library, memory, settings, storage
from resonance.errors import AppError
from resonance.paths import (
    browse_directory,
    discover_mounts,
    empty_library_paths,
    offline_library_paths,
    unreadable_library_paths,
)
from resonance.sources import musicbrainz

router = APIRouter()


def _video_scan_status():
    from curator.video import scanner

    return scanner.status()


def _video_scrape_status():
    from curator.video import scrape

    return scrape.status()


def _scan_queue_snapshot():
    from resonance import scan_queue

    return scan_queue.snapshot()


def _file_job_status():
    from curator.video import files

    return files.status()


@router.get("/api/health")
async def health():
    def work():
        try:
            db.fetchone("SELECT 1 AS ok")
        except Exception:
            return None
        return {"status": "ok"}

    result = await run(work)
    if result is None:
        return JSONResponse({"status": "error"}, status_code=503)
    return result


@router.get("/api/system")
async def system():
    from resonance import connections, lidarr

    def work():
        cfg = settings.load()
        return cleaned({
            "database": "connected",
            "musicbrainz": musicbrainz.status(),
            "scan": jobs.current_job(),
            "video_scan": _video_scan_status(),
            "video_scrape": _video_scrape_status(),
            "scan_queue": _scan_queue_snapshot(),
            "file_job": _file_job_status(),
            "batch": batch.current_job(),
            "lookup": batch.lookup_job(),
            "totals": library.totals(),
            "music_paths": cfg.get("music_paths") or [],
            "movie_paths": cfg.get("movie_paths") or [],
            "tv_paths": cfg.get("tv_paths") or [],
            "mounts": discover_mounts(),
            "offline_paths": offline_library_paths(cfg),
            "unreadable_paths": unreadable_library_paths(cfg),
            "empty_paths": empty_library_paths(cfg),
            "work": jobs.list_work(),
            "backup": backup.status(),
            "lidarr": lidarr.feed(),
            "connections": connections.snapshot(),
            "connection_notices": connections.notices(),
            "fill_missing_during_scan": cfg.get("fill_missing_during_scan", True) is not False,
            "memory": memory.snapshot(),
            "keys": {
                "lastfm": bool(cfg.get("lastfm_key")),
                "fanart": bool(cfg.get("fanart_key")),
                "acoustid": bool(cfg.get("acoustid_key")),
            },
            "cmm_api_key": env.load().api_key,
        })

    return await run(work)


@router.get("/api/storage")
async def storage_info():
    """Size of the data folder (uploaded and replaced artwork) and of the cache."""
    def work():
        return {"data": artwork.additional_stats(), "cache": storage.cache_stats()}

    return await run(work)


@router.post("/api/storage/purge/{folder}")
async def storage_purge(folder: str):
    if folder == "data":
        return await run(artwork.purge_additional)
    if folder == "cache":
        return await run(storage.purge_cache)
    raise AppError("Unknown folder", 404)


@router.get("/api/settings")
async def get_settings():
    return await run(settings.public)


@router.put("/api/settings")
async def put_settings(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        settings.save(payload)
        return settings.public()

    return await run(work)


@router.post("/api/schedule/preview")
async def schedule_preview(body: dict | None = JsonBody):
    from resonance import cron

    payload = body_dict(body)
    kind = "backup" if payload.get("kind") == "backup" else "schedule"
    view = cron.as_schedule(payload, kind) if kind == "backup" else {
        "schedule_enabled": bool(payload.get("schedule_enabled")),
        "schedule_mode": payload.get("schedule_mode"),
        "schedule_preset": payload.get("schedule_preset"),
        "schedule_time": payload.get("schedule_time"),
        "schedule_weekday": payload.get("schedule_weekday"),
        "schedule_day": payload.get("schedule_day"),
        "schedule_cron": payload.get("schedule_cron"),
    }
    return await run(lambda: cron.schedule_summary(view))


@router.post("/api/backup")
async def start_backup():
    return await run(backup.request_manual)


@router.get("/api/backup/files")
async def backup_files():
    return await run(lambda: {"files": backup.list_dumps(), "status": backup.status()})


@router.post("/api/backup/restore")
async def restore_backup(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: backup.request_restore(payload.get("file"), payload.get("confirm"), payload.get("folder")))


@router.post("/api/backup/import-music")
async def import_music(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: backup.request_music_import(payload.get("file"), payload.get("confirm"), payload.get("folder")))


@router.post("/api/settings/test-key")
async def test_api_key(body: dict | None = JsonBody):
    from resonance import keys

    payload = body_dict(body)
    service = payload.get("service")
    if service not in keys.LABELS:
        raise AppError("Unknown API key", 400)
    return await run(lambda: keys.test_service(service, payload.get("key"), bool(payload.get("cleared"))))


@router.get("/api/browse")
async def browse(root: str = "", path: str = ""):
    return await run(lambda: browse_directory(root, path))
