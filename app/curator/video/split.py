"""Lossless split of a multi-episode Matroska file.

Chapters are the cut points when one starts near the expected join. Otherwise a short window
of black and silence is. The user can edit every time. mkvmerge remuxes the parts, and the
source stays in the folder under a name the library does not scan.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime

from psycopg.types.json import Jsonb

from curator.video import naming, renamer
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

_REPEAT = re.compile(r"([._ -])\1+")
_BLACK = re.compile(r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)")
_SILENCE_START = re.compile(r"silence_start:\s*(\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(\d+(?:\.\d+)?)")

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "error": "", "episode_id": None, "parked": "", "original": ""}


def status():
    with _lock:
        snapshot = dict(_state)
        snapshot["results"] = [dict(item) for item in _state.get("results") or []]
    return snapshot


def running():
    with _lock:
        return _state["status"] == "running"


def episode_marker(pairs):
    """How the parked file lists its episodes: 1-3, 1-2-5, or s1e5-s2e1."""
    pairs = [(int(season), int(episode)) for season, episode in pairs]
    seasons = {season for season, _episode in pairs}
    if len(seasons) <= 1:
        numbers = [episode for _season, episode in pairs]
        if len(numbers) > 1 and numbers == list(range(numbers[0], numbers[-1] + 1)):
            return f"{numbers[0]}-{numbers[-1]}"
        return "-".join(str(number) for number in numbers)
    return "-".join(f"s{season}e{episode}" for season, episode in pairs)


def span_token(pairs):
    """The S01E01-E04 text the renamer writes into a multi-episode file name."""
    groups = []
    for season, episode in pairs:
        season, episode = int(season), int(episode)
        if not groups or groups[-1][0] != season:
            groups.append((season, []))
        groups[-1][1].append(episode)
    if not groups:
        return ""
    token = f"S{groups[0][0]:02d}E{renamer._episode_span(groups[0][1])}"
    for season, numbers in groups[1:]:
        token += f"S{season:02d}E{renamer._episode_span(numbers)}"
    return token


def _clean_stem(text):
    return _REPEAT.sub(r"\1", text).strip("._ -")


def parked_name(filename, pairs):
    """Original name, episode span removed, then .split-source-eps-1-3.mkv."""
    stem, ext = os.path.splitext(os.path.basename(filename))
    token = _span_in(filename, pairs)
    if not token:
        return None
    bare = _clean_stem(stem.replace(token, "", 1))
    if not bare:
        return None
    return f"{bare}{ext}.split-source-eps-{episode_marker(pairs)}.mkv"


def _span_in(filename, pairs):
    """The span written in this file name. S01E81-82 and S01E01-E04 are both accepted."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    written = naming.span_text(filename)
    if written and written in stem:
        return written
    token = span_token(pairs)
    return token if token and token in stem else None


def part_names(filename, pairs):
    """One file name per episode, with the span token replaced by SxxEyy."""
    stem, ext = os.path.splitext(os.path.basename(filename))
    token = _span_in(filename, pairs)
    if not token:
        return None
    names = []
    for season, episode in pairs:
        mark = naming.episode_mark(season, episode)
        names.append(f"{stem.replace(token, mark, 1)}{ext}")
    return names


def anchors(duration, runtimes):
    """Join times from the file duration, weighted by each episode's runtime."""
    weights = []
    for runtime in runtimes:
        try:
            number = float(runtime)
        except (TypeError, ValueError):
            number = 0
        weights.append(number if number > 0 else None)
    if not weights or any(item is None for item in weights):
        weights = [1.0] * len(runtimes)
    total = sum(weights) or 1
    cuts, acc = [], 0.0
    for weight in weights[:-1]:
        acc += weight
        cuts.append(float(duration) * acc / total)
    return cuts


def chapter_cut(chapters, anchor, window, duration):
    """Closest chapter start inside the window, ignoring the head and tail of the file."""
    best = None
    limit = max(0.0, float(duration) - 2)
    for start in chapters or []:
        try:
            start = float(start)
        except (TypeError, ValueError):
            continue
        if start <= 2 or start >= limit:
            continue
        if abs(start - anchor) > window:
            continue
        if best is None or abs(start - anchor) < abs(best - anchor):
            best = start
    return best


