"""The webhook queue: Radarr, Sonarr, Bazarr and Lidarr events wait here, then Curator scans only those folders.

Every event for a folder restarts the debounce timer (sliding). The maximum postpone limit, counted from
the oldest waiting event, forces a run during a long download queue. The queue lives in Postgres, so it
survives a restart; a run that was cut short goes back into the queue.

When the timer runs out during a music, movie, or TV library scan, that scan pauses at the next folder,
these imports run, and the library scan resumes. A scrape, file job, or database restore still waits.
Targeted movie and TV scans, a scrape of what they found (if turned on), and Lidarr albums run here.
When that work finishes, one Kodi update is placed at the front of the ARR queue and the import
row is removed. The next import does not wait for Kodi.
"""
from __future__ import annotations

import logging
import os
import posixpath
import re
import threading
import time

from psycopg.types.json import Jsonb

from curator import arr_hooks, automation, folders, notify
from resonance import db
from resonance.paths import inside

logger = logging.getLogger(__name__)
EVENT_LIMIT = 1000

_stop = threading.Event()
_wake = threading.Event()
_abort_guard = threading.Lock()
_abort = set()
_current = {"media": "", "paths": set(), "ids": set()}
_thread = None
_emit = None
_state = {"running": False, "message": "", "waiting": ""}
_cache = {"count": 0, "titles": [], "deadline": 0.0, "refreshed": 0.0, "debounce": 0, "postpone": 0, "forced": False}
_cache_lock = threading.Lock()


def set_emitter(callback):
    global _emit
    _emit = callback


def _send(kind, data):
    if _emit:
        try:
            _emit(kind, data)
        except Exception:
            logger.exception("queue event %s failed", kind)


# Accepting webhooks.

def accept(payload):
    auto, _ = automation.current()
    from curator.video import store

    parsed = arr_hooks.parse(payload, auto["path_mappings"], find=store.find_title)
    source, event = parsed["source"], parsed["event"]
    if parsed["note"] == "lidarr-note":
        from resonance import lidarr

        if not automation.integration_on("lidarr"):
            _event(source, event, _lidarr_label(payload), "", "ignored", "Lidarr is turned off under Settings, Integrations")
            return {"status": "ignored", "reason": "Lidarr is turned off under Settings, Integrations"}
        lidarr.accept(payload)
        _event(source, event, _lidarr_label(payload), "", "noted", "Recorded in the Lidarr activity feed")
        return {"status": "noted"}
    if not parsed["items"]:
        outcome = "test" if event == "Test" else "ignored"
        _event(source, event, parsed.get("label") or "", "", outcome, parsed["note"])
        return {"status": outcome, "reason": parsed["note"]}
    if source in automation.LABELS and not automation.integration_on(source):
        reason = f"{automation.LABELS[source]} is turned off under Settings, Integrations"
        for item in parsed["items"]:
            _event(source, event, item["title"], item["path"], "ignored", reason)
        return {"status": "ignored", "reason": reason}
    if source in automation.LABELS and not automation.integration_on(source, scan=True):
        reason = f"Scan on import is turned off for {automation.LABELS[source]}"
        for item in parsed["items"]:
            _event(source, event, item["title"], item["path"], "noted", reason)
        return {"status": "noted", "reason": reason}
    if not auto["enabled"]:
        for item in parsed["items"]:
            _event(source, event, item["title"], item["path"], "ignored", "The webhook queue is turned off")
        return {"status": "ignored", "reason": "The webhook queue is turned off under Settings > Automation"}
    queued, errors = [], []
    for item in parsed["items"]:
        resolved, error = resolve(item, auto)
        if error:
            errors.append(error)
            _event(source, event, item["title"], item["path"], "unmapped", error)
            continue
        _upsert(resolved)
        _event(source, event, resolved["title"], resolved["path"], "queued", "")
        queued.append(resolved["title"])
    refresh()
    for title in queued:
        _send("ITEM_ENQUEUED", {"title": title, "source": source, "event": event})
    return {"status": "queued" if queued else "ignored", "queued": queued, "errors": errors,
            "debounce_minutes": auto["debounce_minutes"]}


