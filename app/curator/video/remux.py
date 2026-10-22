"""Matroska jobs: Dolby Vision Profile 7 to 8.1, and keeping only the tracks a person chose.

Profile 7 writes a new file beside the original. Track selection rewrites that one file
after the new copy probes cleanly. Disc images are refused.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOB = {"status": "idle", "message": "", "failed": []}
_RUN_TIMEOUT = 6 * 60 * 60


def status():
    with _LOCK:
        return dict(_JOB)


def _busy():
    from curator.video import files, scanner, scrape

    if scanner.running() or scrape.running() or files.running():
        raise AppError("Wait for the running scan, scrape or file job to finish", 409)
    with _LOCK:
        if _JOB.get("status") == "running":
            raise AppError("A remux is already running", 409)


def _set(**values):
    with _LOCK:
        _JOB.update(values)


def tracks_for(kind, item_id):
    """Every video, audio, and subtitle track mkvmerge will see in this item's file."""
    path = _item_path(kind, item_id)
    _require_mkv(path)
    return {"path": os.path.basename(path), "tracks": identify(path)}


def start_profile8(kind, item_id, remove_original=False):
    """Write Name.p8.mkv beside a Profile 7 file. The original stays unless removal was requested."""
    _busy()
    path = _item_path(kind, item_id)
    _require_mkv(path)
    row = _item_probe(kind, item_id)
    if not _profile7(row):
        raise AppError("This file is not Dolby Vision Profile 7 with an enhancement layer", 400)
    _set(status="running", message="Converting Dolby Vision Profile 7", failed=[], item_id=str(item_id), kind=kind)

    def work():
        failed = []
        dest = ""
        try:
            dest = profile8_path(path)
            convert_profile7(path, dest)
            if not remove_original:
                _set(status="done", message=f"Wrote {os.path.basename(dest)}. The original was left in place.", failed=[], item_id=str(item_id), kind=kind)
                return
            kept = _scan_and_replace(kind, item_id, path, dest)
            _set(status="done", message=f"Wrote {os.path.basename(dest)} and removed the original after the deep scan.", failed=[], item_id=kept, kind=kind)
        except Exception as exc:
            logger.exception("profile 7 conversion failed for %s", path)
            failed.append(str(exc))
            written = bool(dest) and os.path.isfile(dest)
            text = str(exc) if written else "Dolby Vision conversion failed."
            _set(status="done", message=text, failed=failed, item_id=str(item_id), kind=kind)

    threading.Thread(target=work, name="curator-dovi", daemon=True).start()
    return status()


def paths_after_swap(parts, library_path, original, dest):
    """Point a movie's file list at the converted file and drop the original path."""
    found = [part for part in (parts or []) if part]
    if not found and library_path and os.path.isfile(library_path):
        found = [library_path]
    swapped = [dest if _same_path(part, original) else part for part in found]
    if not any(_same_path(part, dest) for part in swapped):
        swapped.append(dest)
    swapped = [part for part in swapped if not _same_path(part, original)]
    path = dest if _same_path(library_path, original) else library_path
    return path, swapped


def _scan_and_replace(kind, item_id, original, dest):
    """Deep scan the new file, then remove the original only if that scan finished."""
    _probe_new(dest, kind)
    _set(message="Deep scanning the new file")
    _deep_scan(kind, item_id, original)
    kept = _retire_original(kind, item_id, original, dest)
    return kept


def _probe_new(path, kind):
    from curator.video import probe, store

    summary = probe.analyze(path)
    store.save_file(path, "movie" if kind == "movie" else "episode", os.path.getsize(path), os.path.getmtime(path), summary, [])
    if summary.get("probe_error"):
        raise AppError(f"The new file did not probe cleanly, so the original was kept. {summary['probe_error']}", 500)


