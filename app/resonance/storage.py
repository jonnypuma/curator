"""Size and purge of the app's two disposable-or-not folders: the cache (rebuildable) and the data folder."""
import logging
import os

from resonance.paths import cache_dir

logger = logging.getLogger(__name__)


def _walk(folder):
    files = size = 0
    for base, _dirs, names in os.walk(folder):
        for name in names:
            try:
                size += os.path.getsize(os.path.join(base, name))
                files += 1
            except OSError:
                continue
    return files, size


def cache_stats():
    """Files and bytes in the cache folder, in total and per top-level folder."""
    root = cache_dir()
    parts = []
    total_files = total_bytes = 0
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(root, name)
        if os.path.isdir(path):
            files, size = _walk(path)
            parts.append({"name": name, "files": files, "bytes": size})
        elif os.path.isfile(path):
            try:
                files, size = 1, os.path.getsize(path)
            except OSError:
                continue
            parts.append({"name": name, "files": files, "bytes": size})
        else:
            continue
        total_files += files
        total_bytes += size
    return {
        "path": root,
        "files": total_files,
        "bytes": total_bytes,
        "folders": parts,
        "mounted": os.path.ismount(root),
    }


def purge_cache():
    """Delete everything in the cache folder. Every file in it is rebuilt when it is needed again."""
    root = cache_dir()
    removed = freed = 0
    for base, _dirs, names in os.walk(root, topdown=False):
        for name in names:
            path = os.path.join(base, name)
            try:
                freed += os.path.getsize(path)
                os.remove(path)
                removed += 1
            except OSError:
                logger.info("could not remove %s", path, exc_info=True)
        if base != root:
            try:
                os.rmdir(base)
            except OSError:
                pass
    return {"removed": removed, "bytes": freed}