def _lidarr_label(payload):
    artist = ((payload or {}).get("artist") or {}).get("name") or ""
    album = ((payload or {}).get("album") or {}).get("title") or ""
    return " — ".join(part for part in (artist, album) if part)


def _root_for(path, kind):
    best = None
    for root in folders.mounted(kind):
        if path == root or inside(root, path):
            if best is None or len(root) > len(best):
                best = root
    return best


def resolve(item, auto):
    """Work out the library, library folder and target folder for one parsed item. Returns (item, error)."""
    path = os.path.normpath(item["path"]) if item["path"] else ""
    if item["media"] == "music":
        if not auto["music"]:
            return None, "Music webhooks are turned off under Settings > Automation"
        from resonance import lidarr

        body = {"trackFiles": [{"path": path} for path in item["files"]],
                "artist": {"name": item["title"].split(" — ")[0]},
                "album": {"title": item["title"].split(" — ")[-1]}}
        album, artist, label, error = lidarr.locate(body)
        if error:
            return None, error
        return {**item, "path": album, "title": label or item["title"], "key": f"music:{album}",
                "extra": {**item["extra"], "artist": artist, "label": label}}, None
    if not path:
        return None, "The webhook did not include a folder"
    kind = folders.owner(path)
    if kind not in ("movies", "tv"):
        return None, (f"{path} is not inside a movie or TV folder. Check the library folders, or add a remote "
                      "path mapping under Settings > General.")
    root = _root_for(os.path.realpath(path), kind) or _root_for(path, kind)
    if not root:
        return None, f"{path} is not inside a mounted {kind} folder"
    real = os.path.realpath(path)
    if kind == "movies":
        target = os.path.dirname(real) if os.path.isfile(real) else real
    else:
        relative = os.path.relpath(real, root)
        target = root if relative in (".", "") else os.path.join(root, relative.split(os.sep)[0])
    return {**item, "media": kind, "path": target, "key": f"{kind}:{target}",
            "extra": {**item["extra"], "root": root}}, None


_EPISODE_CODE = re.compile(r"S\d{2,4}E\d{2,4}", re.I)


def _merge_titles(previous, incoming):
    """Keep every episode named on a show folder when a later webhook updates the same queue row."""
    previous = str(previous or "").strip()
    incoming = str(incoming or "").strip()
    if not previous or previous == incoming:
        return incoming or previous
    old_base, old_codes = _episode_title(previous)
    new_base, new_codes = _episode_title(incoming)
    if old_base and old_base.lower() == new_base.lower() and (old_codes or new_codes):
        codes = sorted({*old_codes, *new_codes})
        return f"{new_base} {', '.join(codes)}" if codes else new_base
    if incoming in previous:
        return previous
    if previous in incoming:
        return incoming
    return incoming


def _episode_title(title):
    codes = [code.upper() for code in _EPISODE_CODE.findall(title)]
    base = _EPISODE_CODE.sub("", title) if codes else title
    base = re.sub(r"(?:\s*[,–\-]+\s*)+$", "", base).strip(" ,–-")
    base = re.sub(r"(\(\d{4}\))\s+\1\b", r"\1", base)
    return base, codes


def _upsert(item):
    current = db.fetchone("SELECT title FROM ingest_queue WHERE key = %s", (item["key"],))
    if current and current.get("title"):
        item = {**item, "title": _merge_titles(current["title"], item["title"])}
    db.execute(
        """
        INSERT INTO ingest_queue (key, media, source, event_type, title, path, files, removed, extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (key) DO UPDATE SET
            events = ingest_queue.events + 1,
            first_at = CASE WHEN ingest_queue.status = 'running' THEN LOCALTIMESTAMP ELSE ingest_queue.first_at END,
            last_at = LOCALTIMESTAMP,
            status = 'queued',
            source = EXCLUDED.source,
            event_type = EXCLUDED.event_type,
            title = COALESCE(NULLIF(EXCLUDED.title, ''), ingest_queue.title),
            files = ARRAY(SELECT DISTINCT unnest(ingest_queue.files || EXCLUDED.files)),
            removed = ingest_queue.removed OR EXCLUDED.removed,
            extra = ingest_queue.extra || EXCLUDED.extra
        """,
        (item["key"], item["media"], item["source"], item["event"], item["title"][:300], item["path"],
         item["files"][:200], item["removed"], Jsonb(item["extra"])),
    )


