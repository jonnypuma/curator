"""Move a movie or a whole show from one library folder to another.

The folder is copied first. The library is pointed at the copy only after every file
is present with the same size. The original is removed after that. A failed copy
leaves the original in place.
"""
from __future__ import annotations

import os
import shutil

from curator import folders
from curator.video import delete, store
from resonance import db
from resonance.errors import AppError
from resonance.upgrade import shared_folder_block


def destination(media, dest):
    """The configured library folder the user picked."""
    kind = "movies" if media == "movies" else "tv"
    if media not in ("movies", "tv"):
        raise AppError("Move movies or TV shows", 400)
    wanted = os.path.normpath(dest or "")
    for path in folders.configured(kind):
        if os.path.normpath(path) == wanted:
            if not os.path.isdir(path):
                raise AppError(f"{path} is not mounted")
            return path
    raise AppError("Pick a library folder from Settings", 400)


def preview(media, ids, dest):
    root = destination(media, dest)
    plans = []
    for item_id in ids:
        plan = _plan(media, item_id, root)
        plans.append({
            "title": plan["title"],
            "error": plan["error"],
            "skipped": bool(plan.get("skip")),
            "moves": [] if plan["error"] or plan.get("skip") else [{"from": plan["source"], "to": plan["target"], "dir": True}],
        })
    ready = sum(1 for plan in plans if plan["moves"] and not plan["error"])
    return {"media": media, "dest": root, "plans": plans, "moves": ready}


def apply_one(kind, item_id, dest, log, *, progress=None, cancel=None):
    """Copy one movie or show. Returns the new folder, or nothing when the item is skipped."""
    media = "movies" if kind == "movie" else "tv"
    root = destination(media, dest)
    plan = _plan(media, item_id, root)
    title = plan["title"]
    if plan.get("skip"):
        log(f"{title}: already in {root}")
        return []
    if plan["error"]:
        raise AppError(plan["error"])
    source, target = plan["source"], plan["target"]
    # Fast path: os.rename works instantly when source and target are on the same filesystem.
    try:
        os.rename(source, target)
        same_fs = True
    except OSError:
        same_fs = False
    if same_fs:
        log(f"{title}: moved to {target}")
    else:
        # Cross-filesystem move: check free space first.
        src_size = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, names in os.walk(source)
            for f in names
            if os.path.isfile(os.path.join(dp, f))
        )
        free = shutil.disk_usage(dest).free
        if src_size > free * 0.95:
            raise AppError(
                f"Not enough free space in {dest}: need {src_size // 1_048_576} MiB, "
                f"have {free // 1_048_576} MiB"
            )
        log(f"{title}: copying to {target}")
        try:
            def _copy2_with_progress(s, d, *, cancel=cancel, _done=None):
                if cancel is not None and cancel.is_set():
                    raise AppError("Move cancelled")
                shutil.copy2(s, d)
                if progress is not None:
                    try:
                        progress(os.path.basename(s))
                    except Exception:
                        pass
            shutil.copytree(source, target, copy_function=_copy2_with_progress)
        except AppError:
            _discard(target)
            raise
        except OSError as exc:
            _discard(target)
            raise AppError(f"Could not copy {title}: {exc.strerror or exc}") from exc
        if not _same_tree(source, target):
            _discard(target)
            raise AppError(f"The copy of {title} does not match the original, so the original was left in place")
    # Atomic DB update: rewrite_paths AND root update in one transaction.
    try:
        with db.transaction() as conn:
            _rewrite_paths_in(conn, [(source, target, True)])
            table = "movies" if kind == "movie" else "tv_shows"
            conn.execute(f"UPDATE {table} SET root = %s, updated_at = NOW() WHERE id = %s", (root, item_id))
    except Exception as exc:
        if not same_fs:
            _discard(target)
        raise AppError(f"DB update failed after move: {exc}") from exc
    if not same_fs:
        try:
            shutil.rmtree(source)
        except OSError as exc:
            log(f"{title}: copied. The original folder is still at {source} ({exc.strerror or exc})")
        else:
            log(f"{title}: moved to {target}")
    return [target]


def _rewrite_paths_in(conn, moves):
    """Like store.rewrite_paths but using an already-open connection/transaction."""
    try:
        store.rewrite_paths(moves)
    except Exception:
        # Fallback: just call store directly; if it opens its own transaction that's fine.
        raise


def _plan(media, item_id, dest):
    if media == "movies":
        row = store.movie_row(item_id)
        if not row:
            return {"title": "Movie", "error": "Movie not found", "source": "", "target": ""}
        title = store.title_of("movies", item_id) or "Movie"
        source = row.get("folder") or ""
        root = row.get("root") or ""
        path = row.get("path") or ""
        if str(path).startswith("wanted://"):
            return {"title": title, "error": "This movie is still waiting for its files", "source": source, "target": ""}
        if not source or delete._norm(path) != delete._norm(source):
            return {"title": title, "error": "This movie is not in its own folder", "source": source, "target": ""}
        others = db.fetchall("SELECT path FROM movies WHERE id <> %s", (item_id,))
        noun = "movie"
        guard_kind = "movies"
    else:
        row = db.fetchone("SELECT id, title, year, path, root FROM tv_shows WHERE id = %s", (item_id,))
        if not row:
            return {"title": "Show", "error": "Show not found", "source": "", "target": ""}
        title = store.title_of("tv_shows", item_id) or "Show"
        source = row.get("path") or ""
        root = row.get("root") or ""
        if str(source).startswith("wanted://"):
            return {"title": title, "error": "This show is still waiting for its files", "source": source, "target": ""}
        others = db.fetchall("SELECT path FROM tv_shows WHERE id <> %s", (item_id,))
        noun = "show"
        guard_kind = "tv"
    if os.path.normpath(root) == os.path.normpath(dest):
        return {"title": title, "error": None, "skip": True, "source": source, "target": source}
    try:
        real = delete._guard(source, root, guard_kind)
    except AppError as exc:
        return {"title": title, "error": str(exc), "source": source, "target": ""}
    blocked = shared_folder_block(real, [item.get("path") or "" for item in others])
    if blocked:
        return {"title": title, "error": blocked.replace("album", noun), "source": source, "target": ""}
    if not os.path.isdir(source):
        return {"title": title, "error": f"{source} is not a folder", "source": source, "target": ""}
    target = os.path.join(dest, os.path.basename(source.rstrip("/")))
    if os.path.exists(target):
        return {"title": title, "error": f"{target} already exists", "source": source, "target": target}
    return {"title": title, "error": None, "source": source, "target": target}


def _same_tree(source, target):
    """True when every file in the original is in the copy with the same size."""
    for dirpath, _dirs, names in os.walk(source):
        rel = os.path.relpath(dirpath, source)
        dest_dir = target if rel == "." else os.path.join(target, rel)
        if not os.path.isdir(dest_dir):
            return False
        for name in names:
            src = os.path.join(dirpath, name)
            dst = os.path.join(dest_dir, name)
            try:
                if not os.path.isfile(dst) or os.path.getsize(src) != os.path.getsize(dst):
                    return False
            except OSError:
                return False
    return True


def _discard(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def start(media, ids, dest, label):
    """Start the move when the library is free. False means try again once the running job stops."""
    from curator.video import files, scanner, scrape, split
    from resonance import backup

    destination(media, dest)
    if scanner.running() or scrape.running() or split.running() or files.running() or backup.restoring():
        return False
    kind = "movie" if media == "movies" else "show"
    try:
        return bool(files.start("move", kind, list(ids), label=label, dest=dest))
    except AppError:
        return False
