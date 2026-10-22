"""Download ranked artwork candidates into Kodi file names, honouring the overwrite policy."""
from __future__ import annotations

import asyncio
import io
import logging
import os
from urllib.parse import urlsplit

from PIL import Image

from curator.scrapers.http import ScrapeError
from curator.video import naming, writes

logger = logging.getLogger(__name__)
PNG_KINDS = {"clearlogo", "clearart", "discart", "characterart"}


def image_size(path):
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def _extension(url, kind, fmt):
    if fmt == "PNG":
        return ".png"
    if fmt in {"JPEG", "MPO"}:
        return ".jpg"
    ext = os.path.splitext(urlsplit(url).path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        return ".jpg" if ext == ".jpeg" else ext
    return ".png" if kind in PNG_KINDS else ".jpg"


def better(candidate_size, existing_size):
    """Overwrite All only replaces art when the new image has more pixels."""
    if not existing_size:
        return True
    if not candidate_size:
        return False
    return candidate_size[0] * candidate_size[1] > existing_size[0] * existing_size[1]


async def save_choice(client, url, base, kind):
    """Write the image the user picked, replacing a file of the same name."""
    data = await client.download(url)
    return await save_bytes(data, url, base, kind)


async def save_bytes(data, url, base, kind):
    """Write image bytes under the Kodi file name for this artwork kind. url only hints at the extension."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
    except Exception as exc:
        raise ScrapeError("That image could not be read") from exc
    path = base + _extension(url, kind, fmt)
    await asyncio.to_thread(writes.atomic_write, path, data)
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    for name in names:
        other = os.path.join(folder, name)
        if os.path.splitext(name)[0].lower() == stem and os.path.realpath(other) != os.path.realpath(path):
            try:
                await asyncio.to_thread(os.remove, other)
            except OSError:
                pass
    return path


async def fetch(client, ranked, base, kind, existing, policy, tries=3):
    """Returns the written path, or None when nothing changed. base is the path without the extension."""
    if existing and os.path.exists(existing):
        if policy != "overwrite":
            return None
        existing_size = await asyncio.to_thread(image_size, existing)
    else:
        existing, existing_size = None, None
    for candidate in ranked[:tries]:
        known = (candidate.get("width"), candidate.get("height"))
        if existing_size and known[0] and known[1] and not better(known, existing_size):
            continue
        try:
            data = await client.download(candidate["url"])
        except ScrapeError as exc:
            logger.info("art download failed for %s: %s", candidate["url"], exc)
            continue
        try:
            with Image.open(io.BytesIO(data)) as image:
                size, fmt = image.size, image.format
        except Exception:
            continue
        if existing_size and not better(size, existing_size):
            return None
        path = base + _extension(candidate["url"], kind, fmt)
        await asyncio.to_thread(writes.atomic_write, path, data)
        # Only the same name with another extension is removed, or the old file would keep winning the lookup.
        same_name = existing and os.path.splitext(existing)[0].lower() == base.lower()
        if same_name and os.path.realpath(existing) != os.path.realpath(path):
            try:
                await asyncio.to_thread(os.remove, existing)
            except OSError:
                pass
        return path
    return None


def _existing_named(folder, stem):
    if not os.path.isdir(folder):
        return None
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in names:
        if os.path.splitext(name)[0].lower() == stem.lower() and os.path.splitext(name)[1].lower() in naming.IMAGE_EXTS:
            return os.path.join(folder, name)
    return None


async def extras(client, ranked, folder, prefix, kind, policy, count=10):
    """Save further images as extrafanart/fanartN or extrathumbs/thumbN.

    ranked should already exclude the image used as the main fanart or landscape. A file already in
    the folder is left in place unless the policy is overwrite and the new image is larger.
    count is how many numbered files to fill. None keeps going through every candidate.
    """
    saved = []
    slot = 0
    for candidate in ranked:
        if count is not None and slot >= count:
            break
        slot += 1
        existing = _existing_named(folder, f"{prefix}{slot}")
        if existing and policy != "overwrite":
            continue
        writes.ensure_dir(folder)
        path = await fetch(client, [candidate], os.path.join(folder, f"{prefix}{slot}"), kind, existing, policy, tries=1)
        if path:
            saved.append(path)
    return saved
