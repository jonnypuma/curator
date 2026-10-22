"""Browser-playable preview copies of videos for the sync window.

Browsers cannot decode XviD/AVI, MPEG-2, AC-3/DTS audio, 10-bit or HEVC video, and many other
things a library holds. The sync window only needs to *watch* the video to find the moment a
line is spoken, so a small H.264 + AAC copy is enough. This module:

* probes the file and says whether a browser can play it as it is ("direct"), and
* if not, builds a 360p MP4 once with ffmpeg in the background, caches it under the config
  directory and serves that instead ("proxy"). The original file is never touched.

Timing is identical to the original (no trimming, no frame-rate change), so an anchor marked in
the preview is the right time in the real file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading

from resonance.errors import AppError
from curator.video import cache_store, work_track
from resonance.paths import cache_dir


logger = logging.getLogger(__name__)

_VIDEO_OK = {"h264", "vp8", "vp9", "av1"}
_AUDIO_OK = {"aac", "mp3", "opus", "vorbis", "flac"}
_PIX_OK = {"yuv420p", "yuvj420p"}
_CONTAINER_OK = ("mp4", "mov", "matroska", "webm")
_HEIGHT = 360

_PROBES = {}
_JOBS = {}
_LOCK = threading.Lock()


def _identity(path):
    st = os.stat(path)
    return f"{os.path.realpath(path)}|{st.st_size}|{st.st_mtime_ns}"


def proxy_file(path):
    folder = os.path.join(cache_dir(), "video", "preview")
    return os.path.join(folder, hashlib.sha1(_identity(path).encode("utf-8", "replace")).hexdigest() + ".mp4")


def probe(path):
    """{direct: bool, reason: str, duration: float}. Memoised per file version."""
    key = _identity(path)
    hit = _PROBES.get(key)
    if hit:
        return hit
    if not shutil.which("ffprobe"):
        result = {"direct": True, "reason": "ffprobe is not available", "duration": 0.0}
        return result
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                               "format=format_name,duration:stream=codec_type,codec_name,pix_fmt",
                               "-of", "json", "--", path], capture_output=True, text=True, timeout=60)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        data = {}
    streams = data.get("streams") or []
    fmt = str((data.get("format") or {}).get("format_name") or "")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    reason = ""
    if not any(token in fmt for token in _CONTAINER_OK):
        reason = f"the {fmt.split(',')[0] or 'file'} container"
    elif not video or video.get("codec_name") not in _VIDEO_OK:
        reason = f"{(video or {}).get('codec_name') or 'this'} video"
    elif video.get("codec_name") == "h264" and video.get("pix_fmt") not in _PIX_OK:
        reason = f"{video.get('pix_fmt')} video"
    elif audio and audio.get("codec_name") not in _AUDIO_OK:
        reason = f"{audio.get('codec_name')} audio"
    result = {"direct": not reason, "reason": reason, "duration": duration}
    if len(_PROBES) > 50:
        _PROBES.pop(next(iter(_PROBES)))
    _PROBES[key] = result
    return result


def status(path):
    """{mode, state, percent, reason, error}: mode direct|proxy; state ready|building|error."""
    info = probe(path)
    if info["direct"]:
        return {"mode": "direct", "state": "ready", "percent": 100, "reason": "", "error": ""}
    out = proxy_file(path)
    job = _JOBS.get(out)
    if os.path.isfile(out) and not (job and job["state"] == "building"):
        cache_store.touch(out)
        return {"mode": "proxy", "state": "ready", "percent": 100, "reason": info["reason"], "error": ""}
    if job and job["state"] == "building":
        return {"mode": "proxy", "state": "building", "percent": job["percent"], "reason": info["reason"], "error": ""}
    if job and job["state"] == "error":
        return {"mode": "proxy", "state": "error", "percent": 0, "reason": info["reason"], "error": job["error"]}
    return {"mode": "proxy", "state": "needed", "percent": 0, "reason": info["reason"], "error": ""}


def discard(path):
    """Delete the cached preview copy of one video, if there is one. Returns the bytes freed.
    A copy that is still being built is left alone (it would be recreated half-written)."""
    out = proxy_file(path)
    job = _JOBS.get(out)
    if job and job["state"] == "building":
        raise AppError("The preview copy is still being prepared. Try again when it has finished.", 409)
    freed = 0
    try:
        freed = os.path.getsize(out)
        os.unlink(out)
    except OSError:
        pass
    _JOBS.pop(out, None)
    return freed


def start(path):
    """Start building the preview copy if it is needed and not already building."""
    current = status(path)
    if current["mode"] == "direct" or current["state"] in ("ready", "building"):
        return current
    if not shutil.which("ffmpeg"):
        raise AppError("ffmpeg is not installed in this container", 500)
    out = proxy_file(path)
    with _LOCK:
        if any(j["state"] == "building" for j in _JOBS.values()):
            raise AppError("Another video preview is being prepared. Try again when it has finished.", 409)
        job = {"state": "building", "percent": 0, "error": ""}
        _JOBS[out] = job
    threading.Thread(target=_build, args=(path, out, probe(path)["duration"], job), daemon=True,
                     name="preview-proxy").start()
    return status(path)


def _build(path, out, duration, job):
    tmp = out + ".part.mp4"
    name = os.path.basename(path)
    track = work_track.Tracked("sub-preview", f"Video preview for {name}", 100)
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", path,
               "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
               "-vf", f"scale=-2:{_HEIGHT}:flags=fast_bilinear", "-c:v", "libx264", "-preset", "ultrafast",
               "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
               "-movflags", "+faststart", "-progress", "pipe:1", tmp]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
            if m and duration:
                seconds = int(m.group(1)) / 1_000_000.0
                job["percent"] = max(job["percent"], min(99, int(seconds * 100 / duration)))
                track.update(job["percent"], f"Video preview for {name}")
        error = proc.stderr.read().strip()
        proc.wait()
        if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            raise RuntimeError(error[-300:] or "ffmpeg could not convert this video")
        os.replace(tmp, out)
        job["percent"] = 100
        job["state"] = "done"
        track.finish("completed", f"Video preview for {name} is ready", 100)
        _trim(out)
    except Exception as exc:
        logger.warning("video preview failed for %s: %s", path, exc)
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        track.finish("failed", f"Video preview for {name} failed: {job['error'][:120]}")
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _trim(keep):
    try:
        from curator.video import config

        cache_store.trim_all(config.current(), keep=keep)
    except Exception:
        logger.debug("cache trim skipped", exc_info=True)
