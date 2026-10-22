"""Size caps for the two caches the subtitle tools keep under the cache directory.

`preview/` holds browser-playable video copies, `ocr/` the recognised text of picture subtitles.
Both can be rebuilt, so trimming only costs time: the least recently used files go first.
"""
import os
import time

from resonance.paths import cache_dir


CACHES = ("preview", "ocr")
_STALE_SECONDS = 3600


def folder(which):
    return os.path.join(cache_dir(), "video", which)


def _files(which):
    base = folder(which)
    try:
        names = os.listdir(base)
    except OSError:
        return []
    found = []
    for name in names:
        path = os.path.join(base, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if os.path.isfile(path):
            found.append((path, st.st_size, st.st_mtime))
    return found


def usage(which):
    files = _files(which)
    return {"files": len(files), "bytes": sum(size for _p, size, _m in files)}


def touch(path):
    """Mark a cache file as just used, so trimming keeps what is in use."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def trim(which, limit_bytes, keep=None):
    """Remove stale half-written files, then the least recently used files until the cache is
    within `limit_bytes`. `keep` (a path) is never removed. A limit of 0 means no cap."""
    removed = 0
    now = time.time()
    files = []
    for path, size, mtime in _files(which):
        if (".part" in path or path.endswith(".tmp")) and now - mtime > _STALE_SECONDS:
            try:
                os.unlink(path)
                removed += 1
            except OSError:
                pass
            continue
        files.append((path, size, mtime))
    if limit_bytes and limit_bytes > 0:
        total = sum(size for _p, size, _m in files)
        for path, size, _mtime in sorted(files, key=lambda f: f[2]):
            if total <= limit_bytes:
                break
            if keep and os.path.realpath(path) == os.path.realpath(keep):
                continue
            try:
                os.unlink(path)
                total -= size
                removed += 1
            except OSError:
                pass
    return removed


def clear(which):
    removed = 0
    for path, _size, _mtime in _files(which):
        if ".part" in path:
            continue                      # a build in progress
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            pass
    return removed


def limits(cfg):
    return {"preview": int(float(cfg.get("preview_cache_gb") or 0) * 1024 ** 3),
            "ocr": int(float(cfg.get("ocr_cache_mb") or 0) * 1024 ** 2)}


def trim_all(cfg, keep=None):
    cap = limits(cfg)
    for which in CACHES:
        trim(which, cap[which], keep=keep)
