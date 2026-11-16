import array
import logging
import math
import os
import subprocess

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)


def album(album_id):
    album = db.fetchone("SELECT id, title FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    return _check(tracks, f"Audit {album.get('title') or ''}")


def check_album(album_id):
    """Audit one album's tracks without a job of its own (a bulk job has its own). Returns the newly corrupt tracks;
    the caller reports them (_report_corrupt) once for the whole run."""
    broken = []
    for track in db.fetchall("SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number", (album_id,)):
        flag = inspect(track)
        if flag:
            db.execute("UPDATE tracks SET audio_flag = %s WHERE id = %s", (flag, track["id"]))
        if flag == "corrupt" and track.get("audio_flag") != "corrupt":
            broken.append(track)
    return broken


def unchecked():
    tracks = db.fetchall(
        """
        SELECT * FROM tracks
        WHERE audio_flag IS NULL
        ORDER BY file_path
        """
    )
    if not tracks:
        return {"processed": 0, "total": 0}
    return _check(tracks, "Scheduled audio audit")


def inspect(track):
    path = track.get("file_path") or ""
    if not path or not os.path.isfile(path):
        return None
    flac_file = path.lower().endswith(".flac")
    # FLAC checks its own stored MD5; other formats are decoded once with ffmpeg. Either way a bad file is "corrupt".
    flag = _flac_test(path) if flac_file else _decode_test(path)
    if flag == "corrupt":
        return flag
    rate = int(track.get("sample_rate") or 0)
    if rate > 44100:
        cutoff, ran = _cutoff(path, rate)
        if cutoff:
            return "upscaled"
        if not ran:
            return flag
    if flag is None:
        return None
    return flag


def _check(tracks, message):
    job = db.fetchone(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
        VALUES ('audit', 'running', %s, 0, %s, '', NOW())
        RETURNING id
        """,
        (message, len(tracks)),
    )
    processed = 0
    broken = []
    try:
        for track in tracks:
            flag = inspect(track)
            if flag:
                db.execute("UPDATE tracks SET audio_flag = %s WHERE id = %s", (flag, track["id"]))
            if flag == "corrupt" and track.get("audio_flag") != "corrupt":
                broken.append(track)
            processed += 1
            db.execute(
                "UPDATE work_jobs SET processed = %s WHERE id = %s",
                (processed, job["id"]),
            )
    except Exception as exc:
        db.execute(
            """
            UPDATE work_jobs
            SET status = 'failed', message = %s, finished_at = NOW()
            WHERE id = %s
            """,
            (str(exc)[:400], job["id"]),
        )
        raise
    db.execute(
        """
        UPDATE work_jobs
        SET status = 'completed', message = %s, processed = %s, finished_at = NOW()
        WHERE id = %s
        """,
        (f"Checked {processed} tracks" + (f", {len(broken)} corrupt" if broken else ""), processed, job["id"]),
    )
    _report_corrupt(broken)
    return {"processed": processed, "total": len(tracks), "corrupt": len(broken)}


def _report_corrupt(tracks):
    """Activity history and the "corrupt file" notification, as for a video integrity check. Only newly found ones."""
    if not tracks:
        return
    from resonance import history

    for track in tracks:
        history.record("corrupt", os.path.basename(track.get("file_path") or ""), "track", track.get("file_path") or "",
                       "Audit audio: the file does not decode cleanly")
    try:
        from curator import outbound

        names = ", ".join(os.path.basename(track.get("file_path") or "") for track in tracks[:5])
        more = f" and {len(tracks) - 5} more" if len(tracks) > 5 else ""
        outbound.send("file_corrupt", f"Corrupt music file{'s' if len(tracks) != 1 else ''}: {len(tracks)}",
                      f"{names}{more}", "warning")
    except Exception:
        logger.exception("could not send the corrupt file notification")


def _flac_test(path):
    try:
        completed = subprocess.run(
            ["flac", "-t", "-s", path],
            capture_output=True,
            check=False,
        )
    except OSError:
        logger.info("flac is not installed; integrity check skipped")
        return None
    return "verified" if completed.returncode == 0 else "corrupt"


def _decode_test(path):
    """Decode the audio of a non-FLAC file and discard it. "checked" when it decodes cleanly, "corrupt" when ffmpeg
    reports an error, None when ffmpeg is missing or the check could not run."""
    try:
        completed = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", path, "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, text=True, errors="replace", timeout=600, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.info("ffmpeg could not check %s", path)
        return None
    errors = [line for line in (completed.stderr or "").splitlines() if line.strip()]
    return "corrupt" if completed.returncode or errors else "checked"


def _cutoff(path, sample_rate):
    try:
        completed = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", "8", "-i", path, "-ac", "1", "-f", "f32le", "-"],
            capture_output=True,
            check=False,
        )
    except OSError:
        logger.info("ffmpeg is not installed; cutoff check skipped")
        return False, False
    if completed.returncode or not completed.stdout:
        return False, True
    samples = array.array("f")
    raw = completed.stdout
    usable = len(raw) - (len(raw) % 4)
    if usable < 4096 * 4:
        return False, True
    samples.frombytes(raw[:usable])
    window = samples[:4096]
    low = _band_peak(window, sample_rate, 0, 16000)
    above_16 = _band_peak(window, sample_rate, 16000, sample_rate / 2)
    above_20 = _band_peak(window, sample_rate, 20000, sample_rate / 2)
    if low < 1e-4:
        return False, True
    return above_20 < low * 0.01 or above_16 < low * 0.01, True


def _band_peak(window, sample_rate, low_hz, high_hz):
    count = len(window)
    start = max(1, int(low_hz * count / sample_rate))
    stop = min(count // 2, int(high_hz * count / sample_rate))
    if stop <= start:
        return 0.0
    peak = 0.0
    for bin_index in range(start, stop, 4):
        real = 0.0
        imag = 0.0
        angle = 2 * math.pi * bin_index / count
        for index, sample in enumerate(window):
            real += sample * math.cos(angle * index)
            imag -= sample * math.sin(angle * index)
        peak = max(peak, math.hypot(real, imag))
    return peak
