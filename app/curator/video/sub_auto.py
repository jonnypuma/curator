"""Automatic subtitle sync with alass (https://github.com/kaegi/alass).

alass listens to the video's audio for speech, lines that up with when the subtitle has text, and
finds the shift for every stretch of the file, so it also copes with cut or re-joined releases.
It only needs timings, never the words, which is why picture subtitles (VobSub, PGS) work too:
a throwaway .srt is built from their timings and the text is never read.

The result is not written anywhere. It is turned into anchors for the sync window, so the user
sees the proposed fit, can check it against the video, and presses Save as for a manual sync:

* every line moved by about the same amount     -> one anchor (constant offset, "linear")
* the offset grows steadily (frame rate change) -> two anchors ("linear")
* different offsets for different stretches     -> one anchor per stretch ("steps")
"""
from __future__ import annotations

import logging
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time

from resonance.errors import AppError

logger = logging.getLogger(__name__)

_SAME_MS = 150            # offsets this close count as the same offset
FINE_LIMIT_MS = 5000      # "fine-tune" refuses a proposal that moves any line further than this
UNCHANGED_MS = 100        # a single offset this small means the subtitle was already in sync
MODES = ("fine", "shift", "cuts")
_TIMEOUT = 3 * 3600
_JOBS = {}
_LOCK = threading.Lock()


