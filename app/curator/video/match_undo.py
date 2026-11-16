"""Undo Fix Match: put a movie or show back the way it was before its last Fix Match.

Fix Match points an item at another provider id and then re-scrapes it with overwrite on, which replaces its metadata,
seasons, missing episodes, artwork and .nfo files. Just before the new ids are written (store_edits.set_match, on the
direct and the queued path alike) this saves:

- the rows, as Postgres sees them (to_jsonb): the movie, or the show with every season and episode;
- a copy of the artwork and .nfo files Curator keeps next to the item, and the names of those files in each folder.

Undo writes the rows back with jsonb_populate_record (every column type stays exact), except the columns a scan owns
(paths, the video file, missing). Episodes and seasons the Fix Match added are dropped when they hold no file; a
placeholder it removed comes back. The copied files go back over the new ones, and artwork or .nfo files the Fix Match
added go to the recycle bin. Video files are never touched. One snapshot per item is kept, for seven days.
"""
from __future__ import annotations

import logging
import os
import shutil

from psycopg.types.json import Jsonb

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

KEEP_DAYS = 7
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tbn", ".gif"}
NFO_EXT = {".nfo"}
# Columns a scan owns: Undo leaves them as they are now.
SCAN_OWNED = {"id", "path", "root", "folder", "parts", "file_id", "created_at", "missing", "file_span"}


def _store_dir(item_id):
    from resonance.paths import cache_dir

    return os.path.join(cache_dir(), "match-undo", str(item_id))


def _owned(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXT | NFO_EXT


def _names(folder):
    try:
        with os.scandir(folder) as entries:
            return sorted(entry.name for entry in entries if entry.is_file() and _owned(entry.name))
    except OSError:
        return None


def _movie_scope(row):
    """(folders, name filter) for a movie: its whole folder when the movie has it to itself, else its own files."""
    folder = row.get("folder") or os.path.dirname(row.get("path") or "")
    share = db.fetchone("SELECT count(*)::int AS n FROM movies WHERE folder = %s AND NOT COALESCE(wanted, FALSE)", (folder,))
    if share and share["n"] <= 1:
        return [folder], None
    stems = []
    for part in [row.get("path") or "", *(row.get("parts") or [])]:
        stem = os.path.splitext(os.path.basename(str(part)))[0].lower()
        if stem:
            stems.append(stem)
    return [folder], lambda name: any(name.lower().startswith(stem) and name[len(stem):len(stem) + 1] in ".-" for stem in stems)


def _show_scope(show, episodes, seasons):
    folders = [show.get("path") or ""]
    for row in [*episodes, *seasons]:
        path = str(row.get("path") or "")
        if not path or "://" in path:
            continue
        folder = path if row in seasons else os.path.dirname(path)
        if folder and folder not in folders:
            folders.append(folder)
    return [folder for folder in folders if folder], None


def _files(folders, keep):
    before = {}
    for folder in folders:
        names = _names(folder)
        if names is None:
            continue
        before[folder] = [name for name in names if keep is None or keep(name)]
    return before


def _prune():
    rows = db.fetchall(
        "DELETE FROM match_undo WHERE taken_at < LOCALTIMESTAMP - %s * interval '1 day' RETURNING item_id::text AS id",
        (KEEP_DAYS,),
    )
    for row in rows or []:
        shutil.rmtree(_store_dir(row["id"]), ignore_errors=True)


def snapshot(kind, item_id):
    """Save the item before Fix Match changes it. Never raises: a failed snapshot only means no Undo."""
    try:
        _prune()
        item_id = str(item_id)
        if kind == "movie":
            row = db.fetchone("SELECT to_jsonb(m) AS row FROM movies m WHERE id = %s", (item_id,))
            if not row:
                return False
            data = {"movie": row["row"]}
            folders, keep = _movie_scope(row["row"])
            label = row["row"].get("title") or ""
        elif kind == "show":
            row = db.fetchone("SELECT to_jsonb(s) AS row FROM tv_shows s WHERE id = %s", (item_id,))
            if not row:
                return False
            seasons = [item["row"] for item in db.fetchall("SELECT to_jsonb(x) AS row FROM tv_seasons x WHERE show_id = %s", (item_id,))]
            episodes = [item["row"] for item in db.fetchall("SELECT to_jsonb(e) AS row FROM tv_episodes e WHERE show_id = %s", (item_id,))]
            data = {"show": row["row"], "seasons": seasons, "episodes": episodes}
            folders, keep = _show_scope(row["row"], episodes, seasons)
            label = row["row"].get("title") or ""
        else:
            return False
        before = _files(folders, keep)
        store = _store_dir(item_id)
        shutil.rmtree(store, ignore_errors=True)
        os.makedirs(store, exist_ok=True)
        saved = []
        for folder, names in before.items():
            for name in names:
                source = os.path.join(folder, name)
                target = os.path.join(store, f"{len(saved):05d}{os.path.splitext(name)[1].lower()}")
                try:
                    shutil.copy2(source, target)
                    saved.append({"path": source, "saved": target})
                except OSError as exc:
                    logger.info("Fix Match undo could not copy %s: %s", source, exc)
        data["files"] = saved
        data["before"] = before
        db.execute(
            """
            INSERT INTO match_undo (item_id, kind, label, taken_at, data) VALUES (%s, %s, %s, LOCALTIMESTAMP, %s)
            ON CONFLICT (item_id) DO UPDATE SET kind = EXCLUDED.kind, label = EXCLUDED.label,
                taken_at = EXCLUDED.taken_at, data = EXCLUDED.data
            """,
            (item_id, kind, label, Jsonb(data)),
        )
        return True
    except Exception:
        logger.exception("could not save the state before Fix Match for %s %s", kind, item_id)
        return False


def available(item_id):
    """{"taken_at", "label"} when this item can be put back, else None."""
    row = db.fetchone(
        "SELECT taken_at, label FROM match_undo WHERE item_id = %s AND taken_at >= LOCALTIMESTAMP - %s * interval '1 day'",
        (str(item_id), KEEP_DAYS),
    )
    return {"taken_at": row["taken_at"], "label": row["label"]} if row else None


def _columns(conn, table):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [row["column_name"] for row in rows]


def _restore_row(conn, table, columns, snapshot_row):
    keep = [column for column in columns if column not in SCAN_OWNED]
    targets = ", ".join(f'"{column}"' for column in keep)
    values = ", ".join(f'r."{column}"' for column in keep)
    return conn.execute(
        f"UPDATE {table} AS t SET ({targets}) = (SELECT {values} FROM jsonb_populate_record(NULL::{table}, %s::jsonb) AS r) "
        "WHERE t.id = %s RETURNING t.id",
        (Jsonb(snapshot_row), snapshot_row["id"]),
    ).fetchone()


def _insert_row(conn, table, snapshot_row):
    conn.execute(
        f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, %s::jsonb) ON CONFLICT DO NOTHING",
        (Jsonb(snapshot_row),),
    )


