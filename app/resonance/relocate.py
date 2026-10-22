"""Move an artist folder from one music library folder to another.

The folder is copied first. Album, track and artwork paths are updated only after
every file in the copy matches the original. The original is removed after that.
"""
from __future__ import annotations

import os
import shutil

from curator import folders
from resonance import db
from resonance.errors import AppError
from resonance.paths import like_prefix
from resonance.upgrade import shared_folder_block


def destination(dest):
    """The configured music folder the user picked."""
    wanted = os.path.normpath(dest or "")
    for path in folders.configured("music"):
        if os.path.normpath(path) == wanted:
            if not os.path.isdir(path):
                raise AppError(f"{path} is not mounted")
            return os.path.realpath(path)
    raise AppError("Pick a music folder from Settings", 400)


def preview(ids, dest):
    root = destination(dest)
    plans = []
    for item_id in ids:
        plan = _plan(item_id, root)
        plans.append({
            "title": plan["title"],
            "error": plan["error"],
            "skipped": bool(plan.get("skip")),
            "moves": [] if plan["error"] or plan.get("skip") else [{"from": plan["source"], "to": plan["target"], "dir": True}],
        })
    ready = sum(1 for plan in plans if plan["moves"] and not plan["error"])
    return {"media": "music", "dest": root, "plans": plans, "moves": ready}


def apply_one(artist_id, dest, log):
    root = destination(dest)
    plan = _plan(artist_id, root)
    title = plan["title"]
    if plan.get("skip"):
        log(f"{title}: already in {root}")
        return []
    if plan["error"]:
        raise AppError(plan["error"])
    source, target = plan["source"], plan["target"]
    log(f"{title}: copying to {target}")
    try:
        shutil.copytree(source, target, copy_function=shutil.copy2)
    except OSError as exc:
        _discard(target)
        raise AppError(f"Could not copy {title}: {exc.strerror or exc}") from exc
    if not _same_tree(source, target):
        _discard(target)
        raise AppError(f"The copy of {title} does not match the original, so the original was left in place")
    try:
        _rewrite(source, target)
    except Exception:
        _discard(target)
        raise
    try:
        shutil.rmtree(source)
    except OSError as exc:
        log(f"{title}: copied. The original folder is still at {source} ({exc.strerror or exc})")
    else:
        log(f"{title}: moved to {target}")
    return [target]


def start(ids, dest, label):
    """Start the move when the library is free. False means try again once the running job stops."""
    from curator.video import files, scanner, scrape, split
    from resonance import backup, jobs

    destination(dest)
    if scanner.running() or scrape.running() or split.running() or files.running() or backup.restoring() or jobs.library_active():
        return False
    try:
        return bool(files.start("move", "artist", list(ids), label=label, dest=dest))
    except AppError:
        return False


def _plan(artist_id, dest):
    row = db.fetchone("SELECT id, name, path FROM artists WHERE id = %s", (artist_id,))
    if not row:
        return {"title": "Artist", "error": "Artist not found", "source": "", "target": ""}
    title = row.get("name") or "Artist"
    source = row.get("path") or ""
    if not source or not os.path.isdir(source):
        return {"title": title, "error": "The artist folder is not on disk", "source": source, "target": ""}
    root = _library_root(source)
    if not root:
        return {"title": title, "error": "The artist folder is outside the music library", "source": source, "target": ""}
    if os.path.normpath(source) == os.path.normpath(root):
        return {"title": title, "error": "This artist folder is a library root", "source": source, "target": ""}
    if os.path.normpath(root) == os.path.normpath(dest):
        return {"title": title, "error": None, "skip": True, "source": source, "target": source}
    others = db.fetchall("SELECT path FROM artists WHERE id <> %s", (artist_id,))
    albums = db.fetchall("SELECT path FROM albums WHERE artist_id <> %s", (artist_id,))
    blocked = shared_folder_block(source, [item.get("path") or "" for item in list(others) + list(albums)])
    if blocked:
        return {"title": title, "error": blocked.replace("album", "artist"), "source": source, "target": ""}
    target = os.path.join(dest, os.path.basename(source.rstrip("/")))
    if os.path.exists(target):
        return {"title": title, "error": f"{target} already exists", "source": source, "target": target}
    return {"title": title, "error": None, "source": source, "target": target}


def _library_root(path):
    best = ""
    for root in folders.configured("music"):
        real = os.path.realpath(root) if os.path.isdir(root) else ""
        if not real:
            continue
        if path == real or path.startswith(real.rstrip("/") + "/"):
            if len(real) > len(best):
                best = real
    return best


def _rewrite(old, new):
    like = like_prefix(old)
    with db.transaction() as conn:
        for table, column in (("artists", "path"), ("albums", "path"), ("tracks", "file_path"), ("artwork_pool", "local_path")):
            conn.execute(
                f"UPDATE {table} SET {column} = %s || substr({column}, %s) "
                f"WHERE {column} = %s OR {column} LIKE %s",
                (new, len(old) + 1, old, like),
            )


def _same_tree(source, target):
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
