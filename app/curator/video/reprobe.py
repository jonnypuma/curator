"""Read ffprobe and MediaInfo again for a movie or episode that is already in the library."""
from __future__ import annotations

import json
import logging
import os

from curator.video import config, exports, probe, store
from resonance.errors import AppError

logger = logging.getLogger(__name__)


def refresh(kind, item_ids):
    if kind not in {"movie", "episode"}:
        raise AppError("Media info can be updated for a movie or an episode", 400)
    probed = 0
    updated = 0
    failed = []
    seen = set()
    changed_items = set()
    for item_id in item_ids:
        paths = _paths(kind, item_id)
        if not paths:
            failed.append("No video file")
            continue
        for path in paths:
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            if not os.path.isfile(path):
                failed.append(f"Missing file: {os.path.basename(path)}")
                continue
            summary = probe.analyze(path, open_iso=False if kind == "episode" else None)
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
            existing = store.db.fetchone("SELECT * FROM video_files WHERE path = %s", (path,))
            external = (existing or {}).get("external_subtitles") or []
            file_id = store.save_file(path, "movie" if kind == "movie" else "episode", size, mtime, summary, external)
            _link_file(kind, item_id, path, file_id)
            if summary.get("probe_error"):
                failed.append(f"{os.path.basename(path)}: {summary['probe_error']}")
                continue
            probed += 1
            if _changed(existing, summary):
                updated += 1
                changed_items.add(item_id)
        if item_id in changed_items:
            _write_nfo(kind, item_id)
    if not probed:
        raise AppError(failed[0] if failed else "No video file to probe", 400)
    return {"ok": True, "probed": probed, "updated": updated > 0, "message": _message(updated, failed)}


def _link_file(kind, item_id, path, file_id):
    """Point the item at this video_files row when it is not pointing anywhere yet.

    An item can hold a path with no file_id - a split part, for instance, which is written
    outside a scan. Without this, probing it would store the media info in video_files and the
    item would still show none of it, because nothing joined the two. An item that already has
    a file_id is left alone, so this cannot re-point a movie away from one of its parts.
    """
    if not file_id:
        return
    table = "movies" if kind == "movie" else "tv_episodes"
    try:
        store.db.execute(
            f"UPDATE {table} SET file_id = %s, updated_at = NOW() "
            f"WHERE id = %s AND file_id IS NULL AND path = %s",
            (file_id, item_id, path),
        )
    except Exception:
        logger.warning("could not link %s %s to its file row", kind, item_id, exc_info=True)


def _paths(kind, item_id):
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("That movie is not in the library any more", 404)
        parts = [path for path in (row.get("parts") or []) if path]
        if parts:
            return parts
        return [row["path"]] if row.get("path") and os.path.isfile(row["path"]) else []
    row = store.episode_detail(item_id)
    if not row:
        raise AppError("That episode is not in the library any more", 404)
    return [row["path"]] if row.get("path") else []


def _write_nfo(kind, item_id):
    cfg = config.current()
    if not cfg.get("write_nfo"):
        return
    try:
        if kind == "movie":
            exports.write_movie(item_id, cfg)
            return
        row = store.episode_detail(item_id)
        if row and row.get("show_id"):
            exports.write_show(str(row["show_id"]), cfg, "overwrite", [item_id])
    except Exception:
        return


def _blank(value):
    return value is None or value == "" or value == [] or value == {}


def _same(old, new):
    if _blank(old) and _blank(new):
        return True
    if isinstance(old, bool) or isinstance(new, bool):
        return bool(old) == bool(new)
    if isinstance(old, (list, dict)) or isinstance(new, (list, dict)):
        return json.dumps(old, sort_keys=True, default=str) == json.dumps(new, sort_keys=True, default=str)
    try:
        if old is not None and new is not None and not isinstance(old, str) and not isinstance(new, str):
            return float(old) == float(new)
    except (TypeError, ValueError):
        pass
    return str(old).strip() == str(new).strip()


def _changed(existing, summary):
    """True when the probe fills a blank field or replaces a stored value."""
    before = existing or {}
    for column in store.PROBE_COLUMNS:
        if column == "probe_error":
            continue
        if not _same(before.get(column), summary.get(column)):
            return True
    return False


def _message(updated, failed):
    text = "Media info updated." if updated else "No media info was updated."
    if failed:
        text = f"{text} {failed[0]}"
    return text
