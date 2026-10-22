"""One library job at a time.

Music, movie, and TV scans, scrapes, and a scheduled music pass share this line.
A job that arrives while one is running waits here. Webhook imports are a
separate list and run ahead of these waiting jobs. The Queue window shows both.
"""
import logging
import os
import threading
import uuid

logger = logging.getLogger(__name__)
_guard = threading.Lock()
_items = []
_running = None
_active = False
_retry_timer = None


def snapshot():
    """Waiting scans, with the scan that is already running listed first."""
    with _guard:
        rows = []
        if _running:
            rows.append({
                **_public(_running),
                "status": "running",
                "running_seconds": _running_seconds(_running),
            })
        rows.extend({**_public(item), "status": "queued"} for item in _items)
        return rows


def submit(spec):
    """Start a scan or scrape now, or append it. Returns started, queued, or duplicate."""
    global _active, _running
    spec = dict(spec)
    with _guard:
        if _library_duplicate(spec):
            return "duplicate"
        spec["id"] = str(spec.get("id") or uuid.uuid4())
        if _active or _items or _running or _busy():
            _items.append(spec)
            _active = True
            waiting = True
            logger.info("queued %s %s", spec.get("kind") or "scan", spec.get("media"))
        else:
            _active = True
            waiting = False
    if waiting:
        _persist(spec, "queued")
        _arm_retry()
        return "queued"
    _stamp_running(spec)
    _persist(spec, "running")
    if _launch(spec):
        with _guard:
            _running = spec
        _note_scan(spec, "started")
        return "started"
    _persist(spec, "queued")
    with _guard:
        _running = None
        _items.insert(0, spec)
    logger.info("queued %s %s until the library lock is free", spec.get("kind") or "scan", spec.get("media"))
    _arm_retry()
    return "queued"


def claim():
    """Reserve the gate when nothing is running and nothing is already waiting."""
    global _active
    with _guard:
        if _active or _items or _busy():
            return False
        _active = True
        return True


def hold():
    """Reserve the gate for a webhook batch. Waiting library scans stay in line behind it."""
    global _active
    with _guard:
        if _busy():
            return False
        _active = True
        return True


def clear_waiting():
    """Drop every library scan or scrape that is still waiting. The running job stays."""
    global _active, _items
    with _guard:
        count = len(_items)
        _items = []
        if not _busy() and not _running:
            _active = False
    _forget_queued()
    return count


def cancel(item_id):
    """Stop the library scan or scrape that is already running. Waiting rows use drop."""
    with _guard:
        spec = dict(_running) if _running and str(_running.get("id")) == str(item_id) else None
    if not spec:
        return False
    kind = spec.get("kind") or ""
    media = spec.get("media") or "music"
    if kind == "move":
        if media == "music":
            from resonance import relocate as music_move

            return bool(music_move.cancel()) if hasattr(music_move, "cancel") else False
        from curator.video import relocate

        return bool(relocate.cancel()) if hasattr(relocate, "cancel") else False
    if kind == "scrape" or media == "sets" or kind == "sets":
        from curator.video import scrape

        return bool(scrape.cancel())
    if media == "music":
        from resonance import jobs

        return bool(jobs.request_cancel())
    from curator.video import scanner

    return bool(scanner.cancel())


def drop(item_id):
    """Remove one waiting library scan or scrape. The job that is already running stays."""
    global _active, _items
    with _guard:
        if _running and str(_running.get("id")) == str(item_id):
            return False
        kept = [item for item in _items if str(item.get("id")) != str(item_id)]
        if len(kept) == len(_items):
            return False
        _items = kept
        if not _items and not _busy() and not _running:
            _active = False
    _forget(item_id)
    return True


def restore():
    """A restart puts a scan that was running back in line, then starts the first waiting job."""
    global _active, _items, _running
    try:
        from resonance import db

        if db.pool is None:
            return
        db.execute("UPDATE work_queue SET status = 'queued' WHERE lane = 'scan' AND status = 'running'")
        rows = db.fetchall(
            """
            SELECT id::text AS id, payload FROM work_queue
            WHERE lane = 'scan' AND status = 'queued'
            ORDER BY created_at
            """
        )
    except Exception:
        logger.exception("could not restore the scan queue")
        return
    with _guard:
        _items = []
        _running = None
        for row in rows:
            spec = dict(row.get("payload") or {})
            spec["id"] = str(row["id"])
            _items.append(spec)
        _active = bool(_items) or _busy()
    if _items:
        finished()


