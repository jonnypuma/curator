"""How long each scan stage takes.

A running scan keeps the clock for the stage on screen. A finished scan adds that
time to the saved average, so the next scan can allow for stages that have not started.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_guard = threading.Lock()
_media = ""
_phase = ""
_mark = 0.0
_wall = ""
_processed = 0
_total = 0
_done = {}
_history = {}


def begin(media, phase):
    """Start a scan. Drops the clock from the scan that finished before this one."""
    global _media, _phase, _mark, _wall, _processed, _total, _done, _history
    with _guard:
        _media = str(media or "")
        _phase = ""
        _processed = 0
        _total = 0
        _done = {}
        _history = _load(_media)
        _open(phase)


def note(phase=None, processed=None, total=None):
    """Record progress. A new stage name closes the previous stage's clock."""
    global _processed, _total
    with _guard:
        if phase and phase != _phase and phase != "done":
            _close()
            _open(phase)
        if processed is not None:
            _processed = int(processed or 0)
        if total is not None:
            _total = int(total or 0)


def finish(save):
    """Close the stage on screen. A completed scan stores each stage's time."""
    with _guard:
        _close()
        done = {key: dict(value) for key, value in _done.items()}
        media = _media
        _phase_clear()
    if save and media and done:
        _store(media, done)


def snapshot():
    with _guard:
        return {
            "phase_started_at": _wall,
            "done": {key: dict(value) for key, value in _done.items()},
            "history": {key: dict(value) for key, value in _history.items()},
        }


def _open(phase):
    global _phase, _mark, _wall, _processed, _total
    _phase = str(phase or "")
    _mark = time.monotonic()
    _wall = datetime.now().isoformat(timespec="seconds")
    _processed = 0
    _total = 0


def _close():
    if not _phase:
        return
    seconds = max(0.0, time.monotonic() - _mark)
    items = _total or _processed or 0
    if seconds < 0.05 and not items:
        return
    _done[_phase] = {"seconds": round(seconds, 1), "items": int(items)}


def _phase_clear():
    global _phase
    _phase = ""


def _load(media):
    if not media:
        return {}
    try:
        from resonance import db

        if db.pool is None:
            return {}
        rows = db.fetchall(
            """
            SELECT phase, runs, items, seconds, last_items, last_seconds
            FROM scan_phase_stats
            WHERE media = %s
            """,
            (media,),
        )
    except Exception:
        logger.exception("could not read scan stage times")
        return {}
    found = {}
    for row in rows or []:
        runs = int(row.get("runs") or 0)
        items = int(row.get("items") or 0)
        seconds = float(row.get("seconds") or 0)
        found[row.get("phase") or ""] = {
            "avg_seconds": round(seconds / runs, 1) if runs else 0,
            "seconds_per_item": round(seconds / items, 3) if items else 0,
            "last_items": int(row.get("last_items") or 0),
            "last_seconds": float(row.get("last_seconds") or 0),
        }
    found.pop("", None)
    return found


def _store(media, done):
    try:
        from resonance import db

        if db.pool is None:
            return
        for phase, row in done.items():
            seconds = float(row.get("seconds") or 0)
            items = int(row.get("items") or 0)
            if not phase or seconds <= 0:
                continue
            db.execute(
                """
                INSERT INTO scan_phase_stats (media, phase, runs, items, seconds, last_items, last_seconds)
                VALUES (%s, %s, 1, %s, %s, %s, %s)
                ON CONFLICT (media, phase) DO UPDATE
                    SET runs = scan_phase_stats.runs + 1,
                        items = scan_phase_stats.items + EXCLUDED.items,
                        seconds = scan_phase_stats.seconds + EXCLUDED.seconds,
                        last_items = EXCLUDED.last_items,
                        last_seconds = EXCLUDED.last_seconds
                """,
                (media, phase, items, seconds, items, seconds),
            )
    except Exception:
        logger.exception("could not store scan stage times")
