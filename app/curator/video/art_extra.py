"""Uploaded and replaced artwork for movies, shows, seasons, episodes and sets.

Music keeps these as options in its artwork window (resonance/artwork.py). Video does the same here: an image you
upload, and the image a new choice, upload or removal is about to overwrite, is copied to
data/artwork/additional/<movie|tv|sets>. They are listed again in the picker and can be purged in Settings → Files.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid

from PIL import Image

from resonance import db
from resonance.errors import AppError
from resonance.paths import additional_media_dir

logger = logging.getLogger(__name__)

URL_PREFIX = "/api/v1/artwork/extra/"
_MEDIA = {"movie": "movie", "set": "sets", "show": "tv", "season": "tv", "episode": "tv"}
_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "MPO": ".jpg", "WEBP": ".webp", "GIF": ".gif"}


def media_folder(kind):
    return additional_media_dir(_MEDIA.get(kind, "movie"))


def keep_bytes(kind, item_id, art_kind, data, origin):
    """Save these image bytes for this artwork type unless the same image is already kept. Returns the row id or None."""
    try:
        return _keep_bytes(kind, item_id, art_kind, data, origin)
    except Exception:
        # Keeping a copy is a bonus. It must never stop the artwork from being saved.
        logger.info("could not keep a copy of %s artwork", art_kind, exc_info=True)
        return None


def _keep_bytes(kind, item_id, art_kind, data, origin):
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            ext = _EXTENSIONS.get(image.format, ".jpg")
    except Exception:
        return None
    folder = media_folder(kind)
    digest = hashlib.sha1(data).hexdigest()[:20]
    path = os.path.join(folder, f"{art_kind}-{digest}{ext}")
    known = db.fetchone(
        "SELECT id FROM video_art_extra WHERE kind = %s AND item_id = %s AND art_kind = %s AND path = %s",
        (kind, item_id, art_kind, path),
    )
    if known:
        return str(known["id"])
    try:
        os.makedirs(folder, exist_ok=True)
        if not os.path.isfile(path):
            temp = f"{path}.{uuid.uuid4().hex}.tmp"
            with open(temp, "wb") as handle:
                handle.write(data)
            os.replace(temp, path)
    except OSError:
        logger.info("could not keep a copy of %s artwork", art_kind, exc_info=True)
        return None
    row = db.fetchone(
        """
        INSERT INTO video_art_extra (kind, item_id, art_kind, path, origin, width, height)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (kind, item_id, art_kind, path, origin, width, height),
    )
    return str(row["id"]) if row else None


def keep_file(kind, item_id, art_kind, path, origin="replaced"):
    """Keep the image currently on disk before it is overwritten or deleted."""
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    return keep_bytes(kind, item_id, art_kind, data, origin)


def listed(kind, item_id):
    """The kept images of one item, shaped like the online choices in the artwork picker."""
    rows = db.fetchall(
        "SELECT id, art_kind, path, origin, width, height FROM video_art_extra WHERE kind = %s AND item_id = %s ORDER BY created_at DESC",
        (kind, item_id),
    )
    items = []
    for row in rows:
        if not os.path.isfile(row["path"]):
            continue
        url = f"{URL_PREFIX}{row['id']}"
        items.append({
            "kind": row["art_kind"],
            "url": url,
            "preview": url,
            "width": row.get("width") or 0,
            "height": row.get("height") or 0,
            "score": 0,
            "lang": "",
            "source": "Uploaded" if row["origin"] == "upload" else "Replaced",
            "selected": False,
        })
    return items


def path_for(extra_id):
    try:
        uuid.UUID(str(extra_id))
    except ValueError as exc:
        raise AppError("Artwork not found", 404) from exc
    row = db.fetchone("SELECT path FROM video_art_extra WHERE id = %s", (extra_id,))
    if not row or not os.path.isfile(row["path"]):
        raise AppError("Artwork not found", 404)
    return row["path"]


def read_url(url):
    """The bytes behind one of this module's picker URLs."""
    with open(path_for(str(url)[len(URL_PREFIX):]), "rb") as handle:
        return handle.read()
