"""Delete movies, shows, seasons and episodes from disk, with the same guards as the music delete.

A folder is only removed when it belongs to that one item: never a library folder, and never a folder
that holds another indexed movie or episode. Loose files are removed with their sidecars (.nfo,
artwork and subtitles that share the file name).
"""
from __future__ import annotations

import logging
import os
import shutil

from curator import folders
from curator.video import naming, store, writes
from resonance import db
from resonance.errors import AppError
from resonance.paths import inside, like_prefix, mount_writable
from resonance.upgrade import shared_folder_block

logger = logging.getLogger(__name__)

KINDS = ("movie", "show", "season", "episode", "set")


def _norm(path):
    return os.path.normcase(os.path.abspath(path or ""))


def _guard(path, root, kind):
    """Check that path sits inside a mounted folder of this type, is writable, and is not the folder itself."""
    if not path:
        raise AppError("The item has no path")
    mounted = folders.mounted(kind)
    real_root = os.path.realpath(root) if root else ""
    if real_root not in mounted:
        raise AppError("Its library folder is not mounted")
    real = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if not inside(real_root, real):
        raise AppError("It is outside its library folder")
    if _norm(real) == _norm(real_root):
        raise AppError("Refusing to delete a library folder")
    writes.check(real)
    if not mount_writable(real):
        raise AppError("The folder is mounted read-only", 403)
    return real