def _event(source, event, title, path, outcome, message):
    try:
        db.execute(
            "INSERT INTO ingest_events (source, event_type, title, path, outcome, message) VALUES (%s, %s, %s, %s, %s, %s)",
            (str(source or "")[:20], str(event or "")[:100], str(title or "")[:300], str(path or "")[:1000],
             outcome, str(message or "")[:2000]),
        )
    except Exception:
        logger.exception("could not record the webhook event")
    _send("QUEUE_EVENT", {"source": source, "event": event, "title": title, "outcome": outcome, "message": message})


# Timer.

def refresh():
    """Read the queue size and the time left from the database into the cache the ticker reads."""
    auto, _ = automation.current()
    row = db.fetchone(
        """
        SELECT count(*)::int AS n,
               EXTRACT(EPOCH FROM (LEAST(max(last_at) + make_interval(mins => %s::int),
                                         min(first_at) + make_interval(mins => %s::int)) - LOCALTIMESTAMP))::float AS remaining
        FROM ingest_queue WHERE status = 'queued'
        """,
        (auto["debounce_minutes"], auto["max_postpone_minutes"]),
    ) or {}
    titles = [item["title"] for item in db.fetchall(
        "SELECT title FROM ingest_queue WHERE status = 'queued' ORDER BY last_at DESC LIMIT 20"
    )]
    with _cache_lock:
        count = row.get("n") or 0
        # A forced flush survives the next database refresh; otherwise the refresh puts the old timer back.
        if not count:
            _cache["forced"] = False
        remaining = 0.0 if _cache.get("forced") else float(row.get("remaining") or 0)
        _cache.update({
            "count": count, "titles": titles, "refreshed": time.monotonic(),
            "deadline": time.monotonic() + remaining,
            "debounce": auto["debounce_minutes"], "postpone": auto["max_postpone_minutes"],
        })


def due():
    """True when imported folders have finished their wait and a batch is not already running."""
    if _state["running"]:
        return False
    if time.monotonic() - _cache["refreshed"] > 15:
        refresh()
    with _cache_lock:
        return bool(_cache["count"]) and time.monotonic() >= _cache["deadline"]


def wake():
    """Ask the queue thread to look again. A finished library scan uses this once."""
    _wake.set()


def snapshot():
    from resonance import scan_queue

    scans = scan_queue.snapshot()
    # Do the DB call outside the lock to avoid holding _cache_lock during a potentially slow query.
    try:
        _running_row = db.fetchone("SELECT count(*)::int AS n FROM ingest_queue WHERE status = 'running'")
        running_items = _running_row["n"] if _running_row else 0
    except Exception:
        running_items = 0
    with _cache_lock:
        count = _cache["count"]
        remaining = max(0, int(round(_cache["deadline"] - time.monotonic()))) if count else 0
        message = _state["message"] or _state["waiting"]
        return {
            "scans": scans,
            "active": bool(count) or _state["running"] or bool(running_items),
            "queued_items_count": count,
            "running_items": running_items,
            "remaining_seconds": remaining,
            "total_debounce_seconds": _cache["debounce"] * 60,
            "max_postpone_seconds": _cache["postpone"] * 60,
            "queued_titles": list(_cache["titles"]),
            "running": _state["running"],
            "library_busy": scan_queue.library_busy(),
            "message": message,
        }


def force_flush():
    from resonance import scan_queue
    from resonance.errors import AppError

    if scan_queue.library_busy():
        raise AppError("A scan is already running. Force scan now is available when it finishes.", 409)
    with _cache_lock:
        if not _cache["count"]:
            return False
        _cache["deadline"] = 0.0
        _cache["forced"] = True
    wake()
    return True