def finished():
    """The job that held the gate has stopped. Webhook imports go next, then the next library job."""
    global _active, _running
    _release_running()
    if _busy():
        with _guard:
            waiting = bool(_items)
        if waiting:
            _arm_retry()
        return
    if _webhooks_first():
        with _guard:
            _active = False
        return
    with _guard:
        spec = _items.pop(0) if _items else None
        if not spec:
            _active = False
            return
        _active = True
    _stamp_running(spec)
    _persist(spec, "running")
    if _launch(spec):
        with _guard:
            _running = spec
        _note_scan(spec, "started")
        return
    _persist(spec, "queued")
    with _guard:
        _items.insert(0, spec)
    _arm_retry()


def _library_duplicate(spec):
    if spec.get("kind") == "move":
        for item in _items:
            if item.get("kind") != "move":
                continue
            if (
                item.get("media") == spec.get("media")
                and (item.get("dest") or "") == (spec.get("dest") or "")
                and list(item.get("ids") or []) == list(spec.get("ids") or [])
            ):
                return True
        return False
    if spec.get("kind") == "schedule":
        return False
    if spec.get("kind") == "scrape":
        for item in _items:
            if item.get("kind") != "scrape":
                continue
            if (
                item.get("media") == spec.get("media")
                and (item.get("scope") or "missing") == (spec.get("scope") or "missing")
                and list(item.get("ids") or []) == list(spec.get("ids") or [])
                and (item.get("policy") or "") == (spec.get("policy") or "")
                and bool(item.get("art_only")) == bool(spec.get("art_only"))
                and list(item.get("groups") or []) == list(spec.get("groups") or [])
                and list(item.get("fields") or []) == list(spec.get("fields") or [])
                and list(item.get("art") or []) == list(spec.get("art") or [])
                and (item.get("primary") or "") == (spec.get("primary") or "")
            ):
                return True
        return False
    for item in _items:
        if item.get("kind") in ("schedule", "scrape"):
            continue
        if (
            item.get("media") == spec.get("media")
            and (item.get("mode") or "incremental") == (spec.get("mode") or "incremental")
            and bool(item.get("force")) == bool(spec.get("force"))
            and list(item.get("roots") or []) == list(spec.get("roots") or [])
            and list(item.get("targets") or []) == list(spec.get("targets") or [])
            and list(item.get("albums") or []) == list(spec.get("albums") or [])
            and str(item.get("season_id") or "") == str(spec.get("season_id") or "")
            and str(item.get("episode_id") or "") == str(spec.get("episode_id") or "")
        ):
            return True
    return False


def _webhooks_first():
    """True when imported folders are due. They run before any library scan still waiting."""
    try:
        from curator import ingest

        if not ingest.due():
            return False
        ingest.wake()
        return True
    except Exception:
        logger.exception("could not check the webhook queue")
        return False


def _label(item):
    if item.get("label"):
        return item["label"]
    media = {"movies": "movie", "tv": "TV", "music": "music", "sets": "movie set"}.get(item.get("media") or "music", "library")
    kind = item.get("kind") or "library"
    if kind == "scrape" or item.get("media") == "sets" or kind == "sets":
        return f"{media[:1].upper()}{media[1:]} scrape"
    mode = {"full": "Full", "deep": "Deep", "incremental": "Incremental deep"}.get(item.get("mode") or "", "Incremental deep")
    albums = [path for path in (item.get("albums") or []) if path]
    if len(albums) == 1:
        folder = os.path.basename(albums[0].rstrip("/\\")) or albums[0]
        return f"{mode} music scan of {folder}"
    if albums:
        return f"{mode} music scan of {len(albums)} albums"
    targets = [path for path in (item.get("targets") or []) if path]
    if len(targets) == 1:
        return f"{mode} {media} scan of {os.path.basename(targets[0].rstrip('/')) or targets[0]}"
    if targets:
        return f"{mode} {media} scan of {len(targets)} folders"
    return f"{mode} {media} scan"


