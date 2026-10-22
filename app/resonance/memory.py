"""How much RAM this process is using, and a pause when a container limit is close.

Scans and artwork downloads call wait() before the next heavy step. That keeps a
large library from stacking probes and image downloads until Linux stops the process.
"""
from __future__ import annotations

import gc
import os
import threading
import time

_lock = threading.Lock()
_announced = 0.0
_cached = None
_cached_at = 0.0
_libc = None
# Pause once this much of the container limit, or of the machine, is in use.
_RATIO = 0.80
# Also pause when less than this is still free. 256 MB is enough for one probe or image.
_FLOOR = 256 * 1024 * 1024


def snapshot():
    """Process RSS, RAM still free, and the ceiling. The ceiling is the container limit when one is set."""
    global _cached, _cached_at
    now = time.monotonic()
    with _lock:
        if _cached is not None and now - _cached_at < 0.5:
            return _cached
    info = _read_snapshot()
    with _lock:
        _cached = info
        _cached_at = time.monotonic()
    return info


def release():
    """Give freed Python memory back to the OS so a long scan does not keep old buffers."""
    global _cached, _libc
    gc.collect()
    if _libc is None:
        try:
            import ctypes

            _libc = ctypes.CDLL("libc.so.6")
        except (OSError, AttributeError):
            _libc = False
    if _libc:
        try:
            _libc.malloc_trim(0)
        except (OSError, AttributeError):
            _libc = False
    with _lock:
        _cached = None


def wait(log=None, stop=None):
    """Block while memory is close to the limit. Returns when there is room, the job stops, or the wait gives up."""
    global _announced
    if stop and stop():
        return
    if not _tight():
        return
    release()
    if not _tight():
        return
    now = time.monotonic()
    announce = False
    with _lock:
        if log and now - _announced > 30:
            _announced = now
            announce = True
    if announce:
        log("Memory is close to the limit. Work waits until some is free.")
    for _ in range(45):
        if stop and stop():
            return
        time.sleep(1)
        release()
        if not _tight():
            return
    if log:
        log("Memory is still close to the limit. Work continues.")


def _read_snapshot():
    app_bytes = _proc_rss()
    host_total, host_free = _meminfo()
    limit_free, limit_total = _cgroup_memory()
    available = host_free
    if limit_free is not None:
        available = limit_free if available is None else min(available, limit_free)
    total = limit_total or host_total
    if app_bytes is None and available is None:
        return None
    return {"app_bytes": app_bytes, "available_bytes": available, "total_bytes": total}


def _tight():
    info = snapshot()
    if not info:
        return False
    total = info.get("total_bytes") or 0
    app = info.get("app_bytes") or 0
    free = info.get("available_bytes")
    if total and app / total >= _RATIO:
        return True
    return free is not None and free < _FLOOR


def _proc_rss():
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _meminfo():
    total = free = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                if parts[0] == "MemTotal:":
                    total = int(parts[1]) * 1024
                elif parts[0] == "MemAvailable:":
                    free = int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None, None
    return total, free


def _cgroup_memory():
    """Bytes still inside the container limit, and that limit. None when the container is uncapped."""
    pairs = (
        ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
        ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for current_path, limit_path in pairs:
        try:
            with open(current_path, encoding="utf-8") as current_handle, open(limit_path, encoding="utf-8") as limit_handle:
                current = int(current_handle.read().strip())
                raw = limit_handle.read().strip()
        except (OSError, ValueError):
            continue
        if raw == "max":
            return None, None
        try:
            limit = int(raw)
        except ValueError:
            continue
        if limit <= 0 or limit >= 1 << 60:
            return None, None
        # File cache can be dropped by the kernel, so it does not count as memory the app is holding.
        used = current - _stat_bytes(os.path.join(os.path.dirname(current_path), "memory.stat"))
        return max(0, limit - max(0, used)), limit
    return None, None


def _stat_bytes(path):
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("inactive_file", "total_inactive_file"):
                    return int(parts[1])
    except (OSError, ValueError):
        return 0
    return 0