def clear():
    rows = db.fetchall("DELETE FROM ingest_queue WHERE status = 'queued' RETURNING id")
    if rows:
        _event("curator", "Clear", f"{len(rows)} imports", "", "cleared", "Cleared from the web UI")
    refresh()
    return {"cleared": len(rows)}


def complete_running(ids):
    """Remove rows whose Kodi scan has finished. The queue panel hears about it."""
    ids = [str(item) for item in ids or [] if item]
    if not ids:
        return 0
    rows = db.fetchall(
        "DELETE FROM ingest_queue WHERE id = ANY(%s::uuid[]) AND status = 'running' RETURNING id",
        (ids,),
    )
    if rows:
        refresh()
        _send("QUEUE_FLUSH", {"state": "updated", "count": len(rows)})
    return len(rows)


def drop(item_id):
    row = db.fetchone("DELETE FROM ingest_queue WHERE id = %s AND status = 'queued' RETURNING title", (item_id,))
    refresh()
    return bool(row)


def cancel(item_id):
    """Stop one running import. Other folders in the same batch keep going."""
    row = db.fetchone(
        "SELECT id::text AS id, media, path, title, status FROM ingest_queue WHERE id = %s",
        (str(item_id),),
    )
    if not row:
        return None
    if row["status"] == "queued":
        return "queued" if drop(str(row["id"])) else None
    if row["status"] != "running":
        return None
    with _abort_guard:
        _abort.add(str(row["id"]))
    _stop_current(row["media"], row["path"])
    _event("curator", "Cancel", row.get("title") or row.get("path") or "Import", row.get("path") or "", "cleared", "Stopped from the queue")
    return "running"


def _aborted(item_id):
    with _abort_guard:
        return str(item_id) in _abort


def _live(rows):
    return [row for row in rows if not _aborted(row["id"])]


def _current_stopped():
    with _abort_guard:
        return bool(_current["ids"] & _abort)


def _stop_current(media, path):
    """Stop the scan or scrape that is working on this folder."""
    current = _current["media"]
    paths = _current["paths"]
    if current != media:
        return
    if paths and path and path not in paths and not any(inside(folder, path) or inside(path, folder) for folder in paths):
        return
    if media == "music":
        return
    from curator.video import scanner, scrape

    if not scanner.cancel_import() and scrape.running():
        scrape.cancel()


def items():
    rows = db.fetchall(
        """
        SELECT id, media, source, event_type, title, path, removed, events, status, first_at, last_at, started_at
        FROM ingest_queue ORDER BY status = 'running' DESC, last_at DESC
        """
    )
    cleaned = []
    for row in rows:
        item = db.clean(dict(row))
        if item.get("status") == "running":
            from curator.queue_time import seconds_since

            item["running_seconds"] = seconds_since(row.get("started_at"))
        cleaned.append(item)
    return cleaned


def recent(limit=100):
    rows = db.fetchall("SELECT * FROM ingest_events ORDER BY received_at DESC LIMIT %s", (int(limit),))
    return [db.clean(dict(row)) for row in rows]


# Worker.

def start():
    global _thread
    db.execute("UPDATE ingest_queue SET status = 'queued', started_at = NULL WHERE status = 'running'")
    refresh()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="webhook-queue", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    _wake.set()


def queue_running():
    return bool(_state.get("running"))


def _loop():
    while not _stop.is_set():
        blocked = False
        try:
            if time.monotonic() - _cache["refreshed"] > 15:
                refresh()
            if due():
                blocked = _when_due()
        except Exception:
            logger.exception("webhook queue loop failed")
            _state["running"] = False
        _wake.clear()
        triggered = _wake.wait(2 if blocked else 1)
        if triggered:
            _wake.clear()


def _when_due():
    """Run the queue, pausing a library scan when one is in the way. True when this loop should wait."""
    from curator.video import files, scanner, scrape
    from resonance import backup, jobs, scan_queue

    if backup.restoring():
        _state["waiting"] = "Waiting for the database restore to finish"
        return True
    if jobs.library_active() or scanner.library_active():
        if _stop.is_set():
            return True
        if _interrupt_scan():
            return False
        if _stop.is_set():
            return True
    if files.running() or scrape.running() or scan_queue.library_busy():
        _state["waiting"] = "Waiting for the running scan, scrape or file job to finish"
        return True
    _state["waiting"] = ""
    run()
    return False


