"""Disk space per library folder: free space, what the library uses, growth over time, and what could be freed.

One row per library folder per day goes into disk_usage_history (at startup, twice a day, and when the dashboard is
opened), so the growth chart fills in over time. "Could be freed" lists the weaker copies the duplicate and upgrade
marks already found: a movie or episode with Upgrade available, the other copy of a Duplicate, an episode's weaker
extra file, and an album with a better copy.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import date, timedelta

from resonance import db

logger = logging.getLogger(__name__)

CHECK_HOURS = 1
GIB = 1024 ** 3
_timer = {"thread": None}
_warned = {}


def library_folders():
    """[(kind, folder)] for every mounted library folder."""
    from curator import folders
    from resonance.paths import music_roots

    found = []
    for kind in ("movies", "tv"):
        found += [(kind, root) for root in folders.mounted(kind)]
    found += [("music", os.path.realpath(root)) for root in music_roots()]
    found += [("musicvideos", root) for root in folders.mounted("musicvideos")]
    seen, unique = set(), []
    for kind, root in found:
        if root and root not in seen:
            seen.add(root)
            unique.append((kind, root))
    return unique


def _library_bytes(kind, root):
    if kind == "musicvideos":
        sql = ("SELECT COALESCE(SUM(f.size_bytes), 0)::bigint AS n, count(*)::int AS items FROM music_videos m "
               "JOIN video_files f ON f.id = m.file_id WHERE m.root = %s")
    elif kind == "movies":
        sql = ("SELECT COALESCE(SUM(f.size_bytes), 0)::bigint AS n, count(*)::int AS items FROM movies m "
               "JOIN video_files f ON f.id = m.file_id WHERE m.root = %s")
    elif kind == "tv":
        sql = ("SELECT COALESCE(SUM(f.size_bytes), 0)::bigint AS n, count(*)::int AS items FROM tv_episodes e "
               "JOIN tv_shows s ON s.id = e.show_id JOIN video_files f ON f.id = e.file_id WHERE s.root = %s")
    else:
        from resonance.paths import like_prefix

        row = db.fetchone(
            "SELECT COALESCE(SUM(file_size), 0)::bigint AS n, count(DISTINCT album_id)::int AS items FROM tracks "
            "WHERE file_path LIKE %s ESCAPE '\\'",
            (like_prefix(root),),
        ) or {}
        return int(row.get("n") or 0), int(row.get("items") or 0)
    row = db.fetchone(sql, (root,)) or {}
    return int(row.get("n") or 0), int(row.get("items") or 0)


def usage():
    """One entry per library folder: the drive's size and free space, and what the library holds there."""
    rows = []
    for kind, root in library_folders():
        try:
            disk = shutil.disk_usage(root)
            total, free = disk.total, disk.free
        except OSError:
            total = free = 0
        used, items = _library_bytes(kind, root)
        rows.append({"kind": kind, "root": root, "total_bytes": total, "free_bytes": free,
                     "library_bytes": used, "items": items})
    return rows


def record(rows=None):
    """Store today's numbers (one row per folder per day). Never raises."""
    try:
        for row in rows if rows is not None else usage():
            db.execute(
                """
                INSERT INTO disk_usage_history (day, root, kind, total_bytes, free_bytes, library_bytes)
                VALUES (CURRENT_DATE, %s, %s, %s, %s, %s)
                ON CONFLICT (day, root) DO UPDATE SET total_bytes = EXCLUDED.total_bytes,
                    free_bytes = EXCLUDED.free_bytes, library_bytes = EXCLUDED.library_bytes, kind = EXCLUDED.kind
                """,
                (row["root"], row["kind"], row["total_bytes"], row["free_bytes"], row["library_bytes"]),
            )
    except Exception:
        logger.exception("could not record disk usage")


def check_low(rows=None):
    """Warn about drives under the limit, after freeing recycle bin space when that is switched on. Never raises."""
    from curator import outbound
    from resonance import history as activity, settings, trash

    try:
        cfg = settings.load() or {}
        limit = int(cfg.get("disk_alert_gb") or 0) * GIB
        if not limit:
            return []
        low = []
        for row in rows if rows is not None else usage():
            free = int(row.get("free_bytes") or 0)
            if not row.get("total_bytes") or free >= limit:
                continue
            if cfg.get("disk_alert_empty_bin"):
                freed = trash.free_space(row["root"], limit)
                if freed:
                    free = shutil.disk_usage(row["root"]).free
                    if free >= limit:
                        continue
            low.append(row["root"])
            today = date.today().isoformat()
            if _warned.get(row["root"]) != today:
                _warned[row["root"]] = today
                text = f"{row['root']} has {free / GIB:.1f} GB free, under the limit of {limit / GIB:.0f} GB."
                outbound.send("disk_low", "Library drive low on space", text, "warning")
                activity.record("alert", "Low disk space", "", row["root"], text)
        return low
    except Exception:
        logger.exception("could not check for low disk space")
        return []


