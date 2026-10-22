"""Keep yt-dlp current without rebuilding the image.

YouTube changes often and an old yt-dlp stops working. The image carries the yt-dlp it was built with. This module
can fetch the newest release into the cache folder (`<cache>/bin/yt-dlp`) when asked, and `binary()` then runs
whichever of the two is newer. Nothing here runs by itself: the only unprompted call is the version lookup that
opens the About window, which sends no data from this install.

An update is the release's own `yt-dlp` file. It is checked against the `SHA2-256SUMS` list published with that
release, started once to prove it runs, and only then put in place.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

import requests

from resonance import paths
from resonance.errors import AppError

RELEASE_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
ASSET_URL = "https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/{name}"
LOOKUP_TIMEOUT = 8
DOWNLOAD_TIMEOUT = (10, 60)
MAX_BYTES = 40 * 1024 * 1024
LOOKUP_KEEP = 6 * 3600
LOOKUP_RETRY = 600

_latest = {"at": 0.0, "tag": "", "error": ""}
_lookup_lock = threading.Lock()
_update_lock = threading.Lock()


def cached_path():
    return os.path.join(paths.cache_dir(), "bin", "yt-dlp")


def system_path():
    return shutil.which("yt-dlp")


def version_key(version):
    """Numbers in a yt-dlp version, so 2026.1.5 sorts after 2025.12.31 and a dated nightly after its release."""
    return tuple(int(part) for part in re.findall(r"\d+", str(version or "")))


def _version(path):
    from curator.video import trailers

    return trailers.ytdlp_version(path)


def binary():
    """The yt-dlp to run: the updated copy when it is newer than the one in the image, else the image's."""
    system = system_path()
    cached = cached_path()
    if not (os.path.isfile(cached) and os.access(cached, os.X_OK)):
        return system
    if not system:
        return cached
    return cached if version_key(_version(cached)) > version_key(_version(system)) else system


def status(check=False):
    """What is running, how old it is and, when asked, what GitHub lists as the newest release."""
    from curator.video import trailers

    path = binary()
    version = _version(path) if path else ""
    age = trailers.version_age_days(version)
    info = {
        "installed": bool(path),
        "version": version,
        "age_days": age,
        "stale": age is not None and age > trailers.STALE_AFTER_DAYS,
        "updated": bool(path) and os.path.normpath(path) == os.path.normpath(cached_path()),
        "latest": "",
        "update_available": False,
        "check_error": "",
    }
    if check:
        found = latest()
        info["latest"] = found["tag"]
        info["check_error"] = found["error"]
        info["update_available"] = bool(found["tag"]) and version_key(found["tag"]) > version_key(version)
    return info


def latest(force=False):
    """The newest release GitHub lists. Remembered for six hours; a failed lookup is not repeated for ten minutes."""
    with _lookup_lock:
        age = time.time() - _latest["at"]
        if not force and _latest["at"] and age < (LOOKUP_KEEP if _latest["tag"] else LOOKUP_RETRY):
            return dict(_latest)
        tag, error = "", ""
        try:
            response = requests.get(
                RELEASE_API,
                timeout=LOOKUP_TIMEOUT,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Curator"},
            )
            if response.status_code != 200:
                error = f"GitHub answered {response.status_code}"
            else:
                tag = str((response.json() or {}).get("tag_name") or "").strip()
                if not re.match(r"^\d{4}\.\d{2}\.\d{2}", tag):
                    tag, error = "", "GitHub did not name a release"
        except (requests.RequestException, ValueError) as exc:
            error = f"could not reach GitHub ({exc.__class__.__name__})"
        _latest.update(at=time.time(), tag=tag, error=error)
        return dict(_latest)


def _download(url):
    try:
        with requests.get(url, timeout=DOWNLOAD_TIMEOUT, stream=True) as response:
            if response.status_code != 200:
                raise AppError(f"GitHub answered {response.status_code} for {url.rsplit('/', 1)[-1]}", 502)
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise AppError("The yt-dlp download was far larger than expected; nothing was installed", 502)
            return bytes(data)
    except requests.RequestException as exc:
        raise AppError(f"Could not download yt-dlp ({exc.__class__.__name__})", 502) from None


def expected_hash(listing, name):
    """The SHA-256 a `SHA2-256SUMS` listing gives for one file, or "" when it is not listed."""
    for line in str(listing or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].lstrip("*").strip() == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


def update():
    """Fetch the newest release into the cache folder. Returns the new status."""
    if not _update_lock.acquire(blocking=False):
        raise AppError("An update is already running", 409)
    try:
        found = latest(force=True)
        if not found["tag"]:
            raise AppError(f"Could not find the latest yt-dlp: {found['error'] or 'no answer'}", 502)
        tag = found["tag"]
        current = status()
        if current["installed"] and current["version"] and version_key(current["version"]) >= version_key(tag):
            return {**current, "changed": False, "message": f"yt-dlp {current['version']} is already the newest release"}
        data = _download(ASSET_URL.format(tag=tag, name="yt-dlp"))
        listing = _download(ASSET_URL.format(tag=tag, name="SHA2-256SUMS")).decode("utf-8", "replace")
        wanted = expected_hash(listing, "yt-dlp")
        if not wanted:
            raise AppError("GitHub's checksum list has no entry for yt-dlp; nothing was installed", 502)
        if hashlib.sha256(data).hexdigest() != wanted:
            raise AppError("The download did not match its published checksum; nothing was installed", 502)
        _install(data)
        result = status()
        return {**result, "changed": True, "message": f"Updated yt-dlp to {result['version'] or tag}"}
    finally:
        _update_lock.release()


def _install(data):
    from curator.video import trailers

    target = cached_path()
    folder = os.path.dirname(target)
    try:
        os.makedirs(folder, exist_ok=True)
        handle, temp = tempfile.mkstemp(prefix=".yt-dlp-", dir=folder)
    except OSError as exc:
        raise AppError(f"Cannot write to the cache folder ({exc.strerror or exc.__class__.__name__}); nothing was installed", 500) from None
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temp, 0o755)
        try:
            run = subprocess.run([temp, "--version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError(
                f"The new yt-dlp would not start ({exc.__class__.__name__}). Is the cache folder mounted noexec? Nothing was installed",
                500,
            ) from None
        if run.returncode != 0 or not (run.stdout or "").strip():
            raise AppError("The new yt-dlp would not start; nothing was installed", 500)
        os.replace(temp, target)
        temp = None
        trailers._versions.pop(target, None)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