def parse_black(text, offset=0.0):
    return [(float(match.group(1)) + offset, float(match.group(2)) + offset) for match in _BLACK.finditer(text or "")]


def parse_silence(text, offset=0.0):
    starts = [float(match.group(1)) + offset for match in _SILENCE_START.finditer(text or "")]
    ends = [float(match.group(1)) + offset for match in _SILENCE_END.finditer(text or "")]
    return [(start, end) for start, end in zip(starts, ends) if end > start]


def overlaps(blacks, silences, minimum):
    found = []
    for black_start, black_end in blacks:
        for silence_start, silence_end in silences:
            start, end = max(black_start, silence_start), min(black_end, silence_end)
            if end - start >= minimum and (black_start, black_end) not in found:
                found.append((black_start, black_end))  # the black picture; the cut is placed on it
    return found


def cut_point(start, end, at):
    """Where on a black picture the cut goes: its first frame, its middle or its last frame."""
    if at == "start":
        return start
    if at == "end":
        return end
    return (start + end) / 2


def pick_overlap(spans, anchor, near, apart, at="middle"):
    """Cut point of the black picture closest to the anchor. 'ambiguous' when two are too close."""
    ranked = []
    for start, end in spans:
        ranked.append((abs((start + end) / 2 - anchor), cut_point(start, end, at)))
    ranked.sort()
    if not ranked:
        return None
    _distance, middle = ranked[0]
    for distance, other in ranked[1:]:
        if distance <= near and abs(other - middle) <= apart:
            return "ambiguous"
    return middle


def resolve_join(anchor, duration, chapters, tight, wide, cfg):
    """One join: a chapter, a black-and-silence overlap, or the anchor marked manual."""
    found = chapter_cut(chapters, anchor, cfg["split_chapter_window"], duration)
    if found is not None:
        return {"time": found, "source": "chapter"}
    choice = pick_overlap(tight, anchor, cfg["split_ambiguous_anchor"], cfg["split_ambiguous_apart"], cfg.get("split_cut_at", "middle"))
    if choice == "ambiguous":
        return {"time": anchor, "source": "manual"}
    if choice is not None:
        return {"time": choice, "source": "black-silence"}
    choice = pick_overlap(wide, anchor, cfg["split_ambiguous_anchor"], cfg["split_ambiguous_apart"], cfg.get("split_cut_at", "middle"))
    if choice == "ambiguous":
        return {"time": anchor, "source": "manual"}
    if choice is not None:
        return {"time": choice, "source": "black-silence-wide"}
    return {"time": anchor, "source": "manual"}


