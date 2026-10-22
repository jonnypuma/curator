"""Music scan control. These stay on /api/scan, separate from /api/v1/scan."""

from __future__ import annotations

import os

from fastapi import APIRouter, Query, Request

from curator.routes.music_http import JsonBody, body_dict, cleaned, error, run
from resonance import backup, jobs, library
from resonance.errors import AppError
from resonance.paths import choose_roots, music_roots

router = APIRouter()


@router.post("/api/scan")
async def start_scan(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        from resonance import scan_queue

        from curator.folders import excluded_real

        requested = payload.get("roots") or []
        albums = payload.get("albums") or []
        if isinstance(requested, str):
            requested = [requested]
        if isinstance(albums, str):
            albums = [albums]
        albums = [item.strip() for item in albums if isinstance(item, str) and item.strip()]
        skip = excluded_real()
        mounted_roots = music_roots()
        included = [path for path in mounted_roots if path not in skip]
        if requested:
            allowed = []
            skipped = False
            for item in requested:
                if not isinstance(item, str) or not item.strip():
                    continue
                real = os.path.realpath(item.strip()) if os.path.exists(item.strip()) else os.path.normpath(item.strip())
                if real in skip:
                    skipped = True
                    continue
                allowed.append(item)
            if not allowed and skipped:
                raise AppError("That folder is excluded from scans. Turn Exclude off under Settings, General.", 400)
            requested = allowed
        chosen = choose_roots(requested, included)
        if not chosen:
            if mounted_roots:
                raise AppError("Every music folder is excluded from scans. Turn Exclude off under Settings, General.", 400)
            raise AppError("No music paths are mounted. Add a library path in Settings.", 400)
        outcome = scan_queue.submit({
            "media": "music",
            "mode": payload.get("mode") or "incremental",
            "kind": "library",
            "roots": chosen,
            "albums": albums,
            "force": bool(payload.get("force")),
            "verbose": bool(payload.get("verbose")),
        })
        blocked = ""
        if outcome == "busy":
            blocked = "backup" if backup.status().get("status") == "running" else "scan"
        return cleaned({
            "job": jobs.current_job(),
            "started": outcome == "started",
            "queued": outcome in {"queued", "duplicate"},
            "duplicate": outcome == "duplicate",
            "blocked": blocked,
            "scan_queue": scan_queue.snapshot(),
        })

    return await run(work)


@router.post("/api/scan/cancel")
async def cancel_scan():
    def work():
        if not jobs.request_cancel():
            return None
        return cleaned(jobs.current_job())

    result = await run(work)
    if result is None:
        return error("No scan is running", 409)
    return result


@router.get("/api/scan/prompt")
async def scan_prompt():
    def work():
        prompt = jobs.current_prompt()
        if not prompt:
            raise AppError("The scan is not waiting for a choice", 409)
        return cleaned(prompt)

    return await run(work)


@router.post("/api/scan/prompt")
async def answer_scan_prompt(body: dict | None = JsonBody):
    payload = body_dict(body)
    action = payload.get("action") or "skip"
    if action == "release":
        library.require_uuid(payload.get("release_id") or "")
        decision = {
            "action": "release",
            "release_id": str(payload.get("release_id")),
            "apply": bool(payload.get("apply")),
        }
    elif action in {"continue", "skip"}:
        decision = {"action": action}
    else:
        raise AppError("Unknown scan choice", 400)

    def work():
        if not jobs.resolve_prompt(decision):
            raise AppError("The scan is not waiting for a choice", 409)
        return {"ok": True}

    return await run(work)


@router.get("/api/scan/status")
async def scan_status():
    return await run(lambda: cleaned(jobs.current_job()))


@router.post("/api/webhooks/lidarr")
async def lidarr_webhook(request: Request, token: str = Query("")):
    from resonance import lidarr

    provided = token or request.headers.get("X-Resonance-Token") or ""
    if not lidarr.token_matches(provided):
        return error("Lidarr webhook token was not accepted", 401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run(lambda: lidarr.accept(payload))