def _interrupt_scan():
    """Pause the library scan, run the imports, then let the scan continue."""
    from curator.video import scanner
    from resonance import jobs

    _state["waiting"] = "Pausing the library scan for queued imports"
    asked = False
    if jobs.library_active():
        asked = jobs.request_pause() or asked
    if scanner.library_active():
        asked = scanner.request_pause() or asked
    if not asked:
        return False
    logger.info("pausing the library scan for queued imports")
    if not _wait_parked():
        return False
    jobs.begin_import()
    scanner.begin_import()
    try:
        _state["waiting"] = ""
        run(interrupt=True)
    finally:
        jobs.finish_import()
        scanner.finish_import()
    return True


def _wait_parked():
    from curator.video import scanner
    from resonance import jobs

    while not _stop.is_set():
        music = jobs.library_active()
        video = scanner.library_active()
        if not music and not video:
            return False
        if (not music or jobs.paused()) and (not video or scanner.paused()):
            return True
        _stop.wait(0.4)
    return False


def _claim():
    rows = db.fetchall(
        "UPDATE ingest_queue SET status = 'running', started_at = LOCALTIMESTAMP WHERE status = 'queued' RETURNING *"
    )
    return [dict(row) for row in rows]


def run(interrupt=False):
    """Process every imported folder that is waiting.

    interrupt means a library scan is paused and still owns the gate, so this batch must not
    take or release that gate.
    """
    from resonance import scan_queue

    if not interrupt and not scan_queue.hold():
        _state["waiting"] = "Waiting for the running scan, scrape or file job to finish"
        return
    rows = _claim()
    if not rows:
        refresh()
        if not interrupt:
            scan_queue.finished()
        return
    _state.update({"running": True, "message": f"Processing {len(rows)} queued items"})
    refresh()
    _send("QUEUE_FLUSH", {"state": "started", "count": len(rows)})
    auto, _ = automation.current()
    summary = []
    done = False
    ids = [str(row["id"]) for row in rows]
    try:
        for media in ("movies", "tv"):
            group = _live([row for row in rows if row["media"] == media])
            if group:
                summary.append(_video(media, group, auto, interrupt))
        music = _live([row for row in rows if row["media"] == "music"])
        if music:
            summary.append(_music(music, interrupt))
        message = "; ".join(part for part in summary if part) or "Nothing to do"
        _event("curator", "Run", f"{len(rows)} queued items", "", "done", message)
        done = True
    except Exception as exc:
        logger.exception("webhook queue run failed")
        _event("curator", "Run", f"{len(rows)} queued items", "", "error", str(exc))
        message = str(exc)
    finally:
        if done:
            db.execute("DELETE FROM ingest_queue WHERE id = ANY(%s::uuid[]) AND status = 'running'", (ids,))
        elif ids:
            db.execute("UPDATE ingest_queue SET status = 'queued' WHERE id = ANY(%s::uuid[]) AND status = 'running'", (ids,))
        db.execute(
            "DELETE FROM ingest_events WHERE id IN (SELECT id FROM ingest_events ORDER BY received_at DESC OFFSET %s)",
            (EVENT_LIMIT,),
        )
        _state.update({"running": False, "message": ""})
        _current.update({"media": "", "paths": set(), "ids": set()})
        with _abort_guard:
            _abort.clear()
        refresh()
        if not interrupt:
            scan_queue.finished()
    _send("QUEUE_FLUSH", {"state": "finished", "count": len(rows), "message": message})


