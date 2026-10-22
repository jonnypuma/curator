"""Resized copies of artwork, kept in the cache folder so lists and grids do not load the full image.

A copy is named after the source file's path, size, modification time and the width, so a changed image gets a
new copy and the old one is simply never asked for again. Every copy can be rebuilt, and the cache folder can be
deleted at any time.
"""
import hashlib
import os
import time
import uuid

from resonance.paths import cache_dir

WIDTHS = (160, 342, 500, 780)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def nearest_width(wanted):
    return min(WIDTHS, key=lambda item: abs(item - int(wanted)))


def thumbnail(path, width, folder):
    """The path of a copy no wider than `width` in cache/<folder>, made on first use. An image already that small is returned as is."""
    from PIL import Image

    stat = os.stat(path)
    png = path.lower().endswith(".png")
    key = hashlib.sha1(f"{path}|{stat.st_mtime_ns}|{stat.st_size}|{width}|{int(png)}".encode("utf-8")).hexdigest()
    base = os.path.join(cache_dir(), folder, key[:2])
    target = os.path.join(base, f"{key}.png" if png else f"{key}.jpg")
    if os.path.isfile(target):
        try:
            os.utime(target, None)
        except OSError:
            pass
        return target
    with Image.open(path) as image:
        if image.size[0] <= width and image.size[1] <= width * 3:
            return path
        os.makedirs(base, exist_ok=True)
        image.thumbnail((width, width * 3))
        temp = f"{target}.{uuid.uuid4().hex}.tmp"
        if png:
            if image.mode not in ("RGBA", "LA", "RGB", "L"):
                image = image.convert("RGBA")
            image.save(temp, "PNG")
        else:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(temp, "JPEG", quality=85, optimize=True)
    os.replace(temp, target)
    return target


THUMB_KEEP_SECONDS = 60 * 24 * 3600
THUMB_MAX_BYTES = 1024 * 1024 * 1024
FOLDERS = ("music/thumbs", "video/thumbs")


def trim(folder, keep_seconds=THUMB_KEEP_SECONDS, max_bytes=THUMB_MAX_BYTES):
    """Remove copies not used for a long time, then the least recently used ones when the folder is too big."""
    base = os.path.join(cache_dir(), folder)
    found = []
    for where, _dirs, names in os.walk(base):
        for name in names:
            path = os.path.join(where, name)
            try:
                info = os.stat(path)
            except OSError:
                continue
            found.append((info.st_mtime, info.st_size, path))
    found.sort()
    total = sum(size for _m, size, _p in found)
    now = time.time()
    removed = 0
    for modified, size, path in found:
        if now - modified <= keep_seconds and total <= max_bytes:
            break
        try:
            os.remove(path)
            removed += 1
            total -= size
        except OSError:
            continue
    return removed


def trim_all():
    return sum(trim(folder) for folder in FOLDERS)
