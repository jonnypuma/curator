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
    flag = _flac_test(path) if flac_file else None
    rate = int(track.get("sample_rate") or 0)
    if rate > 44100:
        cutoff, ran = _cutoff(path, rate)
        if cutoff:
            return "upscaled"
        if not ran:
            return flag
    if flac_file and flag is None:
        return None
    return flag or "checked"


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
    try:
        for track in tracks:
            flag = inspect(track)
            if flag:
                db.execute("UPDATE tracks SET audio_flag = %s WHERE id = %s", (flag, track["id"]))
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
        (f"Checked {processed} tracks", processed, job["id"]),
    )
    return {"processed": processed, "total": len(tracks)}


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