def _video(media, group, auto, interrupt=False):
    from curator.video import scanner, store

    noun = "movie" if media == "movies" else "show"
    by_root = {}
    for row in group:
        by_root.setdefault((row.get("extra") or {}).get("root") or "", []).append(row)
    scanned, scraped = 0, 0
    for root, started in by_root.items():
        rows = _live(started)
        if not root or not rows:
            continue
        targets = sorted({row["path"] for row in rows})
        _current.update({"media": media, "paths": set(targets), "ids": {str(row["id"]) for row in started}})
        _state["message"] = f"Scanning {len(targets)} {noun} folder{'s' if len(targets) != 1 else ''}"
        result = None
        while not _stop.is_set():
            result = scanner.run_targeted(media, root, targets, held=True, interrupt=interrupt)
            if result is not None:
                break
            if interrupt:
                raise RuntimeError("The queued folders could not be scanned while the library scan is paused")
            _state["message"] = "Waiting for the running scan to finish"
            _stop.wait(60)
        if result is None:
            raise RuntimeError("The queue is waiting for the scan to finish")
        scanned += len(targets)
        if _current_stopped() or (result or {}).get("status") == "cancelled":
            db.execute(
                "DELETE FROM ingest_queue WHERE id = ANY(%s::uuid[]) AND status = 'running'",
                ([str(row["id"]) for row in started],),
            )
            continue
        present = [target for target in targets if os.path.isdir(target)]
        wanted = auto["scrape_movies"] if media == "movies" else auto["scrape_tv"]
        found = store.ids_under(media, present) if present else []
        ep_ids = []
        if media == "tv":
            files = [f for r in rows for f in (r.get("files") or []) if f]
            if files:
                ep_rows = db.fetchall(
                    "SELECT id::text AS id FROM tv_episodes WHERE path = ANY(%s)",
                    (files,),
                )
                ep_ids = [str(r["id"]) for r in ep_rows if r.get("id")]
        if ep_ids and wanted:
            _state["message"] = f"Scraping {len(ep_ids)} episode{'s' if len(ep_ids) != 1 else ''}"
            _scrape("episodes", ep_ids)
            scraped += len(ep_ids)
        elif found and wanted:
            _state["message"] = f"Scraping {len(found)} {noun}{'s' if len(found) != 1 else ''}"
            _scrape(media, found)
            scraped += len(found)
        if ep_ids:
            _file_jobs(media, found, ep_ids=ep_ids)
        elif found:
            _file_jobs(media, found)
        titles = [row["title"] for row in rows if row.get("title")]
        notify.request("video", folders=targets, clean=any(owes_clean(row) for row in rows),
                       message=_message(rows, titles), front=True, media=media, items=titles)
        db.execute(
            "DELETE FROM ingest_queue WHERE id = ANY(%s::uuid[]) AND status = 'running'",
            ([str(row["id"]) for row in rows],),
        )
    text = f"{scanned} {noun} folder{'s' if scanned != 1 else ''} scanned"
    return text + (f", {scraped} scraped" if scraped else "")


def _file_jobs(media, ids, ep_ids=None):
    """Subtitle clean-up and trailer downloads for freshly imported items, when switched on."""
    from curator.video import config, files

    cfg = config.current()
    kind = "movie" if media == "movies" else "show"
    target_kind = "episode" if (media == "tv" and ep_ids) else kind
    target_ids = ep_ids if (media == "tv" and ep_ids) else ids
    jobs = []
    if cfg["sub_on_webhook"]:
        jobs.append("subtitles")
    if cfg["trailer_on_webhook"] and media == "movies":
        jobs.append("trailers")
    for op in jobs:
        _state["message"] = f"{files.OPS[op]} for {len(target_ids)} {target_kind}{'s' if len(target_ids) != 1 else ''}"
        for item_id in target_ids:
            try:
                files.run_now(op, target_kind, [item_id], log=lambda line: logger.info("webhook %s: %s", op, line))
            except Exception as exc:
                logger.warning("webhook %s failed for %s: %s", op, item_id, exc)
    if cfg.get("trailer_on_sonarr_season") and media == "tv" and (ep_ids or ids):
        _season_trailers(files, ids, ep_ids)
    if cfg.get("theme_on_webhook") and ids:
        _state["message"] = f"{files.OPS['themes']} for {len(ids)} {kind}{'s' if len(ids) != 1 else ''}"
        for item_id in ids:
            try:
                files.run_now("themes", kind, [item_id], log=lambda line: logger.info("webhook themes: %s", line))
            except Exception as exc:
                logger.warning("webhook themes failed for %s: %s", item_id, exc)


