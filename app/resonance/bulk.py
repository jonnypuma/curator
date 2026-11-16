"""Bulk album and artist actions from the music right-click menus, as one background job.

The page used to send one request per album, one after another, and wait for all of them. Now it starts one job: the
Jobs panel shows it with progress and a Stop button, a failure on one album is written to the log and the rest go on,
and the page reads the touched artists again when it ends. Each step calls the same function as the single-album
button. One bulk job runs at a time.
"""
from __future__ import annotations

import logging
import threading

from resonance import db, jobs, library
from resonance.errors import AppError

logger = logging.getLogger(__name__)

KIND = "album-bulk"
# action -> (what the job is called, noun of the items, done verb)
ACTIONS = {
    "apply": ("Apply matches", "album", "Applied"),
    "compilation": ("Treat as compilation", "album", "Treated as compilation"),
    "replaygain": ("Set ReplayGain", "album", "ReplayGain written"),
    "audit": ("Audit audio", "album", "Audited"),
    "gaps": ("Check missing tracks", "album", "Checked"),
    "artist-metadata": ("Find artist metadata", "artist", "Saved"),
}

_lock = threading.Lock()
_cancel = threading.Event()
_running = {"id": None}
# job id -> {"done": [ids], "failed": [ids]}, so the page knows which albums went through (the newest few jobs).
_results = {}


def running():
    return _running["id"]


def results(job_id):
    found = _results.get(str(job_id)) or {}
    return {"done": list(found.get("done") or []), "failed": list(found.get("failed") or [])}


def cancel():
    """Stop after the album being worked on now."""
    if _running["id"]:
        _cancel.set()
        return True
    return False


def start(action, ids, proposals=None):
    """Start the job. Returns (job row, started). started is False when another bulk job runs; its row comes back."""
    if action not in ACTIONS:
        raise AppError("Unknown bulk action", 400)
    items = list(dict.fromkeys(str(library.require_uuid(item)) for item in ids or [] if item))
    if not items:
        raise AppError("Select at least one item")
    proposals = {str(key): value for key, value in (proposals or {}).items()}
    if action == "apply":
        from resonance import settings

        steps = settings.apply_steps()
        if not any(step in {"tags", "nfo", "lyrics"} for step in steps):
            raise AppError("Turn on Tags, .nfo, or Lyrics in Settings")
        items = [item for item in items if isinstance(proposals.get(item), dict)]
        if not items:
            raise AppError("None of the selected albums has a loaded match")
    title, noun, _verb = ACTIONS[action]
    with _lock:
        if _running["id"]:
            return db.fetchone("SELECT * FROM work_jobs WHERE id = %s", (_running["id"],)), False
        row = jobs.begin_work(KIND, f"{title}: {len(items)} {noun}{'s' if len(items) != 1 else ''}", len(items))
        _running["id"] = row["id"]
        _cancel.clear()
    threading.Thread(target=_run, args=(row["id"], action, items, proposals), name=KIND, daemon=True).start()
    row = dict(row)
    row["ids"] = items
    return row, True


def _label(action, item_id):
    if ACTIONS[action][1] == "artist":
        row = db.fetchone("SELECT name FROM artists WHERE id = %s", (item_id,))
        return (row or {}).get("name") or "Artist"
    row = db.fetchone(
        "SELECT ar.name AS artist, al.title FROM albums al LEFT JOIN artists ar ON ar.id = al.artist_id WHERE al.id = %s",
        (item_id,),
    )
    if not row:
        return "Album"
    return " — ".join(part for part in (row.get("artist"), row.get("title")) if part) or "Album"


def _one(action, item_id, proposals, broken):
    """Do the action for one item. Returns a short note for the log."""
    if action == "apply":
        from resonance import match, settings

        result = match.apply(item_id, proposals[item_id], steps=settings.apply_steps())
        warnings = [text for text in (result or {}).get("warnings") or [] if text]
        return warnings[0] if warnings else ""
    if action == "compilation":
        library.treat_compilation(item_id, True)
        return ""
    if action == "replaygain":
        from resonance import gain

        return "; ".join(gain.album_lines(item_id, record=False))
    if action == "audit":
        from resonance import audit

        found = audit.check_album(item_id)
        broken.extend(found)
        return f"{len(found)} corrupt" if found else ""
    if action == "gaps":
        from resonance import gaps

        result = gaps.refresh(item_id) or {}
        missing = len(result.get("missing") or [])
        return f"{missing} missing" if missing else ""
    if action == "artist-metadata":
        from resonance import profile

        data = profile.scrape(item_id) or {}
        profile.save_biography(item_id, data.get("biography") or "", data.get("fields") or {}, only_if_longer=True)
        return ""
    raise AppError("Unknown bulk action")


def _run(job_id, action, items, proposals):
    title, _noun, verb = ACTIONS[action]
    lines, done, failed, broken = [], 0, 0, []
    outcome = {"done": [], "failed": []}
    _results[str(job_id)] = outcome
    for old in list(_results)[:-10]:
        _results.pop(old, None)
    stopped = False
    try:
        for index, item_id in enumerate(items, start=1):
            if _cancel.is_set():
                stopped = True
                break
            label = _label(action, item_id)
            jobs.touch_work(job_id, index - 1, f"{title}: {label} ({index} of {len(items)})", "\n".join(lines[-200:]))
            try:
                note = _one(action, item_id, proposals, broken)
                done += 1
                outcome["done"].append(item_id)
                lines.append(f"{verb} — {label}" + (f" — {note}" if note else ""))
            except Exception as exc:     # one album must not stop the rest
                failed += 1
                outcome["failed"].append(item_id)
                logger.info("bulk %s failed for %s: %s", action, item_id, exc)
                lines.append(f"Failed — {label} — {exc}")
        if action == "audit" and broken:
            from resonance import audit

            audit._report_corrupt(broken)
        summary = f"{title}: {done} done" + (f", {failed} failed" if failed else "") + (", stopped" if stopped else "")
        status = "cancelled" if stopped else ("failed" if failed and not done else "completed")
        jobs.finish_work(job_id, status, summary, done + failed, "\n".join(lines[-500:]))
    except Exception as exc:
        logger.exception("bulk %s failed", action)
        jobs.finish_work(job_id, "failed", str(exc)[:300], log="\n".join(lines[-500:]))
    finally:
        with _lock:
            _running["id"] = None
            _cancel.clear()
