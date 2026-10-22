import hashlib
import logging
import os
import subprocess
from collections import Counter

from resonance import settings

logger = logging.getLogger(__name__)


def fingerprint_tracks(paths, limit=2):
    key = (settings.load().get("acoustid_key") or "").strip()
    chosen = list(paths or [])
    if limit is not None:
        chosen = chosen[:limit]
    files = []
    groups = []
    recordings = []
    scores = []
    lookup = bool(key)
    acoustid = None
    if lookup:
        try:
            import acoustid
        except Exception as exc:
            lookup = False
            logger.info("acoustid import failed: %s", exc)
    for path in chosen:
        best = None
        recording_id = None
        try:
            duration, fingerprint = _fingerprint_file(path)
            digest = hashlib.sha256(
                fingerprint if isinstance(fingerprint, bytes) else str(fingerprint).encode("utf-8")
            ).hexdigest()
            from resonance.jobs import checkpoint

            checkpoint()
        except Exception as exc:
            from resonance.jobs import ScanCancelled

            if isinstance(exc, ScanCancelled):
                raise
            logger.info("fingerprint failed for %s: %s", path, exc)
            scores.append({"path": path, "score": None})
            continue
        data = {}
        if lookup and acoustid is not None:
            try:
                data = acoustid.lookup(key, fingerprint, duration, meta=["recordings", "releasegroups"])
            except Exception as exc:
                from resonance.jobs import ScanCancelled

                if isinstance(exc, ScanCancelled):
                    raise
                logger.info("acoustid failed for %s: %s", path, exc)
        for result in data.get("results") or []:
            score = result.get("score") or 0
            if best is None or score >= best:
                best = score
                first = (result.get("recordings") or [None])[0]
                if first and first.get("id"):
                    recording_id = first.get("id")
            for recording in result.get("recordings") or []:
                recordings.append(
                    {
                        "id": recording.get("id"),
                        "title": recording.get("title"),
                        "score": score,
                    }
                )
                for group in recording.get("releasegroups") or []:
                    if group.get("id"):
                        groups.append(group["id"])
        score_value = None if best is None else int(round(float(best) * 100))
        scores.append({"path": path, "score": score_value})
        files.append(
            {
                "path": path,
                "fingerprint_hash": digest,
                "recording_id": _uuid(recording_id),
                "score": score_value,
            }
        )
    counts = Counter(group_id for group_id in groups if group_id)
    return {
        "skipped": not lookup,
        "release_groups": [group_id for group_id, _count in counts.most_common()],
        "release_group_counts": dict(counts),
        "recordings": recordings[:12],
        "scores": scores,
        "files": files,
    }


def _uuid(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) != 36:
        return None
    return text


def _fingerprint_file(path):
    from resonance.jobs import ScanCancelled, cancelled

    fpcalc = os.environ.get("FPCALC", "fpcalc")
    command = [fpcalc, "-length", "120", path]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        import acoustid

        return acoustid.fingerprint_file(path, maxlength=120)
    while proc.poll() is None:
        if cancelled():
            proc.kill()
            proc.wait(timeout=5)
            raise ScanCancelled()
        try:
            proc.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            continue
    output = proc.stdout.read() if proc.stdout else b""
    if proc.returncode:
        raise RuntimeError(f"fpcalc exited with status {proc.returncode}")
    duration = fingerprint = None
    for line in output.splitlines():
        parts = line.split(b"=", 1)
        if len(parts) != 2:
            continue
        if parts[0] == b"DURATION":
            duration = float(parts[1])
        elif parts[0] == b"FINGERPRINT":
            fingerprint = parts[1]
    if duration is None or not fingerprint:
        raise RuntimeError("fpcalc did not return a fingerprint")
    return duration, fingerprint