def _season_trailers(files, show_ids, ep_ids):
    """Download a trailer for every season that just received episodes (or, without episode ids,
    every season of the imported shows). A season that already has a good enough trailer is skipped
    by the download itself."""
    if ep_ids:
        rows = db.fetchall(
            "SELECT DISTINCT s.id::text AS id FROM tv_seasons s JOIN tv_episodes e "
            "ON e.show_id = s.show_id AND e.season_number = s.season_number "
            "WHERE e.id = ANY(%s::uuid[])", (list(ep_ids),))
    else:
        rows = db.fetchall(
            "SELECT id::text AS id FROM tv_seasons WHERE show_id = ANY(%s::uuid[])", (list(show_ids),))
    season_ids = [row["id"] for row in rows if row.get("id")]
    if not season_ids:
        return
    _state["message"] = f"Downloading trailers for {len(season_ids)} season{'s' if len(season_ids) != 1 else ''}"
    for season_id in season_ids:
        try:
            files.run_now("trailers", "season", [season_id], log=lambda line: logger.info("webhook season trailer: %s", line))
        except Exception as exc:
            logger.warning("webhook season trailer failed for %s: %s", season_id, exc)


def owes_clean(row):
    """A delete, or an upgrade that replaced a file, leaves the player's old entry behind until the player is cleaned.

    A removal reads "Removed: ..." in the notice; an upgrade still reads "Updated: ...", so it is kept apart from removed.
    """
    return bool(row.get("removed") or (row.get("extra") or {}).get("replaced"))


def _message(rows, titles):
    removed = all(row.get("removed") for row in rows)
    verb = "Removed" if removed else "Updated"
    shown = ", ".join(titles[:3]) + (f" and {len(titles) - 3} more" if len(titles) > 3 else "")
    return f"{verb}: {shown}" if shown else None


def _scrape(media, ids):
    from curator.video import scrape

    for _ in range(720):
        if scrape.start(media, "selected", ids, None, label="webhook"):
            break
        time.sleep(5)
    else:
        logger.warning("webhook scrape skipped: another scrape kept running")
        return
    while scrape.running():
        if _current_stopped():
            scrape.cancel()
            break
        time.sleep(2)


def _music(rows, interrupt=False):
    from resonance import jobs

    scanned = 0
    targets = {row["path"] for row in rows if row.get("path")}
    _current.update({"media": "music", "paths": set(targets), "ids": {str(row["id"]) for row in rows}})
    for row in rows:
        if _aborted(row["id"]) or _current_stopped():
            continue
        if row.get("removed"):
            continue
        path = row.get("path")
        if not path or not os.path.isdir(path):
            continue
        extra = row.get("extra") or {}
        artist = extra.get("artist") or (posixpath.dirname(path) if path else "") or path
        label = extra.get("label") or row.get("title") or os.path.basename(path.rstrip("/\\"))
        _state["message"] = f"Scanning {label}"
        try:
            jobs.scan_lidarr_now(path, artist, label)
            scanned += 1
        except Exception as exc:
            logger.warning("lidarr scan failed for %s: %s", path, exc)
    if not _current_stopped():
        titles = [row["title"] for row in rows if row.get("title")]
        folders = []
        for row in rows:
            extra = row.get("extra") or {}
            artist_folder = extra.get("artist") or (posixpath.dirname(row["path"]) if row.get("path") else None)
            folder = artist_folder or row.get("path")
            if folder and folder not in folders:
                folders.append(folder)
        notify.request("music", folders=folders, clean=any(row.get("removed") for row in rows),
                       message=_message(rows, titles), front=True, items=titles)
    db.execute(
        "DELETE FROM ingest_queue WHERE id = ANY(%s::uuid[]) AND status = 'running'",
        ([str(row["id"]) for row in rows],),
    )
    return f"{scanned} album{'s' if scanned != 1 else ''} scanned"