def binary():
    for name in ("alass", "alass-cli"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def available():
    return bool(binary()) and bool(shutil.which("ffmpeg"))


# ======================================================================================
# turning alass's answer into anchors
# ======================================================================================

def derive(starts, news):
    """`starts[i]` is the cue's start before, `news[i]` after alass (None when alass dropped it).
    Returns {mode, anchors: [{index, sub_ms, video_ms}], segments, matched}. Cue indexes are 1-based."""
    rows = [(i + 1, int(s), int(n)) for i, (s, n) in enumerate(zip(starts, news)) if n is not None]
    if not rows:
        raise AppError("alass did not return any lines", 502)
    deltas = [n - s for _i, s, n in rows]
    median = statistics.median(deltas)
    first = rows[0]
    if max(abs(d - median) for d in deltas) <= _SAME_MS:
        return {"mode": "linear", "segments": 1, "matched": len(rows),
                "anchors": [{"index": first[0], "sub_ms": first[1], "video_ms": first[1] + int(round(median))}]}
    # A steady drift (different frame rate): a straight line through every cue.
    xs = [float(s) for _i, s, _n in rows]
    ys = [float(n) for _i, _s, n in rows]
    count = len(rows)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = count * sxx - sx * sx
    if count >= 3 and denom:
        a = (count * sxy - sx * sy) / denom
        b = (sy - a * sx) / count
        if max(abs(a * x + b - y) for x, y in zip(xs, ys)) <= _SAME_MS:
            last = rows[-1]
            return {"mode": "linear", "segments": 1, "matched": count,
                    "anchors": [{"index": first[0], "sub_ms": first[1], "video_ms": int(round(a * first[1] + b))},
                                {"index": last[0], "sub_ms": last[1], "video_ms": int(round(a * last[1] + b))}]}
    # Different offsets in different stretches.
    groups = [[(rows[0], deltas[0])]]
    for row, delta in zip(rows[1:], deltas[1:]):
        if abs(delta - groups[-1][0][1]) <= _SAME_MS:
            groups[-1].append((row, delta))
        else:
            groups.append([(row, delta)])
    anchors = []
    for group in groups:
        offset = int(round(statistics.median(d for _r, d in group)))
        if anchors and abs(offset - (anchors[-1]["video_ms"] - anchors[-1]["sub_ms"])) <= _SAME_MS:
            continue
        (index, start, _new), _d = group[0]
        anchors.append({"index": index, "sub_ms": start, "video_ms": start + offset})
    if len(anchors) == 1:
        return {"mode": "linear", "segments": 1, "matched": count, "anchors": anchors}
    return {"mode": "steps", "segments": len(anchors), "matched": count, "anchors": anchors}


def judge(result, mode):
    """Add max_shift_ms and, where it applies, `rejected` (fine-tune and the proposal is large) or
    `unchanged` (the subtitle was already in sync). A subtitle that is already right should come
    back almost untouched, so a large proposal for it is far more likely alass being fooled (music,
    little speech, a different cut) than a real error."""
    shifts = [abs(a["video_ms"] - a["sub_ms"]) for a in result["anchors"]]
    result["max_shift_ms"] = max(shifts)
    result["rejected"] = mode == "fine" and max(shifts) > FINE_LIMIT_MS
    result["unchanged"] = (not result["rejected"] and result["mode"] == "linear"
                           and len(result["anchors"]) == 1 and shifts[0] < UNCHANGED_MS)
    return result


# ======================================================================================
# running alass
# ======================================================================================

def _timings(sub):
    """[(start_ms, end_ms)] per cue, in the order the sync window numbers them."""
    from curator.video import sub_ocr, sub_sync

    if sub_sync.is_image(sub):
        items = sub_ocr._items(sub_ocr._source(sub))["items"]
        return [(int(it["start_ms"]), int(it["end_ms"])) for it in items]
    return [(int(c["start_ms"]), int(c["end_ms"])) for c in sub_sync.read(sub)["cues"]]


def _write_srt(path, timings):
    from curator.video import sub_sync

    with open(path, "w", encoding="utf-8") as handle:
        for i, (start, end) in enumerate(timings, 1):
            handle.write(f"{i}\n{sub_sync._ms_to_srt(start)} --> {sub_sync._ms_to_srt(max(end, start + 1))}\n{i}\n\n")


def _read_result(path):
    from curator.video import sub_sync

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        cues = sub_sync._parse_srt(handle.read().lstrip("﻿"))
    found = {}
    for cue in cues:
        try:
            found[int(str(cue.get("text") or "").strip())] = int(cue["start_ms"])
        except ValueError:
            continue
    return found


def _command(video, source, out, split, penalty):
    cmd = [binary(), "--allow-negative-timestamps"]
    if not split:
        cmd.append("--no-split")
    else:
        cmd += ["--split-penalty", str(penalty)]
    return cmd + [video, source, out]


def run(video, sub, mode="fine", penalty=7, on_process=None):
    """Blocking. Returns derive()'s result for one subtitle against one video."""
    if not available():
        raise AppError("alass is not installed in this container", 500)
    mode = mode if mode in MODES else "fine"
    split = mode == "cuts"
    timings = _timings(sub)
    if len(timings) < 3:
        raise AppError("That subtitle has too few lines to sync automatically", 400)
    work = tempfile.mkdtemp(prefix="curator-alass-")
    try:
        source, out, log = (os.path.join(work, n) for n in ("in.srt", "out.srt", "alass.log"))
        _write_srt(source, timings)
        with open(log, "w", encoding="utf-8") as sink:
            proc = subprocess.Popen(_command(video, source, out, split, penalty), stdout=sink, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL)
            if on_process:
                on_process(proc)
            try:
                code = proc.wait(timeout=_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise AppError("alass took too long and was stopped", 504)
        if code != 0 or not os.path.isfile(out):
            with open(log, "r", encoding="utf-8", errors="replace") as handle:
                tail = handle.read().strip().splitlines()[-3:]
            raise AppError("alass could not sync this: " + (" ".join(tail)[:300] or f"exit code {code}"), 502)
        found = _read_result(out)
        news = [found.get(i) for i in range(1, len(timings) + 1)]
        if sum(1 for n in news if n is not None) < len(timings) * 0.8:
            raise AppError("alass returned too few of the subtitle lines", 502)
        return judge(derive([s for s, _e in timings], news), mode)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ======================================================================================
# background job
# ======================================================================================

def _key(sub):
    return os.path.realpath(sub)


def status(sub):
    job = _JOBS.get(_key(sub))
    if not job:
        return {"state": "idle", "available": available()}
    out = {"state": job["state"], "error": job["error"], "available": available(), "mode": job["mode"]}
    if job["state"] == "done":
        out["result"] = job["result"]
    return out


def start(sub, video, mode="fine", penalty=7):
    if not available():
        raise AppError("alass is not installed in this container", 500)
    key = _key(sub)
    with _LOCK:
        if any(j["state"] == "running" for j in _JOBS.values()):
            if _JOBS.get(key, {}).get("state") == "running":
                return status(sub)
            raise AppError("Another automatic sync is running. Try again when it has finished.", 409)
        job = {"state": "running", "error": "", "result": None, "proc": None, "cancel": False, "mode": mode,
               "started": time.time()}
        _JOBS[key] = job
    threading.Thread(target=_worker, args=(sub, video, mode, penalty, job), daemon=True, name="sub-auto").start()
    return status(sub)


def cancel(sub):
    job = _JOBS.get(_key(sub))
    if job and job["state"] == "running":
        job["cancel"] = True
        proc = job.get("proc")
        if proc and proc.poll() is None:
            proc.kill()
    return status(sub)


def _worker(sub, video, mode, penalty, job):
    from curator.video import work_track

    name = os.path.basename(sub)
    track = work_track.Tracked("sub-auto", f"Automatic sync of {name}", 0)
    try:
        job["result"] = run(video, sub, mode, penalty, on_process=lambda p: job.__setitem__("proc", p))
        if job["cancel"]:
            raise AppError("Cancelled", 499)
        job["state"] = "done"
        res = job["result"]
        outcome = ("proposal refused (too large)" if res["rejected"] else "already in sync" if res["unchanged"]
                   else f"found {res['segments']} stretch{'es' if res['segments'] != 1 else ''}")
        track.finish("completed", f"Automatic sync of {name}: {outcome}")
    except Exception as exc:
        if job["cancel"]:
            job["state"] = "cancelled"
            job["error"] = ""
            track.finish("cancelled", f"Automatic sync of {name} cancelled")
        else:
            logger.warning("automatic sync failed for %s: %s", sub, exc)
            job["state"] = "error"
            job["error"] = str(getattr(exc, "message", None) or exc) or exc.__class__.__name__
            track.finish("failed", f"Automatic sync of {name} failed: {job['error'][:120]}")