def history(days=365):
    since = date.today() - timedelta(days=max(1, int(days)))
    rows = db.fetchall(
        "SELECT day, root, kind, free_bytes, library_bytes FROM disk_usage_history WHERE day >= %s ORDER BY day",
        (since,),
    )
    return [{**dict(row), "day": row["day"].isoformat()} for row in rows]


def savings(limit=40):
    """The weaker copies the duplicate and upgrade marks found, biggest first, with the folder each one is in."""
    found = []
    for row in db.fetchall(
        """
        SELECT m.id::text AS id, m.title, m.year, f.path AS path, f.size_bytes,
               CASE WHEN m.upgrade_source_id IS NOT NULL THEN 'upgrade' ELSE 'duplicate' END AS reason
        FROM movies m JOIN video_files f ON f.id = m.file_id
        WHERE m.upgrade_source_id IS NOT NULL OR m.duplicate_release
        """
    ):
        label = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        found.append({"kind": "movie", "id": row["id"], "label": label, "path": row["path"],
                      "size_bytes": int(row["size_bytes"] or 0), "reason": row["reason"]})
    for row in db.fetchall(
        """
        SELECT e.id::text AS id, s.title AS show_title, e.season_number, e.episode_number, e.path, f.size_bytes,
               CASE WHEN e.upgrade_source_id IS NOT NULL THEN 'upgrade' ELSE 'duplicate' END AS reason
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id JOIN video_files f ON f.id = e.file_id
        WHERE e.upgrade_source_id IS NOT NULL OR e.duplicate_release
        """
    ):
        found.append({"kind": "episode", "id": row["id"], "path": row["path"], "size_bytes": int(row["size_bytes"] or 0),
                      "label": f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}",
                      "reason": row["reason"]})
    for row in db.fetchall(
        """
        SELECT e.id::text AS episode_id, s.title AS show_title, e.season_number, e.episode_number, c.path, f.size_bytes
        FROM episode_copies c JOIN tv_episodes e ON e.id = c.episode_id JOIN tv_shows s ON s.id = e.show_id
        LEFT JOIN video_files f ON f.id = c.file_id
        WHERE COALESCE(e.upgrade_copy_path, '') = '' OR e.upgrade_copy_path <> c.path
        """
    ):
        found.append({"kind": "episode", "id": f"file:{row['path']}", "path": row["path"],
                      "size_bytes": int(row["size_bytes"] or 0), "reason": "extra copy",
                      "label": f"{row['show_title']} S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"})
    for row in db.fetchall(
        """
        SELECT al.id::text AS id, al.title, ar.name AS artist, al.path,
               (SELECT COALESCE(SUM(t.file_size), 0) FROM tracks t WHERE t.album_id = al.id)::bigint AS size_bytes
        FROM albums al LEFT JOIN artists ar ON ar.id = al.artist_id
        WHERE al.upgrade_source_id IS NOT NULL
        """
    ):
        found.append({"kind": "album", "id": row["id"], "path": row["path"] or "", "size_bytes": int(row["size_bytes"] or 0),
                      "label": f"{row['artist']} — {row['title']}" if row.get("artist") else row["title"], "reason": "upgrade"})
    found.sort(key=lambda item: item["size_bytes"], reverse=True)
    folders = {}
    for item in found:
        folder = os.path.dirname(item["path"] or "")
        entry = folders.setdefault(folder, {"folder": folder, "size_bytes": 0, "count": 0})
        entry["size_bytes"] += item["size_bytes"]
        entry["count"] += 1
    top_folders = sorted(folders.values(), key=lambda entry: entry["size_bytes"], reverse=True)[:limit]
    return {"items": found[:limit], "folders": top_folders, "total_bytes": sum(item["size_bytes"] for item in found),
            "count": len(found)}


def dashboard():
    from resonance import settings, trash

    rows = usage()
    record(rows)
    bins = trash.size_by_root()
    limit = int((settings.load() or {}).get("disk_alert_gb") or 0) * GIB
    for row in rows:
        row["trash_bytes"] = bins.get(row["root"], 0)
        row["low"] = bool(limit and row.get("total_bytes") and row["free_bytes"] < limit)
    return {"folders": rows, "history": history(), "savings": savings()}


def start_timer():
    if _timer["thread"] and _timer["thread"].is_alive():
        return

    def loop():
        stop = threading.Event()
        while True:
            rows = usage()
            record(rows)
            check_low(rows)
            stop.wait(CHECK_HOURS * 3600)

    _timer["thread"] = threading.Thread(target=loop, name="disk-usage", daemon=True)
    _timer["thread"].start()