def _remove_tree(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isfile(path):
        os.remove(path)


def stems_for(files):
    """File stems whose sidecars belong to these files. Stacked parts also claim the shared name (Movie for Movie-cd1)."""
    stems = []
    for path in files:
        name = os.path.basename(path)
        stems.append(os.path.splitext(name)[0])
        stacked = naming.stack_key(name)
        if stacked and len(files) > 1:
            match = naming._STACK.match(os.path.splitext(name)[0])
            head = (match.group(1) or "").strip(" ._-") if match else ""
            if head:
                stems.append(head)
    return [stem for stem in dict.fromkeys(stems) if stem]


def sidecars(folder, stems, protected):
    """Files in folder named after one of stems (stem.nfo, stem-poster.jpg, stem.en.srt).

    protected holds the paths of other indexed video files in the same folder. A sidecar that also matches
    a longer protected stem (Movie-2.nfo when deleting Movie) belongs to that file and is kept.
    """
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    own = [stem.lower() for stem in stems]
    others = [os.path.splitext(os.path.basename(path))[0].lower() for path in protected]
    keep = {_norm(path) for path in protected}
    found = []
    for name in sorted(names):
        full = os.path.join(folder, name)
        if _norm(full) in keep or not os.path.isfile(full):
            continue
        lowered = name.lower()
        for stem in own:
            if not (lowered.startswith(stem) and len(lowered) > len(stem) and lowered[len(stem)] in ".-"):
                continue
            if any(len(other) > len(stem) and lowered.startswith(other) and lowered[len(other):len(other) + 1] in ("", ".", "-")
                   for other in others):
                break
            found.append(full)
            break
    return found


def _remove_files(files):
    removed = 0
    for path in files:
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    return removed


def _indexed_videos(folder, exclude_ids, table):
    """Indexed video file paths in one folder, apart from the rows being deleted."""
    if table == "movies":
        rows = db.fetchall("SELECT parts, path FROM movies WHERE folder = %s AND NOT (id = ANY(%s::uuid[]))",
                           (folder, list(exclude_ids)))
        paths = []
        for row in rows:
            paths.extend(row.get("parts") or [row.get("path")])
        return [path for path in paths if path]
    rows = db.fetchall("SELECT path FROM tv_episodes WHERE path LIKE %s AND NOT (id = ANY(%s::uuid[]))",
                       (like_prefix(folder), list(exclude_ids)))
    return [row["path"] for row in rows if os.path.dirname(row["path"]) == folder]


def _other_media_paths(exclude_kind=None, exclude_ids=None):
    """Collect paths of all indexed items across movies, tv_shows, tv_episodes, and albums."""
    paths = []
    exclude_ids = list(exclude_ids or [])

    if exclude_kind == "movie" and exclude_ids:
        rows = db.fetchall("SELECT path, folder, parts FROM movies WHERE NOT (id = ANY(%s::uuid[]))", (exclude_ids,))
    else:
        rows = db.fetchall("SELECT path, folder, parts FROM movies")
    for r in rows:
        if r.get("path"):
            paths.append(r["path"])
        if r.get("folder"):
            paths.append(r["folder"])
        for p in (r.get("parts") or []):
            if p:
                paths.append(p)

    if exclude_kind == "show" and exclude_ids:
        rows = db.fetchall("SELECT path FROM tv_shows WHERE NOT (id = ANY(%s::uuid[]))", (exclude_ids,))
    else:
        rows = db.fetchall("SELECT path FROM tv_shows")
    for r in rows:
        if r.get("path"):
            paths.append(r["path"])

    if exclude_kind == "episode" and exclude_ids:
        rows = db.fetchall("SELECT path FROM tv_episodes WHERE NOT (id = ANY(%s::uuid[]))", (exclude_ids,))
    else:
        rows = db.fetchall("SELECT path FROM tv_episodes")
    for r in rows:
        if r.get("path"):
            paths.append(r["path"])

    try:
        album_rows = db.fetchall("SELECT path FROM albums")
        for r in album_rows:
            if r.get("path"):
                paths.append(r["path"])
    except Exception:
        pass

    return paths


def delete_movie(movie_id):
    row = db.fetchone("SELECT id, title, year, path, folder, root, parts FROM movies WHERE id = %s", (movie_id,))
    if not row:
        raise AppError("Movie not found", 404)
    title = store.title_of("movies", movie_id)
    path, folder = row.get("path") or "", row.get("folder") or ""
    own_folder = path and folder and _norm(path) == _norm(folder)
    if own_folder:
        real = _guard(folder, row.get("root"), "movies")
        others = _other_media_paths(exclude_kind="movie", exclude_ids=[movie_id])
        blocked = shared_folder_block(real, others)
        if blocked:
            raise AppError(blocked.replace("album", "media item"))
        _remove_tree(real)
    else:
        parts = [part for part in (row.get("parts") or [path]) if part]
        for part in parts:
            _guard(part, row.get("root"), "movies")
        protected = _indexed_videos(folder, [movie_id], "movies")
        if any(_norm(part) in {_norm(item) for item in protected} for part in parts):
            raise AppError("Another indexed movie uses the same file")
        _remove_files(parts + sidecars(folder, stems_for(parts), protected))
    with db.transaction() as conn:
        conn.execute("DELETE FROM video_dismissed_duplicates WHERE kind = 'movie' AND (left_id = %s OR right_id = %s)", (movie_id, movie_id))
        conn.execute("DELETE FROM movies WHERE id = %s", (movie_id,))
    return title


def delete_show(show_id):
    row = db.fetchone("SELECT id, path, root FROM tv_shows WHERE id = %s", (show_id,))
    if not row:
        raise AppError("Show not found", 404)
    title = store.title_of("tv_shows", show_id)
    real = _guard(row.get("path"), row.get("root"), "tv")
    others = _other_media_paths(exclude_kind="show", exclude_ids=[show_id])
    blocked = shared_folder_block(real, others)
    if blocked:
        raise AppError(blocked.replace("album", "media item"))
    _remove_tree(real)
    db.execute("DELETE FROM tv_shows WHERE id = %s", (show_id,))
    return title


def season_art(show_path, number):
    """Season artwork kept in the show folder (season01-poster.jpg, season-specials-poster.jpg)."""
    prefixes = ["season-specials-", "season-specials."] if number == 0 else []
    prefixes += [f"season{number:02d}-", f"season{number:02d}."]
    try:
        names = os.listdir(show_path)
    except OSError:
        return []
    return [os.path.join(show_path, name) for name in sorted(names)
            if name.lower().startswith(tuple(prefixes)) and naming.ext(name) in naming.IMAGE_EXTS]


def delete_season(season_id):
    row = db.fetchone(
        """
        SELECT x.id, x.season_number, x.path, s.id AS show_id, s.path AS show_path, s.root, s.title
        FROM tv_seasons x JOIN tv_shows s ON s.id = x.show_id WHERE x.id = %s
        """,
        (season_id,),
    )
    if not row:
        raise AppError("Season not found", 404)
    number = row["season_number"]
    title = f"{row['title']} {'Specials' if number == 0 else f'season {number}'}"
    episodes = db.fetchall("SELECT id, path FROM tv_episodes WHERE season_id = %s", (season_id,))
    own_ids = [str(item["id"]) for item in episodes]
    folder = row.get("path") or ""
    if folder and _norm(folder) != _norm(row["show_path"]):
        real = _guard(folder, row["root"], "tv")
        others = _other_media_paths(exclude_kind="episode", exclude_ids=own_ids)
        blocked = shared_folder_block(real, others)
        if blocked:
            raise AppError(blocked.replace("album", "media item"))
        _remove_tree(real)
    else:
        _delete_episode_files([item["path"] for item in episodes], own_ids, row["root"])
    _remove_files([path for path in season_art(row["show_path"], number) if writes.check(path)])
    db.execute("DELETE FROM tv_seasons WHERE id = %s", (season_id,))
    return title


def _delete_episode_files(paths, own_ids, root):
    by_folder = {}
    for path in dict.fromkeys(path for path in paths if path):
        _guard(path, root, "tv")
        by_folder.setdefault(os.path.dirname(path), []).append(path)
    for folder, files in by_folder.items():
        protected = _indexed_videos(folder, own_ids, "tv_episodes")
        if any(_norm(path) in {_norm(item) for item in protected} for path in files):
            raise AppError("Another indexed episode uses the same file")
        _remove_files(files + sidecars(folder, stems_for(files), protected))


def delete_episode(episode_id, allowed_ids=None):
    row = db.fetchone(
        """
        SELECT e.id, e.path, e.show_id, e.season_number, e.episode_number, s.root, s.title
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE e.id = %s
        """,
        (episode_id,),
    )
    if not row:
        raise AppError("Episode not found", 404)
    if row.get("path"):
        sharing = db.fetchall(
            "SELECT id FROM tv_episodes WHERE path = %s AND id <> %s",
            (row["path"], episode_id),
        )
        sharing_ids = [str(item["id"]) for item in sharing]
        if sharing_ids:
            allowed = {str(i) for i in (allowed_ids or [episode_id])}
            if not set(sharing_ids).issubset(allowed):
                raise AppError("Another indexed episode uses the same file")
        movie_sharing = db.fetchone(
            "SELECT id FROM movies WHERE path = %s OR %s = ANY(parts)",
            (row["path"], row["path"]),
        )
        if movie_sharing:
            raise AppError("An indexed movie uses the same file")
        own_ids = [str(episode_id)] + sharing_ids
        _delete_episode_files([row["path"]], own_ids, row["root"])
    with db.transaction() as conn:
        conn.execute("DELETE FROM video_dismissed_duplicates WHERE kind = 'episode' AND (left_id = %s OR right_id = %s)", (episode_id, episode_id))
        conn.execute("DELETE FROM tv_episodes WHERE id = %s", (episode_id,))
        conn.execute(
            "DELETE FROM tv_seasons x WHERE x.show_id = %s AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = x.id)",
            (row["show_id"],),
        )
    return f"{row['title']} S{row['season_number']:02d}E{row['episode_number']:02d}"


def delete_set(set_id):
    """Remove the set folder (artwork and set.nfo) and the set row. Movies stay."""
    row = store.set_row(set_id)
    if not row:
        raise AppError("Set not found", 404)
    _remove_set_folder(row)
    name = row.get("name") or "Set"
    db.execute("DELETE FROM movie_sets WHERE id = %s", (set_id,))
    return name


def _remove_set_folder(row):
    from curator.video import config, sets

    root = (config.current().get("set_folder") or "").strip()
    folder = row.get("folder") or ""
    if not folder and root:
        folder = sets.folder_for(root, row.get("name") or "")
    if not folder or not os.path.isdir(folder):
        return
    if not root:
        raise AppError("No movie set folder is configured, so the set files were left in place")
    real_root = os.path.realpath(root)
    real = os.path.realpath(folder)
    if not inside(real_root, real) or _norm(real) == _norm(real_root):
        raise AppError("The set folder is outside the movie set information folder")
    others = _other_media_paths()
    blocked = shared_folder_block(real, others)
    if blocked:
        raise AppError(f"Cannot remove set folder: {blocked.replace('album', 'media item')}")
    shutil.rmtree(real)


HANDLERS = {"movie": delete_movie, "show": delete_show, "season": delete_season, "episode": delete_episode, "set": delete_set}


def _id_list(rows, key):
    found = []
    for row in rows:
        value = row.get(key)
        if value and value not in found:
            found.append(value)
    return found


def _mark_seeds(kind, ids):
    """Rows that identify the duplicate group, read before the delete removes them."""
    from curator.video import copies

    if kind == "movie":
        return copies.movie_seed_rows(ids)
    if kind == "episode":
        return copies.episode_seed_rows(ids)
    if kind == "season":
        return copies.episode_seeds_for_seasons(ids)
    if kind == "show":
        return copies.episode_seeds_for_shows(ids)
    return []


def _leftover_files(kind, ids):
    """Video file and movie set ids that may have no owner after this delete."""
    file_ids, set_ids, paths = [], [], []
    if kind == "movie":
        rows = db.fetchall(
            "SELECT file_id, set_id, path, parts FROM movies WHERE id = ANY(%s::uuid[])",
            (list(ids),),
        )
        file_ids = _id_list(rows, "file_id")
        set_ids = _id_list(rows, "set_id")
        for row in rows:
            if row.get("path"):
                paths.append(row["path"])
            paths.extend(part for part in (row.get("parts") or []) if part)
    elif kind == "episode":
        rows = db.fetchall(
            """
            SELECT id, file_id, path FROM tv_episodes
            WHERE id = ANY(%s::uuid[])
               OR (show_id, path) IN (
                    SELECT show_id, path FROM tv_episodes
                    WHERE id = ANY(%s::uuid[]) AND COALESCE(path, '') <> ''
               )
            """,
            (list(ids), list(ids)),
        )
        file_ids = _id_list(rows, "file_id")
        episode_ids = _id_list(rows, "id")
        if episode_ids:
            copies = db.fetchall(
                "SELECT file_id FROM episode_copies WHERE episode_id = ANY(%s::uuid[])",
                (episode_ids,),
            )
            file_ids.extend(item for item in _id_list(copies, "file_id") if item not in file_ids)
            paths.extend(row["path"] for row in rows if row.get("path"))
    elif kind in {"season", "show"}:
        column = "season_id" if kind == "season" else "show_id"
        rows = db.fetchall(
            f"SELECT id, file_id, path FROM tv_episodes WHERE {column} = ANY(%s::uuid[])",
            (list(ids),),
        )
        file_ids = _id_list(rows, "file_id")
        episode_ids = _id_list(rows, "id")
        if episode_ids:
            copies = db.fetchall(
                "SELECT file_id FROM episode_copies WHERE episode_id = ANY(%s::uuid[])",
                (episode_ids,),
            )
            file_ids.extend(item for item in _id_list(copies, "file_id") if item not in file_ids)
        paths.extend(row["path"] for row in rows if row.get("path"))
    if paths:
        found = db.fetchall("SELECT id FROM video_files WHERE path = ANY(%s::text[])", (paths,))
        file_ids.extend(item for item in _id_list(found, "id") if item not in file_ids)
    return file_ids, set_ids


def _release_files(file_ids):
    if not file_ids:
        return
    db.execute(
        """
        DELETE FROM video_files f
        WHERE f.id = ANY(%s::uuid[])
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.file_id = f.id OR f.path = ANY(m.parts))
          AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.file_id = f.id)
          AND NOT EXISTS (SELECT 1 FROM episode_copies c WHERE c.file_id = f.id)
        """,
        (list(file_ids),),
    )


def _release_sets(set_ids):
    if not set_ids:
        return
    db.execute(
        """
        DELETE FROM movie_sets s
        WHERE s.id = ANY(%s::uuid[])
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.set_id = s.id)
        """,
        (list(set_ids),),
    )


def delete_items(kind, ids):
    """Delete each item, carrying on after a refusal. Returns the deleted titles and one line per error."""
    handler = HANDLERS.get(kind)
    if not handler:
        raise AppError("Unknown item type", 400)
    seeds = _mark_seeds(kind, ids)
    file_ids, set_ids = _leftover_files(kind, ids)
    deleted, errors, gone, peers = [], [], [], []
    for item_id in ids:
        try:
            title = handler(item_id, allowed_ids=ids) if kind == "episode" else handler(item_id)
            deleted.append(title)
            gone.append(str(item_id))
            logger.info("Deleted %s from disk: %s", kind, title)
        except AppError as exc:
            logger.info("refused to delete %s %s: %s", kind, item_id, exc)
            errors.append(f"{_label(kind, item_id)}: {exc}")
        except OSError as exc:
            logger.warning("delete of %s %s failed: %s", kind, item_id, exc)
            errors.append(f"{_label(kind, item_id)}: {exc.strerror or exc}")
    if deleted:
        _release_files(file_ids)
        _release_sets(set_ids)
        from curator.video import copies

        if kind == "movie":
            copies.refresh_movie_seeds(seeds)
            peers = copies.peer_flags("movie", seeds)
        elif kind in {"episode", "season", "show"}:
            copies.refresh_episode_seeds(seeds)
            peers = copies.peer_flags("episode", seeds)
        rescan_arr_after_delete(kind, seeds)
    return {"deleted": deleted, "errors": errors, "ids": gone, "peers": peers}


def rescan_arr_after_delete(kind, seeds):
    """Tell Radarr or Sonarr to rescan if surviving items exist, and clear arr_ids cache."""
    try:
        from curator import arr_ids

        if kind == "movie":
            from curator import radarr

            arr_ids.clear_cache("radarr")
            tmdb_ids = {str(s.get("tmdb_id") or "").strip() for s in (seeds or []) if str(s.get("tmdb_id") or "").strip()}
            for tmdb in tmdb_ids:
                surviving = db.fetchone("SELECT id FROM movies WHERE btrim(tmdb_id) = %s LIMIT 1", (tmdb,))
                if surviving:
                    radarr.rescan_movie(tmdb_id=tmdb)
        elif kind in {"episode", "season", "show"}:
            from curator import sonarr

            arr_ids.clear_cache("sonarr")
            tvdb_ids = {str(s.get("tvdb_id") or "").strip() for s in (seeds or []) if str(s.get("tvdb_id") or "").strip()}
            for tvdb in tvdb_ids:
                surviving = db.fetchone(
                    """
                    SELECT e.id FROM tv_episodes e
                    JOIN tv_shows s ON s.id = e.show_id
                    WHERE btrim(s.tvdb_id) = %s LIMIT 1
                    """,
                    (tvdb,),
                )
                if surviving:
                    sonarr.rescan_series(tvdb_id=tvdb)
    except Exception as exc:
        logger.warning("Failed triggering *arr rescan after delete (%s): %s", kind, exc)



def label(kind, item_id):
    return _label(kind, item_id)


def _label(kind, item_id):
    table = {"movie": "movies", "show": "tv_shows", "episode": "tv_episodes", "set": "movie_sets"}.get(kind)
    if table:
        return store.title_of(table, item_id)
    return "Season"