def _deep_scan(kind, item_id, original):
    from resonance import scan_queue
    from curator.video import scanner

    target = _scan_target(kind, item_id, original)
    scan_id = str(uuid.uuid4())
    spec = {
        "id": scan_id,
        "media": target["media"],
        "mode": "deep",
        "kind": "library",
        "origin": "file job",
        "roots": target["roots"],
        "targets": target["targets"],
        "season_id": target.get("season_id"),
        "label": "Deep scan after Dolby Vision conversion",
    }
    before = str((scanner.status(include_log=False) or {}).get("id") or "")
    outcome = scan_queue.submit(spec)
    if outcome not in {"started", "queued", "duplicate"}:
        raise AppError("The deep scan did not start, so the original was kept", 500)
    started = time.time()
    deadline = started + _RUN_TIMEOUT
    seen = False
    while time.time() < deadline:
        time.sleep(2)
        queued = scan_queue.snapshot()
        ours = any(_same_scan(item, scan_id, spec) for item in queued)
        running = scanner.running()
        snap = scanner.status(include_log=False)
        current = str(snap.get("id") or "")
        if ours or (running and current not in {"", before}):
            seen = True
            continue
        if running:
            continue
        finished = snap.get("status") == "completed" and (seen or current not in {"", before})
        if finished:
            return
        if seen or current not in {"", before}:
            raise AppError("The deep scan did not finish, so the original was kept", 500)
        if time.time() - started > 30:
            raise AppError("The deep scan did not start, so the original was kept", 500)
    raise AppError("The deep scan did not finish, so the original was kept", 500)


def _same_scan(item, scan_id, spec):
    if str(item.get("id") or "") == scan_id or item.get("label") == spec["label"]:
        return True
    return (
        item.get("media") == spec["media"]
        and item.get("mode") == "deep"
        and list(item.get("targets") or []) == list(spec.get("targets") or [])
    )


def _scan_target(kind, item_id, original):
    if kind == "movie":
        row = db.fetchone("SELECT root, folder, path FROM movies WHERE id = %s", (item_id,))
        if not row:
            raise AppError("That movie is no longer in the library, so the original was kept", 404)
        folder = row.get("folder") or os.path.dirname(original)
        return {"media": "movies", "roots": [row["root"]], "targets": [folder]}
    row = db.fetchone(
        """
        SELECT e.season_id, s.root
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id
        WHERE e.id = %s
        """,
        (item_id,),
    )
    if not row:
        raise AppError("That episode is no longer in the library, so the original was kept", 404)
    return {
        "media": "tv",
        "roots": [row["root"]],
        "targets": [os.path.dirname(original)],
        "season_id": str(row["season_id"]),
    }


def _retire_original(kind, item_id, original, dest):
    file_row = db.fetchone("SELECT id, probe_error FROM video_files WHERE path = %s", (dest,))
    if not file_row or file_row.get("probe_error"):
        raise AppError("The new file was not scanned, so the original was kept", 500)
    if not os.path.isfile(dest) or not os.path.isfile(original):
        raise AppError("The original was kept because one of the files is missing", 500)
    if kind == "movie":
        kept = _retire_movie(item_id, original, dest, file_row["id"])
    else:
        kept = _retire_episode(item_id, original, dest, file_row["id"])
    os.remove(original)
    return kept


def _retire_movie(item_id, original, dest, file_id):
    rows = db.fetchall(
        """
        SELECT id, path, folder, parts FROM movies
        WHERE id = %s OR path = %s OR %s = ANY(parts) OR path = %s OR %s = ANY(parts)
        """,
        (item_id, original, original, dest, dest),
    )
    survivor = next((row for row in rows if _movie_uses(row, dest) and str(row["id"]) != str(item_id)), None)
    current = next((row for row in rows if str(row["id"]) == str(item_id)), None)
    if survivor:
        if current:
            _delete_movie_row(current["id"])
        return str(survivor["id"])
    if not current:
        raise AppError("The new file was not added to the library, so the original was kept", 500)
    path, parts = paths_after_swap(current.get("parts"), current.get("path"), original, dest)
    db.execute(
        "UPDATE movies SET path = %s, parts = %s, file_id = %s, updated_at = NOW() WHERE id = %s",
        (path, parts, file_id, current["id"]),
    )
    return str(current["id"])


