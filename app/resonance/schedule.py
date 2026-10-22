import datetime
import logging
import threading
import time

logger = logging.getLogger(__name__)
_started = False


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="library-schedule", daemon=True).start()


def _loop():
    last_fired = {}
    last_checked_utc = None
    while True:
        try:
            from resonance import cron
            from resonance.settings import load as load_settings

            cfg = load_settings()
            schedules = cfg.get("scan_schedules") or []
            if cfg.get("schedule_enabled") and schedules:
                tz = cron.get_timezone()
                now = datetime.datetime.now(tz)
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                current_minute = (now.year, now.month, now.day, now.hour, now.minute)
                current_keys = set()
                for item in schedules:
                    expr = str(item.get("cron") or "")
                    sched_key = f"{item.get('media')}:{item.get('scan_mode')}:{expr}"
                    current_keys.add(sched_key)
                    if last_fired.get(sched_key) == current_minute:
                        continue
                    matched = cron.matches_cron(now, expr)
                    if not matched and last_checked_utc is not None:
                        gap_seconds = (now_utc - last_checked_utc).total_seconds()
                        if 60 <= gap_seconds <= 7200:
                            chk = last_checked_utc + datetime.timedelta(minutes=1)
                            while chk < now_utc:
                                if cron.matches_cron(chk.astimezone(tz), expr):
                                    matched = True
                                    break
                                chk += datetime.timedelta(minutes=1)
                    if not matched:
                        continue
                    last_fired[sched_key] = current_minute
                    mode = item.get("scan_mode") or "incremental"
                    logger.info(
                        "Triggering scheduled %s scan: %s (%s)",
                        mode,
                        expr,
                        cron.describe_cron(expr),
                    )
                    _pass(item)
                last_checked_utc = now_utc
                last_fired = {key: value for key, value in last_fired.items() if key in current_keys}
        except Exception:
            logger.exception("scheduled pass check failed")
        time.sleep(15)


def status():
    from resonance import cron
    from resonance.settings import load as load_settings

    cfg = load_settings()
    enabled = bool(cfg.get("schedule_enabled"))
    return {
        "enabled": enabled,
        "schedules": [
            cron.saved_schedule_summary(item, enabled) for item in (cfg.get("scan_schedules") or [])
        ],
    }


def _pass(item):
    from resonance import scan_queue
    from resonance.scanner import normalize_scan_mode
    from resonance.settings import load as load_settings

    cfg = load_settings()
    if not cfg.get("schedule_enabled"):
        return
    mode = normalize_scan_mode((item or {}).get("scan_mode"))
    media = str((item or {}).get("media") or "music")
    if media in {"movies", "tv", "sets"}:
        from curator import folders

        kind = "tv" if media == "tv" else "movies"
        roots = folders.included(kind)
        if not roots:
            logger.info("scheduled %s scan skipped: every folder is excluded", media)
            return
        outcome = scan_queue.submit({
            "media": media,
            "mode": "full" if media == "sets" else mode,
            "kind": "sets" if media == "sets" else "library",
            "origin": "scheduled",
            "roots": list(roots or []),
            "item": item or {},
        })
        if outcome == "queued":
            logger.info("scheduled %s %s scan queued until the running scan finishes", media, mode)
        return
    outcome = scan_queue.submit({
        "media": "music",
        "mode": mode,
        "kind": "schedule",
        "roots": [],
        "item": item or {},
    })
    if outcome == "queued":
        logger.info("scheduled %s scan queued until the running scan finishes", mode)


