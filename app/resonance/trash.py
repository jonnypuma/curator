"""The recycle bin: files and folders deleted from disk are moved aside first, so a delete can be undone.

A deleted item moves into `.curator-trash` at the top of the library folder it was in. That keeps it on the same
drive, so even a large file moves at once instead of being copied. Each item is listed in trash_items with the place it
came from. Restore puts it back; items older than the chosen number of days are deleted for good.

Scans skip the folder (its name starts with a dot), and marker files keep Kodi, Plex and Jellyfin out of it.
When the recycle bin is switched off, discard() deletes at once as before.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

FOLDER = ".curator-trash"
DEFAULT_DAYS = 30
# .nomedia (Kodi and Jellyfin), .plexignore (Plex), .ignore (Jellyfin and Emby) so no player lists the bin.
_MARKERS = {".nomedia": "", ".ignore": "", ".plexignore": "*\n"}
_lock = threading.Lock()


def settings():
    """(on, days) from Settings, General. On by default, 30 days."""
    from resonance.settings import load

    cfg = load() or {}
    on = cfg.get("trash_enabled", True) is not False
    try:
        days = int(cfg.get("trash_days") or DEFAULT_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS
    return on, max(1, min(days, 365))


def library_roots():
    """Every mounted library folder: movies, TV, music videos, music, and the movie set folder."""
    from curator import folders
    from resonance.paths import music_roots

    roots = []
    for kind in ("movies", "tv", "musicvideos"):
        roots.extend(folders.mounted(kind))
    roots.extend(os.path.realpath(path) for path in music_roots())
    sets = folders.set_root()
    if sets:
        roots.append(sets)
    return list(dict.fromkeys(roots))


def root_for(path, roots=None):
    """The library folder that holds path (the longest one), or "" when none does."""
    real = os.path.realpath(path)
    best = ""
    for root in roots if roots is not None else library_roots():
        root = os.path.realpath(root)
        if real == root:
            continue
        if real.startswith(root.rstrip(os.sep) + os.sep) and len(root) > len(best):
            best = root
    return best


def _note(action, path, label, kind, detail):
    from resonance import history

    history.record(action, str(label or os.path.basename(str(path or ""))), kind or "", path, detail)


def _bin_folder(root):
    folder = os.path.join(root, FOLDER)
    os.makedirs(folder, exist_ok=True)
    for name, text in _MARKERS.items():
        marker = os.path.join(folder, name)
        if not os.path.exists(marker):
            try:
                with open(marker, "w", encoding="utf-8") as handle:
                    handle.write(text)
            except OSError:
                pass
    return folder


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for folder, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def _remove_now(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def discard(path, label="", kind=""):
    """Delete a file or folder: into the recycle bin when it is on, at once when it is off.

    Returns the trash row id, or "" when the item was deleted at once. A path outside every library folder (where
    there is no bin to put it in) is deleted at once too. Raises OSError like os.remove and shutil.rmtree do.
    """
    if not path or not os.path.lexists(path):
        return ""
    on, _days = settings()
    root = root_for(path) if on else ""
    if not on or not root:
        _remove_now(path)
        _note("deleted", path, label, kind, "Deleted at once" if not on else "Deleted at once: outside every library folder")
        return ""
    from resonance import db

    item_id = str(uuid.uuid4())
    original = os.path.realpath(path)
    is_dir = os.path.isdir(path)
    size = _size(path)
    relative = os.path.relpath(original, root)
    target = os.path.join(_bin_folder(root), item_id, relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        os.rename(path, target)
    except OSError:
        shutil.move(path, target)       # another drive inside the same library folder: copy, then remove
    db.execute(
        """
        INSERT INTO trash_items (id, original_path, trash_path, root, label, kind, is_dir, size_bytes, deleted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, LOCALTIMESTAMP)
        """,
        (item_id, original, target, root,
         str(label or os.path.basename(path))[:300], str(kind or "")[:20], is_dir, size),
    )
    logger.info("moved to the recycle bin: %s", path)
    _note("deleted", original, label, kind, "Moved to the recycle bin")
    return item_id


def items():
    """Everything in the bin, newest first, with the day it will be deleted for good."""
    from resonance import db

    purge_expired()
    _on, days = settings()
    rows = db.fetchall(
        """
        SELECT id::text AS id, original_path, trash_path, root, label, kind, is_dir, size_bytes, deleted_at
        FROM trash_items ORDER BY deleted_at DESC
        """
    )
    found = []
    for row in rows:
        row = dict(row)
        deleted = row.get("deleted_at")
        row["expires_at"] = (deleted + timedelta(days=days)).isoformat(timespec="seconds") if deleted else None
        row["deleted_at"] = deleted.isoformat(timespec="seconds") if deleted else None
        row["present"] = os.path.lexists(row.get("trash_path") or "")
        found.append(row)
    return found


def restore(ids):
    """Move items back where they were. Returns (restored paths, errors). An item whose place is taken stays."""
    from resonance import db

    restored, errors = [], []
    pending = [str(item) for item in ids or []]
    seen = set()
    while pending:
        item_id = pending.pop(0)
        if item_id in seen:
            continue
        seen.add(item_id)
        row = db.fetchone("SELECT * FROM trash_items WHERE id = %s", (str(item_id),))
        if not row:
            continue
        original, held = row["original_path"], row["trash_path"]
        name = os.path.basename(original)
        if not os.path.lexists(held):
            db.execute("DELETE FROM trash_items WHERE id = %s", (str(item_id),))
            errors.append(f"{name}: it is no longer in the recycle bin")
            continue
        if os.path.lexists(original):
            errors.append(f"{name}: something else is in its place now, so it was left in the recycle bin")
            continue
        try:
            os.makedirs(os.path.dirname(original), exist_ok=True)
            try:
                os.rename(held, original)
            except OSError:
                shutil.move(held, original)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
            continue
        db.execute("DELETE FROM trash_items WHERE id = %s", (str(item_id),))
        _tidy(held, row["root"])
        restored.append(original)
        _note("restored", original, row.get("label"), row.get("kind"), "Back from the recycle bin")
        pending.extend(item for item in _sidecars_of(row) if item not in seen)
    return restored, errors


def _sidecars_of(row):
    """A music video goes to the bin with its .nfo, media info file and pictures as separate items, binned without a
    label in the same delete. Restoring the video brings them back too."""
    from resonance import db

    if row.get("kind") != "musicvideo" or not row.get("label"):
        return []
    stem = os.path.splitext(row["original_path"])[0]
    rows = db.fetchall(
        "SELECT id::text AS id, original_path FROM trash_items WHERE kind = 'musicvideo' AND label = '' "
        "AND id <> %s AND starts_with(original_path, %s) "
        "AND deleted_at BETWEEN %s - interval '10 minutes' AND %s + interval '10 minutes'",
        (str(row["id"]), stem, row["deleted_at"], row["deleted_at"]),
    )
    return [item["id"] for item in rows if item["original_path"][len(stem):len(stem) + 1] in (".", "-")]


def delete(ids=None):
    """Delete items for good: these ids, or everything when ids is None. Returns how many went."""
    from resonance import db

    if ids is None:
        rows = db.fetchall("SELECT * FROM trash_items")
    else:
        wanted = [str(item) for item in ids or []]
        rows = db.fetchall("SELECT * FROM trash_items WHERE id::text = ANY(%s)", (wanted,)) if wanted else []
    gone = 0
    for row in rows:
        held = row["trash_path"]
        try:
            if os.path.lexists(held):
                _remove_now(held)
        except OSError as exc:
            logger.warning("could not empty %s from the recycle bin: %s", held, exc)
            continue
        db.execute("DELETE FROM trash_items WHERE id = %s", (row["id"],))
        _tidy(held, row["root"])
        gone += 1
        _note("purged", row.get("original_path") or held, row.get("label"), row.get("kind"), "Gone from the recycle bin")
    return gone


def free_space(root, needed_free):
    """Delete the oldest items of this library folder's bin for good until the drive has needed_free bytes free.

    Returns how many went. A file on another drive would not help, so only this folder's bin is touched."""
    from resonance import db, history

    gone = 0
    rows = db.fetchall("SELECT id::text AS id FROM trash_items WHERE root = %s ORDER BY deleted_at", (root,))
    with history.why("The drive was low on space"):
        for row in rows:
            if shutil.disk_usage(root).free >= needed_free:
                break
            gone += delete([row["id"]])
    return gone


