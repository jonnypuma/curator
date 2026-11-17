"""Bulk duplicate cleanup: keep the best copy of each title and delete the others, after a preview and a confirmation.

A preview (build_plan) touches nothing. Within one movie, episode or album it picks the copy to keep: the best one, and
among copies of the same quality the one Radarr, Sonarr or Lidarr uses. A copy is only offered for deletion when losing
it cannot lose anything else, so a group or copy is skipped, with the reason shown, when:

- the kept copy is not on disk, is empty, failed its probe, or the integrity check called it Corrupt;
- the copy is another edition, is locked, or is a pair marked Not duplicates;
- the copy is the same file as the kept one (one file through two mounts), or a file two episodes share;
- an album copy has a track the kept copy lacks.

Weaker copies (Upgrade available) only go when "also delete weaker copies" is ticked. Deletes run through the normal
delete, so they go to the recycle bin when it is on, and the apps are asked to rescan.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from collections import deque
from datetime import datetime

from curator.video import copies, integrity
from resonance import db, history
from resonance.errors import AppError

logger = logging.getLogger(__name__)

MEDIA = ("movies", "tv", "music", "musicvideos")
REASON = "Bulk duplicate cleanup"

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "processed": 0, "total": 0, "plan": None, "token": "", "result": {}}
_log = deque(maxlen=1000)


def status():
    from resonance import trash

    with _lock:
        snapshot = dict(_state)
        snapshot["log"] = "\n".join(_log)
        if snapshot["status"] == "running":
            snapshot["plan"] = None     # the window only reads the plan while it is ready; the list can be very large
    snapshot["trash_enabled"], snapshot["trash_days"] = trash.settings()
    return snapshot


def _say(line, **values):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        _state["message"] = line
        _state.update(values)


# Choosing what to keep

def _in_use(item):
    arr = item.get("arr") or {}
    return bool(arr.get("id")) and arr.get("linked") is not False


def _healthy(item):
    path = item.get("file_path") or item.get("path") or ""
    if "://" in path or not os.path.exists(path):
        return False
    if item.get("probe_error") or int(item.get("size_bytes") or 0) <= 0:
        return False
    return not integrity.corrupt(item)


def choose_video(items, include_upgrades, dismissed):
    """(keeper, [(item, reason)] to delete, [(item, why not)] skipped). keeper is None when no copy is healthy."""
    healthy = [item for item in items if _healthy(item)]
    if not healthy:
        return None, [], [(item, "No healthy copy to keep") for item in items]
    best = max(healthy, key=lambda item: item["score"])
    tied = [item for item in healthy if item is best or copies.same_release(best, item)]
    keeper = next((item for item in tied if _in_use(item)), best)
    remove, skipped = [], []
    for item in items:
        if item is keeper:
            continue
        same = copies.same_release(keeper, item)
        if not same and not (include_upgrades and item["score"] < keeper["score"]):
            if not same and item["score"] >= keeper["score"]:
                skipped.append((item, "Not a weaker copy"))
            continue
        if item.get("locked"):
            skipped.append((item, "Locked"))
        elif frozenset((str(item.get("pair_id") or item["id"]), str(keeper.get("pair_id") or keeper["id"]))) in dismissed:
            skipped.append((item, "Marked Not duplicates"))
        elif copies.file_key(item.get("file_path") or item.get("path")) == copies.file_key(keeper.get("file_path") or keeper.get("path")):
            skipped.append((item, "The same file as the copy being kept"))
        elif item.get("shared"):
            skipped.append((item, "This file holds more than one episode"))
        else:
            remove.append((item, "Duplicate" if same else "Weaker copy"))
    return keeper, remove, skipped


def _titles(tracks):
    return {re.sub(r"[^a-z0-9]+", "", str(track.get("title") or "").lower()) for track in tracks} - {""}


def choose_album(items, include_upgrades, dismissed):
    """Like choose_video for album copies: rank decides, and every track of a deleted copy must be in the kept one."""
    healthy = [item for item in items if item.get("track_titles") and os.path.isdir(item.get("path") or "")]
    if not healthy:
        return None, [], [(item, "No copy on disk to keep") for item in items]
    # The most complete copy of the best quality.
    best = max(healthy, key=lambda item: (int(item.get("quality_rank") or 0), len(item["track_titles"])))
    tied = [item for item in healthy if int(item.get("quality_rank") or 0) == int(best.get("quality_rank") or 0)
            and item["track_titles"] >= best["track_titles"]]
    keeper = next((item for item in tied if _in_use(item)), best)
    remove, skipped = [], []
    for item in items:
        if item is keeper:
            continue
        rank, kept = int(item.get("quality_rank") or 0), int(keeper.get("quality_rank") or 0)
        if rank > kept or (rank < kept and not include_upgrades):
            continue
        if item.get("locked"):
            skipped.append((item, "Locked"))
        elif frozenset((str(item["id"]), str(keeper["id"]))) in dismissed:
            skipped.append((item, "Marked Not duplicates"))
        elif not item.get("track_titles") or not item["track_titles"] <= keeper["track_titles"]:
            skipped.append((item, "Has tracks the copy being kept does not"))
        else:
            remove.append((item, "Duplicate" if rank == kept else "Weaker copy"))
    return keeper, remove, skipped


# Reading the library

def _video_item(row, key, item_id=None, kind="movie"):
    item = dict(row)
    item.update({"id": str(item_id or row["id"]), "kind": kind, "key": key, "score": copies.score(row),
                 "size_bytes": int(row.get("size_bytes") or 0)})
    return item


def _movie_groups():
    rows = db.fetchall(
        """
        SELECT m.id::text AS id, m.title, m.year, m.tmdb_id, m.imdb_id, m.path, m.locked, m.edition AS movie_edition,
               m.duplicate_release, m.upgrade_source_id, f.path AS file_path, f.height, f.bitrate_mbps, f.size_bytes,
               f.source_format, f.video_source, f.hdr_format, f.is_3d, f.stereo_mode, f.edition AS file_edition,
               f.probe_error, f.probed_at, f.integrity, f.integrity_size, f.integrity_mtime, f.mtime
        FROM movies m LEFT JOIN video_files f ON f.id = m.file_id
        WHERE NOT COALESCE(m.wanted, FALSE)
        """
    )
    picture = copies._picture_key(copies.movie_key)
    groups = {}
    for row in rows:
        base = picture(row)
        if base:
            edition = str(row.get("movie_edition") or row.get("file_edition") or "").strip().lower()
            groups.setdefault(base + (edition,), []).append(_video_item(row, base))
    return [items for items in groups.values()
            if len(items) > 1 and any(item.get("duplicate_release") or item.get("upgrade_source_id") for item in items)]


def _episode_groups():
    rows = db.fetchall(
        """
        SELECT e.id::text AS id, e.show_id, e.season_number, e.episode_number, e.path, e.locked, e.file_span,
               e.duplicate_release, e.upgrade_source_id, e.upgrade_copy_path,
               s.title AS show_title, s.year AS show_year, s.tmdb_id, s.tvdb_id,
               f.path AS file_path, f.height, f.bitrate_mbps, f.size_bytes, f.source_format, f.video_source,
               f.hdr_format, f.is_3d, f.stereo_mode, f.probe_error, f.probed_at, f.integrity, f.integrity_size,
               f.integrity_mtime, f.mtime
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id LEFT JOIN video_files f ON f.id = e.file_id
        WHERE NOT e.missing AND COALESCE(e.path, '') <> '' AND e.path NOT LIKE '%%://%%'
        """
    )
    uses = {}
    for row in rows:
        uses[row["path"]] = uses.get(row["path"], 0) + 1
    picture = copies._picture_key(copies.episode_key)
    groups, owners = {}, {}
    for row in rows:
        base = picture(row)
        owners[row["id"]] = (base, row)
        if base:
            item = _video_item(row, base, kind="episode")
            span = row.get("file_span")
            item["shared"] = uses.get(row["path"], 0) > 1 or (isinstance(span, list) and len(span) > 1)
            groups.setdefault(base, []).append(item)
    extras = db.fetchall(
        """
        SELECT c.episode_id::text AS owner_id, c.path, f.path AS file_path, f.height, f.bitrate_mbps, f.size_bytes,
               f.source_format, f.video_source, f.hdr_format, f.is_3d, f.stereo_mode, f.probe_error, f.probed_at,
               f.integrity, f.integrity_size, f.integrity_mtime, f.mtime
        FROM episode_copies c LEFT JOIN video_files f ON f.id = c.file_id
        """
    )
    for extra in extras:
        base, owner = owners.get(extra["owner_id"], (None, None))
        if not base:
            continue
        merged = {**owner, **extra, "path": extra["path"], "file_path": extra.get("file_path") or extra["path"]}
        item = _video_item(merged, base, item_id=f"file:{extra['path']}", kind="episode")
        item["extra"] = True
        item["pair_id"] = extra["owner_id"]
        groups.setdefault(base, []).append(item)
    return [items for items in groups.values() if len(items) > 1 and any(
        item.get("duplicate_release") or item.get("upgrade_source_id") or item.get("upgrade_copy_path") for item in items)]


def _musicvideo_groups():
    """Music videos of one artist and title more than once. A locked one is left alone by choose_video."""
    from resonance.fields import norm_name

    rows = db.fetchall(
        """
        SELECT mv.id::text AS id, mv.path, mv.title, mv.artist, mv.locked, f.path AS file_path, f.height, f.bitrate_mbps,
               f.size_bytes, f.source_format, f.video_source, f.hdr_format, f.is_3d, f.stereo_mode, f.probe_error,
               f.probed_at, f.integrity, f.integrity_size, f.integrity_mtime, f.mtime
        FROM music_videos mv LEFT JOIN video_files f ON f.id = mv.file_id
        """
    )
    groups = {}
    for row in rows:
        key = (norm_name(row["artist"]), norm_name(row["title"]))
        if key[0] and key[1]:
            groups.setdefault(key, []).append(_video_item(row, key, kind="musicvideo"))
    return [items for items in groups.values() if len(items) > 1]


def _album_groups():
    from resonance.fields import norm_name
    from resonance.quality import copy_kind
    from resonance.upgrade import version_label

    rows = db.fetchall(
        """
        SELECT al.id::text AS id, al.title, al.path, al.type, al.edition, al.quality_rank, al.locked,
               al.duplicate_release, al.upgrade_source_id, al.musicbrainz_release_group_id, ar.name AS artist_name,
               (SELECT count(*)::int FROM tracks t WHERE t.album_id = al.id) AS track_count
        FROM albums al JOIN artists ar ON ar.id = al.artist_id
        """
    )
    groups = {}
    for row in rows:
        key = (norm_name(row["artist_name"]), norm_name(row["title"]), copy_kind(row, "duplicate"),
               version_label(row.get("edition"), "", row.get("type")))
        if key[0] and key[1]:
            groups.setdefault(key, []).append({**dict(row), "kind": "album", "release_group": str(row.get("musicbrainz_release_group_id") or "")})
    wanted = [items for items in groups.values() if len(items) > 1 and any(
        item.get("duplicate_release") or item.get("upgrade_source_id") for item in items)]
    ids = [item["id"] for items in wanted for item in items]
    if ids:
        tracks, sizes = {}, {}
        for track in db.fetchall("SELECT album_id::text AS album_id, title, file_size FROM tracks WHERE album_id = ANY(%s::uuid[])",
                                 (db.uuid_array(ids),)):
            tracks.setdefault(track["album_id"], []).append(track)
            sizes[track["album_id"]] = sizes.get(track["album_id"], 0) + int(track.get("file_size") or 0)
        for items in wanted:
            for item in items:
                item["track_titles"] = _titles(tracks.get(item["id"], []))
                item["size_bytes"] = sizes.get(item["id"], 0)
    return wanted


def _label(item):
    if item.get("kind") == "musicvideo":
        return f"{item.get('artist')} — {item.get('title')}"
    if item.get("kind") == "album":
        return f"{item.get('artist_name')} — {item.get('title')}"
    if item.get("kind") == "episode":
        return f"{item.get('show_title')} S{int(item.get('season_number') or 0):02d}E{int(item.get('episode_number') or 0):02d}"
    return f"{item.get('title')} ({item['year']})" if item.get("year") else str(item.get("title") or "")


def _public(item, reason=""):
    return {"id": item["id"], "kind": item.get("kind"), "path": item.get("path") or "", "file": item.get("file_path") or "",
            "size_bytes": int(item.get("size_bytes") or 0),
            "reason": reason, "in_use": _in_use(item), "arr": (item.get("arr") or {}).get("app") or ""}


def _dismissed(kind):
    if kind == "musicvideo":
        return set()        # a locked music video is the way to say "this is not a duplicate"
    if kind == "album":
        rows = db.fetchall("SELECT album_a::text AS a, album_b::text AS b FROM dismissed_album_duplicates")
        return {frozenset((row["a"], row["b"])) for row in rows}
    return copies._dismissed_pairs(kind)


def build_plan(media=MEDIA, include_upgrades=False):
    """Nothing is touched here. Returns {"groups": [...], "count", "bytes", "skipped"}."""
    from curator import arr_ids

    groups = []
    readers = (("movies", _movie_groups, arr_ids.movie_groups, choose_video, "movie"),
               ("tv", _episode_groups, arr_ids.episode_groups, choose_video, "episode"),
               ("music", _album_groups, arr_ids.album_groups, choose_album, "album"),
               ("musicvideos", _musicvideo_groups, lambda groups: None, choose_video, "musicvideo"))
    for name, read, label, choose, kind in readers:
        if name not in media:
            continue
        found = read()
        if found:
            _say(f"Asking which copies the apps use ({name})")
            label(found)
        dismissed = _dismissed(kind)
        for items in found:
            keeper, remove, skipped = choose(items, include_upgrades, dismissed)
            if not remove and not skipped:
                continue
            groups.append({
                "id": str(uuid.uuid4()), "media": name, "label": _label(items[0]),
                "keep": _public(keeper) if keeper else None,
                "remove": [_public(item, reason) for item, reason in remove],
                "skipped": [_public(item, reason) for item, reason in skipped],
            })
    groups.sort(key=lambda group: (group["media"], group["label"].casefold()))
    return {
        "groups": groups, "include_upgrades": bool(include_upgrades),
        "count": sum(len(group["remove"]) for group in groups),
        "skipped": sum(len(group["skipped"]) for group in groups),
        "bytes": sum(item["size_bytes"] for group in groups for item in group["remove"]),
    }


# Running

def start_preview(media, include_upgrades):
    wanted = [name for name in media or [] if name in MEDIA]
    if not wanted:
        raise AppError("Pick at least one library", 400)
    with _lock:
        if _state["status"] in ("planning", "running"):
            return False
        _log.clear()
        _state.update({"status": "planning", "message": "Comparing copies", "plan": None, "token": "", "result": {}, "processed": 0, "total": 0})
    threading.Thread(target=_preview, args=(wanted, include_upgrades), name="cleanup-preview", daemon=True).start()
    return True


def _preview(media, include_upgrades):
    try:
        plan = build_plan(media, include_upgrades)
        with _lock:
            _state.update({"status": "ready", "plan": plan, "token": str(uuid.uuid4()),
                           "message": f"{plan['count']} copies can be deleted."})
    except Exception as exc:
        logger.exception("bulk cleanup preview failed")
        with _lock:
            _state.update({"status": "failed", "message": str(exc)})


def start_run(token, skip_groups=()):
    """Delete what the shown preview listed. token must be that preview's, so an old window cannot delete anything."""
    from resonance import scan_queue

    with _lock:
        if _state["status"] != "ready" or not token or token != _state["token"]:
            raise AppError("That preview is out of date. Preview again.", 409)
        plan = _state["plan"]
    if not scan_queue.hold():
        raise AppError("Wait for the running scan, scrape or file job to finish", 409)
    with _lock:
        _state.update({"status": "running", "token": "", "processed": 0, "message": "Deleting"})
    skip = {str(item) for item in skip_groups or []}
    threading.Thread(target=_run, args=(plan, skip), name="cleanup-run", daemon=True).start()
    return True