def _locked_pass(item):
    from resonance import db, scanner
    from resonance.scanner import normalize_scan_mode

    scan_mode = normalize_scan_mode((item or {}).get("scan_mode"))
    label = f"Scheduled {scan_mode} scan"

    work = db.fetchone(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
        VALUES ('schedule', 'running', 'Scheduled library pass', 0, 3, '', NOW())
        RETURNING id
        """
    )
    scan_row = db.fetchone(
        """
        INSERT INTO scan_jobs (status, message, processed, total, started_at, phase, mode, log, result)
        VALUES ('running', %s, 0, 0, NOW(), 'directory', %s, '', '{"origin": "scheduled"}'::jsonb)
        RETURNING id
        """,
        (label, scan_mode),
    )
    fingerprint_count = 0
    lyric_albums = 0
    from resonance import jobs as music_jobs

    music_jobs.bind_pause(scan_row["id"])
    try:
        message = scanner.scan(scan_row["id"], force=False, mode=scan_mode)
        status = "cancelled" if message == "Scan cancelled" else "completed"
        db.execute(
            """
            UPDATE scan_jobs
            SET status = %s, message = %s, finished_at = NOW()
            WHERE id = %s
            """,
            (status, message, scan_row["id"]),
        )
        try:
            from curator import outbound

            outbound.scan_done("music", status, message, "scheduled")
        except Exception:
            logger.exception("could not send the scan notification")
        fingerprint_count = _fingerprint_unmatched()
        lyric_albums = _lyrics_missing()
        from resonance import audit

        audit.unchecked()
        summary = f"{scan_mode.capitalize()} scan finished. Fingerprints {fingerprint_count}. Lyric albums {lyric_albums}."
        db.execute(
            """
            UPDATE work_jobs
            SET status = 'completed', message = %s, processed = 3, total = 3, log = %s, finished_at = NOW()
            WHERE id = %s
            """,
            (summary, summary, work["id"]),
        )
    except Exception as exc:
        from resonance.jobs import ScanCancelled

        cancelled = isinstance(exc, ScanCancelled)
        db.execute(
            """
            UPDATE scan_jobs
            SET status = %s, message = %s, finished_at = NOW()
            WHERE id = %s AND status = 'running'
            """,
            ("cancelled" if cancelled else "failed", "Scan cancelled" if cancelled else str(exc)[:400], scan_row["id"]),
        )
        db.execute(
            """
            UPDATE work_jobs
            SET status = %s, message = %s, finished_at = NOW()
            WHERE id = %s
            """,
            ("cancelled" if cancelled else "failed", "Scheduled pass cancelled" if cancelled else str(exc)[:400], work["id"]),
        )
        if not cancelled:
            raise
    finally:
        music_jobs.unbind_pause()


def _fingerprint_unmatched():
    from resonance import db
    from resonance.sources import fingerprint

    albums = db.fetchall(
        """
        SELECT id FROM albums
        WHERE match_tier = 'unmatched' OR musicbrainz_release_id IS NULL
        """
    )
    checked = 0
    for album in albums:
        tracks = db.fetchall("SELECT id, file_path FROM tracks WHERE album_id = %s", (album["id"],))
        result = fingerprint.fingerprint_tracks(
            [track["file_path"] for track in tracks if track.get("file_path")],
            limit=None,
        )
        for item in result.get("files") or []:
            db.execute(
                """
                UPDATE tracks
                SET fingerprint_hash = COALESCE(%s, fingerprint_hash),
                    acoustid_recording_id = COALESCE(%s, acoustid_recording_id),
                    acoustid_score = COALESCE(%s, acoustid_score)
                WHERE file_path = %s
                """,
                (item.get("fingerprint_hash"), item.get("recording_id"), item.get("score"), item.get("path")),
            )
            checked += 1
    _record("fingerprint", checked, len(albums))
    return checked


def _lyrics_missing():
    from resonance import db, lyrics

    albums = db.fetchall(
        """
        SELECT DISTINCT album_id FROM tracks
        WHERE lyrics_type IS NULL OR lyrics_type = 'none'
        """
    )
    written = 0
    for album in albums:
        result = lyrics.fetch_album(album["album_id"], only_missing=True)
        written += result.get("written") or 0
    _record("lyrics", written, len(albums))
    return len(albums)


def _record(kind, processed, total):
    from resonance import db

    db.execute(
        """
        INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at, finished_at)
        VALUES (%s, 'completed', %s, %s, %s, '', NOW(), NOW())
        """,
        (kind, f"{kind} {processed}/{total}", processed, total),
    )
