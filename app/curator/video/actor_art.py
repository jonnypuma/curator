"""Save actor portraits into the Kodi ``.actors`` folder. The image file is stored as downloaded."""
from __future__ import annotations

import os
import re
import asyncio

from curator.scrapers.http import ScrapeError
from curator.video import writes

_BAD = re.compile(r'[<>:"/\\|?*\x00]')


def _filename(name):
    """Kodi looks up ``.actors/First_Last.jpg``. Spaces in the name become underscores."""
    cleaned = _BAD.sub("", str(name or "")).strip().rstrip(".").replace(" ", "_")
    return f"{cleaned}.jpg" if cleaned else ""


def collapse_files(folder):
    """Keep one portrait per actor. A spaced name and its underscore twin are the same file to Kodi."""
    directory = os.path.join(folder or "", ".actors")
    if not directory or not os.path.isdir(directory):
        return 0
    groups = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".tbn"}:
                    continue
                groups.setdefault(stem.replace(" ", "_").casefold(), []).append(entry.path)
    except OSError:
        return 0
    removed = 0
    for paths in groups.values():
        ordered = sorted(paths, key=lambda path: (" " in os.path.splitext(os.path.basename(path))[0], path))
        keep = ordered[0]
        stem, ext = os.path.splitext(os.path.basename(keep))
        if " " in stem:
            dest = os.path.join(directory, f"{stem.replace(' ', '_')}{ext}")
            if os.path.normcase(dest) != os.path.normcase(keep) and not os.path.exists(dest):
                try:
                    os.replace(keep, dest)
                    keep = dest
                except OSError:
                    pass
        for path in ordered[1:]:
            if os.path.normcase(path) == os.path.normcase(keep):
                continue
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


async def store_thumbs(client, folder, actors):
    """Download remote thumbs. Existing files are left as they are. Returns the actor list."""
    if not folder or not actors:
        return actors or []
    dest = os.path.join(folder, ".actors")
    rows = []
    for actor in actors:
        item = dict(actor)
        filename = _filename(item.get("name"))
        item["_file"] = os.path.join(dest, filename) if filename else ""
        rows.append(item)
    if any(_remote(item) for item in rows):
        await asyncio.to_thread(os.makedirs, dest, exist_ok=True)
    gate = asyncio.Semaphore(4)

    async def one(item):
        path = item.pop("_file", "")
        url = str(item.get("thumb") or "")
        if not path:
            return item
        async with gate:
            exists = await asyncio.to_thread(os.path.isfile, path)
            if not exists:
                legacy = _legacy_filename(item.get("name"))
                legacy_path = os.path.join(os.path.dirname(path), legacy) if legacy else ""
                if legacy_path and await asyncio.to_thread(os.path.isfile, legacy_path):
                    await asyncio.to_thread(os.replace, legacy_path, path)
                    exists = True
            if _remote(item) and not exists:
                try:
                    data = await client.download(url)
                except ScrapeError:
                    return item
                await _write(path, data)
                exists = True
        if exists:
            item["thumb"] = os.path.basename(path)
        return item

    saved = list(await asyncio.gather(*(one(item) for item in rows)))
    await asyncio.to_thread(collapse_files, folder)
    return saved


def _legacy_filename(name):
    cleaned = _BAD.sub("", str(name or "")).strip().rstrip(".")
    return f"{cleaned}.jpg" if cleaned and " " in cleaned else ""


def _remote(item):
    return str(item.get("thumb") or "").lower().startswith(("http://", "https://"))


async def _write(path, data):
    await asyncio.to_thread(writes.atomic_write, path, data)