def _retire_episode(item_id, original, dest, file_id):
    sharing = db.fetchall("SELECT id FROM tv_episodes WHERE path = %s AND id <> %s", (original, item_id))
    if sharing:
        raise AppError("Another episode uses this file, so the original was kept", 409)
    current = db.fetchone("SELECT id FROM tv_episodes WHERE id = %s", (item_id,))
    if not current:
        raise AppError("That episode is no longer in the library, so the original was kept", 404)
    db.execute("DELETE FROM episode_copies WHERE path = %s OR path = %s", (original, dest))
    db.execute(
        "UPDATE tv_episodes SET path = %s, file_id = %s, updated_at = NOW() WHERE id = %s",
        (dest, file_id, item_id),
    )
    return str(item_id)


def _delete_movie_row(movie_id):
    db.execute(
        "DELETE FROM video_dismissed_duplicates WHERE kind = 'movie' AND (left_id = %s OR right_id = %s)",
        (movie_id, movie_id),
    )
    db.execute("DELETE FROM movies WHERE id = %s", (movie_id,))


def _movie_uses(row, path):
    if _same_path(row.get("path"), path):
        return True
    return any(_same_path(part, path) for part in row.get("parts") or [])


def _same_path(left, right):
    if not left or not right:
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def keep(kind, item_id, track_ids):
    """Rewrite one file so only the chosen tracks remain. Chapters and attachments stay."""
    _busy()
    path = _item_path(kind, item_id)
    _require_mkv(path)
    chosen = _chosen(path, track_ids)
    _set(status="running", message="Rewriting tracks", failed=[])

    def work():
        try:
            rewrite_tracks(path, chosen)
            _reprobe(kind, item_id)
            _set(status="done", message="Tracks saved.", failed=[])
        except Exception as exc:
            logger.exception("track remux failed for %s", path)
            _set(status="done", message="The file was left unchanged.", failed=[str(exc)])

    threading.Thread(target=work, name="curator-tracks", daemon=True).start()
    return status()


def identify(path):
    if not shutil.which("mkvmerge"):
        raise AppError("mkvmerge is not installed", 500)
    result = _run(["mkvmerge", "-J", path], 120)
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AppError("mkvmerge did not describe this file", 500) from exc
    found = []
    for track in data.get("tracks") or []:
        props = track.get("properties") or {}
        kind = str(track.get("type") or "")
        if kind not in {"video", "audio", "subtitles"}:
            continue
        found.append({
            "id": int(track.get("id")),
            "type": "subtitle" if kind == "subtitles" else kind,
            "codec": track.get("codec") or "",
            "lang": props.get("language_ietf") or props.get("language") or "",
            "name": props.get("track_name") or "",
            "channels": props.get("audio_channels") or "",
            "default": bool(props.get("default_track")),
            "forced": bool(props.get("forced_track")),
        })
    return found


def select_tracks(rows, track_ids):
    """The mkvmerge ids the user kept. One video track and one audio track must remain."""
    wanted = {int(item) for item in track_ids or []}
    video = [row["id"] for row in rows if row["type"] == "video" and row["id"] in wanted]
    audio = [row["id"] for row in rows if row["type"] == "audio" and row["id"] in wanted]
    subs = [row["id"] for row in rows if row["type"] == "subtitle" and row["id"] in wanted]
    if not video or not audio:
        raise AppError("Keep at least one video track and one audio track", 400)
    return {"video": video, "audio": audio, "subtitle": subs}


def _chosen(path, track_ids):
    return select_tracks(identify(path), track_ids)


