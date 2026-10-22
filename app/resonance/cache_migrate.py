"""One-time move of files out of the old artwork cache folder.

Before the cache folder existed, everything the app wrote lived under config/artwork. Now:

* images downloaded from a web address go to cache/music (they are fetched again when missing),
* uploaded files and kept copies go to the data folder (data/artwork/additional), the undo history to config/undo,
* thumbnails, video previews and recognised subtitle text go to cache/video.

The first cache layout (v1.3.5, with cache/artwork, cache/video-thumbs and so on) is brought up to date too.

Rows in the database that point at a moved file are updated. A file that cannot be moved is left where it is and
its row is not changed, so the next start tries again. Nothing is deleted except empty folders.
"""
import logging
import os
import shutil
import uuid

from resonance import db
from resonance.paths import (
    artwork_cache_dir,
    cache_dir,
    config_dir,
    additional_artwork_dir,
    additional_media_dir,
    data_dir,
    legacy_artwork_cache_dir,
    previous_additional_artwork_dir,
    previous_artwork_cache_dir,
    undo_dir,
)

logger = logging.getLogger(__name__)

def _folders():
    """Folders in config that held only rebuildable files: (old place, new place)."""
    config = config_dir()
    cache = cache_dir()
    return (
        (os.path.join(config, "artwork", "video-thumbs"), os.path.join(cache, "video", "thumbs")),
        (os.path.join(config, "preview"), os.path.join(cache, "video", "preview")),
        (os.path.join(config, "ocr"), os.path.join(cache, "video", "ocr")),
    )


def _renames():
    """The v1.3.5 layout of the cache folder, as (old place, new place)."""
    cache = cache_dir()
    return (
        (os.path.join(cache, "video-thumbs"), os.path.join(cache, "video", "thumbs")),
        (os.path.join(cache, "preview"), os.path.join(cache, "video", "preview")),
        (os.path.join(cache, "ocr"), os.path.join(cache, "video", "ocr")),
        (os.path.join(cache, "thumbs"), os.path.join(cache, "music", "thumbs")),
    )


def _norm(path):
    return os.path.normcase(os.path.realpath(path))


def _inside(folder, path):
    base = _norm(folder)
    real = _norm(path)
    return real == base or real.startswith(base + os.sep)


def _move(path, folder):
    """Move one file into a folder, keeping its name unless that name is taken. Returns the new path."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, os.path.basename(path))
    if os.path.exists(target):
        if _norm(target) == _norm(path):
            return target
        stem, ext = os.path.splitext(os.path.basename(path))
        target = os.path.join(folder, f"{stem}-{uuid.uuid4().hex[:8]}{ext}")
    shutil.move(path, target)
    return target


def _artwork_pool(old, include_cache, include_data=True):
    """Move the pool files out of the old folder. Downloaded images go to the cache only when include_cache is set."""
    rows = db.fetchall("SELECT id, source_url, local_path FROM artwork_pool WHERE local_path IS NOT NULL", ())
    moved = {}
    counts = {"cache": 0, "additional": 0, "failed": 0}
    for row in rows:
        path = row["local_path"]
        if not _inside(old, path) or not os.path.isfile(path):
            continue
        source = str(row.get("source_url") or "")
        rebuildable = source.startswith(("http://", "https://"))
        if rebuildable and not include_cache:
            continue
        if not rebuildable and not include_data:
            continue
        if path not in moved:
            try:
                moved[path] = _move(path, artwork_cache_dir() if rebuildable else additional_media_dir("music"))
            except OSError:
                logger.warning("could not move %s", path, exc_info=True)
                counts["failed"] += 1
                continue
            counts["cache" if rebuildable else "additional"] += 1
        new = moved[path]
        if source == path:
            db.execute("UPDATE artwork_pool SET local_path = %s, source_url = %s WHERE id = %s", (new, new, row["id"]))
        else:
            db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (new, row["id"]))
    return counts


def _relocate_cache(old):
    """Move downloaded artwork from the v1.3.5 folder to the music cache folder and update the saved paths."""
    rows = db.fetchall("SELECT id, local_path FROM artwork_pool WHERE local_path IS NOT NULL", ())
    moved = {}
    for row in rows:
        path = row["local_path"]
        if not _inside(old, path) or not os.path.isfile(path):
            continue
        if path not in moved:
            try:
                moved[path] = _move(path, artwork_cache_dir())
            except OSError:
                logger.warning("could not move %s", path, exc_info=True)
                continue
        db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (moved[path], row["id"]))
    return len(moved)


def _undo(old):
    rows = db.fetchall("SELECT subject_kind, subject_id, cache_path FROM artwork_undo", ())
    moved = 0
    for row in rows:
        path = row["cache_path"]
        if not path or not _inside(old, path) or not os.path.isfile(path):
            continue
        try:
            new = _move(path, undo_dir())
        except OSError:
            logger.warning("could not move %s", path, exc_info=True)
            continue
        db.execute(
            "UPDATE artwork_undo SET cache_path = %s WHERE subject_kind = %s AND subject_id = %s",
            (new, row["subject_kind"], row["subject_id"]),
        )
        moved += 1
    return moved


def _prune(old):
    """Remove the old folder's empty sub-folders, and the folder itself when nothing is left in it."""
    for base, _dirs, _files in os.walk(old, topdown=False):
        try:
            os.rmdir(base)
        except OSError:
            pass