def _delete_one(item):
    from curator.routes.scrape import ItemsBody, delete_items
    from resonance import upgrade

    if item["kind"] == "album":
        upgrade.discard(item["id"])
        return None
    if item["kind"] == "musicvideo":
        from curator.video import musicvideos

        errors = musicvideos.delete([item["id"]]).get("errors") or []
        return errors[0] if errors else None
    result = delete_items(ItemsBody(kind=item["kind"], ids=[item["id"]], keep_copy=True))
    errors = result.get("errors") or []
    return errors[0] if errors else None


def _keeper_present(group):
    keep = group.get("keep") or {}
    target = keep.get("file") or keep.get("path")      # a movie's path is its folder: the file itself must still be there
    return bool(target) and os.path.exists(target)


def run_plan(plan, skip=()):
    """Delete in the calling thread. A group whose kept copy has gone since the preview is left alone."""
    deleted = failed = freed = 0
    video, music = set(), set()
    groups = [group for group in plan["groups"] if group["id"] not in skip and group["remove"]]
    total = sum(len(group["remove"]) for group in groups)
    done = 0
    from resonance import backup

    # One snapshot for the whole run: each delete below is one item, which never reaches the setting's minimum alone.
    backup.snapshot_before("a bulk duplicate cleanup", total)
    with history.why(REASON):
        for group in groups:
            if not _keeper_present(group):
                _say(f"{group['label']}: the copy to keep is gone, so nothing was deleted")
                failed += len(group["remove"])
                done += len(group["remove"])
                continue
            # A second file of an episode goes first, so its episode cannot promote it after the main file goes.
            for item in sorted(group["remove"], key=lambda row: 0 if str(row["id"]).startswith("file:") else 1):
                done += 1
                _say(f"Deleting {done}/{total}: {group['label']}", processed=done, total=total)
                try:
                    error = _delete_one(item)
                except (AppError, OSError) as exc:
                    error = str(exc)
                except Exception as exc:     # one bad item must not stop the rest, or leave the list half done
                    logger.exception("bulk cleanup could not delete %s", item.get("path"))
                    error = f"Unexpected error: {exc}"
                if error:
                    failed += 1
                    _say(f"{group['label']}: {error}")
                    continue
                deleted += 1
                freed += item["size_bytes"]
                (music if item["kind"] == "album" else video).add(os.path.dirname(item["path"]))
                _say(f"Deleted {item['path']} (kept {group['keep']['path']})")
    try:
        from curator import notify

        if video:
            notify.request("video", folders=sorted(video), clean=True, trigger="Bulk duplicate cleanup")
        if music:
            notify.request("music", folders=sorted(music), clean=True, trigger="Bulk duplicate cleanup")
    except Exception:
        logger.info("the library update after the cleanup was not sent", exc_info=True)
    history.record("cleanup", f"{deleted} copies deleted", detail=f"{failed} failed, {freed} bytes freed")
    return {"deleted": deleted, "failed": failed, "bytes": freed}


def _run(plan, skip):
    from resonance import scan_queue

    try:
        result = run_plan(plan, skip)
        final, message = "done", f"Deleted {result['deleted']} copies" + (f", {result['failed']} failed" if result["failed"] else "")
    except Exception as exc:
        logger.exception("bulk cleanup failed")
        result, final, message = {}, "failed", str(exc)
    finally:
        scan_queue.finished()
    _say(message)
    with _lock:
        _state.update({"status": final, "message": message, "result": result, "plan": None})