def rewrite_tracks(path, chosen):
    folder = os.path.dirname(path)
    handle, temp = tempfile.mkstemp(prefix=".curator-tracks-", suffix=".mkv", dir=folder)
    os.close(handle)
    os.remove(temp)
    try:
        command = ["mkvmerge", "-o", temp, "--video-tracks", _ids(chosen["video"]), "--audio-tracks", _ids(chosen["audio"])]
        if chosen["subtitle"]:
            command.extend(["--subtitle-tracks", _ids(chosen["subtitle"])])
        else:
            command.append("--no-subtitles")
        command.append(path)
        _merge(command)
        _accept(path, temp)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def convert_profile7(path, dest):
    if not shutil.which("ffmpeg") or not shutil.which("dovi_tool") or not shutil.which("mkvmerge"):
        raise AppError("ffmpeg, dovi_tool, and mkvmerge are required", 500)
    videos = [row for row in identify(path) if row["type"] == "video"]
    if not videos:
        raise AppError("This file has no video track", 400)
    work = tempfile.mkdtemp(prefix="curator-dovi-")
    try:
        rpu_index = _rpu_index(path, len(videos), work)
        if rpu_index is None:
            raise AppError("dovi_tool could not read a Dolby Vision RPU from this file", 500)
        base_index = _base_index(videos, rpu_index)
        base = os.path.join(work, "base.hevc")
        _ffmpeg_copy(path, base_index, base)
        rpu = os.path.join(work, "rpu.bin")
        _extract_rpu(path, rpu_index, rpu)
        converted = os.path.join(work, "rpu8.bin")
        _tool(["dovi_tool", "convert", "-m", "2", "-i", rpu, "-o", converted])
        if not os.path.isfile(converted) or os.path.getsize(converted) <= 0:
            raise AppError("dovi_tool did not write a Profile 8.1 RPU", 500)
        injected = os.path.join(work, "base8.hevc")
        _tool(["dovi_tool", "inject-rpu", "-i", base, "--rpu-in", converted, "-o", injected])
        if not os.path.isfile(injected) or os.path.getsize(injected) <= 0:
            raise AppError("dovi_tool did not write the converted video", 500)
        folder = os.path.dirname(dest)
        handle, temp = tempfile.mkstemp(prefix=".curator-dovi-", suffix=".mkv", dir=folder)
        os.close(handle)
        os.remove(temp)
        try:
            _merge(["mkvmerge", "-o", temp, injected, "--no-video", path])
            if not _playable(temp, path):
                raise AppError("The converted file did not probe cleanly", 500)
            os.replace(temp, dest)
        finally:
            if os.path.exists(temp):
                os.remove(temp)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def profile8_path(path):
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    candidate = os.path.join(folder, f"{stem}.p8.mkv")
    number = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}.p8-{number}.mkv")
        number += 1
    return candidate


def _base_index(videos, rpu_index):
    """The base layer is the other video track when the RPU sits on the enhancement layer."""
    if len(videos) == 1 or rpu_index >= len(videos):
        return 0
    if len(videos) == 2:
        return 1 if rpu_index == 0 else 0
    return 0


def _rpu_index(path, count, work):
    for index in range(count):
        sample = os.path.join(work, f"sample-{index}.hevc")
        rpu = os.path.join(work, f"sample-{index}.bin")
        try:
            _ffmpeg_copy(path, index, sample, seconds=8)
            _extract_rpu_file(sample, rpu)
        except AppError:
            continue
        if os.path.isfile(rpu) and os.path.getsize(rpu) > 0:
            return index
    return None


def _ffmpeg_copy(path, index, dest, seconds=None):
    command = ["ffmpeg", "-y", "-v", "error", "-i", path, "-map", f"0:v:{index}", "-c:v", "copy"]
    if seconds:
        command.extend(["-t", str(seconds)])
    command.extend(["-f", "hevc", dest])
    _run(command, _RUN_TIMEOUT)
    if not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
        raise AppError("ffmpeg could not copy the video stream", 500)


