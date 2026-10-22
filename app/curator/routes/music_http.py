"""Helpers for music routes that moved off Flask."""

from __future__ import annotations

from fastapi import Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from resonance import db, thumbs


def body_dict(body):
    return body if isinstance(body, dict) else {}


JsonBody = Body(default=None)


async def run(fn, *args, **kwargs):
    return await run_in_threadpool(fn, *args, **kwargs)


def cleaned(value):
    return db.clean(value)


def file_response(path, max_age=0):
    cache = "no-store" if not max_age else f"public, max-age={int(max_age)}"
    return FileResponse(path, headers={"Cache-Control": cache})


def image_response(path, width=0, max_age=0):
    """The image, or a cached smaller copy when a width is asked for. Falls back to the original file."""
    if width and str(path).lower().endswith(thumbs.IMAGE_EXTENSIONS):
        try:
            thumb = thumbs.thumbnail(path, thumbs.nearest_width(width), "music/thumbs")
        except (OSError, ValueError):
            thumb = path
        if thumb != path:
            # The copy's name changes with the image, so the browser may keep it and only check that it is current.
            return FileResponse(thumb, headers={"Cache-Control": "private, no-cache"})
    return file_response(path, max_age)


def error(message, status):
    return JSONResponse({"error": message}, status_code=status)
