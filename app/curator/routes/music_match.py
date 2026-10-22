"""Music match, review, and batch lookup."""

from __future__ import annotations

from fastapi import APIRouter

from curator.routes.music_http import JsonBody, body_dict, cleaned, run
from resonance import batch, library, match, settings
from resonance.errors import AppError

router = APIRouter()


@router.post("/api/batch")
async def start_batch(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        job, started = batch.start(payload.get("album_ids") or [], payload)
        return cleaned({"job": job, "started": started})

    return await run(work)


@router.get("/api/batch/status")
async def batch_status():
    return await run(lambda: cleaned(batch.current_job()))


@router.post("/api/batch/lookup")
async def start_batch_lookup(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        state, started = batch.start_lookup(payload.get("album_ids") or [], payload.get("mode"))
        return cleaned({"job": state, "started": started})

    return await run(work)


@router.get("/api/batch/lookup")
async def batch_lookup_status():
    return await run(lambda: cleaned(batch.lookup_state()))


@router.post("/api/batch/lookup/apply")
async def apply_batch_lookup(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        state, started = batch.apply_lookup(payload.get("choices") or [], payload.get("steps"))
        return cleaned({"job": state, "started": started})

    return await run(work)


@router.post("/api/batch/rollback")
async def rollback_batch():
    from resonance import undo

    return await run(lambda: cleaned(undo.rollback_last()))


@router.get("/api/matches")
async def list_loaded_matches():
    return await run(lambda: cleaned({"matches": library.loaded_matches()}))


@router.put("/api/matches/{album_id}")
async def save_loaded_match(album_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: library.store_loaded_match(album_id, payload))


@router.delete("/api/matches/{album_id}")
async def delete_loaded_match(album_id: str):
    return await run(lambda: library.drop_loaded_match(album_id))


@router.get("/api/albums/{album_id}/variants")
async def album_variants(album_id: str):
    def work():
        library.require_uuid(album_id)
        return cleaned(match.release_variants(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/match")
async def match_album(album_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(album_id)
        if payload.get("release_id"):
            library.require_uuid(payload["release_id"])
            if payload.get("compare"):
                return cleaned(match.release_comparison(album_id, payload["release_id"]))
            return cleaned(match.build_proposal(album_id, payload["release_id"]))
        if payload.get("force"):
            return cleaned(match.search(
                album_id,
                artist_name=str(payload.get("artist") or ""),
                album_title=str(payload.get("title") or ""),
                force_text=True,
            ))
        return cleaned(match.search(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/review")
async def fetch_album_review(album_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(album_id)
        if payload.get("save"):
            return cleaned(match.save_chosen_review(
                album_id,
                payload.get("review"),
                payload.get("source"),
                payload.get("url"),
                allow_blank=bool(payload.get("manual")),
            ))
        if payload.get("search"):
            return cleaned(match.search_album_reviews(album_id, payload.get("artist"), payload.get("title")))
        return cleaned(match.lookup_album_review(album_id, refresh=bool(payload.get("refresh"))))

    return await run(work)


@router.post("/api/albums/{album_id}/apply")
async def apply_album(album_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        steps = settings.apply_steps()
        if not any(step in {"tags", "nfo", "lyrics"} for step in steps):
            raise AppError("Turn on Tags, .nfo, or Lyrics in Settings")
        library.require_uuid(album_id)
        return cleaned(match.apply(album_id, payload, steps=steps))

    return await run(work)


@router.post("/api/albums/{album_id}/library-update")
async def queue_album_library_update(album_id: str):
    def work():
        library.require_uuid(album_id)
        return cleaned(match.queue_artist_update(album_id))

    return await run(work)
