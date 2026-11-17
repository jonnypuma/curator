"""The stages of a movie or TV scan after the files are read: artwork notes, subtitles, trailers, themes, .nfo files, copy marks."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, CancelledError, ThreadPoolExecutor, wait as wait_futures
from curator.video import activity, artwork, mediainfo_xml, naming, nfo, probe, store
import os
import threading


def _log_saved_artwork(job, roots, targets=None, season_id=None, episode_id=None):
    """Log the .nfo files and artwork stored while folders and files were read."""
    from resonance import db

    roots = [root for root in roots if root]
    if not roots:
        job.log("Saved artwork: no library folder")
        return
    folders = scanner._artwork_folders(roots, targets, season_id, episode_id)
    if folders is not None and not folders:
        job.log("Saved artwork: none")
        return
    limit, limit_params = ("", [])
    if folders:
        limit, limit_params = scanner._under_clause("path" if job.media == "movies" else "h.path", folders)
        limit = " AND " + limit
    if job.media == "movies":
        nfos = db.fetchone(
            f"""
            SELECT count(*) FILTER (WHERE nfo_path IS NOT NULL)::int AS nfo
            FROM movies
            WHERE root = ANY(%s){limit}
            """,
            (roots, *limit_params),
        ) or {}
        rows = db.fetchall(
            f"""
            SELECT art.key, count(*)::int AS n
            FROM movies m
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(m.artwork, '{{}}'::jsonb)) AS art(key, value)
            WHERE m.root = ANY(%s){limit.replace("path", "m.path")}
              AND btrim(art.value) <> ''
            GROUP BY art.key
            """,
            (roots, *limit_params),
        )
    else:
        show_limit = limit.replace("h.path", "path")
        nfos = db.fetchone(
            f"""
            SELECT
                (SELECT count(*)::int FROM tv_shows WHERE root = ANY(%s){show_limit} AND nfo_path IS NOT NULL) AS show_nfo,
                (SELECT count(*)::int FROM tv_seasons s
                    JOIN tv_shows h ON h.id = s.show_id
                    WHERE h.root = ANY(%s){limit} AND s.nfo_path IS NOT NULL) AS season_nfo,
                (SELECT count(*)::int FROM tv_episodes e
                    JOIN tv_shows h ON h.id = e.show_id
                    WHERE h.root = ANY(%s){limit} AND e.nfo_path IS NOT NULL) AS episode_nfo
            """,
            (roots, *limit_params, roots, *limit_params, roots, *limit_params),
        ) or {}
        rows = db.fetchall(
            f"""
            SELECT art.key, count(*)::int AS n
            FROM (
                SELECT h.artwork
                FROM tv_shows h
                WHERE h.root = ANY(%s){limit}
                UNION ALL
                SELECT s.artwork
                FROM tv_seasons s
                JOIN tv_shows h ON h.id = s.show_id
                WHERE h.root = ANY(%s){limit}
                UNION ALL
                SELECT e.artwork
                FROM tv_episodes e
                JOIN tv_shows h ON h.id = e.show_id
                WHERE h.root = ANY(%s){limit}
            ) items
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(items.artwork, '{{}}'::jsonb)) AS art(key, value)
            WHERE btrim(art.value) <> ''
            GROUP BY art.key
            """,
            (roots, *limit_params, roots, *limit_params, roots, *limit_params),
        )
    job.log(scanner._artwork_report(job.media, nfos, scanner._bucket_artwork(rows)))


def _refresh_replaced(job):
    """Download artwork that is still missing, then write the new release into the .nfo."""
    movies, episodes = job.replaced()
    if not movies and not episodes:
        return
    from curator.video import config, exports, scrape

    cfg = config.current()
    scrape.fill_replaced_artwork(job, movies, episodes)
    if job.cancelled:
        return
    written = 0
    for movie_id in movies:
        if job.cancelled:
            return
        try:
            if exports.write_movie(movie_id, cfg, "overwrite"):
                written += 1
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
    for show_id, episode_ids in episodes.items():
        if job.cancelled:
            return
        try:
            written += len(exports.write_show(show_id, cfg, "overwrite", episode_ids, True) or [])
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
    if written:
        job.count("nfo", written)
        job.log(f"NFO: rewrote {written} after a replaced file")


def _shows_just_scanned(targets, season_id):
    """Show ids a folder or season deep scan just walked, and the one season when that is all it walked."""
    if season_id:
        season = store.season_row(season_id)
        if not season:
            return [], None
        return [str(season["show_id"])], {int(season["season_number"])}
    return store.show_ids_by_path(targets or []), None


def _trailers_enabled(job, cfg):
    if job.media == "tv":
        return bool(cfg.get("scan_download_tv_trailers"))
    return bool(cfg.get("scan_download_trailers"))


def _themes_enabled(job, cfg):
    if job.media == "tv":
        return bool(cfg.get("scan_download_tv_themes"))
    return bool(cfg.get("scan_download_themes"))


def _subtitles_enabled(job, cfg):
    return bool(cfg.get("subs_download_tv" if job.media == "tv" else "subs_download_movies"))


def _subtitle_units(job, roots, db):
    """Movie or episode ids this scan covers: new and changed ones for an incremental scan, otherwise every one."""
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND COALESCE(path, '') <> ''", (ids,))
        else:
            rows = db.fetchall("SELECT id FROM movies WHERE root = ANY(%s) AND COALESCE(path, '') <> ''", (list(roots),))
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        # Only the episodes this scan added or read again, not every episode of their shows.
        episode_ids = job.changed_episode_ids()
        if not episode_ids:
            return []
        rows = db.fetchall(
            "SELECT id FROM tv_episodes WHERE id = ANY(%s::uuid[]) AND COALESCE(path, '') <> '' AND NOT missing "
            "ORDER BY season_number, episode_number", (episode_ids,),
        )
    else:
        rows = db.fetchall(
            "SELECT e.id FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id "
            "WHERE s.root = ANY(%s) AND COALESCE(e.path, '') <> '' ORDER BY s.sort_title, e.season_number, e.episode_number",
            (list(roots),),
        )
    return [("episode", str(row["id"])) for row in rows]


def _subtitles_from_scan(job, roots):
    """Download missing subtitles from OpenSubtitles.com for the wanted languages."""
    from curator.video import config, opensubs
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _subtitles_enabled(job, cfg):
        return
    if not opensubs.can_download(cfg):
        job.log("Subtitles: set the OpenSubtitles API key, username and password in Settings to download them")
        return
    units = _subtitle_units(job, roots, db)
    if not units:
        job.log("Subtitles: nothing to look up")
        return
    saved = failed = 0
    remaining = None
    job.progress(message=f"Subtitles 0/{len(units)}", processed=0, total=len(units), phase="subtitles", force=True)
    for index, (kind, item_id) in enumerate(units, start=1):
        if job.cancelled:
            return
        job.progress(message=f"Subtitles {index}/{len(units)}", processed=index, total=len(units), phase="subtitles")
        try:
            got, left = opensubs.auto_item(cfg, kind, item_id, job.log)
            saved += got
            if left is not None:
                remaining = left
        except opensubs.QuotaError as exc:
            job.log(f"Subtitles: {exc}. The rest wait for the next scan")
            break
        except AppError as exc:
            failed += 1
            job.log(f"Subtitles: {exc}")
            if exc.status == 401:
                break
    job.count("subtitles", saved)
    if failed:
        job.count("subtitle_failed", failed)
    job.log(f"Subtitles: {saved} saved" + (f". {remaining} OpenSubtitles download{'s' if remaining != 1 else ''} left today" if remaining is not None else ""))


def _original_language_from_scan(job):
    """Switch new and changed dubbed releases to the original language, when that is switched on."""
    from curator.video import config, original_language

    cfg = config.current()
    kind = "movie" if job.media == "movies" else "episode"
    if not original_language.enabled(cfg, kind):
        return
    ids = job.changed_ids() if kind == "movie" else job.changed_episode_ids()
    if not ids:
        return
    changed = 0
    for row in original_language.targets(kind, ids):
        if job.cancelled:
            return
        try:
            changed += bool(original_language.apply(row, cfg, lambda line: job.log(f"Original language: {line}")))
        except Exception as exc:
            job.log(f"Original language: {row['label']}: {exc}")
    if changed:
        job.log(f"Original language: {changed} file{'s' if changed != 1 else ''} switched to the original audio")


def _fix_art_shapes_from_scan(job, roots):
    """Artwork of the wrong shape for its type (a fanart saved as the poster) gets the picture the artwork window
    suggests for that type. The files of the movies or shows this scan looked at are checked on disk first; only an
    item with a wrong shape is looked up online. Uploaded or kept pictures and locked items are left alone."""
    from curator.video import art_pick, art_shape, clean_fanart, config

    cfg = config.current()
    suffix = "tv" if job.media == "tv" else "movies"
    if not cfg.get(f"scan_fix_art_shape_{suffix}", True):
        return
    kind = "show" if job.media == "tv" else "movie"
    ids = job.changed_ids() if job.mode == "incremental" else store.ids_in(job.media, roots, "all")
    ids = [str(item) for item in dict.fromkeys(ids or [])]
    if not ids:
        return
    table = "tv_shows" if kind == "show" else "movies"
    rows = store_db().fetchall(f"SELECT id, title, artwork, locked FROM {table} WHERE id = ANY(%s::uuid[])", (ids,))
    # The sizes come from the database (the artwork map keeps them); only a file without a stored size is opened, once.
    todo = []
    for row in rows:
        if job.cancelled:
            return
        if row.get("locked"):
            continue
        found = clean_fanart._checked(kind, str(row["id"]), row.get("artwork") or {})
        below = clean_fanart.wrong_below(kind, str(row["id"])) if kind == "show" else []
        if found or below:
            todo.append(str(row["id"]))
            notes = [f"{art_type} {art_shape.describe(art_type, size)}" for art_type, _path, size in found]
            notes += [f"{label} {', '.join(name for name, _path, _size in clean_fanart.wrong_shapes(level, art))}"
                      for level, _id, label, art in below]
            job.log(f"Artwork shape: {row.get('title') or row['id']}: {'; '.join(notes)}")
    if not todo:
        if kind == "movie":
            _fix_set_art_shapes(job, cfg)
        return
    if not cfg.get("tmdb_key"):
        job.log(f"Artwork shape: {len(todo)} with the wrong shape left as they are, no TMDB API key under Settings, General")
        return
    job.progress(message=f"Artwork shape 0/{len(todo)}", processed=0, total=len(todo), phase="cleanart", force=True)
    changed = 0
    with art_pick.batched_player_art(players=[]):          # the scan's last step tells the players
        for index, item_id in enumerate(todo, start=1):
            if job.cancelled:
                break
            try:
                if clean_fanart.replace(kind, item_id, cfg, lambda line: job.log(f"Artwork shape: {line}"),
                                        art_types=[clean_fanart.WRONG_SHAPE], fill_missing=False):
                    changed += 1
            except Exception as exc:
                job.log(f"Artwork shape: {item_id} failed: {exc}")
            job.progress(message=f"Artwork shape {index}/{len(todo)}", processed=index, total=len(todo), phase="cleanart")
    job.log(f"Artwork shape: {changed} of {len(todo)} {'shows' if kind == 'show' else 'movies'} with the wrong shape fixed")
    if kind == "movie":
        _fix_set_art_shapes(job, cfg)


def _fix_set_art_shapes(job, cfg):
    """Movie sets have no scan of their own: their artwork is checked with the movies."""
    from curator.video import art_pick, clean_fanart

    if not cfg.get("set_folder") or not cfg.get("tmdb_key") or not cfg.get("scan_fix_art_shape_sets", True):
        return
    rows = store_db().fetchall("SELECT id, name, artwork, locked FROM movie_sets")
    todo = [str(row["id"]) for row in rows
            if not row.get("locked") and clean_fanart._checked("set", str(row["id"]), row.get("artwork") or {})]
    changed = 0
    with art_pick.batched_player_art(players=[]):
        for item_id in todo:
            if job.cancelled:
                break
            try:
                if clean_fanart.replace("set", item_id, cfg, lambda line: job.log(f"Artwork shape: {line}"),
                                        art_types=[clean_fanart.WRONG_SHAPE], fill_missing=False):
                    changed += 1
            except Exception as exc:
                job.log(f"Artwork shape: set {item_id} failed: {exc}")
    if todo:
        job.log(f"Artwork shape: {changed} of {len(todo)} movie sets with the wrong shape fixed")


def _clean_art_from_scan(job, roots):
    """Clean artwork as a scan stage, after the artwork lookup and before the .nfo files: the Clean artwork job (only
    pictures with a title or logo on them; extra fanart repeats) for the movies or shows this scan looked at. An item
    whose fanart and character art were already picked or cleaned (their source is recorded) is skipped without asking
    TMDB, unless extra fanart is ticked. The players hear of the new pictures through the scan's own last step
    (Update client libraries for items with updated artwork)."""
    from curator.video import art_pick, clean_fanart, config

    cfg = config.current()
    suffix = "tv" if job.media == "tv" else "movies"
    if not cfg.get(f"scan_clean_art_{suffix}"):
        return
    if not cfg.get("tmdb_key"):
        job.log("Clean artwork: skipped, no TMDB API key under Settings, General")
        return
    kind = "show" if job.media == "tv" else "movie"
    types = list(cfg.get(f"scan_clean_art_types_{suffix}") or ["fanart"])
    if job.mode == "incremental":
        ids = job.changed_ids()
    else:
        ids = store.ids_in(job.media, roots, "all")
    ids = [str(item) for item in dict.fromkeys(ids or [])]
    if not ids:
        return
    table = "tv_shows" if kind == "show" else "movies"
    rows = {str(row["id"]): row for row in store_db().fetchall(
        f"SELECT id, artwork, locked FROM {table} WHERE id = ANY(%s::uuid[])", (ids,))}
    todo = []
    for item_id in ids:
        row = rows.get(item_id)
        if not row or row.get("locked"):
            continue
        sources = (row.get("artwork") or {}).get("_sources") or {}
        single = [name for name in types if name != "extrafanart"]
        if "extrafanart" not in types and single and all(sources.get(name) for name in single):
            continue
        todo.append(item_id)
    if not todo:
        job.log(f"Clean artwork: nothing to do ({', '.join(types)})")
        return
    job.progress(message=f"Clean artwork 0/{len(todo)}", processed=0, total=len(todo), phase="cleanart", force=True)
    changed = 0
    # The scan's last step tells the players; this stage does not queue its own refreshes.
    with art_pick.batched_player_art(players=[]):
        for index, item_id in enumerate(todo, start=1):
            if job.cancelled:
                break
            try:
                if clean_fanart.replace(kind, item_id, cfg, lambda line: job.log(f"Clean artwork: {line}"), art_types=types,
                                        fill_missing=False):
                    changed += 1
            except Exception as exc:
                job.log(f"Clean artwork: {item_id} failed: {exc}")
            job.progress(message=f"Clean artwork {index}/{len(todo)}", processed=index, total=len(todo), phase="cleanart")
    job.log(f"Clean artwork: {changed} of {len(todo)} {'shows' if kind == 'show' else 'movies'} changed ({', '.join(types)})")


def store_db():
    from resonance import db

    return db


def _fill_and_trailers(job, roots):
    """Look up metadata and artwork, and download trailers and theme songs during that same stretch."""
    from curator.video import config

    cfg = config.current()
    job.scan_trailers = _trailers_enabled(job, cfg)
    job.scan_themes = _themes_enabled(job, cfg)
    thread = None
    if job.scan_trailers and cfg.get("scan_fill_missing", True):
        thread = threading.Thread(
            target=_trailers_from_scan, args=(job, roots), kwargs={"alongside": True},
            name="scan-trailers", daemon=True,
        )
        thread.start()
    theme_thread = None
    if job.scan_themes and cfg.get("scan_fill_missing", True):
        theme_thread = threading.Thread(
            target=_themes_from_scan, args=(job, roots), kwargs={"alongside": True},
            name="scan-themes", daemon=True,
        )
        theme_thread.start()
    _fill_from_scan(job, roots)
    if thread:
        thread.join()
    elif job.scan_trailers and not job.cancelled:
        _trailers_from_scan(job, roots)
    if theme_thread:
        theme_thread.join()
    elif job.scan_themes and not job.cancelled:
        _themes_from_scan(job, roots)


def _fill_from_scan(job, roots):
    """Same idea as the music scan: local files first, then missing metadata and artwork."""
    from curator.video import config, scrape

    cfg = config.current()
    if not cfg.get("scan_fill_missing", True):
        job.log("Metadata and artwork during a scan are off in Settings")
        return
    if job.mode == "incremental":
        ids = job.changed_ids()
    elif job.mode == "deep":
        ids = store.ids_in(job.media, roots, "all")
    else:
        ids = list(dict.fromkeys([*store.ids_with_gaps(job.media, roots, cfg), *job.changed_ids()]))
    scrape.fill_during_scan(job, ids, limited=bool(cfg.get("scan_limited_art")))


def _trailers_from_scan(job, roots, alongside=False):
    """Download YouTube trailers that are already known and not on disk yet.

    alongside keeps the lookup progress on screen. Several trailers download at once.
    """
    from curator.video import config, trailers
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _trailers_enabled(job, cfg):
        return
    units = _trailer_units(job, roots, db)
    if job.cancelled:
        return
    if not units:
        job.log("Trailers: nothing to download")
        if not alongside:
            job.progress(message="Trailers: nothing to download", phase="trailers", force=True)
        return
    saved = skipped = 0
    counts = threading.Lock()
    workers = max(1, min(len(units), int(cfg.get("concurrency") or 4)))
    if alongside:
        with scanner._lock:
            scanner._state["trailers_alongside"] = True
            scanner._state["trailers_done"] = False
    if not alongside:
        job.progress(message=f"Trailers 0/{len(units)}", processed=0, total=len(units), phase="trailers", force=True)
    else:
        job.log(f"Trailers: downloading {len(units)} while the lookup runs")

    def one(index_unit):
        nonlocal saved, skipped
        index, unit = index_unit
        if job.cancelled:
            return
        kind, item_id = unit[0], unit[1]
        show_id = unit[2] if len(unit) > 2 else None
        if not alongside:
            job.progress(message=f"Trailers {index}/{len(units)}", processed=index, total=len(units), phase="trailers")
        try:
            with activity.holding() as hold:
                hold(item_id, show_id)
                path = trailers.download(kind, item_id, cfg, job.log, quiet_skip=True)
        except AppError as exc:
            job.log(str(exc))
            job.count("trailer_failed")
            return
        with counts:
            if path:
                saved += 1
                job.count("trailers")
            else:
                skipped += 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trailer") as pool:
        list(pool.map(one, enumerate(units, start=1)))
    if alongside:
        with scanner._lock:
            scanner._state["trailers_alongside"] = False
            scanner._state["trailers_done"] = True
    job.log(f"Trailers: {saved} saved, {skipped} already on disk or without a YouTube link")


def _trailer_units(job, roots, db):
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall(
                "SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
                (ids,),
            )
        else:
            rows = db.fetchall(
                "SELECT id FROM movies WHERE root = ANY(%s) AND COALESCE(trailer, '') <> ''",
                (list(roots),),
            )
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        show_ids = job.changed_ids()
        if not show_ids:
            return []
        shows = db.fetchall(
            "SELECT id FROM tv_shows WHERE id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
            (show_ids,),
        )
        seasons = db.fetchall(
            "SELECT id, show_id FROM tv_seasons WHERE show_id = ANY(%s::uuid[]) AND COALESCE(trailer, '') <> ''",
            (show_ids,),
        )
    else:
        shows = db.fetchall(
            "SELECT id FROM tv_shows WHERE root = ANY(%s) AND COALESCE(trailer, '') <> ''",
            (list(roots),),
        )
        seasons = db.fetchall(
            """
            SELECT x.id, x.show_id FROM tv_seasons x
            JOIN tv_shows s ON s.id = x.show_id
            WHERE s.root = ANY(%s) AND COALESCE(x.trailer, '') <> ''
            """,
            (list(roots),),
        )
    return [("show", str(row["id"])) for row in shows] + [
        ("season", str(row["id"]), str(row["show_id"])) for row in seasons
    ]


def _themes_from_scan(job, roots, alongside=False):
    """Download theme songs (theme.mp3) for movies or shows that do not have one on disk yet."""
    from curator.video import config, trailers
    from resonance import db
    from resonance.errors import AppError

    cfg = config.current()
    if not _themes_enabled(job, cfg):
        return
    units = _theme_units(job, roots, db)
    if job.cancelled:
        return
    if not units:
        job.log("Theme songs: nothing to download")
        if not alongside:
            job.progress(message="Theme songs: nothing to download", phase="themes", force=True)
        return
    saved = skipped = 0
    counts = threading.Lock()
    workers = max(1, min(len(units), int(cfg.get("concurrency") or 4)))
    if not alongside:
        job.progress(message=f"Theme songs 0/{len(units)}", processed=0, total=len(units), phase="themes", force=True)
    else:
        job.log(f"Theme songs: checking {len(units)} while the lookup runs")

    def one(index_unit):
        nonlocal saved, skipped
        index, unit = index_unit
        if job.cancelled:
            return
        kind, item_id = unit[0], unit[1]
        if not alongside:
            job.progress(message=f"Theme songs {index}/{len(units)}", processed=index, total=len(units), phase="themes")
        try:
            with activity.holding() as hold:
                hold(item_id)
                path = trailers.download_theme(kind, item_id, cfg, job.log, quiet_skip=True)
        except AppError as exc:
            job.log(str(exc))
            job.count("theme_failed")
            return
        with counts:
            if path:
                saved += 1
                job.count("themes")
            else:
                skipped += 1

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="theme") as pool:
        list(pool.map(one, enumerate(units, start=1)))
    job.log(f"Theme songs: {saved} saved, {skipped} already on disk")


def _theme_units(job, roots, db):
    if job.media == "movies":
        if job.mode == "incremental":
            ids = job.changed_ids()
            if not ids:
                return []
            rows = db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[])", (ids,))
        else:
            rows = db.fetchall("SELECT id FROM movies WHERE root = ANY(%s)", (list(roots),))
        return [("movie", str(row["id"])) for row in rows]
    if job.mode == "incremental":
        show_ids = job.changed_ids()
        if not show_ids:
            return []
        shows = db.fetchall("SELECT id FROM tv_shows WHERE id = ANY(%s::uuid[])", (show_ids,))
    else:
        shows = db.fetchall("SELECT id FROM tv_shows WHERE root = ANY(%s)", (list(roots),))
    return [("show", str(row["id"])) for row in shows]


def _generate_missing_ep_thumbs(job, roots):
    """Generate episode thumbnails using ffmpeg for episodes that have no thumb file.

    Enabled by the scan_generate_ep_thumb setting (default: on).
    Samples from ~40% into the file, skips black frames.
    """
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile
    from curator.video import config
    from resonance import db

    cfg = config.current()
    if not cfg.get("scan_generate_ep_thumb", True):
        return
    if not _shutil.which("ffmpeg") or not _shutil.which("ffprobe"):
        job.log("Episode thumb generation skipped: ffmpeg not found")
        return

    # An incremental scan only looks at the episodes it added or read again; full and deep check them all.
    only = ""
    params = [db.text_array(roots)]
    if job.mode == "incremental":
        episode_ids = job.changed_episode_ids()
        if not episode_ids:
            return
        only = "AND e.id = ANY(%s::uuid[])"
        params.append(db.uuid_array(episode_ids))
    rows = db.fetchall(
        f"""
        SELECT e.id, e.path, e.season_number, e.episode_number,
               e.artwork
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        WHERE s.root = ANY(%s)
          AND e.path IS NOT NULL
          AND e.path NOT LIKE 'missing://%%'
          AND e.path NOT LIKE 'wanted://%%'
          AND e.status IS DISTINCT FROM 'IGNORED'
          {only}
        ORDER BY e.path
        """,
        params,
    )
    from collections import Counter

    per_file = Counter(str(row.get("path") or "") for row in rows)
    need_thumb = []
    for row in rows:
        art = row.get("artwork") or {}
        if art.get("thumb") and os.path.isfile(str(art["thumb"])):
            continue
        path = str(row.get("path") or "")
        if not path or not os.path.isfile(path):
            continue
        folder = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        season_num = row.get("season_number")
        ep_num = row.get("episode_number")
        if season_num is not None and ep_num is not None and per_file[path] > 1:
            ep_mark = naming.episode_mark(season_num, ep_num)
            thumb_name = f"{stem}-{ep_mark}-thumb.jpg" if ep_mark else f"{stem}-thumb.jpg"
        else:
            thumb_name = f"{stem}-thumb.jpg"
        thumb_path = os.path.join(folder, thumb_name)
        if os.path.isfile(thumb_path):
            continue
        need_thumb.append((row, path, thumb_path))

    if not need_thumb:
        return

    job.progress(message=f"Generating episode thumbs 0/{len(need_thumb)}", processed=0, total=len(need_thumb), phase="nfo", force=True)
    for index, (row, vid_path, thumb_path) in enumerate(need_thumb, start=1):
        if job.cancelled:
            break
        try:
            from curator.video import framegrab

            info = framegrab.probe(vid_path)
            if info["duration"] < 30:
                continue
            with _tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                if framegrab.grab(vid_path, tmp_path, info):
                    _shutil.move(tmp_path, thumb_path)
                    store.set_artwork("tv_episodes", row["id"], {**(row.get("artwork") or {}), "thumb": thumb_path})
                else:
                    job.log(f"Episode thumb: no frame from {os.path.basename(vid_path)}")
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception as exc:
            job.log(f"Episode thumb: {os.path.basename(vid_path)}: {exc}")
        job.progress(message=f"Generating episode thumbs {index}/{len(need_thumb)}", processed=index, total=len(need_thumb), phase="nfo")


def _nfos_from_scan(job, roots, targets=None):
    """Write an .nfo for anything that does not have one. Optionally replace the ones that do."""
    from curator.video import config, exports

    cfg = config.current()
    # Rewrite all is for full and deep scans. An incremental scan (and a webhook import) writes only missing files.
    rewrite = bool(cfg.get("scan_rewrite_nfo")) and job.mode in {"full", "deep"}
    policy = "overwrite" if rewrite else "missing"
    ids = store.ids_for_nfo(job.media, roots, targets or None, rewrite)
    if job.cancelled:
        return
    if not ids:
        job.log("NFO: nothing to write")
        job.progress(message="NFO", processed=1, total=1, phase="nfo", force=True)
        return
    label = "Rewriting .nfo" if rewrite else "Writing missing .nfo"
    written = 0
    same = 0
    job.progress(message=f"{label} 0/{len(ids)}", processed=0, total=len(ids), phase="nfo", force=True)
    for index, item_id in enumerate(ids, start=1):
        if job.cancelled:
            return
        job.progress(message=f"{label} {index}/{len(ids)}", processed=index, total=len(ids), phase="nfo")
        try:
            with activity.holding() as hold:
                hold(item_id)
                made = exports.write_movie(item_id, cfg, policy) if job.media == "movies" else exports.write_show(item_id, cfg, policy)
        except Exception as exc:
            job.log(f"Could not write .nfo: {exc}")
            continue
        made = [made] if isinstance(made, str) else list(made or [])
        if made:
            written += len(made)
            job.count("nfo", len(made))
        else:
            same += 1
    # A file that already held the same text is not written again (nfo_write.write compares first).
    unchanged = f", {same} {'item' if same == 1 else 'items'} already up to date" if same else ""
    job.log(f"NFO: {written} written{unchanged}.")


def _note_copies(job):
    from curator.video import copies

    try:
        count = None
        if job.mode == "incremental":
            count = _note_copies_incremental(job, copies)
        if count is None:
            count = copies.refresh_movies() if job.media == "movies" else copies.refresh_episodes()
        if count:
            job.log(f"Catalogue: {count} items have a higher-quality copy")
    except Exception as exc:
        job.log(f"Could not record duplicates and upgrades: {exc}")


COPIES_SEED_LIMIT = 2000


def _note_copies_incremental(job, copies):
    """Duplicate and upgrade marks for what an incremental scan touched, or None to check the whole library.

    The seeds are the items this scan added or read again, plus every item that already carries a mark: when a copy
    left the library, the copy that is still marked is how its group gets looked at again. A scan that touched very
    many items checks everything at once instead, which is quicker than a long list of identities.
    """
    from resonance import db

    if job.media == "movies":
        ids = job.changed_ids()
        marked = "SELECT id::text AS id FROM movies WHERE duplicate_release OR upgrade_source_id IS NOT NULL"
    else:
        ids = job.changed_episode_ids()
        marked = ("SELECT id::text AS id FROM tv_episodes WHERE duplicate_release OR upgrade_source_id IS NOT NULL"
                  " OR COALESCE(upgrade_copy_path, '') <> ''")
    ids = list(dict.fromkeys([*ids, *(row["id"] for row in db.fetchall(marked))]))
    if len(ids) > COPIES_SEED_LIMIT:
        return None
    if not ids:
        return 0
    if job.media == "movies":
        return copies.refresh_movie_seeds(copies.movie_seed_rows(ids))
    return copies.refresh_episode_seeds(copies.episode_seed_rows(ids))

# Imported last: the old module imports this one's names, so importing it first must not start a cycle.
from curator.video import scanner  # noqa: E402