def format_time(seconds):
    whole = max(0, int(round(float(seconds))))
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_mkv(seconds):
    millis = max(0, int(round(float(seconds) * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def parse_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except (TypeError, ValueError):
        raise AppError("Enter each cut as HH:MM:SS", 400)


def validate_times(cuts, duration, min_part, count):
    """Posted cuts have to move forward and leave every part at least the minimum length."""
    if len(cuts) != count:
        raise AppError("Each join needs a time", 400)
    duration = float(duration or 0)
    if duration <= 0:
        raise AppError("The file duration is unknown", 400)
    floor = max(1.0, float(min_part if min_part is not None else 1.0))
    previous = 0.0
    points = []
    for index, cut in enumerate(cuts, 1):
        seconds = parse_time(cut)
        if seconds <= previous:
            raise AppError("Cut times have to move forward", 400)
        if seconds < 1 or seconds > duration - 1:
            raise AppError("Each cut has to sit inside the file", 400)
        part_len = seconds - previous
        if part_len < floor:
            raise AppError(f"Part {index} would be {round(part_len, 1)}s, shorter than the minimum {round(floor, 1)}s", 400)
        points.append(seconds)
        previous = seconds
    last_len = duration - previous
    if last_len < floor:
        raise AppError(f"Part {len(cuts) + 1} would be {round(last_len, 1)}s, shorter than the minimum {round(floor, 1)}s", 400)
    return points


def _pairs(rows):
    return [(int(row["season_number"]), int(row["episode_number"])) for row in rows]


def can_split(path):
    """A library Matroska file. Parked sources and other containers are refused."""
    base = os.path.basename(path or "")
    lowered = base.lower()
    return lowered.endswith(".mkv") and ".split-source-eps-" not in lowered


def _group(episode_id):
    row = db.fetchone(
        """
        SELECT e.id, e.show_id, e.season_number, e.episode_number, e.path, e.file_id, e.file_span,
               e.nfo_path, e.artwork, e.split_source, e.split_original, e.runtime_minutes,
               f.duration_seconds, f.audio_tracks
        FROM tv_episodes e
        LEFT JOIN video_files f ON f.id = e.file_id
        WHERE e.id = %s
        """,
        (episode_id,),
    )
    if not row:
        raise AppError("That episode is not in the library any more", 404)
    episode = db.clean(dict(row))
    path = episode.get("path") or ""
    if not can_split(path):
        raise AppError("Only a Matroska file can be split", 400)
    if not os.path.isfile(path):
        raise AppError("That episode has no video file", 400)
    rows = db.fetchall(
        """
        SELECT id, season_number, episode_number, title, runtime_minutes, path, nfo_path, artwork
        FROM tv_episodes
        WHERE show_id = %s AND path = %s
        ORDER BY season_number, episode_number
        """,
        (episode["show_id"], path),
    )
    group = [db.clean(dict(item)) for item in rows]
    span = episode.get("file_span") or []
    if len(span) < 2 or len(group) < 2:
        raise AppError("This file holds one episode", 400)
    if len(group) != len(span):
        raise AppError("The episodes in this file are not all on one path", 400)
    return episode, group


def _duration(path, stored):
    try:
        duration = float(stored or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        return duration
    return _probe_duration(path)


def _probe_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=120, check=False,
        )
        payload = json.loads(result.stdout or "{}")
        return float((payload.get("format") or {}).get("duration") or 0)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("duration probe failed for %s: %s", path, exc)
        return 0


def _chapters(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", path],
            capture_output=True, text=True, timeout=120, check=False,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.warning("chapter probe failed for %s: %s", path, exc)
        return []
    found = []
    for chapter in payload.get("chapters") or []:
        try:
            found.append(float(chapter.get("start_time")))
        except (TypeError, ValueError):
            continue
    return found


def _audio_index(tracks):
    if not isinstance(tracks, list):
        return 0
    for index, track in enumerate(tracks):
        if isinstance(track, dict) and track.get("default"):
            return index
    return 0


def _signals(path, anchor, window, duration, cfg, audio_index):
    """Black-picture spans and silent spans inside the window around the anchor."""
    start = max(0.0, anchor - window)
    length = min(window * 2, max(0.0, duration - start))
    if length <= 0:
        return [], []
    black = _ffmpeg(path, start, length, cfg, audio_index, video=True)
    silence = _ffmpeg(path, start, length, cfg, audio_index, video=False)
    return parse_black(black, start), parse_silence(silence, start)


def _detect(path, anchor, window, duration, cfg, audio_index):
    blacks, silences = _signals(path, anchor, window, duration, cfg, audio_index)
    return overlaps(blacks, silences, cfg["split_overlap_seconds"])


def near_black(blacks, silences, gap, at="middle"):
    """Black spans with a silent span touching them or within `gap` seconds; returns each one's cut point."""
    found = []
    for black_start, black_end in blacks:
        for silence_start, silence_end in silences:
            if silence_start <= black_end + gap and silence_end >= black_start - gap:
                found.append(cut_point(black_start, black_end, at))
                break
    return found


def _loose_silence(path, blacks, cfg, audio_index):
    """A second, more sensitive silence pass (quieter-than -35 dB for 0.1 s) around each black picture."""
    spans = []
    for black_start, black_end in blacks:
        start = max(0.0, black_start - 3)
        text = _ffmpeg(path, start, (black_end - black_start) + 6, cfg, audio_index, video=False, level=-35, seconds=0.1)
        spans.extend(parse_silence(text, start))
    return spans


def single_signal(blacks, silences, anchor, at="middle"):
    """When no black picture lines up with silence, the black or silent span closest to the anchor.

    Only a suggestion: the join stays unconfirmed so the user checks it before splitting."""
    spans = [("black-only", start, end) for start, end in blacks] + [("silence-only", start, end) for start, end in silences]
    if not spans:
        return None
    label, start, end = min(spans, key=lambda item: abs((item[1] + item[2]) / 2 - anchor))
    return cut_point(start, end, at if label == "black-only" else "middle"), label


def _ffmpeg(path, start, length, cfg, audio_index, video, level=None, seconds=None):
    if video:
        filters = (
            f"blackdetect=d={cfg['split_black_seconds']}:pic_th={cfg['split_black_pic']}:"
            f"pix_th={cfg['split_black_pix']}"
        )
        command = ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", path,
                   "-map", "0:v:0", "-vf", filters, "-an", "-f", "null", "-"]
    else:
        level = cfg["split_silence_db"] if level is None else level
        seconds = cfg["split_silence_seconds"] if seconds is None else seconds
        command = ["ffmpeg", "-hide_banner", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", path,
                   "-map", f"0:a:{audio_index}", "-af", f"silencedetect=n={level}dB:d={seconds}",
                   "-vn", "-f", "null", "-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("split detect failed for %s: %s", path, exc)
        return ""
    return (result.stderr or "") + (result.stdout or "")


def _part_payload(row):
    return {
        "season": int(row["season_number"]),
        "episode": int(row["episode_number"]),
        "title": (row.get("title") or "").strip(),
    }


def _join_payload(left, right, resolved):
    return {
        "after": {"season": left[0], "episode": left[1]},
        "before": {"season": right[0], "episode": right[1]},
        "time": round(resolved["time"], 3),
        "time_text": format_time(resolved["time"]),
        "anchor": round(resolved.get("anchor", resolved["time"]), 3),
        "source": resolved["source"],
    }


def plan(episode_id):
    """Propose a cut for every join. Nothing is written."""
    _ensure_not_splitting()
    episode, group = _group(episode_id)
    path = episode["path"]
    pairs = _pairs(group)
    names = part_names(path, pairs)
    parked = parked_name(path, pairs)
    if not names or not parked:
        raise AppError("The file name has no episode span to replace", 400)
    folder = os.path.dirname(path)
    outputs = [os.path.join(folder, name) for name in names]
    parked_path = os.path.join(folder, parked)
    for dest in outputs:
        if os.path.exists(dest):
            raise AppError(f"{os.path.basename(dest)} already exists", 400)
    if os.path.exists(parked_path):
        raise AppError(f"{parked} already exists", 400)
    from curator.video import config

    cfg = config.current()
    duration = _duration(path, episode.get("duration_seconds"))
    if duration <= 0:
        raise AppError("The file duration is unknown", 400)
    points = anchors(duration, [item.get("runtime_minutes") for item in group])
    chapters = _chapters(path)
    audio = _audio_index(episode.get("audio_tracks"))
    wide = max(cfg["split_wide_window"], cfg["split_detect_window"])
    joins = []
    for index, anchor in enumerate(points):
        found = chapter_cut(chapters, anchor, cfg["split_chapter_window"], duration)
        if found is not None:
            resolved = {"time": found, "source": "chapter", "anchor": anchor}
        else:
            blacks, silences = _signals(path, anchor, cfg["split_detect_window"], duration, cfg, audio)
            tight = overlaps(blacks, silences, cfg["split_overlap_seconds"])
            choice = pick_overlap(tight, anchor, cfg["split_ambiguous_anchor"], cfg["split_ambiguous_apart"], cfg.get("split_cut_at", "middle"))
            if isinstance(choice, float):
                resolved = {"time": choice, "source": "black-silence", "anchor": anchor}
            elif choice == "ambiguous":
                resolved = {"time": anchor, "source": "manual", "anchor": anchor}
            else:
                wider = _detect(path, anchor, wide, duration, cfg, audio)
                choice = pick_overlap(wider, anchor, cfg["split_ambiguous_anchor"], cfg["split_ambiguous_apart"], cfg.get("split_cut_at", "middle"))
                if isinstance(choice, float):
                    resolved = {"time": choice, "source": "black-silence-wide", "anchor": anchor}
                else:
                    loose = near_black(blacks, _loose_silence(path, blacks, cfg, audio), 1.0, cfg.get("split_cut_at", "middle")) if blacks else []
                    single = single_signal(blacks, silences, anchor, cfg.get("split_cut_at", "middle"))
                    if loose:
                        resolved = {"time": min(loose, key=lambda value: abs(value - anchor)), "source": "black-short-silence", "anchor": anchor}
                    elif single:
                        resolved = {"time": single[0], "source": single[1], "anchor": anchor}
                    else:
                        resolved = {"time": anchor, "source": "manual", "anchor": anchor}
        joins.append(_join_payload(pairs[index], pairs[index + 1], resolved))
    ready = all(item["source"] in {"chapter", "black-silence"} for item in joins)
    min_part = float(cfg.get("split_min_part") or 30.0)
    bounds = [0.0, *[j["time"] for j in joins], duration]
    if any((end - start) < min_part for start, end in zip(bounds, bounds[1:])):
        ready = False
    return {
        "episode_id": str(episode["id"]),
        "source": path,
        "duration": duration,
        "parts": [_part_payload(item) for item in group],
        "joins": joins,
        "outputs": outputs,
        "parked": parked_path,
        "ready": ready,
        "min_part": cfg["split_min_part"],
    }


# Pending split jobs, protected by _lock, drained by _watch_pending when the scanner,
# scrape, file job and database restore are all idle. A split asked for while any of those
# are running goes here instead of being refused, so the UI can tell the user "Split queued
# for after the current scan" rather than "Wait for the running scan or file job to finish".
_pending: list = []
_watcher_running = False


def _ensure_not_splitting():
    """Planning only reads the file, so a running scan or scrape does not matter. Another split does."""
    with _lock:
        if _state.get("status") == "running":
            raise AppError("A split is already running. Wait for it to finish.", 409)


def _ensure_idle():
    """Restore and delete move files, so they wait for every other job to finish."""
    _ensure_not_splitting()
    if not _idle_now():
        raise AppError("Wait for the running scan, scrape or file job to finish", 409)


def _idle_now():
    from curator.video import files, scanner, scrape
    from resonance import backup

    return not (scanner.running() or scrape.running() or files.running() or backup.restoring())


def _start_watcher():
    """Start the drainer thread, if one is not already running."""
    global _watcher_running
    with _lock:
        if _watcher_running:
            return
        _watcher_running = True
    threading.Thread(target=_watch_pending, name="episode-split-queue", daemon=True).start()


def _watch_pending():
    """Drain the pending queue once the system is idle. One pass per idle state."""
    global _watcher_running
    import time

    try:
        while True:
            jobs = None
            with _lock:
                if not _pending:
                    return
                if _state.get("status") != "running" and _idle_now():
                    jobs = _pending.copy()
                    _pending.clear()
            if jobs:
                _begin_run(jobs)  # takes _lock itself, so it must run after the lock is released
                return
            time.sleep(5)
    finally:
        with _lock:
            _watcher_running = False


def _begin_run(queued):
    """Mark state as running and spawn the worker. Caller holds no lock we need."""
    with _lock:
        _state.update({
            "status": "running", "message": "Splitting", "error": "",
            "episode_id": queued[0][0], "parked": "", "original": "",
            "index": 1, "total": len(queued), "results": [],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })
    threading.Thread(target=_apply_many, args=(queued,), name="episode-split", daemon=True).start()


def start(episode_id, times):
    """Returns {"started": bool, "queued": bool, "message": str}."""
    return start_many([(episode_id, times)])


def start_many(jobs):
    """Split each file in order, or queue them to run once the system is idle.

    Returns a dict carrying `started` (worker now running) or `queued` (added to _pending),
    with a human message in `message`. Only an empty jobs list is rejected.
    """
    queued = [(str(episode_id), list(times or [])) for episode_id, times in jobs if episode_id]
    if not queued:
        raise AppError("Choose a file to split", 400)
    with _lock:
        split_running = _state.get("status") == "running"
    if split_running or not _idle_now():
        with _lock:
            _pending.extend(queued)
        _start_watcher()
        from curator.video import files, scanner, scrape
        from resonance import backup

        busy = [name for name, active in (("a split", split_running), ("a scan", scanner.running()), ("a scrape", scrape.running()),
                                          ("a file job", files.running()), ("a database restore", backup.restoring())) if active]
        what = "the split episodes are" if len(queued) > 1 else "the split is"
        label = f"Waiting for {' and '.join(busy) or 'running jobs'} to finish; {what} queued"
        return {"started": False, "queued": True, "message": label}
    _begin_run(queued)
    return {"started": True, "queued": False, "message": f"Splitting {len(queued)} file(s)"}
    with _lock:
        if _state["status"] == "running":
            return False
        _state.update({
            "status": "running", "message": "Splitting", "error": "", "episode_id": queued[0][0],
            "parked": "", "original": "", "index": 1, "total": len(queued), "results": [],
            "started_at": datetime.now().isoformat(timespec="seconds"),
        })
    threading.Thread(target=_apply_many, args=(queued,), name="episode-split", daemon=True).start()
    return True


def _set(**values):
    with _lock:
        _state.update(values)


def _apply_many(jobs):
    from curator.video import work_track

    results = []
    total = len(jobs)
    track = work_track.Tracked("episode-split", f"Splitting {total} file{'s' if total != 1 else ''}", total)
    for index, (episode_id, times) in enumerate(jobs, 1):
        _set(message=f"Splitting {index} of {total}", episode_id=episode_id, index=index, total=total, error="")
        track.update(index - 1, f"Splitting {index} of {total}", force=True)
        try:
            results.append(_run_split(episode_id, times))
        except AppError as exc:
            results.append({"episode_id": episode_id, "status": "error", "message": str(exc), "error": str(exc)})
        except Exception:
            logger.exception("episode split failed")
            results.append({"episode_id": episode_id, "status": "error", "message": "The split failed", "error": "The split failed"})
        _set(results=list(results))
    _after_split_notify(results)
    _start_watcher()  # any further splits queued meanwhile start as soon as this one ends
    failed = [item for item in results if item.get("status") == "error"]
    if not failed:
        message = f"Split {total} file" if total == 1 else f"Split {total} files"
        if total == 1:
            message = results[0].get("message") or message
        _set(status="done", message=message, error="", parked=results[-1].get("parked") or "", original=results[-1].get("original") or "")
        track.finish("completed", message, total)
    elif len(failed) == total:
        _set(status="error", message=failed[-1]["message"], error=failed[-1]["message"])
        track.finish("failed", failed[-1]["message"], 0)
    else:
        message = f"Split {total - len(failed)} of {total} files"
        _set(status="done", message=message, error="")
        track.finish("completed", message, total - len(failed))



def _after_split_notify(results):
    """Trigger a library update for the folders the split just produced, when enabled.

    Opt-in by the `scan_split_notify` setting (TV shows tab). The library notification goes
    through the normal webhook path, so the Kodi stale-prune step we already wired into
    `_run_one` fires too - a user who deletes the parked `.split-source-eps-...mkv`
    afterwards gets Kodi's old row removed on the follow-up scan without extra work here.
    """
    from curator.video import config

    try:
        cfg = config.current()
    except Exception:
        logger.debug("split notify skipped: config unavailable", exc_info=True)
        return
    if not cfg.get("scan_split_notify"):
        return
    folders = []
    titles = []
    for item in results:
        if item.get("status") != "done":
            continue
        parked = str(item.get("parked") or "")
        if not parked:
            continue
        folder = os.path.dirname(parked)
        if folder and folder not in folders:
            folders.append(folder)
        titles.append(os.path.basename(parked))
    if not folders:
        return
    try:
        from curator import notify

        notify.request("video", folders=folders, media="tv", items=titles,
                       message=f"Split episodes imported into {len(folders)} folder(s)")
    except Exception:
        logger.warning("split post-notify failed", exc_info=True)

def _run_split(episode_id, times):
    from curator.video import config

    episode, group = _group(episode_id)
    path = episode["path"]
    pairs = _pairs(group)
    names = part_names(path, pairs)
    parked = parked_name(path, pairs)
    if not names or not parked:
        raise AppError("The file name has no episode span to replace", 400)
    folder = os.path.dirname(path)
    outputs = [os.path.join(folder, name) for name in names]
    parked_path = os.path.join(folder, parked)
    for dest in outputs + [parked_path]:
        if os.path.exists(dest):
            raise AppError(f"{os.path.basename(dest)} already exists", 400)
    cfg = config.current()
    duration = _duration(path, episode.get("duration_seconds"))
    points = validate_times(times, duration, 1.0, len(pairs) - 1)
    stem = os.path.splitext(os.path.basename(path))[0]
    pattern = os.path.join(folder, f".{stem}.split-tmp-%02d.mkv")
    _set(message="Splitting")
    bounds = [0.0, *points, duration]
    spec = ",".join(f"{format_mkv(start)}-{format_mkv(end)}" for start, end in zip(bounds, bounds[1:]))
    try:
        result = subprocess.run(
            ["mkvmerge", "-o", pattern, "--split", f"parts:{spec}", path],
            capture_output=True, text=True, timeout=7200, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _cleanup_temps(folder, stem)
        raise AppError(f"mkvmerge failed: {exc}", 500)
    temps = _temp_parts(folder, stem)
    if result.returncode != 0 or len(temps) != len(outputs):
        detail = (result.stderr or result.stdout or "mkvmerge failed").strip().splitlines()
        _cleanup_temps(folder, stem)
        raise AppError(detail[-1] if detail else "mkvmerge failed", 500)
    _set(message="Checking durations")
    for temp, start, end in zip(temps, bounds, bounds[1:]):
        actual = _probe_duration(temp)
        planned = end - start
        if actual < 1.0 or abs(actual - planned) > max(5.0, planned * 0.02):
            _cleanup_temps(folder, stem)
            raise AppError("A split part does not match its planned length", 400)
    renamed = []
    try:
        for temp, dest in zip(temps, outputs):
            os.replace(temp, dest)
            renamed.append((dest, temp))
        os.replace(path, parked_path)
        renamed.append((parked_path, path))
        # Index the parts before the episodes are pointed at them. Each new file needs its own
        # video_files row, and the episode needs that row's id: file_id was being left NULL, so
        # the split parts had no media info, no size and no duration anywhere in the library.
        _set(message="Reading the new files")
        file_ids = _index_parts(outputs)
        _set(message="Updating the library", parked=parked_path, original=path)
        old_stem = stem
        with db.transaction() as conn:
            for row, dest, file_id in zip(group, outputs, file_ids):
                new_stem = os.path.splitext(os.path.basename(dest))[0]
                nfo_path, thumb = _move_sidecar(folder, old_stem, new_stem, row["season_number"], row["episode_number"])
                artwork = dict(row.get("artwork") or {})
                if thumb:
                    artwork["thumb"] = thumb
                conn.execute(
                    """
                    UPDATE tv_episodes
                    SET path = %s, nfo_path = COALESCE(%s, nfo_path), artwork = %s, file_span = %s,
                        file_id = %s, split_source = %s, split_original = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (dest, nfo_path, Jsonb(artwork), Jsonb([]), file_id, parked_path, path, row["id"]),
                )
    except Exception:
        for dest, src in reversed(renamed):
            if os.path.exists(dest) and not os.path.exists(src):
                try:
                    os.replace(dest, src)
                except OSError:
                    logger.warning("could not undo split rename %s", dest)
        raise
    return {
        "episode_id": str(episode["id"]), "status": "done",
        "message": f"Split into {len(outputs)} files", "parked": parked_path, "original": path,
    }


def _index_parts(paths):
    """Probe each freshly written part and store its video_files row. Returns the row ids.

    The same two calls the scanner makes for any video it finds, so a split part ends up with
    the media info, size, duration and mediainfo sidecar it would have had if a scan had found
    it. A part whose probe fails keeps a null id rather than failing the whole split; a later
    scan or Update media info will fill it in.
    """
    from curator.video import probe, store

    ids = []
    for dest in paths:
        try:
            summary = probe.analyze(dest, open_iso=False)
            size = os.path.getsize(dest)
            mtime = os.path.getmtime(dest)
            existing = db.fetchone("SELECT external_subtitles FROM video_files WHERE path = %s", (dest,))
            external = (existing or {}).get("external_subtitles") or []
            ids.append(store.save_file(dest, "episode", size, mtime, summary, external))
        except Exception:
            logger.exception("could not index the split part %s", dest)
            ids.append(None)
    return ids


def _temp_parts(folder, stem):
    prefix = f".{stem}.split-tmp-"
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        if name.startswith(prefix) and name.lower().endswith(".mkv"):
            found.append(os.path.join(folder, name))
    found.sort()
    return found


def _cleanup_temps(folder, stem):
    for path in _temp_parts(folder, stem):
        try:
            os.remove(path)
        except OSError:
            logger.warning("could not remove split temp %s", path)


def _move_sidecar(folder, old_stem, new_stem, season, episode, reverse=False):
    mark = naming.episode_mark(season, episode)
    multi_nfo = os.path.join(folder, f"{old_stem}-{mark}.nfo")
    part_nfo = os.path.join(folder, f"{new_stem}.nfo")
    src, dst = (part_nfo, multi_nfo) if reverse else (multi_nfo, part_nfo)
    nfo_path = None
    if os.path.isfile(src) and not os.path.exists(dst):
        os.replace(src, dst)
        nfo_path = dst
    thumb = None
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        multi_thumb = os.path.join(folder, f"{old_stem}-{mark}-thumb{ext}")
        part_thumb = os.path.join(folder, f"{new_stem}-thumb{ext}")
        src, dst = (part_thumb, multi_thumb) if reverse else (multi_thumb, part_thumb)
        if os.path.isfile(src) and not os.path.exists(dst):
            os.replace(src, dst)
            thumb = dst
            break
    return nfo_path, thumb


def _split_rows(episode_id):
    row = db.fetchone(
        "SELECT id, split_source, split_original FROM tv_episodes WHERE id = %s",
        (episode_id,),
    )
    if not row or not row["split_source"] or not row["split_original"]:
        raise AppError("This episode has no parked source file", 400)
    rows = db.fetchall(
        """
        SELECT id, season_number, episode_number, path, nfo_path, artwork
        FROM tv_episodes WHERE split_source = %s
        ORDER BY season_number, episode_number
        """,
        (row["split_source"],),
    )
    return row["split_source"], row["split_original"], [db.clean(dict(item)) for item in rows]


def restore(episode_id):
    """Put the parked file back under its original name and delete the parts."""
    _ensure_idle()
    parked, original, rows = _split_rows(episode_id)
    if not rows:
        raise AppError("This episode has no parked source file", 400)
    if not os.path.isfile(parked):
        raise AppError("The parked source file is not there any more", 400)
    if os.path.exists(original):
        raise AppError("The original file name is already in use", 400)
    missing = [row["path"] for row in rows if not row.get("path") or not os.path.isfile(row["path"])]
    if missing:
        raise AppError("A split part was renamed or deleted, so the source was left as it is", 400)
    folder = os.path.dirname(original)
    old_stem = os.path.splitext(os.path.basename(original))[0]
    restored = []
    for row in rows:
        new_stem = os.path.splitext(os.path.basename(row["path"]))[0]
        nfo_path, thumb = _move_sidecar(folder, old_stem, new_stem, row["season_number"], row["episode_number"], reverse=True)
        artwork = dict(row.get("artwork") or {})
        if thumb:
            artwork["thumb"] = thumb
        restored.append((row, nfo_path, artwork))
    for row, _nfo_path, _artwork in restored:
        os.remove(row["path"])
    os.replace(parked, original)
    span = [{"season": int(row["season_number"]), "episode": int(row["episode_number"])} for row, _nfo_path, _artwork in restored]
    with db.transaction() as conn:
        for row, nfo_path, artwork in restored:
            conn.execute(
                """
                UPDATE tv_episodes
                SET path = %s, nfo_path = COALESCE(%s, nfo_path), artwork = %s, file_span = %s, file_id = NULL,
                    split_source = NULL, split_original = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (original, nfo_path, Jsonb(artwork), Jsonb(span), row["id"]),
            )
    return {"message": "The original file is restored.", "path": original}


def delete_source(episode_id):
    """Delete the parked source and keep the split parts."""
    _ensure_idle()
    parked, _original, rows = _split_rows(episode_id)
    if os.path.isfile(parked):
        os.remove(parked)
    db.execute(
        "UPDATE tv_episodes SET split_source = NULL, split_original = NULL, updated_at = NOW() WHERE split_source = %s",
        (parked,),
    )
    return {"message": "The source file was deleted.", "episodes": len(rows)}
