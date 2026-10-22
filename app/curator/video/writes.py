"""Guarded writes into movie, TV and movie set folders. Anything outside a configured, mounted video folder is refused."""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from resonance.errors import AppError
from resonance.paths import inside

_roots = {"at": 0.0, "list": []}


def _video_roots():
    if time.monotonic() - _roots["at"] > 30:
        from curator import folders

        sets = folders.set_root()
        _roots["list"] = folders.mounted("movies") + folders.mounted("tv") + ([sets] if sets else [])
        _roots["at"] = time.monotonic()
    return _roots["list"]


def forget_roots():
    """Settings changed: look the folders up again on the next write."""
    _roots["at"] = 0.0


def check(path):
    real = os.path.realpath(path)
    if not any(real == root or inside(root, real) for root in _video_roots()):
        raise AppError(f"Refusing to write outside the movie, TV and movie set folders: {path}", 403)
    return real


def ensure_dir(path):
    """Create a folder inside an allowed video folder."""
    real = check(path)
    os.makedirs(real, exist_ok=True)
    return real


def atomic_write(path, data):
    real = check(path)
    directory = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".curator-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if os.path.exists(real):
            try:
                shutil.copymode(real, tmp)
            except OSError:
                pass
        else:
            try:
                os.chmod(tmp, 0o664)
            except OSError:
                pass
        os.replace(tmp, real)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return real
