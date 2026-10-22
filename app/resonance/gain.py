import logging
import shutil
import subprocess

from resonance import db
from resonance.errors import AppError
from resonance.paths import assert_library_writable

logger = logging.getLogger(__name__)


def album_lines(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    assert_library_writable(album["path"])
    if not shutil.which("rsgain"):
        raise AppError("rsgain is not installed in this image")
    job = db.fetchone(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
        VALUES ('replaygain', 'running', 'Writing ReplayGain', 0, 1, '', NOW())
        RETURNING id
        """
    )
    try:
        completed = subprocess.run(
            ["rsgain", "easy", album["path"]],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        _finish(job["id"], "failed", str(exc))
        raise AppError(f"rsgain failed: {exc}") from exc
    output = (completed.stderr or completed.stdout or "").strip()
    if completed.returncode:
        _finish(job["id"], "failed", output[-500:])
        raise AppError(output[-400:] or "rsgain failed")
    _finish(job["id"], "completed", "ReplayGain tags written")
    return ["ReplayGain tags written"]


def _finish(job_id, status, message):
    db.execute(
        """
        UPDATE work_jobs
        SET status = %s, message = %s, processed = 1, finished_at = NOW(), log = %s
        WHERE id = %s
        """,
        (status, message, message, job_id),
    )
    logger.info("replaygain %s: %s", status, message)
