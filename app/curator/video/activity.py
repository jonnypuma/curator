"""Items a scan, scrape, or file job is using right now.

A delete or remove is allowed while a job runs. It is refused only for an item the job is
currently writing, or for a show or season whose episode the job is currently writing.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.Lock()
_items = {}
_shows = {}
_seasons = {}


def _bump(table, key, step):
    if not key:
        return
    key = str(key)
    count = table.get(key, 0) + step
    if count <= 0:
        table.pop(key, None)
    else:
        table[key] = count


def hold(item_id, show_id=None, season_id=None):
    if not item_id:
        return
    with _lock:
        _bump(_items, item_id, 1)
        _bump(_shows, show_id, 1)
        _bump(_seasons, season_id, 1)


def release(item_id, show_id=None, season_id=None):
    if not item_id:
        return
    with _lock:
        _bump(_items, item_id, -1)
        _bump(_shows, show_id, -1)
        _bump(_seasons, season_id, -1)


@contextmanager
def holding():
    marks = []

    def add(item_id, show_id=None, season_id=None):
        if not item_id:
            return
        hold(item_id, show_id, season_id)
        marks.append((str(item_id), None if show_id is None else str(show_id), None if season_id is None else str(season_id)))

    try:
        yield add
    finally:
        for mark in reversed(marks):
            release(*mark)


def conflicts(kind, ids):
    """Ids in this list that a running job is using."""
    blocked = []
    with _lock:
        for item in ids or []:
            key = str(item)
            hit = _items.get(key)
            if not hit and kind == "show":
                hit = _shows.get(key)
            if not hit and kind == "season":
                hit = _seasons.get(key)
            if hit:
                blocked.append(item)
    return blocked


def partition(kind, ids):
    busy = {str(item) for item in conflicts(kind, ids)}
    free = [item for item in ids if str(item) not in busy]
    held = [item for item in ids if str(item) in busy]
    return free, held