def _scrape_titles(item):
    """Names and folders for a queued scrape. Empty when this row is a library scan."""
    if (item.get("kind") or "") != "scrape":
        return []
    media = item.get("media") or "movies"
    nouns = {
        "movies": ("movie", "Movies"),
        "tv": ("TV show", "TV shows"),
        "episodes": ("episode", "Episodes"),
        "seasons": ("season", "Seasons"),
        "sets": ("movie set", "Movie sets"),
    }
    one, many = nouns.get(media, ("item", "Items"))
    ids = [str(value) for value in (item.get("ids") or []) if value]
    scope = item.get("scope") or "selected"
    if not ids:
        if scope == "missing":
            return [f"{many} still missing metadata"]
        if scope == "all":
            return [f"Every {one}"]
        return []
    try:
        from resonance import db

        if db.pool is None:
            return []
        rows = _scrape_rows(db, media, ids)
    except Exception:
        logger.exception("could not name the queued scrape")
        return []
    lines = [line for line in (_scrape_line(media, row) for row in rows) if line]
    missing = len(ids) - len(lines)
    if missing > 0:
        lines.append(f"{missing} more")
    return lines[:12]


def _scrape_rows(db, media, ids):
    wanted = db.uuid_array(ids)
    if media == "tv":
        return db.fetchall(
            "SELECT title, year, path AS place FROM tv_shows WHERE id = ANY(%s::uuid[])",
            (wanted,),
        )
    if media == "seasons":
        return db.fetchall(
            """
            SELECT sh.title AS show, sh.year, se.season_number,
                   COALESCE(NULLIF(se.path, ''), sh.path) AS place
            FROM tv_seasons se
            JOIN tv_shows sh ON sh.id = se.show_id
            WHERE se.id = ANY(%s::uuid[])
            """,
            (wanted,),
        )
    if media == "episodes":
        return db.fetchall(
            """
            SELECT sh.title AS show, ep.season_number, ep.episode_number, ep.title, ep.path AS place
            FROM tv_episodes ep
            JOIN tv_shows sh ON sh.id = ep.show_id
            WHERE ep.id = ANY(%s::uuid[])
            """,
            (wanted,),
        )
    if media == "sets":
        return db.fetchall(
            "SELECT name AS title FROM movie_sets WHERE id = ANY(%s::uuid[])",
            (wanted,),
        )
    return db.fetchall(
        """
        SELECT title, year, COALESCE(NULLIF(folder, ''), path) AS place
        FROM movies WHERE id = ANY(%s::uuid[])
        """,
        (wanted,),
    )


def _scrape_line(media, row):
    place = str(row.get("place") or "").strip()
    if media == "seasons":
        show = str(row.get("show") or "Show").strip()
        year = row.get("year")
        name = f"{show} ({year})" if year else show
        number = row.get("season_number")
        season = f"season {number}" if number or number == 0 else "season"
        text = f"{name} · {season}"
        return f"{text} — {place}" if place else text
    if media == "episodes":
        show = str(row.get("show") or "Show").strip()
        title = str(row.get("title") or "").strip()
        code = _episode_code(row.get("season_number"), row.get("episode_number"))
        text = " ".join(part for part in (show, code, title) if part)
        return f"{text} — {place}" if place else text
    title = str(row.get("title") or "Untitled").strip()
    year = row.get("year")
    name = f"{title} ({year})" if year else title
    return f"{name} — {place}" if place else name


def _episode_code(season, episode):
    try:
        return f"S{int(season):02d}E{int(episode):02d}"
    except (TypeError, ValueError):
        return ""


def _stamp_running(spec):
    from curator.queue_time import stamp

    spec["started_at"] = stamp()


def _running_seconds(item):
    from curator.queue_time import seconds_since

    return seconds_since(item.get("started_at"))


def _public(item):
    kind = item.get("kind") or "library"
    titles = _scrape_titles(item)
    return {
        "id": item.get("id") or "",
        "media": item.get("media") or "music",
        "mode": item.get("mode") or ("" if kind == "scrape" else "incremental"),
        "scope": item.get("scope") or "",
        "kind": kind,
        "label": _label(item),
        "roots": list(item.get("roots") or []),
        "targets": list(item.get("targets") or []),
        "titles": titles,
        "force": bool(item.get("force")),
    }


def _busy():
    from curator.video import files, scanner, scrape
    from resonance import jobs

    job = jobs.current_job() or {}
    if job.get("status") == "running":
        return True
    return bool(scanner.running() or scrape.running() or files.running())


def library_busy():
    """True only while a scan, scrape, or file job is actually running."""
    return _busy()


def busy():
    """True when a scan, scrape, or file job holds the library, or one is waiting."""
    with _guard:
        if _active or _items:
            return True
    return _busy()


def depth():
    """Place in line of the latest waiting job. The running job counts as number 1."""
    with _guard:
        waiting = len(_items)
    if waiting <= 0:
        return 1 if _busy() else 0
    return waiting + (1 if _busy() else 0)