def _restore_movie(conn, data):
    movie = dict(data["movie"])
    if movie.get("set_id") and not conn.execute("SELECT 1 FROM movie_sets WHERE id = %s", (movie["set_id"],)).fetchone():
        movie["set_id"] = None            # the set it was in is gone since
    if not _restore_row(conn, "movies", _columns(conn, "movies"), movie):
        raise AppError("That movie is gone", 404)
    conn.execute("UPDATE movies SET updated_at = NOW() WHERE id = %s", (movie["id"],))
    return movie["id"]


def _restore_show(conn, data):
    show = data["show"]
    show_id = show["id"]
    if not _restore_row(conn, "tv_shows", _columns(conn, "tv_shows"), show):
        raise AppError("That show is gone", 404)
    season_cols, episode_cols = _columns(conn, "tv_seasons"), _columns(conn, "tv_episodes")
    old_seasons = {str(row["id"]): row for row in data.get("seasons") or []}
    old_episodes = {str(row["id"]): row for row in data.get("episodes") or []}
    # Placeholders the Fix Match added (missing episodes of the new match) go first, so restored numbers do not clash.
    added = conn.execute(
        "DELETE FROM tv_episodes WHERE show_id = %s AND missing AND NOT (id::text = ANY(%s)) RETURNING id",
        (show_id, list(old_episodes)),
    ).fetchall()
    # Numbers are unique per show and the new match may have moved them around: park the rows on numbers no real
    # episode or season has, then write the old numbers back one by one without clashing.
    conn.execute(
        "UPDATE tv_episodes e SET episode_number = -1000000 - t.n FROM ("
        "SELECT id, row_number() OVER (ORDER BY id) AS n FROM tv_episodes WHERE show_id = %s AND id::text = ANY(%s)) t "
        "WHERE e.id = t.id",
        (show_id, list(old_episodes)),
    )
    conn.execute(
        "UPDATE tv_seasons x SET season_number = -1000000 - t.n FROM ("
        "SELECT id, row_number() OVER (ORDER BY id) AS n FROM tv_seasons WHERE show_id = %s AND id::text = ANY(%s)) t "
        "WHERE x.id = t.id",
        (show_id, list(old_seasons)),
    )
    for season_id, row in old_seasons.items():
        if not _restore_row(conn, "tv_seasons", season_cols, row):
            _insert_row(conn, "tv_seasons", row)
    for episode_id, row in old_episodes.items():
        if not _restore_row(conn, "tv_episodes", episode_cols, row) and row.get("missing"):
            _insert_row(conn, "tv_episodes", row)          # a placeholder the Fix Match removed
    # Seasons the Fix Match added, now empty.
    conn.execute(
        "DELETE FROM tv_seasons x WHERE show_id = %s AND NOT (id::text = ANY(%s)) "
        "AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = x.id)",
        (show_id, list(old_seasons)),
    )
    for table in ("tv_shows", "tv_seasons", "tv_episodes"):
        column = "id" if table == "tv_shows" else "show_id"
        conn.execute(f"UPDATE {table} SET updated_at = NOW() WHERE {column} = %s", (show_id,))
    return show_id, len(added)