def _extract_rpu(path, index, dest):
    hevc = dest + ".hevc"
    _ffmpeg_copy(path, index, hevc)
    _extract_rpu_file(hevc, dest)
    os.remove(hevc)


def _extract_rpu_file(hevc, dest):
    _run(["dovi_tool", "extract-rpu", hevc, "-o", dest], _RUN_TIMEOUT)


def _tool(command):
    result = _run(command, _RUN_TIMEOUT)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "dovi_tool failed").strip().splitlines()
        raise AppError(detail[-1] if detail else "dovi_tool failed", 500)
    return result


def _accept(path, temp):
    if not _playable(temp, path):
        raise AppError("The new file did not probe cleanly. The original was kept.", 500)
    backup = path + ".bak"
    os.replace(path, backup)
    try:
        os.replace(temp, path)
    except OSError:
        if not os.path.exists(path) and os.path.exists(backup):
            os.replace(backup, path)
        raise
    if not _playable(path, backup):
        os.replace(path, temp)
        os.replace(backup, path)
        raise AppError("The replaced file did not probe cleanly. The original was restored.", 500)
    os.remove(backup)


def _playable(path, original):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return False
    video = _run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        180,
    )
    if "video" not in (video.stdout or ""):
        return False
    new = _duration(path)
    old = _duration(original)
    if old <= 0 or new <= 0:
        return new > 0 or old <= 0
    return abs(new - old) <= 3


def _duration(path):
    result = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
        180,
    )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return 0
    try:
        return float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0


def _merge(command):
    if not shutil.which("mkvmerge"):
        raise AppError("mkvmerge is not installed", 500)
    result = _run(command, _RUN_TIMEOUT)
    if result.returncode not in {0, 1}:
        detail = (result.stderr or result.stdout or "mkvmerge failed").strip().splitlines()
        raise AppError(detail[-1] if detail else "mkvmerge failed", 500)
    return result


def _run(command, timeout):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AppError(f"{os.path.basename(command[0])} took too long", 500) from exc
    except OSError as exc:
        raise AppError(str(exc), 500) from exc


def _ids(values):
    return ",".join(str(int(value)) for value in values)


def _require_mkv(path):
    if os.path.splitext(path)[1].lower() != ".mkv":
        raise AppError("Only Matroska files can be remuxed", 400)


def _profile7(row):
    profile = str((row or {}).get("dovi_profile") or "")
    layer = str((row or {}).get("dovi_el_type") or "").upper()
    return profile.startswith("7") and layer in {"FEL", "MEL"}


def _item_path(kind, item_id):
    row = _item_probe(kind, item_id)
    path = str((row or {}).get("path") or "")
    if not path or not os.path.isfile(path):
        raise AppError("That item has no video file", 404)
    return path


def _item_probe(kind, item_id):
    if kind == "movie":
        table, alias = "movies", "m"
    elif kind == "episode":
        table, alias = "tv_episodes", "e"
    else:
        raise AppError("Tracks can be edited on a movie or an episode", 400)
    return db.fetchone(
        f"""
        SELECT {alias}.id, f.path, f.dovi_profile, f.dovi_el_type, f.hdr_format, f.duration_seconds
        FROM {table} {alias}
        JOIN video_files f ON f.id = {alias}.file_id
        WHERE {alias}.id = %s
        """,
        (item_id,),
    )


def _reprobe(kind, item_id):
    from curator.video import reprobe

    row = _item_probe(kind, item_id)
    if not row:
        return
    file_id = db.fetchone(
        "SELECT id FROM video_files WHERE path = %s",
        (row["path"],),
    )
    if not file_id:
        reprobe.refresh(kind, [item_id])
        return
    if kind == "movie":
        reprobe.refresh("movie", [item_id])
        return
    episodes = db.fetchall("SELECT id FROM tv_episodes WHERE file_id = %s", (file_id["id"],))
    reprobe.refresh("episode", [str(item["id"]) for item in episodes] or [item_id])