def _launch(spec):
    if spec.get("kind") == "move":
        if spec.get("media") == "music":
            from resonance import relocate as music_move

            return music_move.start(spec.get("ids") or [], spec.get("dest") or "", spec.get("label") or "Move")
        from curator.video import relocate

        return relocate.start(spec.get("media"), spec.get("ids") or [], spec.get("dest") or "", spec.get("label") or "Move")
    if spec.get("kind") == "scrape":
        from curator.video import scrape

        return bool(scrape.start(
            spec.get("media"),
            spec.get("scope") or "missing",
            spec.get("ids") or None,
            spec.get("policy"),
            label=spec.get("label") or "Queued scrape",
            meta_policy=spec.get("meta_policy"),
            art_policy=spec.get("art_policy"),
            rewrite_nfo=spec.get("rewrite_nfo"),
            art_only=bool(spec.get("art_only")),
            release_queue=True,
            groups=spec.get("groups"),
            primary=spec.get("primary"),
            fields=spec.get("fields"),
            art=spec.get("art"),
            art_primary=spec.get("art_primary"),
        ))
    if spec.get("media") == "sets" or spec.get("kind") == "sets":
        from curator.video import scrape

        return bool(scrape.start("sets", "all", label="Set scrape", release_queue=True))
    if spec.get("kind") == "schedule":
        from resonance import jobs

        if not jobs.try_lock():
            return False
        threading.Thread(target=_run_schedule, args=(spec,), name="scheduled-scan", daemon=True).start()
        return True
    if (spec.get("media") or "music") == "music":
        from resonance import jobs

        _row, started = jobs.start_scan(
            force=bool(spec.get("force")),
            mode=spec.get("mode") or "incremental",
            roots=spec.get("roots") or None,
            verbose=bool(spec.get("verbose")),
            albums=spec.get("albums") or None,
            origin=spec.get("origin") or "manual",
        )
        return bool(started)
    from curator.video import scanner

    return bool(scanner.start(
        spec.get("media"),
        spec.get("mode") or "incremental",
        spec.get("roots") or [],
        spec.get("targets") or None,
        season_id=spec.get("season_id"),
        episode_id=spec.get("episode_id"),
        verbose=bool(spec.get("verbose")),
        origin=spec.get("origin") or "manual",
    ))


def _run_schedule(spec):
    from resonance import jobs
    from resonance.schedule import _locked_pass

    try:
        _locked_pass(spec.get("item") or {})
    finally:
        jobs.release_lock()
        finished()


def _arm_retry():
    global _retry_timer
    if _retry_timer:
        _retry_timer.cancel()
    _retry_timer = threading.Timer(2.0, _retry)
    _retry_timer.daemon = True
    _retry_timer.start()


def _retry():
    if _busy():
        return
    finished()


def _release_running():
    global _running
    with _guard:
        spec = _running
        _running = None
    if spec and spec.get("id"):
        _forget(spec["id"])
        _note_scan(spec, "done")


def _persist(spec, status):
    try:
        from psycopg.types.json import Jsonb
        from resonance import db

        if db.pool is None:
            return
        payload = {key: value for key, value in spec.items() if key != "id"}
        db.execute(
            """
            INSERT INTO work_queue (id, lane, kind, title, source, priority, status, payload)
            VALUES (%s, 'scan', %s, %s, 'curator', 10, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status = EXCLUDED.status, title = EXCLUDED.title, payload = EXCLUDED.payload
            """,
            (spec["id"], spec.get("kind") or "library", _label(spec)[:240], status, Jsonb(payload)),
        )
    except Exception:
        logger.exception("could not store the scan queue row")


def _forget(item_id):
    try:
        from resonance import db

        if db.pool is None or not item_id:
            return
        db.execute("DELETE FROM work_queue WHERE id = %s AND lane = 'scan'", (str(item_id),))
    except Exception:
        logger.exception("could not remove the scan queue row")


def _note_scan(spec, outcome):
    try:
        from curator import work_log

        paths = spec.get("targets") or spec.get("roots") or []
        work_log.note(
            "scan",
            "curator",
            spec.get("mode") or spec.get("kind") or "scan",
            _label(spec),
            ", ".join(str(path) for path in paths[:8]),
            outcome,
            spec.get("media") or "",
        )
    except Exception:
        logger.exception("could not record the scan")


def _forget_queued():
    try:
        from resonance import db

        if db.pool is None:
            return
        db.execute("DELETE FROM work_queue WHERE lane = 'scan' AND status = 'queued'")
    except Exception:
        logger.exception("could not clear the scan queue")