def _restore_files(data):
    """Copied files go back; artwork and .nfo files that appeared since go to the recycle bin. Returns (back, binned)."""
    from curator.video import writes
    from resonance import trash

    back = binned = 0
    for item in data.get("files") or []:
        try:
            writes.check(item["path"])
            if os.path.isfile(item["saved"]):
                shutil.copy2(item["saved"], item["path"])
                back += 1
        except (OSError, AppError) as exc:
            logger.info("Fix Match undo could not put back %s: %s", item.get("path"), exc)
    for folder, names in (data.get("before") or {}).items():
        now = _names(folder)
        if now is None:
            continue
        known = set(names)
        for name in now:
            if name in known:
                continue
            path = os.path.join(folder, name)
            try:
                writes.check(path)
                trash.discard(path, kind="video")
                binned += 1
            except (OSError, AppError) as exc:
                logger.info("Fix Match undo left %s: %s", path, exc)
    return back, binned


def undo(kind, item_id):
    """Put the item back. Returns a short summary; raises AppError when there is nothing to undo."""
    from curator.video import copies, scanner, scrape

    if scanner.running() or scrape.running():
        raise AppError("A scan or scrape is running. Undo Fix Match when it has finished.", 409)
    row = db.fetchone("SELECT kind, data FROM match_undo WHERE item_id = %s", (str(item_id),))
    if not row or row["kind"] != kind or not available(item_id):
        raise AppError("There is no Fix Match to undo for this item (they are kept for 7 days).", 404)
    data = row["data"]
    if kind == "movie":
        before = copies.movie_seed_rows([item_id])
        with db.transaction() as conn:
            _restore_movie(conn, data)
        removed = 0
    else:
        before = copies.episode_seeds_for_shows([item_id])
        with db.transaction() as conn:
            _, removed = _restore_show(conn, data)
    back, binned = _restore_files(data)
    db.execute("DELETE FROM match_undo WHERE item_id = %s", (str(item_id),))
    shutil.rmtree(_store_dir(item_id), ignore_errors=True)
    if kind == "movie":
        seeds = list(before) + list(copies.movie_seed_rows([item_id]))
        copies.refresh_movie_seeds(seeds)
        peers = copies.peer_flags("movie", seeds)
    else:
        seeds = list(before) + list(copies.episode_seeds_for_shows([item_id]))
        copies.refresh_episode_seeds(seeds)
        peers = copies.peer_flags("episode", seeds)
    from resonance import history

    history.record("restored", data.get("movie", data.get("show", {})).get("title") or "", kind,
                   data.get("movie", data.get("show", {})).get("path") or "",
                   f"Undo Fix Match: {back} files put back, {binned} new ones to the recycle bin")
    return {"restored": True, "files_back": back, "files_binned": binned, "placeholders_removed": removed, "peers": peers}