def _relocate_additional(old):
    """Move uploaded and replaced artwork from config/artwork/additional to the data folder."""
    target = additional_media_dir("music")
    if _norm(old) == _norm(target):
        return 0
    rows = db.fetchall("SELECT id, source_url, local_path FROM artwork_pool WHERE local_path IS NOT NULL", ())
    by_path = {}
    for row in rows:
        by_path.setdefault(_norm(row["local_path"]), []).append(row)
    count = 0
    for base, _dirs, names in os.walk(old):
        for name in names:
            path = os.path.join(base, name)
            try:
                new = _move(path, target)
            except OSError:
                logger.warning("could not move %s", path, exc_info=True)
                continue
            count += 1
            for row in by_path.get(_norm(path), []) or by_path.get(os.path.normcase(os.path.abspath(path)), []):
                if str(row.get("source_url") or "") == row["local_path"]:
                    db.execute("UPDATE artwork_pool SET local_path = %s, source_url = %s WHERE id = %s", (new, new, row["id"]))
                else:
                    db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (new, row["id"]))
    return count


def _lift_root_files():
    """v1.4.3 kept music files straight in data/artwork/additional. They belong in its music folder."""
    base = additional_artwork_dir()
    if not os.path.isdir(base):
        return 0
    loose = [os.path.join(base, name) for name in os.listdir(base) if os.path.isfile(os.path.join(base, name))]
    if not loose:
        return 0
    rows = db.fetchall("SELECT id, source_url, local_path FROM artwork_pool WHERE local_path IS NOT NULL", ())
    count = 0
    for path in loose:
        try:
            new = _move(path, additional_media_dir("music"))
        except OSError:
            logger.warning("could not move %s", path, exc_info=True)
            continue
        count += 1
        for row in rows:
            if _norm(row["local_path"]) == _norm(path):
                if str(row.get("source_url") or "") == row["local_path"]:
                    db.execute("UPDATE artwork_pool SET local_path = %s, source_url = %s WHERE id = %s", (new, new, row["id"]))
                else:
                    db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (new, row["id"]))
    return count


def run():
    """Move what is still in the old places. Safe to run on every start: with nothing left to move it does nothing."""
    on_volume = os.path.ismount(cache_dir())
    data_volume = os.path.ismount(data_dir())
    if not data_volume:
        logger.warning(
            "%s is not a mounted volume. Add './data:/data' to docker-compose so uploaded and replaced artwork "
            "is kept outside the container.",
            data_dir(),
        )
    old = legacy_artwork_cache_dir()
    if os.path.isdir(old):
        # Downloaded images are only moved onto a real cache volume. Without one they would land inside the
        # container and be lost on the next rebuild, so they stay where they are and keep working.
        if not on_volume:
            logger.warning(
                "%s is not a mounted volume. Add './cache:/cache' to docker-compose to move the artwork cache there.",
                cache_dir(),
            )
        try:
            counts = _artwork_pool(old, on_volume, data_volume)
            undo = _undo(old)
        except Exception:
            logger.exception("artwork migration skipped: the database could not be used")
            return
        if counts["cache"] or counts["additional"] or undo or counts["failed"]:
            logger.info(
                "artwork migration: %d to the cache, %d in config, %d undo files, %d failed",
                counts["cache"], counts["additional"], undo, counts["failed"],
            )
        if on_volume:
            left = sum(len(files) for _b, _d, files in os.walk(old))
            if left:
                logger.info("%d unreferenced file(s) remain in %s and can be deleted", left, old)
        _prune(old)
    earlier = previous_additional_artwork_dir()
    if data_volume and os.path.isdir(earlier):
        try:
            count = _relocate_additional(earlier)
        except Exception:
            logger.exception("uploaded and replaced artwork could not be moved to the data folder")
            count = 0
        if count:
            logger.info("moved %d uploaded or replaced artwork file(s) from %s to %s", count, earlier, additional_artwork_dir())
        _prune(earlier)
    if data_volume:
        try:
            lifted = _lift_root_files()
        except Exception:
            logger.exception("music artwork could not be moved into the music folder of the data folder")
            lifted = 0
        if lifted:
            logger.info("moved %d music artwork file(s) into %s", lifted, additional_media_dir("music"))
    previous = previous_artwork_cache_dir()
    if os.path.isdir(previous):
        try:
            count = _relocate_cache(previous)
        except Exception:
            logger.exception("downloaded artwork could not be moved to the music cache folder")
            count = 0
        if count:
            logger.info("moved %d downloaded artwork file(s) from %s to %s", count, previous, artwork_cache_dir())
        _prune(previous)
    for source, target in _renames():
        if os.path.isdir(source) and not os.path.exists(target):
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.move(source, target)
                logger.info("moved %s to %s", source, target)
            except OSError:
                logger.warning("could not move %s", source, exc_info=True)
    if on_volume:
        for source, target in _folders():
            if os.path.isdir(source) and not os.path.exists(target):
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.move(source, target)
                    logger.info("moved %s to %s", source, target)
                except OSError:
                    logger.warning("could not move %s", source, exc_info=True)