def size_by_root():
    """{library folder: bytes in its bin}."""
    from resonance import db

    rows = db.fetchall("SELECT root, COALESCE(SUM(size_bytes), 0)::bigint AS n FROM trash_items GROUP BY root")
    return {row["root"]: int(row["n"] or 0) for row in rows}


def purge_expired():
    """Delete for good what has been in the bin longer than the chosen number of days. Never raises."""
    from resonance import db

    if not _lock.acquire(blocking=False):
        return 0
    try:
        _on, days = settings()
        cutoff = datetime.now() - timedelta(days=days)
        rows = db.fetchall("SELECT id::text AS id FROM trash_items WHERE deleted_at < %s", (cutoff,))
        if not rows:
            return 0
        from resonance import history

        with history.why(f"In the recycle bin longer than {days} days"):
            return delete([row["id"] for row in rows])
    except Exception:
        logger.exception("could not empty old items from the recycle bin")
        return 0
    finally:
        _lock.release()


_timer = {"thread": None}
CHECK_HOURS = 6


def start_timer():
    """Empty expired items now and every few hours, in the background."""
    if _timer["thread"] and _timer["thread"].is_alive():
        return

    def loop():
        stop = threading.Event()
        while True:
            purge_expired()
            stop.wait(CHECK_HOURS * 3600)

    _timer["thread"] = threading.Thread(target=loop, name="recycle-bin", daemon=True)
    _timer["thread"].start()


def _tidy(held, root):
    """Remove the item's own bin folder once it is empty. The bin folder and its markers stay."""
    bin_folder = os.path.join(root or "", FOLDER)
    folder = os.path.dirname(held)
    while folder and os.path.realpath(folder) != os.path.realpath(bin_folder) and folder.startswith(bin_folder):
        try:
            os.rmdir(folder)
        except OSError:
            return
        folder = os.path.dirname(folder)
