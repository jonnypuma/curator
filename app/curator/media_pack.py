"""The shipped badge images (studio, network and record label logos, codec and resolution badges, provider icons).

They are thousands of small files, which makes the folder slow to copy and the image slow to build, so they travel as
one file, media.zip, built by scripts/pack-media.py. This module reads them from the zip when it is there, else from
the media/ folder (a checkout that was not packed). The zip is opened once and kept open; reads take a lock, because a
ZipFile is not safe to read from several threads at once. Logos the user adds (Settings, Files) are not in here: they
live in the config folder and curator.video.brands reads them from disk.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import threading
import zipfile

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "media.zip")
FOLDER = os.path.join(ROOT, "media")
SKIP_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}

_lock = threading.Lock()
_zip = None
_names = None             # {folder: {filename: zip entry name}}
_opened = False


def _open():
    """The zip and its index, opened on first use. None when there is no media.zip."""
    global _zip, _names, _opened
    with _lock:
        if _opened:
            return _zip
        _opened = True
        if not os.path.isfile(PACK):
            return None
        try:
            _zip = zipfile.ZipFile(PACK)
        except (OSError, zipfile.BadZipFile):
            logger.exception("media.zip could not be opened; the media folder is used instead")
            _zip = None
            return None
        _names = {}
        for info in _zip.infolist():
            if info.is_dir():
                continue
            parts = info.filename.replace("\\", "/").split("/")
            if len(parts) != 2 or parts[1].lower() in SKIP_NAMES:
                continue
            _names.setdefault(parts[0], {})[parts[1]] = info.filename
        logger.info("media.zip: %d badge images in %d folders", sum(len(v) for v in _names.values()), len(_names))
        return _zip


def reset():
    """Forget the open zip (tests, and after pack-media.py wrote a new one)."""
    global _zip, _names, _opened
    with _lock:
        if _zip is not None:
            try:
                _zip.close()
            except OSError:
                pass
        _zip, _names, _opened = None, None, False


def packed():
    return _open() is not None


def listing(folder, root=None):
    """The file names of one folder of shipped images (studios, network, …), from the zip or the folder.

    root: another media folder to read instead (tests point brands at a temporary one); the zip is not used then."""
    if root is None or os.path.normcase(os.path.abspath(root)) == os.path.normcase(os.path.abspath(FOLDER)):
        if _open() is not None:
            return list((_names or {}).get(folder, {}))
        root = FOLDER
    try:
        return [name for name in os.listdir(os.path.join(root, folder)) if name.lower() not in SKIP_NAMES]
    except OSError:
        return []


def _safe(folder, filename):
    return (folder and filename and "/" not in folder and "\\" not in folder and "/" not in filename
            and "\\" not in filename and not filename.startswith(".") and folder not in (".", ".."))


def read(folder, filename):
    """(bytes, etag) of one shipped image, or None. The etag is the zip's CRC, or the file's size and time."""
    if not _safe(folder, filename):
        return None
    if _open() is not None:
        entry = ((_names or {}).get(folder) or {}).get(filename)
        if not entry:
            return None
        with _lock:
            try:
                info = _zip.getinfo(entry)
                data = _zip.read(entry)
            except (KeyError, OSError, zipfile.BadZipFile):
                return None
        return data, f'"{info.CRC:08x}-{info.file_size}"'
    path = os.path.join(FOLDER, folder, filename)
    try:
        stat = os.stat(path)
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    return data, f'"{int(stat.st_mtime)}-{stat.st_size}"'


def media_type(filename):
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def response(folder, filename, if_none_match=None):
    """A FastAPI response for one shipped image: 304 when the browser's copy is current, 404 when there is none.
    The browser may keep the image a day without asking (the shipped set only changes with a new version)."""
    from fastapi import HTTPException
    from fastapi.responses import Response

    found = read(folder, filename)
    if found is None:
        raise HTTPException(status_code=404)
    data, etag = found
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if if_none_match and etag in [part.strip() for part in str(if_none_match).split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type(filename), headers=headers)
