"""Postgres reads and writes for movies, movie sets, TV shows, seasons, episodes and video files."""
from __future__ import annotations

import json
import logging
import os

from psycopg.types.json import Jsonb

from curator.video import health
from resonance import db
from resonance.paths import like_prefix

logger = logging.getLogger(__name__)

PROBE_COLUMNS = (
    "container", "duration_seconds", "bitrate_mbps", "video_bitrate_mbps", "video_codec", "video_profile",
    "width", "height", "resolution", "fps", "aspect_ratio", "bit_depth", "hdr_format", "hdr_secondary",
    "is_hybrid", "dovi_profile", "dovi_el_type", "dovi_bl_compat", "max_cll", "max_fall", "is_3d", "stereo_mode",
    "video_source", "source_format", "edition", "chapters", "audio_tracks", "subtitle_tracks", "probe_error",
)
JSON_COLUMNS = {
    "audio_tracks", "subtitle_tracks", "external_subtitles", "actors", "ids", "ratings", "artwork", "certifications",
    "season_names", "guest_stars", "file_span",
}
LOCKABLE = {"movies", "tv_shows", "tv_episodes", "movie_sets"}
# File tracking follows the disk even on locked rows; everything else is metadata the lock protects.
TRACKING = {
    "path", "root", "folder", "file_id", "parts", "disc_format", "nfo_path", "nfo_mtime", "artwork",
    "show_id", "season_id", "season_number", "episode_number", "file_span", "missing",
}
TABLES = {"movie": "movies", "show": "tv_shows", "episode": "tv_episodes", "set": "movie_sets"}

RATING_COLUMNS = (
    ("imdb", "rating_imdb"),
    ("themoviedb", "rating_tmdb"),
    ("tomatometerallcritics", "rating_rt"),
    ("tomatometeravguseraudience", "rating_rt_audience"),
    ("metacritic", "rating_metacritic"),
    ("metacriticuser", "rating_metacritic_user"),
    ("trakt", "rating_trakt"),
    ("anilist", "rating_anilist"),
    ("ofdb", "rating_ofdb"),
    ("tvdb", "rating_tvdb"),
)
ID_COLUMNS = {
    "imdb": "imdb_id", "tmdb": "tmdb_id", "tvdb": "tvdb_id",
    "anilist": "anilist_id", "ofdb": "ofdb_id", "trakt": "trakt_id",
}
ID_ON_TABLE = {
    "movies": ("imdb_id", "tmdb_id", "anilist_id", "ofdb_id", "trakt_id"),
    "tv_shows": ("imdb_id", "tmdb_id", "tvdb_id", "anilist_id", "ofdb_id", "trakt_id"),
    "tv_episodes": ("anilist_id", "ofdb_id", "trakt_id"),
}


def project_source_columns(table, values):
    """Copy ratings and source ids out of the JSON fields into their own columns."""
    ratings = values.get("ratings")
    if isinstance(ratings, dict):
        for key, column in RATING_COLUMNS:
            row = ratings.get(key)
            raw = row.get("value") if isinstance(row, dict) else None
            if raw is None or raw == "":
                continue
            try:
                values[column] = round(float(raw), 2)
            except (TypeError, ValueError):
                continue
    ids = values.get("ids")
    allowed = set(ID_ON_TABLE.get(table) or ())
    if isinstance(ids, dict):
        for key, column in ID_COLUMNS.items():
            if column in allowed and ids.get(key):
                values[column] = str(ids[key])[:80]
    return values


def source_column_sql(alias):
    names = [column for _, column in RATING_COLUMNS] + ["anilist_id", "ofdb_id", "trakt_id"]
    return ", ".join(f"{alias}.{name}" for name in names)


def _value(column, value):
    return Jsonb(value) if column in JSON_COLUMNS else value


def _update_clause(table, column):
    if table == "video_files" and column == "release_group":
        return "release_group = COALESCE(EXCLUDED.release_group, video_files.release_group)"
    if table not in LOCKABLE or column in TRACKING:
        return f"{column} = EXCLUDED.{column}"
    return (f"{column} = CASE WHEN {table}.locked OR '{column}' = ANY({table}.locked_fields) "
            f"THEN {table}.{column} ELSE EXCLUDED.{column} END")


def _upsert(conn, table, keys, values):
    if table in ("movies", "tv_shows", "tv_episodes"):
        values = project_source_columns(table, dict(values))
    columns = list(values)
    updates = [_update_clause(table, column) for column in columns if column not in keys]
    updates.append("updated_at = NOW()")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {', '.join(updates)} "
        "RETURNING id, (xmax = 0) AS inserted"
    )
    row = conn.execute(sql, [_value(column, values[column]) for column in columns]).fetchone()
    return row["id"], bool(row["inserted"])


def _under(roots):
    clauses, params = [], []
    for root in roots:
        clauses.append("(path = %s OR path LIKE %s)")
        params.extend([root, like_prefix(root)])
    return " OR ".join(clauses) or "FALSE", params


def known_files(roots):
    where, params = _under(roots)
    rows = db.fetchall(
        f"SELECT id, path, size_bytes, mtime, probe_error, probed_at, duration_seconds FROM video_files WHERE {where}", params
    )
    return {row["path"]: row for row in rows}


# Column limits of video_files. A damaged file can report a duration or size far beyond them, and
# one such value made the whole INSERT fail with "integer out of range".
_INT_COLUMNS = {"duration_seconds", "width", "height", "bit_depth", "chapters"}
_NUMERIC_LIMITS = {"bitrate_mbps": 9_999_999.99, "video_bitrate_mbps": 9_999_999.99, "fps": 99_999.999}


def _fit_column(column, value):
    """The value, or None when it cannot fit its column (so one bad number never loses the row)."""
    if value is None or isinstance(value, bool):
        return value
    if column in _INT_COLUMNS:
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if 0 <= number <= 2_147_483_647 else None
    if column in _NUMERIC_LIMITS:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if abs(number) < _NUMERIC_LIMITS[column] else None
    return value


def save_file(path, kind, size, mtime, summary=None, external=None):
    from curator.video import naming

    values = {"path": path, "media_kind": kind, "size_bytes": size, "mtime": mtime,
              "external_subtitles": external or [],
              "release_group": naming.release_group(path) or None}
    if summary is not None:
        for column in PROBE_COLUMNS:
            value = summary.get(column)
            if column == "edition":
                from curator.video.sources import canonical_edition

                cleaned = canonical_edition(value)
                if cleaned:
                    values[column] = cleaned
                elif str(value or "").strip():
                    values[column] = None
                continue
            if column in {"source_format", "video_source"} and not value:
                continue
            # Columns typed as JSONB arrays must never be stored as a scalar or null, or
            # analytics' jsonb_array_length chokes on them later. A probe that half-failed
            # could leave None here, which _value() would wrap as JSON null.
            if column in {"subtitle_tracks", "audio_tracks", "external_subtitles"} and not isinstance(value, list):
                value = []
            values[column] = _fit_column(column, value)
    with db.transaction() as conn:
        file_id, _ = _upsert(conn, "video_files", ("path",), values)
        if summary is not None:
            conn.execute("UPDATE video_files SET probed_at = NOW() WHERE id = %s", (file_id,))
    if summary is not None and not summary.get("probe_error"):
        payload = dict(summary)
        payload["external_subtitles"] = external or summary.get("external_subtitles") or []
        try:
            from curator.video import mediainfo_xml
            mediainfo_xml.write(path, payload, size)
        except OSError:
            pass
    return file_id


def save_set(info):
    with db.transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO movie_sets (name, tmdb_collection_id, overview)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                tmdb_collection_id = COALESCE(EXCLUDED.tmdb_collection_id, movie_sets.tmdb_collection_id),
                overview = COALESCE(NULLIF(EXCLUDED.overview, ''), movie_sets.overview),
                updated_at = NOW()
            RETURNING id
            """,
            (info["name"], info.get("tmdb_id"), info.get("overview") or ""),
        ).fetchone()
    return row["id"]


def known_movies(roots):
    rows = db.fetchall(
        """
        SELECT id, path, folder, parts, nfo_path, nfo_mtime, file_id, artwork, set_id, edition,
               title, year, plot, tagline, ratings, rating, votes, actors, mpaa, certifications,
               updated_at
        FROM movies WHERE root = ANY(%s)
        """,
        (list(roots),),
    )
    return {row["path"]: row for row in rows}


def _stamp_nfo(table, row_id, values):
    if not (values or {}).get("nfo_path"):
        return
    from curator.video import nfo_digest

    nfo_digest.remember(table, row_id, values)


def save_movie(values):
    with db.transaction() as conn:
        row_id, inserted = _upsert(conn, "movies", ("path",), values)
    _stamp_nfo("movies", row_id, values)
    return row_id, inserted


def art_keys(art):
    """Artwork type names. Source URLs live under _sources and are not a type."""
    return sorted(key for key, value in (art or {}).items() if isinstance(value, str) and value and not str(key).startswith("_"))


def clear_placeholder_edition(movie_id, file_id=None):
    """Drop a stored NONE. That word means the .nfo had no edition."""
    from curator.video.sources import canonical_edition

    if movie_id:
        row = db.fetchone("SELECT edition, locked, locked_fields FROM movies WHERE id = %s", (movie_id,))
        locked = set(row.get("locked_fields") or []) if row else set()
        if row and not row.get("locked") and "edition" not in locked:
            if str(row.get("edition") or "").strip() and not canonical_edition(row.get("edition")):
                db.execute("UPDATE movies SET edition = NULL, updated_at = NOW() WHERE id = %s", (movie_id,))
    if file_id:
        row = db.fetchone("SELECT edition FROM video_files WHERE id = %s", (file_id,))
        if row and str(row.get("edition") or "").strip() and not canonical_edition(row.get("edition")):
            db.execute("UPDATE video_files SET edition = NULL, updated_at = NOW() WHERE id = %s", (file_id,))


def set_movie_edition(movie_id, file_id, edition):
    """Fill an empty movie edition, and the file edition when that is empty too."""
    if not movie_id or not edition:
        return
    db.execute(
        "UPDATE movies SET edition = %s, updated_at = NOW() WHERE id = %s AND COALESCE(edition, '') = ''",
        (edition, movie_id),
    )
    if file_id:
        db.execute(
            "UPDATE video_files SET edition = %s WHERE id = %s AND COALESCE(edition, '') = ''",
            (edition, file_id),
        )


def set_artwork(table, row_id, art):
    db.execute(f"UPDATE {table} SET artwork = %s, updated_at = NOW() WHERE id = %s", (Jsonb(art), row_id))


def save_pending_match(table, row_id, art):
    if table not in {"movies", "tv_shows"}:
        return
    db.execute(
        f"UPDATE {table} SET pending_match = %s, updated_at = NOW() WHERE id = %s",
        (Jsonb({"held": True, "art": art or {}}), row_id),
    )


def clear_pending_match(table, row_id):
    if table not in {"movies", "tv_shows"}:
        return
    db.execute(
        f"UPDATE {table} SET pending_match = NULL, updated_at = NOW() WHERE id = %s AND pending_match IS NOT NULL",
        (row_id,),
    )


def pending_match_ids():
    movies = db.fetchall("SELECT id::text AS id FROM movies WHERE pending_match IS NOT NULL")
    shows = db.fetchall("SELECT id::text AS id FROM tv_shows WHERE pending_match IS NOT NULL")
    return [row["id"] for row in movies], [row["id"] for row in shows]


def pending_match_items():
    """The movies and shows a scan matched but held back, for the Apply match window."""
    movies = db.fetchall(
        "SELECT id::text AS id, title, year, path, folder FROM movies WHERE pending_match IS NOT NULL ORDER BY sort_title NULLS LAST, title"
    )
    shows = db.fetchall(
        "SELECT id::text AS id, title, year, path FROM tv_shows WHERE pending_match IS NOT NULL ORDER BY sort_title NULLS LAST, title"
    )
    items = [{"kind": "movie", "id": r["id"], "title": r["title"], "year": r.get("year"), "path": r.get("folder") or r.get("path")} for r in movies]
    items += [{"kind": "show", "id": r["id"], "title": r["title"], "year": r.get("year"), "path": r.get("path")} for r in shows]
    return items


def pending_match_count():
    movies, shows = pending_match_ids()
    return len(movies) + len(shows)


def count_under(table, root):
    row = db.fetchone(f"SELECT count(*)::int AS n FROM {table} WHERE root = %s", (root,))
    return row["n"] if row else 0


def mark_prune_held(media, root, keep, hold):
    """Record which rows under a library root a scan left in place on purpose.

    Rows the walk found are cleared. With `hold`, the rest (not wanted) are marked, so they can
    be filtered and removed by hand. Without it the rest were just pruned, so nothing remains
    to mark.
    """
    table = "movies" if media == "movies" else "tv_shows"
    paths = list(keep or [])
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE {table} SET prune_held = FALSE WHERE root = %s AND prune_held AND path = ANY(%s)",
            (root, paths),
        )
        if hold:
            conn.execute(
                f"UPDATE {table} SET prune_held = TRUE WHERE root = %s AND NOT wanted AND NOT prune_held "
                f"AND NOT (path = ANY(%s))",
                (root, paths),
            )


def prune_movies(root, keep, allow_empty=False):
    if not keep and not allow_empty:
        return []
    with db.transaction() as conn:
        if keep:
            rows = conn.execute(
                "DELETE FROM movies WHERE root = %s AND NOT wanted AND NOT (path = ANY(%s)) RETURNING id",
                (root, list(keep)),
            ).fetchall()
        else:
            rows = conn.execute("DELETE FROM movies WHERE root = %s AND NOT wanted RETURNING id", (root,)).fetchall()
    return [str(row["id"]) for row in rows]


def prune_movies_under(root, folder, keep):
    """Drop movies at or below one folder that a targeted scan did not find."""
    with db.transaction() as conn:
        rows = conn.execute(
            "DELETE FROM movies WHERE root = %s AND NOT wanted AND (path = %s OR path LIKE %s) AND NOT (path = ANY(%s)) RETURNING id",
            (root, folder, like_prefix(folder), list(keep)),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def remove_under_root(media, root):
    """Remove every movie or show filed under a library path the user took out of Settings.

    Rows carry the library root they were found under, so matching on it cannot reach a
    sibling path on the same mount, and a nested path keeps its own rows.

    Wanted rows go too. A wanted row is a title with no file yet, holding the root its file
    was meant to land in; once that root is no longer a library path it has nowhere to land,
    so keeping it would leave a broken placeholder. Radarr or Sonarr still holds the request
    and may well have moved it elsewhere. No file is touched: this only removes rows.
    """
    table = "movies" if media == "movies" else "tv_shows"
    with db.transaction() as conn:
        rows = conn.execute(
            f"DELETE FROM {table} WHERE root = %s RETURNING id, wanted", (root,)
        ).fetchall()
    return [str(row["id"]) for row in rows], sum(1 for row in rows if row.get("wanted"))


def _inside(path, roots):
    path = str(path or "").rstrip("/")
    return any(path == root or path.startswith(root + "/") for root in roots)


def remove_outside_roots(media, roots):
    """Remove movies or shows that sit outside every library path of their media type.

    `roots` is every path configured for this media type, offline and excluded ones included.
    A row counts as inside when its root or its own path is at or below one of them, under
    either spelling (as typed and as resolved), so a symlinked or nested path never makes a
    found item look outside. With nothing configured, nothing is removed. Rows only: no file is
    touched. Returns (ids, how many were wanted).
    """
    allowed = []
    for root in roots or []:
        for spelling in (str(root), os.path.realpath(str(root))):
            spelling = spelling.rstrip("/") or "/"
            if spelling not in allowed:
                allowed.append(spelling)
    if not allowed:
        return [], 0
    table = "movies" if media == "movies" else "tv_shows"
    rows = db.fetchall(f"SELECT id, root, path, wanted FROM {table} WHERE root IS NOT NULL AND root <> ''")
    gone = [row for row in rows if not _inside(row["root"], allowed) and not _inside(row.get("path"), allowed)]
    if not gone:
        return [], 0
    ids = [str(row["id"]) for row in gone]
    with db.transaction() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ANY(%s::uuid[])", (db.uuid_array(ids),))
    return ids, sum(1 for row in gone if row.get("wanted"))


def prune_show_path(root, path):
    with db.transaction() as conn:
        rows = conn.execute(
            "DELETE FROM tv_shows WHERE root = %s AND path = %s AND NOT wanted RETURNING id", (root, path)
        ).fetchall()
    return [str(row["id"]) for row in rows]


def ids_under(media, folders):
    """Movie or show ids at or below these folders, for the scrape that follows a webhook scan."""
    table = "movies" if media == "movies" else "tv_shows"
    where, params = _under(folders)
    rows = db.fetchall(f"SELECT id FROM {table} WHERE {where}", params)
    return [str(row["id"]) for row in rows]


def find_title(media, title, year=None):
    """The folder of the movie or show with this title, for Bazarr messages that carry no path."""
    if media == "movies":
        sql = "SELECT folder AS path, year FROM movies WHERE lower(title) = lower(%s)"
    else:
        sql = "SELECT path, year FROM tv_shows WHERE lower(title) = lower(%s)"
    rows = db.fetchall(sql, (title,))
    if year:
        rows = [row for row in rows if not row.get("year") or abs(int(row["year"]) - int(year)) <= 1] or []
    return rows[0]["path"] if len(rows) == 1 else None


def known_shows(roots):
    rows = db.fetchall(
        "SELECT id, path, nfo_path, nfo_mtime, artwork, updated_at FROM tv_shows WHERE root = ANY(%s)", (list(roots),)
    )
    return {row["path"]: row for row in rows}


def known_show_paths(root):
    """Paths of the shows indexed under one library root that a scan is allowed to prune."""
    rows = db.fetchall("SELECT path FROM tv_shows WHERE root = %s AND NOT wanted", (root,))
    return {row["path"] for row in rows}


def save_show(values):
    with db.transaction() as conn:
        row_id, inserted = _upsert(conn, "tv_shows", ("path",), values)
    _stamp_nfo("tv_shows", row_id, values)
    return row_id, inserted


def save_season(values):
    with db.transaction() as conn:
        row_id, inserted = _upsert(conn, "tv_seasons", ("show_id", "season_number"), values)
    _stamp_nfo("tv_seasons", row_id, values)
    return row_id, inserted


def episode_index(roots):
    """Episode paths already stored, grouped by show, so an unchanged show can be left alone."""
    rows = db.fetchall(
        """
        SELECT e.show_id::text AS show_id, e.season_number, e.episode_number, e.path
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        WHERE s.root = ANY(%s) AND NOT e.missing
        """,
        (list(roots),),
    )
    grouped = {}
    for row in rows:
        grouped.setdefault(row["show_id"], []).append(row)
    return grouped


def known_episodes(show_id):
    rows = db.fetchall(
        """
        SELECT id, show_id, season_number, episode_number, path, nfo_path, nfo_mtime, file_id, artwork, file_span,
               title, plot, ratings, rating, votes, guest_stars, mpaa, certifications, missing
        FROM tv_episodes WHERE show_id = %s
        """,
        (show_id,),
    )
    return {(row["season_number"], row["episode_number"]): row for row in rows}


def save_episode(values):
    with db.transaction() as conn:
        row_id, inserted = _upsert(conn, "tv_episodes", ("show_id", "season_number", "episode_number"), values)
    _stamp_nfo("tv_episodes", row_id, values)
    return row_id, inserted


def season_nfo_index(show_id):
    """Stored season .nfo path and mtime, so an empty season is reread only when that file changed."""
    rows = db.fetchall(
        "SELECT season_number, nfo_path, nfo_mtime FROM tv_seasons WHERE show_id = %s",
        (show_id,),
    )
    return {row["season_number"]: row for row in rows}


def prune_show(show_id, keep):
    numbers = sorted(keep)
    with db.transaction() as conn:
        removed = conn.execute(
            """
            DELETE FROM tv_episodes e
            WHERE e.show_id = %s
              AND NOT e.missing
              AND NOT EXISTS (
                SELECT 1 FROM unnest(%s::int[], %s::int[]) AS k(s, n)
                WHERE k.s = e.season_number AND k.n = e.episode_number
              )
            RETURNING id
            """,
            (show_id, [item[0] for item in numbers], [item[1] for item in numbers]),
        ).fetchall()
        rows = conn.execute(
            """
            SELECT id, nfo_path FROM tv_seasons s WHERE s.show_id = %s
              AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = s.id)
            """,
            (show_id,),
        ).fetchall()
        drop = [row["id"] for row in rows if not row["nfo_path"] or not os.path.isfile(row["nfo_path"])]
        if drop:
            conn.execute("DELETE FROM tv_seasons WHERE id = ANY(%s)", (drop,))
    return len(removed)


def prune_shows(root, keep, allow_empty=False):
    if not keep and not allow_empty:
        return []
    with db.transaction() as conn:
        if keep:
            rows = conn.execute(
                "DELETE FROM tv_shows WHERE root = %s AND NOT wanted AND NOT (path = ANY(%s)) RETURNING id",
                (root, list(keep)),
            ).fetchall()
        else:
            rows = conn.execute("DELETE FROM tv_shows WHERE root = %s AND NOT wanted RETURNING id", (root,)).fetchall()
    return [str(row["id"]) for row in rows]


def claim_wanted_movie(tmdb_id, path, folder):
    """Move a wanted movie onto the folder a scan just found, or drop it when that TMDB id is already filed."""
    tmdb_id = str(tmdb_id or "").strip()
    if not tmdb_id or not path:
        return
    with db.transaction() as conn:
        other = conn.execute(
            "SELECT id FROM movies WHERE tmdb_id = %s AND NOT wanted AND path <> %s LIMIT 1",
            (tmdb_id, path),
        ).fetchone()
        taken = conn.execute(
            "SELECT id FROM movies WHERE path = %s AND NOT wanted LIMIT 1",
            (path,),
        ).fetchone()
        if other or taken:
            conn.execute("DELETE FROM movies WHERE wanted AND tmdb_id = %s", (tmdb_id,))
            return
        row = conn.execute(
            "SELECT id FROM movies WHERE wanted AND tmdb_id = %s LIMIT 1",
            (tmdb_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE movies SET path = %s, folder = %s, wanted = FALSE, updated_at = NOW() WHERE id = %s",
            (path, folder, row["id"]),
        )


def claim_wanted_show(tvdb_id, tmdb_id, path):
    """Move a wanted show onto the folder a scan just found. TVDB wins when both ids are known."""
    tvdb_id = str(tvdb_id or "").strip()
    tmdb_id = str(tmdb_id or "").strip()
    if not path or not (tvdb_id or tmdb_id):
        return
    with db.transaction() as conn:
        for column, value in (("tvdb_id", tvdb_id), ("tmdb_id", tmdb_id)):
            if not value:
                continue
            other = conn.execute(
                f"SELECT id FROM tv_shows WHERE {column} = %s AND NOT wanted AND path <> %s LIMIT 1",
                (value, path),
            ).fetchone()
            taken = conn.execute(
                "SELECT id FROM tv_shows WHERE path = %s AND NOT wanted LIMIT 1",
                (path,),
            ).fetchone()
            wanted = conn.execute(
                f"SELECT id FROM tv_shows WHERE wanted AND {column} = %s LIMIT 1",
                (value,),
            ).fetchone()
            if other or taken:
                if wanted:
                    conn.execute("DELETE FROM tv_shows WHERE id = %s", (wanted["id"],))
                return
            if wanted:
                conn.execute(
                    "UPDATE tv_shows SET path = %s, wanted = FALSE, updated_at = NOW() WHERE id = %s",
                    (path, wanted["id"]),
                )
                return


def touch_show(show_id):
    """Mark a show changed so a scan refresh can send its row again."""
    if show_id:
        db.execute("UPDATE tv_shows SET updated_at = NOW() WHERE id = %s", (show_id,))


def drop_unconfigured(movie_roots=None, tv_roots=None):
    """Drop movies and shows whose library folder is no longer in Settings."""
    movies = _drop_roots("movies", movie_roots) if movie_roots is not None else 0
    shows = _drop_roots("tv_shows", tv_roots) if tv_roots is not None else 0
    if movies or shows:
        drop_orphans()
    return movies, shows


def _drop_roots(table, roots):
    allowed = [os.path.normpath(root) for root in roots if root]
    rows = db.fetchall(f"SELECT id, root FROM {table}")
    gone = []
    for row in rows:
        root = os.path.normpath(row["root"] or "")
        if not any(root == item or root.startswith(item + os.sep) for item in allowed):
            gone.append(row["id"])
    if not gone:
        return 0
    deleted = db.fetchall(f"DELETE FROM {table} WHERE id = ANY(%s::uuid[]) RETURNING id", (gone,))
    return len(deleted)


def drop_orphans():
    with db.transaction() as conn:
        files = conn.execute(
            """
            DELETE FROM video_files f
            WHERE NOT EXISTS (SELECT 1 FROM movies m WHERE m.file_id = f.id OR f.path = ANY(m.parts))
              AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.file_id = f.id)
              AND NOT EXISTS (SELECT 1 FROM episode_copies c WHERE c.file_id = f.id)
            RETURNING id
            """
        ).fetchall()
        sets = conn.execute(
            """
            DELETE FROM movie_sets s
            WHERE NOT EXISTS (SELECT 1 FROM movies m WHERE m.set_id = s.id)
            RETURNING id
            """
        ).fetchall()
    return len(files), len(sets)


def totals():
    row = db.fetchone(
        """
        SELECT
            (SELECT count(*) FROM movies)::int AS movies,
            (SELECT count(*) FROM movie_sets)::int AS sets,
            (SELECT count(*) FROM movies WHERE set_id IS NOT NULL)::int AS set_movies,
            (SELECT COALESCE(SUM(f.size_bytes), 0)::bigint FROM movies m JOIN video_files f ON f.id = m.file_id) AS movie_bytes,
            (SELECT COALESCE(SUM(f.duration_seconds), 0)::bigint FROM movies m JOIN video_files f ON f.id = m.file_id) AS movie_seconds,
            (SELECT count(*) FROM tv_shows)::int AS shows,
            (SELECT count(*) FROM tv_seasons)::int AS seasons,
            (SELECT count(*) FROM tv_episodes)::int AS episodes,
            (SELECT COALESCE(SUM(f.size_bytes), 0)::bigint FROM tv_episodes e JOIN video_files f ON f.id = e.file_id) AS episode_bytes,
            (SELECT COALESCE(SUM(f.duration_seconds), 0)::bigint FROM tv_episodes e JOIN video_files f ON f.id = e.file_id) AS episode_seconds
        """
    )
    return row or {
        "movies": 0, "sets": 0, "set_movies": 0, "movie_bytes": 0, "movie_seconds": 0,
        "shows": 0, "seasons": 0, "episodes": 0, "episode_bytes": 0, "episode_seconds": 0,
    }


FILE_BRIEF = """
    f.resolution, f.width, f.height, f.video_codec, f.video_profile, f.hdr_format, f.hdr_secondary,
    f.is_hybrid, f.dovi_profile, f.dovi_el_type, f.is_3d, f.stereo_mode, f.bit_depth, f.audio_tracks, f.subtitle_tracks,
    f.external_subtitles, f.size_bytes, f.bitrate_mbps, f.duration_seconds, f.container, f.probe_error,
    f.video_source, f.source_format, f.probed_at, f.fps, f.aspect_ratio, f.max_cll, f.max_fall, f.mtime
"""


def _audio_main(tracks):
    codec, channels = _audio_parts(tracks)
    return " ".join(part for part in (codec, channels) if part)


def _audio_parts(tracks):
    if not tracks:
        return "", ""
    track = next((item for item in tracks if item.get("default")), tracks[0])
    return str(track.get("codec") or ""), str(track.get("channels") or "")


def _langs(tracks):
    seen = []
    for track in tracks or []:
        lang = track.get("lang") or ""
        if lang and lang not in seen:
            seen.append(lang)
    return seen


def brief_file(row):
    """Matrix columns from the joined video_files fields. Drops the full track lists."""
    audio = row.pop("audio_tracks", None) or []
    row["health"] = health.warnings(row, audio, row.get("duration_seconds"), row.get("runtime_minutes"))
    subs = (row.pop("subtitle_tracks", None) or [])
    external = row.pop("external_subtitles", None) or []
    row["audio_codec"], row["audio_channels"] = _audio_parts(audio)
    row["audio_main"] = " ".join(part for part in (row["audio_codec"], row["audio_channels"]) if part)
    row["audio_langs"] = _langs(audio)
    row["audio_count"] = len(audio)
    row["sub_langs"] = _langs(subs + external)
    row["sub_count"] = len(subs) + len(external)
    row["audio_unknown"] = sum(1 for track in audio if health.unknown_language(track.get("lang")))
    row["sub_unknown"] = sum(1 for track in subs + external if health.unknown_language(track.get("lang")))
    art = row.get("artwork") or {}
    row["artwork"] = art_keys(art)
    return row


def _with_local_art(item, folder):
    from curator.video import artwork as local_art

    if not item or not folder:
        return item
    item["artwork"] = local_art.apply_local_extras(folder, item.get("artwork"))
    if item.get("actors"):
        item["actors"] = local_art.bind_actor_thumbs(folder, item.get("actors"))
    return item


def _named_file(folder, names):
    if not folder or not os.path.isdir(folder):
        return None
    wanted = {name.lower() for name in names}
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file() and entry.name.lower() in wanted:
                    return entry.path
    except OSError:
        return None
    return None


def _bind_season_nfo(show, season, episodes):
    """Point a season at season.nfo when the file is on disk and the row has not stored it yet."""
    current = season.get("nfo_path")
    if current and os.path.isfile(current):
        season["has_nfo"] = True
        return
    number = int(season.get("season_number") or 0)
    show_path = show.get("path") or ""
    folders = []
    if season.get("path"):
        folders.append(season["path"])
    for episode in episodes:
        if str(episode.get("season_id")) != str(season.get("id")):
            continue
        folder = os.path.dirname(episode.get("path") or "")
        if folder and folder != show_path:
            folders.append(folder)
    found = None
    seen = set()
    for folder in folders:
        if folder in seen:
            continue
        seen.add(folder)
        found = _named_file(folder, ["season.nfo"])
        if found:
            break
    if not found and show_path:
        found = _named_file(show_path, [f"season{number:02d}.nfo", f"season{number}.nfo"])
    if not found:
        season["has_nfo"] = False
        return
    season["nfo_path"] = found
    season["has_nfo"] = True
    if not season.get("path"):
        season["path"] = os.path.dirname(found)
    try:
        save_nfo_state("tv_seasons", season.get("id"), found, os.path.getmtime(found))
    except OSError:
        save_nfo_state("tv_seasons", season.get("id"), found, None)


def _annotate_display(row):
    from resonance.paths import display_path_fast as display_path

    if not isinstance(row, dict):
        return row
    for key in ("path", "folder", "nfo_path", "upgrade_path", "mediainfo_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            shown = display_path(value)
            display_key = "display_path" if key == "path" else f"display_{key}"
            row[display_key] = shown
    if "edition" in row:
        from curator.video.sources import canonical_edition

        row["edition"] = canonical_edition(row.get("edition"))
    nested = row.get("file")
    if isinstance(nested, dict):
        _annotate_display(nested)
    return row


def _movie_rows(where="", params=()):
    import time

    started = time.monotonic()
    rows = db.fetchall(
        f"""
        SELECT m.id, m.title, m.sort_title, m.original_title, m.english_title, m.year, m.edition, m.runtime_minutes, m.mpaa,
               m.genres, m.studios, m.countries, m.directors, m.rating, m.votes, m.imdb_id, m.tmdb_id,
               m.status, m.playcount, m.path, m.folder, m.root, m.nfo_path, m.nfo_digest, m.nfo_path IS NOT NULL AS has_nfo,
               m.tagline, m.outline, m.plot, m.premiered, m.tags, m.writers, m.trailer, m.has_local_trailer, m.has_local_theme,
               concat_ws(' ', array_to_string(m.writers, ' '), array_to_string(m.tags, ' '),
                         (SELECT string_agg(e->>'name', ' ') FROM jsonb_array_elements(COALESCE(m.actors, '[]'::jsonb)) e)) AS search_extra,
               (m.plot IS NOT NULL AND btrim(m.plot) <> '') AS has_plot, m.artwork,
               {source_column_sql("m")},
               m.created_at, m.date_added, m.disc_format, cardinality(m.parts) AS part_count,
               m.locked, m.scraped_at, m.scrape_error, m.duplicate_release, m.prune_held, m.wanted,
               (m.upgrade_source_id IS NOT NULL) AS upgrade, up.path AS upgrade_path,
               s.id AS set_id, s.name AS set_name, f.path AS file_path, {FILE_BRIEF}
        FROM movies m
        LEFT JOIN video_files f ON f.id = m.file_id
        LEFT JOIN movie_sets s ON s.id = m.set_id
        LEFT JOIN movies up ON up.id = m.upgrade_source_id
        {where}
        ORDER BY lower(COALESCE(m.sort_title, m.title)), m.year NULLS LAST
        """,
        params,
    )
    queried = time.monotonic()
    movies = [_annotate_display(db.clean(brief_file(dict(row)))) for row in rows]
    shaped = time.monotonic()
    from curator.video import copies, nfo_digest

    movies = copies.library_rows(movies)
    deduped = time.monotonic()
    nfo_digest.apply("movies", movies)
    finished = time.monotonic()
    if finished - started > 3.0:
        logger.info("movie rows: query %.1fs, paths and fields %.1fs, duplicate check %.1fs, .nfo check %.1fs (%d rows)",
                    queried - started, shaped - queried, deduped - shaped, finished - deduped, len(rows))
    for movie in movies:
        movie["has_trailer"] = bool(movie.get("trailer"))
        for key in ("tagline", "outline", "plot", "premiered", "tags", "writers", "trailer", "nfo_digest", "english_title"):
            movie.pop(key, None)
    return movies


def list_movies():
    return _movie_rows()


def _file(file_id):
    if not file_id:
        return None
    row = db.fetchone("SELECT * FROM video_files WHERE id = %s", (file_id,))
    if not row:
        return None
    from curator.video import mediainfo_xml, sync_marks

    found = db.clean(dict(row))
    # The media info sidecar written next to the video, shown with the other files of the item when it exists.
    sidecar = mediainfo_xml.path_for(found["path"]) if found.get("path") else ""
    found["mediainfo_path"] = sidecar if sidecar and os.path.isfile(sidecar) else None
    return sync_marks.annotate(found)


def movie_detail(movie_id):
    row = db.fetchone(
        """
        SELECT m.*, s.name AS set_name, s.overview AS set_overview,
               (SELECT count(*)::int FROM movies o WHERE o.set_id = m.set_id) AS set_count
        FROM movies m LEFT JOIN movie_sets s ON s.id = m.set_id
        WHERE m.id = %s
        """,
        (movie_id,),
    )
    if not row:
        return None
    movie = db.clean(dict(row))
    movie["file"] = _file(row["file_id"])
    from curator.video import trailers

    movie["trailer_file"] = trailers.local_trailer(movie)
    movie["theme_file"] = trailers.local_theme(movie.get("folder") or movie.get("path"))
    from curator.video import copies

    movie = _annotate_display(copies.present(movie, "movies"))
    from curator.video import brands, mediaflags

    movie["studio_icons"] = brands.icons(movie.get("studios"), "studios")
    movie["media_flags"] = mediaflags.cards(movie.get("file"))
    return _with_local_art(movie, movie.get("folder") or movie.get("path"))


def list_sets():
    rows = db.fetchall(
        """
        SELECT s.id, s.name, s.overview, s.tmdb_collection_id, s.artwork, s.nfo_path, s.nfo_digest, s.scraped_at, s.scrape_error,
               s.locked, s.status::text AS status,
               count(m.id)::int AS movie_count, min(m.year) AS first_year, max(m.year) AS last_year,
               (s.status = 'NEW') AS has_new,
               (SELECT count(*)::int FROM movie_set_parts p WHERE p.set_id = s.id) AS part_count,
               (SELECT count(*)::int FROM movie_set_parts p WHERE p.set_id = s.id
                  AND NOT EXISTS (SELECT 1 FROM movies o WHERE o.tmdb_id = p.tmdb_id)) AS missing_count
        FROM movie_sets s LEFT JOIN movies m ON m.set_id = s.id
        GROUP BY s.id
        ORDER BY lower(s.name)
        """
    )
    sets = [db.clean(dict(row)) for row in rows]
    from curator.video import nfo_digest

    nfo_digest.apply("movie_sets", sets)
    for item in sets:
        item.pop("nfo_digest", None)
    return sets


def set_detail(set_id):
    row = db.fetchone("SELECT * FROM movie_sets WHERE id = %s", (set_id,))
    if not row:
        return None
    detail = db.clean(dict(row))
    movies = db.fetchall(
        f"""
        SELECT m.id, m.title, m.year, m.edition, m.rating, m.runtime_minutes, m.artwork, m.status, m.plot,
               {FILE_BRIEF}
        FROM movies m LEFT JOIN video_files f ON f.id = m.file_id
        WHERE m.set_id = %s
        ORDER BY m.year NULLS LAST, lower(m.title)
        """,
        (set_id,),
    )
    detail["movies"] = []
    for movie in movies:
        item = dict(movie)
        art = item.get("artwork") or {}
        item = brief_file(item)
        item["poster"] = art.get("poster")
        detail["movies"].append(db.clean(item))
    detail["missing"] = missing_parts(set_id)
    detail["part_count"] = db.fetchone(
        "SELECT count(*)::int AS n FROM movie_set_parts WHERE set_id = %s", (set_id,)
    )["n"]
    from curator.video import nfo_digest

    nfo_digest.apply("movie_sets", [detail])
    return detail


def missing_parts(set_id):
    rows = db.fetchall(
        """
        SELECT p.tmdb_id, p.title, p.year, p.release_date, p.overview, p.poster
        FROM movie_set_parts p
        WHERE p.set_id = %s AND NOT EXISTS (SELECT 1 FROM movies o WHERE o.tmdb_id = p.tmdb_id)
        ORDER BY p.release_date NULLS LAST, lower(p.title)
        """,
        (set_id,),
    )
    return [db.clean(dict(row)) for row in rows]


def save_set_parts(set_id, parts):
    with db.transaction() as conn:
        conn.execute("DELETE FROM movie_set_parts WHERE set_id = %s", (set_id,))
        for part in parts or []:
            conn.execute(
                "INSERT INTO movie_set_parts (set_id, tmdb_id, title, year, release_date, overview, poster) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (set_id, part["tmdb_id"], part["title"], part.get("year"), part.get("release_date") or None,
                 part.get("overview") or None, part.get("poster") or None),
            )
        conn.execute("UPDATE movie_sets SET parts_synced_at = NOW() WHERE id = %s", (set_id,))


def _family_nfo_shows():
    """Show ids whose season.nfo or episode.nfo no longer matches the database."""
    from curator.video import nfo_digest

    seasons = [
        db.clean(dict(row)) for row in db.fetchall(
            """
            SELECT id, show_id, nfo_path, nfo_digest, title, plot, premiered, year, season_number,
                   sort_title, ids
            FROM tv_seasons WHERE nfo_path IS NOT NULL
            """
        )
    ]
    episodes = [
        db.clean(dict(row)) for row in db.fetchall(
            """
            SELECT id, show_id, nfo_path, nfo_digest, title, plot, aired, season_number, episode_number,
                   rating, directors, playcount, user_rating, display_season, display_episode,
                   resume_position, resume_total, mpaa, certifications, original_title, english_title
            FROM tv_episodes WHERE nfo_path IS NOT NULL
            """
        )
    ]
    nfo_digest.apply("tv_seasons", seasons)
    nfo_digest.apply("tv_episodes", episodes)
    return {str(row["show_id"]) for row in seasons + episodes if row.get("nfo_stale")}


def _show_rows(where="", params=()):
    rows = db.fetchall(
        f"""
        SELECT s.id, s.title, s.sort_title, s.original_title, s.year, s.show_status, s.genres, s.studios, s.countries,
               s.directors, s.mpaa, s.rating, s.plot, s.outline, s.tagline, s.runtime_minutes, s.premiered,
               s.tags, s.trailer, s.has_local_trailer, s.has_local_theme, s.nfo_digest, s.user_rating, s.top250, s.playcount, s.last_played,
               s.original_language, s.english_title,
               concat_ws(' ', array_to_string(s.tags, ' '),
                         (SELECT string_agg(e->>'name', ' ') FROM jsonb_array_elements(COALESCE(s.actors, '[]'::jsonb)) e)) AS search_extra,
               s.imdb_id, s.tvdb_id, s.tmdb_id, s.status, s.path, s.root, s.nfo_path, s.nfo_path IS NOT NULL AS has_nfo,
               {source_column_sql("s")},
               (s.plot IS NOT NULL AND btrim(s.plot) <> '') AS has_plot,
               s.artwork, s.created_at, s.locked, s.scraped_at, s.scrape_error, s.wanted, s.prune_held,
               (SELECT count(*)::int FROM tv_seasons x WHERE x.show_id = s.id) AS season_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.show_id = s.id) AS episode_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.show_id = s.id AND e.status = 'NEW') AS new_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.show_id = s.id AND e.missing) AS missing_count,
               (SELECT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.show_id = s.id AND e.duplicate_release)) AS duplicate_release,
               (SELECT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.show_id = s.id AND (e.upgrade_source_id IS NOT NULL OR COALESCE(e.upgrade_copy_path, '') <> ''))) AS upgrade,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.show_id = s.id
                    AND jsonb_typeof(e.file_span) = 'array' AND jsonb_array_length(e.file_span) > 1) AS multi_count
        FROM tv_shows s
        {where}
        ORDER BY lower(COALESCE(s.sort_title, s.title)), s.year NULLS LAST
        """,
        params,
    )
    shows = []
    for row in rows:
        item = db.clean(dict(row))
        item["artwork"] = art_keys(item.get("artwork") or {})
        shows.append(_annotate_display(item))
    from curator.video import nfo_digest

    nfo_digest.apply("tv_shows", shows)
    family = _family_nfo_shows()
    for show in shows:
        show["nfo_family_stale"] = bool(show.get("nfo_stale")) or str(show["id"]) in family
        show["has_trailer"] = bool(show.get("trailer"))
        for key in ("plot", "outline", "tagline", "runtime_minutes", "premiered", "tags", "trailer", "nfo_digest", "original_title",
                    "user_rating", "top250", "playcount", "last_played", "original_language", "english_title"):
            show.pop(key, None)
    return shows


def list_shows():
    return _show_rows()


def changes(media, since):
    """Rows written after `since`, for a library refresh while a scan is running."""
    from resonance.errors import AppError
    from resonance.library import _since

    if media not in {"movies", "tv"}:
        raise AppError("Unknown library", 400)
    moment = _since(since)
    # Use clock_timestamp() so we get wall-clock time even inside a long transaction,
    # not the transaction start time that NOW() would return.
    as_of = db.fetchone("SELECT clock_timestamp() AS t")["t"]
    if media == "movies":
        rows = _movie_rows("WHERE m.updated_at > %s AND m.updated_at <= %s", (moment, as_of))
        return {"movies": rows, "removed": [], "as_of": as_of}
    if media == "tv":
        where = """
            WHERE (s.updated_at > %s AND s.updated_at <= %s)
               OR EXISTS (
                    SELECT 1 FROM tv_episodes e
                    WHERE e.show_id = s.id AND e.updated_at > %s AND e.updated_at <= %s
               )
               OR EXISTS (
                    SELECT 1 FROM tv_seasons x
                    WHERE x.show_id = s.id AND x.updated_at > %s AND x.updated_at <= %s
               )
        """
        params = (moment, as_of, moment, as_of, moment, as_of)
        return {"shows": _show_rows(where, params), "removed": [], "as_of": as_of}
    raise AppError("Unknown library", 400)


def show_ids_by_path(paths):
    rows = db.fetchall(
        "SELECT id::text AS id FROM tv_shows WHERE path = ANY(%s)",
        (list(paths or []),),
    )
    return [row["id"] for row in rows]


def show_row(show_id):
    row = db.fetchone("SELECT * FROM tv_shows WHERE id = %s", (show_id,))
    return db.clean(dict(row)) if row else None


def season_row(season_id):
    row = db.fetchone("SELECT * FROM tv_seasons WHERE id = %s", (season_id,))
    return db.clean(dict(row)) if row else None


def show_detail(show_id):
    row = db.fetchone("SELECT * FROM tv_shows WHERE id = %s", (show_id,))
    if not row:
        return None
    show = db.clean(dict(row))
    seasons = db.fetchall(
        """
        SELECT s.*, s.nfo_path IS NOT NULL AS has_nfo,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id) AS episode_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id AND e.missing) AS missing_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id AND e.status = 'NEW') AS new_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id
                    AND jsonb_typeof(e.file_span) = 'array' AND jsonb_array_length(e.file_span) > 1) AS multi_count
        FROM tv_seasons s WHERE s.show_id = %s ORDER BY s.season_number
        """,
        (show_id,),
    )
    from curator.video import trailers

    show["trailer_file"] = trailers.show_trailer(show)
    show["theme_file"] = trailers.local_theme(show.get("path"))
    show["seasons"] = []
    for item in seasons:
        season = db.clean(dict(item))
        season["trailer_file"] = trailers.season_trailer(show, season)
        show["seasons"].append(season)
    from curator.video import nfo_digest

    episodes = db.fetchall(
        f"""
        SELECT e.id, e.season_id, e.season_number, e.episode_number, e.title, e.plot, e.aired, e.status, e.scrape_error, e.scraped_at,
               (e.plot IS NOT NULL AND btrim(e.plot) <> '') AS has_plot, e.playcount, e.nfo_digest,
               e.rating, e.rating_imdb, e.directors, e.user_rating, e.display_season, e.display_episode,
               e.resume_position, e.resume_total, e.mpaa, e.certifications, e.original_title, e.english_title,
               e.path, e.nfo_path, e.nfo_path IS NOT NULL AS has_nfo, e.artwork, e.locked, e.created_at,
               e.file_span, e.missing,
               {source_column_sql("e")},
               e.duplicate_release,
               (e.upgrade_source_id IS NOT NULL OR COALESCE(e.upgrade_copy_path, '') <> '') AS upgrade,
               COALESCE(up.path, e.upgrade_copy_path) AS upgrade_path,
               {FILE_BRIEF}
        FROM tv_episodes e
        LEFT JOIN video_files f ON f.id = e.file_id
        LEFT JOIN tv_episodes up ON up.id = e.upgrade_source_id
        WHERE e.show_id = %s
        ORDER BY e.season_number, e.episode_number
        """,
        (show_id,),
    )
    show["episodes"] = [_annotate_display(db.clean(brief_file(dict(item)))) for item in episodes]
    nfo_digest.apply("tv_episodes", show["episodes"])
    for episode in show["episodes"]:
        episode.pop("plot", None)
        episode.pop("nfo_digest", None)
    for season in show["seasons"]:
        _bind_season_nfo(show, season, show["episodes"])
        _annotate_display(season)
    nfo_digest.apply("tv_shows", [show])
    nfo_digest.apply("tv_seasons", show["seasons"])
    child = any(item.get("nfo_stale") for item in show["seasons"]) or any(item.get("nfo_stale") for item in show["episodes"])
    show["nfo_family_stale"] = bool(show.get("nfo_stale")) or child
    _annotate_display(show)
    _annotate_season_gaps(show)
    from curator.video import brands, mediaflags

    show["network_icons"] = brands.icons(show.get("studios"), "network")
    by_season = {}
    for episode in show["episodes"]:
        episode_flags = mediaflags.cards(episode)
        by_season.setdefault(episode.get("season_id"), []).append(episode_flags)
    show["media_flags"] = mediaflags.unique(flag for flags in by_season.values() for flag in flags)
    for season in show["seasons"]:
        season["media_flags"] = mediaflags.unique(by_season.get(season.get("id")) or [])
        season["network_icons"] = show["network_icons"]
    return _with_local_art(show, show.get("path"))


def episode_file_count(path):
    """How many episodes share this video file."""
    row = db.fetchone("SELECT count(*)::int AS n FROM tv_episodes WHERE path = %s", (path,))
    return int(row["n"]) if row else 0


def episode_detail(episode_id):
    row = db.fetchone(
        """
        SELECT e.*, s.title AS show_title, s.year AS show_year, s.mpaa AS show_mpaa,
               s.imdb_id AS show_imdb_id, s.tmdb_id AS show_tmdb_id, s.tvdb_id AS show_tvdb_id,
               s.trakt_id AS show_trakt_id,
               s.certifications AS show_certifications, s.countries AS show_countries, s.studios AS show_studios,
               x.title AS season_title, x.tmdb_episode_count, x.tmdb_episode_numbers,
               s.artwork AS show_artwork, x.artwork AS season_artwork
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        JOIN tv_seasons x ON x.id = e.season_id
        WHERE e.id = %s
        """,
        (episode_id,),
    )
    if not row:
        return None
    episode = db.clean(dict(row))
    episode["file"] = _file(row["file_id"])
    others = db.fetchall(
        "SELECT episode_number FROM tv_episodes WHERE file_id = %s AND id <> %s ORDER BY episode_number",
        (row["file_id"], episode_id),
    ) if row["file_id"] else []
    episode["shares_file_with"] = [item["episode_number"] for item in others]
    expected = expected_episode_numbers(episode)
    episode["extra"] = bool(expected) and episode.get("episode_number") not in expected
    from curator.video import copies

    episode = _annotate_display(copies.present(episode, "tv_episodes"))
    from curator.video import brands, mediaflags

    episode["network_icons"] = brands.icons(episode.get("show_studios"), "network")
    episode["media_flags"] = mediaflags.cards(episode.get("file"))
    return episode


def mark(table, ids, status):
    if table not in {"movies", "tv_shows", "tv_seasons", "tv_episodes"}:
        raise ValueError(table)
    db.execute(f"UPDATE {table} SET status = %s, updated_at = NOW() WHERE id = ANY(%s::uuid[])", (status, list(ids)))


def mark_sets(set_ids, status):
    """Mark the sets themselves. Movies keep their own status."""
    db.execute(
        "UPDATE movie_sets SET status = %s, updated_at = NOW() WHERE id = ANY(%s::uuid[])",
        (status, list(set_ids)),
    )


def note_set_new(set_id):
    """A movie just joined this set, so the set is new again."""
    if not set_id:
        return
    db.execute(
        "UPDATE movie_sets SET status = 'NEW', updated_at = NOW() WHERE id = %s AND status IS DISTINCT FROM 'NEW'",
        (set_id,),
    )


def start_job(media, mode, roots):
    row = db.fetchone(
        "INSERT INTO video_scan_jobs (media, mode, roots, status) VALUES (%s, %s, %s, 'running') RETURNING id",
        (media, mode, list(roots)),
    )
    return str(row["id"]) if row else None


def finish_job(job_id, status, message, result):
    if not job_id:
        return
    db.execute(
        "UPDATE video_scan_jobs SET status = %s, message = %s, result = %s, finished_at = NOW() WHERE id = %s",
        (status, message, Jsonb(result), job_id),
    )


def interrupt_running():
    for table in ("video_scan_jobs", "video_scrape_jobs"):
        db.execute(
            f"UPDATE {table} SET status = 'interrupted', message = 'Interrupted by restart', finished_at = NOW() "
            "WHERE status = 'running'"
        )


# Scraping, edits and locks.

MOVIE_FIELDS = (
    "title", "original_title", "english_title", "sort_title", "year", "tagline", "outline", "plot", "runtime_minutes", "mpaa",
    "premiered", "genres", "countries", "studios", "tags", "directors", "writers", "producers", "actors",
    "languages", "original_language", "trailer", "top250", "rating", "votes", "ratings", "ids", "imdb_id",
    "tmdb_id", "anilist_id", "ofdb_id", "trakt_id", "edition", "certifications", "scrape_language",
    "rating_imdb", "rating_tmdb", "rating_rt", "rating_rt_audience", "rating_metacritic",
    "rating_metacritic_user", "rating_trakt", "rating_anilist", "rating_ofdb", "rating_tvdb",
    "playcount", "last_played",
)
SHOW_FIELDS = (
    "title", "original_title", "english_title", "sort_title", "year", "tagline", "outline", "plot", "show_status", "premiered",
    "mpaa", "runtime_minutes", "genres", "studios", "countries", "tags", "actors", "original_language",
    "trailer", "rating", "votes", "user_rating", "top250", "playcount", "last_played",
    "ratings", "ids", "imdb_id", "tmdb_id", "tvdb_id", "anilist_id", "ofdb_id",
    "trakt_id", "season_names",
    "directors",
    "episode_order", "certifications", "scrape_language",
    "rating_imdb", "rating_tmdb", "rating_rt", "rating_rt_audience", "rating_metacritic",
    "rating_metacritic_user", "rating_trakt", "rating_anilist", "rating_ofdb", "rating_tvdb",
)
EPISODE_FIELDS = (
    "title", "original_title", "english_title", "plot", "aired", "runtime_minutes", "mpaa", "certifications", "scrape_language", "directors", "writers", "guest_stars", "tags",
    "rating", "votes",
    "user_rating", "display_season", "display_episode", "resume_position", "resume_total",
    "ratings", "ids", "anilist_id", "ofdb_id", "trakt_id",
    "rating_imdb", "rating_tmdb", "rating_rt", "rating_rt_audience", "rating_metacritic",
    "rating_metacritic_user", "rating_trakt", "rating_anilist", "rating_ofdb", "rating_tvdb",
    "playcount", "last_played",
)
SET_FIELDS = ("name", "overview")
FIELDS = {"movies": MOVIE_FIELDS, "tv_shows": SHOW_FIELDS, "tv_episodes": EPISODE_FIELDS, "movie_sets": SET_FIELDS}


def table_for(kind):
    table = TABLES.get(kind)
    if not table:
        raise ValueError(kind)
    return table


def ids_for_nfo(media, roots, folders=None, rewrite=False):
    """Movie or show ids whose .nfo should be written at the end of a scan.

    Missing files are always included. rewrite adds every item in the scanned folders.
    """
    roots = [root for root in roots if root]
    if not roots:
        return []
    if media == "movies":
        where = ["root = ANY(%s)"]
        params = [list(roots)]
        if not rewrite:
            where.append("nfo_path IS NULL")
        if folders:
            under, extra = _under(folders)
            where.append(f"({under})")
            params.extend(extra)
        rows = db.fetchall(f"SELECT id FROM movies WHERE {' AND '.join(where)}", tuple(params))
        return [str(row["id"]) for row in rows]
    where = ["s.root = ANY(%s)"]
    params = [list(roots)]
    if folders:
        under, extra = _under(folders)
        where.append(f"({under.replace('path', 's.path')})")
        params.extend(extra)
    if not rewrite:
        where.append(
            """(
                s.nfo_path IS NULL
                OR EXISTS (
                    SELECT 1 FROM tv_seasons x
                    WHERE x.show_id = s.id AND x.nfo_path IS NULL
                      AND (
                        (x.path IS NOT NULL AND x.path <> s.path)
                        OR EXISTS (
                            SELECT 1 FROM tv_episodes e
                            WHERE e.season_id = x.id AND NOT e.missing
                              AND COALESCE(e.path, '') <> ''
                              AND e.path NOT LIKE 'missing://%'
                        )
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM tv_episodes e
                    WHERE e.show_id = s.id AND (
                        e.nfo_path IS NULL
                        OR (
                            jsonb_typeof(e.file_span) = 'array' AND jsonb_array_length(e.file_span) > 1
                            AND COALESCE(e.nfo_path, '') !~* '-S[0-9]+E[0-9]+\\.nfo$'
                        )
                    )
                )
            )"""
        )
    rows = db.fetchall(f"SELECT s.id FROM tv_shows s WHERE {' AND '.join(where)}", tuple(params))
    return [str(row["id"]) for row in rows]


def _season_without_poster(show_id):
    """A season still in the library with no poster file recorded."""
    return (
        "EXISTS (SELECT 1 FROM tv_seasons x "
        f"WHERE x.show_id = {show_id} AND NOT x.locked AND x.status IS DISTINCT FROM 'IGNORED' "
        "AND NOT (x.artwork ? 'poster'))"
    )


# Empty values that are normal for a finished title. A full scan does not treat these as gaps.
_GAP_SKIP = {"title", "set", "top250", "trailer"}

_MOVIE_FIELD_SQL = {
    "original_title": "btrim(COALESCE({a}.original_title, '')) = ''",
    "english_title": "btrim(COALESCE({a}.english_title, '')) = ''",
    "mpaa": "btrim(COALESCE({a}.mpaa, '')) = ''",
    "certification": "{a}.certifications = '{{}}'::jsonb",
    "tagline": "btrim(COALESCE({a}.tagline, '')) = ''",
    "plot": "btrim(COALESCE({a}.plot, '')) = ''",
    "year": "{a}.year IS NULL",
    "release_date": "btrim(COALESCE({a}.premiered, '')) = ''",
    "rating": "{a}.rating IS NULL",
    "runtime": "{a}.runtime_minutes IS NULL",
    "genres": "cardinality({a}.genres) = 0",
    "language": "btrim(COALESCE({a}.original_language, '')) = '' AND cardinality({a}.languages) = 0",
    "country": "cardinality({a}.countries) = 0",
    "studio": "cardinality({a}.studios) = 0",
    "tags": "cardinality({a}.tags) = 0",
    "actors": "{a}.actors = '[]'::jsonb",
    "crew": "cardinality({a}.producers) = 0 AND cardinality({a}.directors) = 0 AND cardinality({a}.writers) = 0",
    "director": "cardinality({a}.directors) = 0",
    "premiered": "btrim(COALESCE({a}.premiered, '')) = ''",
    "credits": "cardinality({a}.writers) = 0",
    "ids": "btrim(COALESCE({a}.tmdb_id, '')) = '' AND btrim(COALESCE({a}.imdb_id, '')) = ''",
}

_SHOW_FIELD_SQL = {
    "original_title": "btrim(COALESCE({a}.original_title, '')) = ''",
    "english_title": "btrim(COALESCE({a}.english_title, '')) = ''",
    "tagline": "btrim(COALESCE({a}.tagline, '')) = ''",
    "plot": "btrim(COALESCE({a}.plot, '')) = ''",
    "aired": "btrim(COALESCE({a}.premiered, '')) = ''",
    "year": "{a}.year IS NULL",
    "rating": "{a}.rating IS NULL",
    "runtime": "{a}.runtime_minutes IS NULL",
    "certification": "{a}.certifications = '{{}}'::jsonb",
    "genres": "cardinality({a}.genres) = 0",
    "language": "btrim(COALESCE({a}.original_language, '')) = ''",
    "country": "cardinality({a}.countries) = 0",
    "studio": "cardinality({a}.studios) = 0",
    "tags": "cardinality({a}.tags) = 0",
    "actors": "{a}.actors = '[]'::jsonb",
    "crew": "cardinality({a}.directors) = 0",
}

_SEASON_FIELD_SQL = {
    "title": "btrim(COALESCE({a}.title, '')) = ''",
    "sort_title": "btrim(COALESCE({a}.sort_title, '')) = ''",
    "year": "{a}.year IS NULL",
    "plot": "btrim(COALESCE({a}.plot, '')) = ''",
    "premiered": "btrim(COALESCE({a}.premiered, '')) = ''",
}

_SEASON_ID_SQL = {
    "id_tmdb": "tmdb", "id_imdb": "imdb", "id_tvdb": "tvdb", "id_trakt": "trakt",
    "id_tvmaze": "tvmaze", "id_wikidata": "wikidata",
}

_EPISODE_FIELD_SQL = {
    "title": "btrim(COALESCE({a}.title, '')) = ''",
    "original_title": "btrim(COALESCE({a}.original_title, '')) = ''",
    "english_title": "btrim(COALESCE({a}.english_title, '')) = ''",
    "plot": "btrim(COALESCE({a}.plot, '')) = ''",
    "aired": "btrim(COALESCE({a}.aired, '')) = ''",
    "rating": "{a}.rating IS NULL",
    "tags": "cardinality({a}.tags) = 0",
    "runtime": "{a}.runtime_minutes IS NULL",
    "actors": "{a}.guest_stars = '[]'::jsonb",
    "crew": "cardinality({a}.directors) = 0 AND cardinality({a}.writers) = 0",
    "credits": "cardinality({a}.writers) = 0",
    "director": "cardinality({a}.directors) = 0",
    "premiered": "btrim(COALESCE({a}.aired, '')) = ''",
    "ids": "{a}.ids = '{{}}'::jsonb",
}


def _gap_clauses(fields, mapping, alias):
    chosen = []
    for name in fields or []:
        if name in _GAP_SKIP:
            continue
        sql = mapping.get(name)
        if sql:
            chosen.append(sql.format(a=alias))
    return chosen


def _art_clauses(alias, kinds, params):
    clauses = []
    for kind in kinds or []:
        if not kind or kind in {"extrafanart", "extrathumbs"}:
            continue
        clauses.append(f"NOT ({alias}.artwork ? %s)")
        params.append(kind)
    return clauses


def ids_with_gaps(media, roots, cfg):
    """Titles under these folders that are missing an enabled field or an enabled image.

    A title, a set membership, a Top 250 place, and a trailer are not gaps. Extrafanart
    and extrathumbs live in folders and are filled when the title is looked up for another gap.
    """
    cfg = cfg or {}
    params = [list(roots)]
    if media == "movies":
        art = [kind for kind, on in (cfg.get("movie_art") or {}).items() if on]
        if cfg.get("scan_limited_art"):
            art = ["poster"] if "poster" in art else []
        clauses = _gap_clauses(cfg.get("movie_fields"), _MOVIE_FIELD_SQL, "m")
        clauses.extend(_art_clauses("m", art, params))
        if not clauses:
            return []
        rows = db.fetchall(
            "SELECT m.id FROM movies m WHERE m.root = ANY(%s) AND NOT m.locked "
            "AND m.status IS DISTINCT FROM 'IGNORED' AND (" + " OR ".join(clauses) + ")",
            tuple(params),
        )
        return [str(row["id"]) for row in rows]
    show_art = [kind for kind, on in (cfg.get("tv_art") or {}).items() if on]
    season_art = [kind for kind, on in (cfg.get("season_art") or {}).items() if on]
    if cfg.get("scan_limited_art"):
        show_art = ["poster"] if "poster" in show_art else []
        season_art = ["poster"] if "poster" in season_art else []
    show_clauses = _gap_clauses(cfg.get("show_fields"), _SHOW_FIELD_SQL, "s")
    show_clauses.extend(_art_clauses("s", show_art, params))
    season_clauses = _gap_clauses(cfg.get("season_fields"), _SEASON_FIELD_SQL, "x")
    for name in cfg.get("season_fields") or []:
        key = _SEASON_ID_SQL.get(name)
        if key:
            season_clauses.append("NOT (COALESCE(x.ids, '{}'::jsonb) ? %s)")
            params.append(key)
    season_clauses.extend(_art_clauses("x", season_art, params))
    episode_clauses = _gap_clauses(cfg.get("episode_fields"), _EPISODE_FIELD_SQL, "e")
    if cfg.get("episode_thumbs", True) and not cfg.get("scan_limited_art"):
        episode_clauses.append("NOT (e.artwork ? 'thumb')")
    parts = []
    if show_clauses:
        parts.append("(" + " OR ".join(show_clauses) + ")")
    if season_clauses:
        parts.append(
            "EXISTS (SELECT 1 FROM tv_seasons x WHERE x.show_id = s.id AND NOT x.locked "
            "AND x.status IS DISTINCT FROM 'IGNORED' AND (" + " OR ".join(season_clauses) + "))"
        )
    if episode_clauses:
        parts.append(
            "EXISTS (SELECT 1 FROM tv_episodes e WHERE e.show_id = s.id AND NOT e.locked "
            "AND e.status IS DISTINCT FROM 'IGNORED' AND NOT e.missing "
            "AND COALESCE(e.path, '') <> '' AND e.path NOT LIKE 'missing://%' AND ("
            + " OR ".join(episode_clauses) + "))"
        )
    if not parts:
        return []
    rows = db.fetchall(
        "SELECT s.id FROM tv_shows s WHERE s.root = ANY(%s) AND NOT s.locked "
        "AND s.status IS DISTINCT FROM 'IGNORED' AND (" + " OR ".join(parts) + ")",
        tuple(params),
    )
    return [str(row["id"]) for row in rows]


def ids_in(media, roots, scope):
    """Movie or show ids under these library folders. scope is "all" or "missing"."""
    table = "movies" if media == "movies" else "tv_shows"
    where = ["root = ANY(%s)", "NOT locked", "status IS DISTINCT FROM 'IGNORED'"]
    if scope == "missing" and media == "movies":
        where.append("(scraped_at IS NULL OR plot IS NULL OR tmdb_id IS NULL OR NOT (artwork ? 'poster'))")
    elif scope == "missing":
        where.append(
            "(scraped_at IS NULL OR plot IS NULL OR NOT (artwork ? 'poster') "
            "OR EXISTS (SELECT 1 FROM tv_episodes e WHERE e.show_id = tv_shows.id AND NOT e.locked AND e.status IS DISTINCT FROM 'IGNORED' "
            "AND (e.scraped_at IS NULL OR e.plot IS NULL OR btrim(COALESCE(e.plot, '')) = '' "
            "OR e.title IS NULL OR btrim(e.title) = '')) "
            f"OR {_season_without_poster('tv_shows.id')})"
        )
    rows = db.fetchall(f"SELECT id FROM {table} WHERE {' AND '.join(where)}", (list(roots),))
    return [str(row["id"]) for row in rows]


def movie_ids(scope, ids=None):
    if scope == "selected":
        rows = db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND NOT locked AND status IS DISTINCT FROM 'IGNORED'", (list(ids or []),))
    elif scope == "missing":
        rows = db.fetchall(
            "SELECT id FROM movies WHERE NOT locked AND status IS DISTINCT FROM 'IGNORED' AND (scraped_at IS NULL OR plot IS NULL OR tmdb_id IS NULL "
            "OR NOT (artwork ? 'poster')) ORDER BY lower(COALESCE(sort_title, title))"
        )
    else:
        rows = db.fetchall("SELECT id FROM movies WHERE NOT locked AND status IS DISTINCT FROM 'IGNORED' ORDER BY lower(COALESCE(sort_title, title))")
    return [str(row["id"]) for row in rows]


def show_ids(scope, ids=None):
    if scope == "selected":
        rows = db.fetchall("SELECT id FROM tv_shows WHERE id = ANY(%s::uuid[]) AND NOT locked AND status IS DISTINCT FROM 'IGNORED'", (list(ids or []),))
    elif scope == "missing":
        rows = db.fetchall(
            f"""
            SELECT s.id FROM tv_shows s WHERE NOT s.locked AND s.status IS DISTINCT FROM 'IGNORED' AND (
                s.scraped_at IS NULL OR s.plot IS NULL OR NOT (s.artwork ? 'poster')
                OR EXISTS (SELECT 1 FROM tv_episodes e WHERE e.show_id = s.id AND NOT e.locked AND e.status IS DISTINCT FROM 'IGNORED'
                           AND (e.scraped_at IS NULL OR e.plot IS NULL OR btrim(COALESCE(e.plot, '')) = ''
                                OR e.title IS NULL OR btrim(e.title) = ''))
                OR {_season_without_poster('s.id')})
            ORDER BY lower(COALESCE(s.sort_title, s.title))
            """
        )
    else:
        rows = db.fetchall("SELECT id FROM tv_shows WHERE NOT locked AND status IS DISTINCT FROM 'IGNORED' ORDER BY lower(COALESCE(sort_title, title))")
    return [str(row["id"]) for row in rows]


def movie_version_peers(movie):
    """Copies Kodi would treat as the same movie: TMDB id, else IMDb id, else title and year."""
    tmdb = str(movie.get("tmdb_id") or "").strip()
    imdb = str(movie.get("imdb_id") or "").strip()
    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    if tmdb:
        where, params = "m.tmdb_id = %s", (tmdb,)
    elif imdb:
        where, params = "lower(m.imdb_id) = lower(%s)", (imdb,)
    elif title and year:
        where, params = "lower(m.title) = lower(%s) AND m.year = %s", (title, int(year))
    else:
        return [{"id": movie.get("id"), "height": None, "bitrate_mbps": None}]
    rows = db.fetchall(
        f"""
        SELECT m.id, f.height, f.bitrate_mbps
        FROM movies m LEFT JOIN video_files f ON f.id = m.file_id
        WHERE {where}
        """,
        params,
    )
    peers = [db.clean(dict(row)) for row in rows]
    if not any(str(item.get("id")) == str(movie.get("id")) for item in peers):
        peers.append({"id": movie.get("id"), "height": None, "bitrate_mbps": None})
    return peers


def movie_row(movie_id):
    row = db.fetchone(
        """
        SELECT m.*, s.name AS set_name, s.overview AS set_overview, s.tmdb_collection_id AS set_tmdb_id
        FROM movies m LEFT JOIN movie_sets s ON s.id = m.set_id WHERE m.id = %s
        """,
        (movie_id,),
    )
    if not row:
        return None
    movie = dict(row)
    movie["file"] = _file(row["file_id"])
    return movie


def show_rows(show_id):
    show = db.fetchone("SELECT * FROM tv_shows WHERE id = %s", (show_id,))
    if not show:
        return None, [], []
    seasons = db.fetchall("SELECT * FROM tv_seasons WHERE show_id = %s ORDER BY season_number", (show_id,))
    episodes = db.fetchall(
        "SELECT * FROM tv_episodes WHERE show_id = %s ORDER BY season_number, episode_number", (show_id,)
    )
    return dict(show), [dict(row) for row in seasons], [dict(row) for row in episodes]


def file_row(file_id):
    return _file(file_id)


PATH_COLUMNS = {
    "video_files": ("path",),
    "movies": ("path", "folder", "nfo_path"),
    "tv_shows": ("path", "nfo_path"),
    "tv_seasons": ("path", "nfo_path"),
    "tv_episodes": ("path", "nfo_path"),
    "movie_sets": ("folder", "nfo_path"),
}
PATH_JSON = {
    "movies": ("artwork",), "tv_shows": ("artwork",), "tv_seasons": ("artwork",), "tv_episodes": ("artwork",),
    "video_files": ("external_subtitles",),
}


def rewrite_paths(moves):
    """Point stored paths at renamed files and folders. moves are (old, new, is_dir), applied in order."""
    with db.transaction() as conn:
        for old, new, is_dir in moves:
            like = like_prefix(old)
            for table, columns in PATH_COLUMNS.items():
                for column in columns:
                    if is_dir:
                        conn.execute(
                            f"UPDATE {table} SET {column} = %s || substr({column}, %s) "
                            f"WHERE {column} = %s OR {column} LIKE %s",
                            (new, len(old) + 1, old, like),
                        )
                    else:
                        conn.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = %s", (new, old))
            if is_dir:
                conn.execute(
                    """
                    UPDATE movies SET parts = ARRAY(
                        SELECT CASE WHEN u.p = %s OR u.p LIKE %s THEN %s || substr(u.p, %s) ELSE u.p END
                        FROM unnest(parts) WITH ORDINALITY AS u(p, n) ORDER BY u.n)
                    WHERE EXISTS (SELECT 1 FROM unnest(parts) AS x(p) WHERE x.p = %s OR x.p LIKE %s)
                    """,
                    (old, like, new, len(old) + 1, old, like),
                )
            else:
                conn.execute("UPDATE movies SET parts = array_replace(parts, %s, %s) WHERE %s = ANY(parts)",
                             (old, new, old))
            old_json = json.dumps(old, ensure_ascii=False)[1:-1]
            new_json = json.dumps(new, ensure_ascii=False)[1:-1]
            pattern = f'"{old_json}/' if is_dir else f'"{old_json}"'
            replacement = f'"{new_json}/' if is_dir else f'"{new_json}"'
            for table, columns in PATH_JSON.items():
                for column in columns:
                    conn.execute(
                        f"UPDATE {table} SET {column} = replace({column}::text, %s, %s)::jsonb "
                        f"WHERE strpos({column}::text, %s) > 0",
                        (pattern, replacement, pattern),
                    )


def refresh_external_subs(video_path):
    """Re-read the subtitle sidecars next to one video file after they were renamed."""
    from curator.video import naming

    folder, name = os.path.split(video_path)
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return
    external = []
    for other in names:
        if naming.ext(other) in naming.SUBTITLE_EXTS:
            info = naming.subtitle_info(name, other)
            if info:
                external.append(info)
    db.execute("UPDATE video_files SET external_subtitles = %s, updated_at = NOW() WHERE path = %s",
               (Jsonb(external), video_path))


def apply_fields(table, row_id, values, *, source=None, error=None, scraped=True):
    """Write scraped values. Locked rows and locked fields are left alone inside the same statement."""
    values = project_source_columns(table, dict(values))
    allowed = set(FIELDS[table]) | {"set_id"}
    columns = [column for column in values if column in allowed]
    sets, params = [], []
    for column in columns:
        sets.append(
            f"{column} = CASE WHEN '{column}' = ANY(locked_fields) THEN {column} ELSE %s END"
        )
        params.append(_value(column, values[column]))
    if scraped:
        sets.append("scraped_at = NOW()")
        sets.append("scrape_error = %s")
        params.append(error)
        if table != "tv_episodes":
            sets.append("scrape_source = COALESCE(%s, scrape_source)")
            params.append(source)
    sets.append("updated_at = NOW()")
    params.append(row_id)
    row = db.fetchone(
        f"UPDATE {table} SET {', '.join(sets)} WHERE id = %s AND NOT locked RETURNING id", params
    )
    return bool(row)


def set_ids(scope, ids=None):
    if scope == "selected":
        rows = db.fetchall("SELECT id FROM movie_sets WHERE id = ANY(%s::uuid[])", (list(ids or []),))
    elif scope == "missing":
        rows = db.fetchall(
            "SELECT id FROM movie_sets WHERE scraped_at IS NULL OR NOT (artwork ? 'poster') ORDER BY lower(name)"
        )
    else:
        rows = db.fetchall("SELECT id FROM movie_sets ORDER BY lower(name)")
    return [str(row["id"]) for row in rows]


def set_row(set_id):
    row = db.fetchone("SELECT * FROM movie_sets WHERE id = %s", (set_id,))
    return dict(row) if row else None


def save_set_meta(set_id, overview, tmdb_id):
    db.execute(
        "UPDATE movie_sets SET overview = CASE WHEN 'overview' = ANY(COALESCE(locked_fields, ARRAY[]::text[])) "
        "THEN overview ELSE COALESCE(NULLIF(%s, ''), overview) END, "
        "tmdb_collection_id = COALESCE(tmdb_collection_id, %s), updated_at = NOW() "
        "WHERE id = %s AND NOT COALESCE(locked, FALSE)",
        (overview or "", tmdb_id, set_id),
    )


def save_set_art(set_id, art, folder, nfo_path, error=None):
    db.execute(
        "UPDATE movie_sets SET artwork = %s, folder = %s, nfo_path = COALESCE(%s, nfo_path), scraped_at = NOW(), "
        "scrape_error = %s, updated_at = NOW() WHERE id = %s",
        (Jsonb(art or {}), folder, nfo_path, error, set_id),
    )


def title_of(table, row_id):
    if table == "movie_sets":
        row = db.fetchone("SELECT name FROM movie_sets WHERE id = %s", (row_id,))
        return row["name"] if row else str(row_id)
    if table == "tv_seasons":
        row = db.fetchone(
            "SELECT x.season_number, x.title, s.title AS show_title "
            "FROM tv_seasons x JOIN tv_shows s ON s.id = x.show_id WHERE x.id = %s",
            (row_id,),
        )
        if not row:
            return str(row_id)
        label = row.get("title") or ("Specials" if row.get("season_number") == 0 else f"Season {row.get('season_number')}")
        return f"{row['show_title']} · {label}" if row.get("show_title") else label
    try:
        row = db.fetchone(f"SELECT title, year FROM {table} WHERE id = %s", (row_id,))
    except Exception:
        return str(row_id)
    if not row:
        return str(row_id)
    return f"{row['title']} ({row['year']})" if row.get("year") else row["title"]


def scrape_failed(table, row_id, message):
    db.execute(f"UPDATE {table} SET scrape_error = %s, updated_at = NOW() WHERE id = %s", (message, row_id))


def expected_episode_numbers(season):
    """Episode numbers TMDB listed for this season. A count alone means 1..count, except for specials."""
    numbers = []
    for item in season.get("tmdb_episode_numbers") or []:
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    if numbers:
        return set(numbers)
    try:
        count = int(season.get("tmdb_episode_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0 and season.get("season_number") != 0:
        return set(range(1, count + 1))
    return set()


def _annotate_season_gaps(show):
    grouped = {}
    for episode in show.get("episodes") or []:
        grouped.setdefault(episode.get("season_id"), []).append(episode)
    for season in show.get("seasons") or []:
        have = {episode.get("episode_number") for episode in grouped.get(season["id"], [])}
        expected = expected_episode_numbers(season)
        extra = have - expected if expected else set()
        season["missing_episodes"] = sorted(expected - have) if expected else []
        season["extra_episodes"] = sorted(extra)
        for episode in grouped.get(season["id"], []):
            episode["extra"] = episode.get("episode_number") in extra


def fill_empty_source(file_id, label):
    """Keep a <source> tag from an .nfo when the filename did not name a source."""
    from curator.video.sources import canonical_source

    if not file_id or not label:
        return
    current = db.fetchone("SELECT source_format FROM video_files WHERE id = %s", (file_id,))
    if not current or current.get("source_format"):
        return
    source, group = canonical_source(label)
    if not source:
        return
    db.execute(
        "UPDATE video_files SET source_format = %s, video_source = COALESCE(video_source, %s), updated_at = NOW() WHERE id = %s",
        (source, group, file_id),
    )


def apply_release_names(file_id, facts):
    """Write the release parsed from the new file and folder over the previous one.

    Edition follows the new name, and is cleared when the new name does not name one.
    Source and release group are written when the new name has them. Hybrid and 3D stay
    when the probe already saw them in the streams.
    """
    if not file_id or not facts:
        return
    columns = ["edition = %s", "is_hybrid = is_hybrid OR %s",
               "is_3d = CASE WHEN %s THEN TRUE ELSE is_3d END",
               "stereo_mode = CASE WHEN %s <> '' THEN %s ELSE stereo_mode END"]
    params = [
        facts.get("edition"), bool(facts.get("is_hybrid")), bool(facts.get("is_3d")),
        facts.get("stereo_mode") or "", facts.get("stereo_mode") or "",
    ]
    if facts.get("source_format"):
        columns.extend(["source_format = %s", "video_source = %s"])
        params.extend([facts.get("source_format"), facts.get("video_source")])
    if facts.get("release_group"):
        columns.append("release_group = %s")
        params.append(facts.get("release_group"))
    params.append(file_id)
    db.execute(
        f"UPDATE video_files SET {', '.join(columns)}, updated_at = NOW() WHERE id = %s",
        params,
    )


def retarget_movie(movie_id, path, folder):
    """Point an existing movie at a replacement file when the movie row was the old file path."""
    db.execute(
        "UPDATE movies SET path = %s, folder = %s, updated_at = NOW() WHERE id = %s",
        (path, folder, movie_id),
    )


def update_item_file(kind, row_id, values):
    """Source, edition and hybrid live on the video file, not the movie or episode row."""
    from curator.video.sources import canonical_source

    table = "movies" if kind == "movie" else "tv_episodes"
    row = db.fetchone(f"SELECT file_id FROM {table} WHERE id = %s", (row_id,))
    if not row or not row.get("file_id"):
        return False
    stored = {}
    if "source_format" in values:
        label, group = canonical_source(values.get("source_format"))
        stored["source_format"] = label
        stored["video_source"] = group
    if "edition" in values:
        from curator.video.sources import canonical_edition

        stored["edition"] = canonical_edition(values.get("edition"))
    if "is_hybrid" in values:
        stored["is_hybrid"] = bool(values.get("is_hybrid"))
    if "release_group" in values:
        text = str(values.get("release_group") or "").strip()
        stored["release_group"] = text[:40] or None
    if not stored:
        return False
    columns = list(stored)
    db.execute(
        f"UPDATE video_files SET {', '.join(f'{column} = %s' for column in columns)}, updated_at = NOW() WHERE id = %s",
        [stored[column] for column in columns] + [row["file_id"]],
    )
    return True


def save_ratings(kind, row_id, ratings, rating, votes):
    table = table_for(kind)
    values = project_source_columns(table, {"ratings": ratings or {}})
    columns = ["ratings", "rating", "votes"] + [column for _, column in RATING_COLUMNS if column in values]
    params = [Jsonb(ratings or {}), rating, votes] + [values[column] for _, column in RATING_COLUMNS if column in values]
    db.execute(
        f"UPDATE {table} SET {', '.join(f'{column} = %s' for column in columns)}, updated_at = NOW() WHERE id = %s",
        params + [row_id],
    )


def merge_ids(kind, row_id, ids):
    table = table_for(kind)
    values = project_source_columns(table, {"ids": ids or {}})
    columns = [column for column in ID_ON_TABLE[table] if column in values]
    if not columns and not ids:
        return
    sets = ["ids = COALESCE(ids, '{}'::jsonb) || %s::jsonb"]
    params = [json.dumps({key: value for key, value in (ids or {}).items() if value})]
    for column in columns:
        sets.append(f"{column} = %s")
        params.append(values[column])
    params.append(row_id)
    db.execute(f"UPDATE {table} SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s", params)


def save_season_meta(season_id, values):
    allowed = ("title", "plot", "premiered", "trailer", "year", "sort_title", "tmdb_episode_count", "tmdb_episode_numbers")
    if values.get("premiered") and "year" not in values:
        text = str(values["premiered"])
        if len(text) >= 4 and text[:4].isdigit():
            values = dict(values)
            values["year"] = int(text[:4])
    columns = [column for column in allowed if column in values]
    ids = values.get("ids") if isinstance(values.get("ids"), dict) else None
    if not columns and not ids:
        return
    sets = [f"{column} = %s" for column in columns]
    params = [values[column] for column in columns]
    if ids:
        sets.append("ids = COALESCE(ids, '{}'::jsonb) || %s::jsonb")
        params.append(Jsonb({key: value for key, value in ids.items() if value}))
    params.append(season_id)
    db.execute(
        f"UPDATE tv_seasons SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s AND NOT locked",
        params,
    )


def merge_season_name(show_id, number, name):
    """Remember a season title that is a name, so tvshow.nfo can write namedseason."""
    if not show_id or number is None:
        return
    text = str(name or "").strip()
    if not text:
        db.execute(
            """
            UPDATE tv_shows
            SET season_names = COALESCE(season_names, '{}'::jsonb) - %s, updated_at = NOW()
            WHERE id = %s AND NOT locked
            """,
            (str(number), show_id),
        )
        return
    db.execute(
        """
        UPDATE tv_shows
        SET season_names = COALESCE(season_names, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
        WHERE id = %s AND NOT locked
        """,
        (Jsonb({str(number): text}), show_id),
    )


def save_nfo_state(table, row_id, nfo_path, nfo_mtime):
    db.execute(
        f"UPDATE {table} SET nfo_path = %s, nfo_mtime = %s WHERE id = %s", (nfo_path, nfo_mtime, row_id)
    )


def link_set(movie_id, info):
    set_id = save_set(info)
    row = db.fetchone(
        "SELECT set_id FROM movies WHERE id = %s AND NOT locked AND NOT ('set' = ANY(locked_fields))",
        (movie_id,),
    )
    if not row:
        return set_id
    previous = row.get("set_id")
    db.execute("UPDATE movies SET set_id = %s WHERE id = %s", (set_id, movie_id))
    if str(previous or "") != str(set_id):
        note_set_new(set_id)
    return set_id


def set_watched(kind, row_id, watched):
    """Mark a movie or episode watched without lowering a play count that is already above one."""
    table = table_for(kind)
    if table not in {"movies", "tv_episodes"}:
        raise ValueError(kind)
    if watched:
        assignment = "playcount = GREATEST(COALESCE(playcount, 0), 1)"
        locked = ["playcount"]
    else:
        assignment = "playcount = 0, last_played = NULL"
        locked = ["playcount", "last_played"]
    db.execute(
        f"UPDATE {table} SET {assignment}, "
        "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))), "
        "updated_at = NOW() WHERE id = %s AND NOT locked",
        (locked, row_id),
    )


def edit(kind, row_id, values):
    """Inline edit from the UI. Every edited field joins locked_fields so scrapes leave it alone."""
    table = table_for(kind)
    allowed = FIELDS[table]
    values = dict(values)
    locked_extra = []
    if kind == "movie" and "set_name" in values:
        set_name = str(values.pop("set_name") or "").strip()
        set_overview = str(values.pop("set_overview", "") or "").strip()
        if set_name:
            values["set_id"] = save_set({"name": set_name, "overview": set_overview})
        else:
            values["set_id"] = None
        locked_extra.append("set")
    columns = [column for column in values if column in allowed or column == "set_id"]
    if not columns:
        return False
    sets = [f"{column} = %s" for column in columns]
    params = [_value(column, values[column]) for column in columns]
    locked_cols = [col for col in columns if col != "set_id"] + locked_extra
    sets.append("locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[])))")
    params.append(locked_cols)
    sets.append("updated_at = NOW()")
    params.append(row_id)
    row = db.fetchone(f"UPDATE {table} SET {', '.join(sets)} WHERE id = %s RETURNING id", params)
    return bool(row)


def match_ids(source, source_id, extra=None):
    """Ids to store for a Fix Match pick. Companions from the search hit are kept; anything else is dropped."""
    allowed = {"tmdb", "imdb", "tvdb", "trakt"}
    ids = {}
    for key, value in (extra or {}).items():
        text = str(value or "").strip()
        if text and key in allowed:
            ids[key] = text
    source_id = str(source_id or "").strip()
    if source == "omdb":
        ids["imdb"] = source_id
    elif source in allowed:
        ids[source] = source_id
    return ids


def set_match(kind, row_id, source, source_id, extra=None):
    """Point an item at a different scraper id. Old ids are dropped so the next scrape cannot mix two titles.

    Returns the duplicate and upgrade flags for the copies that share the old or new identity.
    None means the item is locked or gone.
    """
    from curator.video import copies

    ids = match_ids(source, source_id, extra)
    if kind == "movie" and source in {"tmdb", "tvdb", "omdb", "trakt"}:
        before = copies.movie_seed_rows([row_id])
        row = db.fetchone(
            "UPDATE movies SET ids = %s, tmdb_id = %s, imdb_id = %s, trakt_id = %s "
            "WHERE id = %s AND NOT locked RETURNING id",
            (Jsonb(ids), ids.get("tmdb"), ids.get("imdb"), ids.get("trakt"), row_id),
        )
    elif kind == "show" and source in {"tmdb", "tvdb", "omdb", "trakt"}:
        before = copies.episode_seeds_for_shows([row_id])
        row = db.fetchone(
            "UPDATE tv_shows SET ids = %s, tmdb_id = %s, tvdb_id = %s, imdb_id = %s, trakt_id = %s "
            "WHERE id = %s AND NOT locked RETURNING id",
            (Jsonb(ids), ids.get("tmdb"), ids.get("tvdb"), ids.get("imdb"), ids.get("trakt"), row_id),
        )
    elif kind == "set" and source == "tmdb":
        row = db.fetchone(
            "UPDATE movie_sets SET tmdb_collection_id = %s, updated_at = NOW() "
            "WHERE id = %s AND NOT COALESCE(locked, FALSE) RETURNING id",
            (ids.get("tmdb"), row_id),
        )
        return [] if row else None
    else:
        raise ValueError(f"{kind}/{source}")
    if not row:
        return None
    # A title the user matched by hand is no longer waiting for Apply match.
    clear_pending_match("movies" if kind == "movie" else "tv_shows", row_id)
    if kind == "movie":
        seeds = list(before) + list(copies.movie_seed_rows([row_id]))
        copies.refresh_movie_seeds(seeds)
        return copies.peer_flags("movie", seeds)
    seeds = list(before) + list(copies.episode_seeds_for_shows([row_id]))
    copies.refresh_episode_seeds(seeds)
    return copies.peer_flags("episode", seeds)


_PREF_TABLES = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes"}


def scrape_prefs(kind, row_id):
    table = _PREF_TABLES.get(kind)
    if not table:
        raise ValueError(kind)
    columns = "preferred_source, preferred_art"
    if kind == "show":
        columns += ", episode_order"
    row = db.fetchone(f"SELECT {columns} FROM {table} WHERE id = %s", (row_id,))
    return dict(row) if row else None


def save_scrape_prefs(kind, row_id, source, art, episode_order=None):
    """Store a per-item provider. Empty values mean the global chain. Episode order locks like Edit."""
    table = _PREF_TABLES.get(kind)
    if not table:
        raise ValueError(kind)
    source = source or None
    art = art or None
    if kind != "show":
        row = db.fetchone(
            f"UPDATE {table} SET preferred_source = %s, preferred_art = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            (source, art, row_id),
        )
        return bool(row)
    if episode_order:
        row = db.fetchone(
            """
            UPDATE tv_shows
            SET preferred_source = %s, preferred_art = %s, episode_order = %s,
                locked_fields = (
                    SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['episode_order']::text[]))
                ),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (source, art, episode_order, row_id),
        )
    else:
        row = db.fetchone(
            """
            UPDATE tv_shows
            SET preferred_source = %s, preferred_art = %s, episode_order = NULL,
                locked_fields = ARRAY(
                    SELECT unnest(locked_fields) EXCEPT SELECT 'episode_order'
                ),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (source, art, row_id),
        )
    return bool(row)


def lock_fields(kind, row_id, fields):
    table = table_for(kind)
    db.execute(
        f"UPDATE {table} SET locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))), "
        "updated_at = NOW() WHERE id = %s",
        (list(fields), row_id),
    )


def unlock_fields(kind, row_id, fields):
    table = table_for(kind)
    db.execute(
        f"UPDATE {table} SET locked_fields = ARRAY(SELECT unnest(locked_fields) EXCEPT SELECT unnest(%s::text[])), "
        "updated_at = NOW() WHERE id = %s",
        (list(fields), row_id),
    )


def set_lock(kind, ids, locked):
    ids = list(ids)
    with db.transaction() as conn:
        if kind == "movie":
            conn.execute("UPDATE movies SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "show":
            conn.execute("UPDATE tv_shows SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_seasons SET locked = %s WHERE show_id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE show_id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "season":
            conn.execute("UPDATE tv_seasons SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE season_id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "episode":
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "set":
            conn.execute("UPDATE movie_sets SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        else:
            raise ValueError(kind)


def remove(kind, ids):
    ids = list(ids)
    flag_kind, seeds, flag_ids = _removal_seeds(kind, ids)
    table = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes", "set": "movie_sets"}.get(kind)
    if not table:
        raise ValueError(kind)
    if not ids:
        return []
    file_ids, paths, set_ids = [], [], []
    with db.transaction() as conn:
        if kind in {"show", "season"}:
            column = "show_id" if kind == "show" else "season_id"
            held = conn.execute(
                f"""
                SELECT e.file_id, e.path FROM tv_episodes e WHERE e.{column} = ANY(%s::uuid[])
                UNION ALL
                SELECT c.file_id, NULL::text FROM episode_copies c
                JOIN tv_episodes e ON e.id = c.episode_id
                WHERE e.{column} = ANY(%s::uuid[])
                """,
                (ids, ids),
            ).fetchall()
            for row in held:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                if row["path"]:
                    paths.append(row["path"])
        if kind == "movie":
            rows = conn.execute(
                "DELETE FROM movies WHERE id = ANY(%s::uuid[]) RETURNING id, file_id, parts, set_id",
                (ids,),
            ).fetchall()
            for row in rows:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                paths.extend(row["parts"] or [])
                if row["set_id"]:
                    set_ids.append(row["set_id"])
        elif kind == "episode":
            copies = conn.execute(
                "SELECT file_id FROM episode_copies WHERE episode_id = ANY(%s::uuid[])",
                (ids,),
            ).fetchall()
            file_ids.extend(row["file_id"] for row in copies if row["file_id"])
            rows = conn.execute(
                "DELETE FROM tv_episodes WHERE id = ANY(%s::uuid[]) RETURNING id, file_id, path",
                (ids,),
            ).fetchall()
            for row in rows:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                if row["path"]:
                    paths.append(row["path"])
        else:
            rows = conn.execute(f"DELETE FROM {table} WHERE id = ANY(%s::uuid[]) RETURNING id", (ids,)).fetchall()
    _drop_released_files(file_ids, paths)
    _drop_empty_sets(set_ids)
    removed = [str(row["id"]) for row in rows]
    peers = _settle_removed_flags(flag_kind, seeds, flag_ids) if removed else []
    return removed, peers


def _removal_seeds(kind, ids):
    """Identity rows and the item ids whose Not duplicates rows should go, read before the delete."""
    from curator.video import copies

    if kind == "movie":
        return "movie", copies.movie_seed_rows(ids), list(ids)
    if kind == "episode":
        return "episode", copies.episode_seed_rows(ids), list(ids)
    if kind == "season":
        rows = db.fetchall(
            "SELECT id::text AS id FROM tv_episodes WHERE season_id = ANY(%s::uuid[])",
            (list(ids),),
        )
        return "episode", copies.episode_seeds_for_seasons(ids), [row["id"] for row in rows]
    if kind == "show":
        rows = db.fetchall(
            "SELECT id::text AS id FROM tv_episodes WHERE show_id = ANY(%s::uuid[])",
            (list(ids),),
        )
        return "episode", copies.episode_seeds_for_shows(ids), [row["id"] for row in rows]
    return "", [], []


def _settle_removed_flags(kind, seeds, ids):
    """Drop Not duplicates rows for the removed copies and rewrite the flags on whatever remains."""
    from curator.video import copies

    ids = [str(item) for item in ids or [] if item]
    if ids and kind in {"movie", "episode"}:
        db.execute(
            """
            DELETE FROM video_dismissed_duplicates
            WHERE kind = %s AND (left_id = ANY(%s::uuid[]) OR right_id = ANY(%s::uuid[]))
            """,
            (kind, ids, ids),
        )
    if kind == "movie":
        copies.refresh_movie_seeds(seeds)
        return copies.peer_flags("movie", seeds)
    if kind == "episode":
        copies.refresh_episode_seeds(seeds)
        return copies.peer_flags("episode", seeds)
    return []


def _drop_released_files(file_ids, paths):
    """Drop probe rows that belonged to the items just removed and are not used by anything left."""
    file_ids = [item for item in file_ids if item] or ["00000000-0000-0000-0000-000000000000"]
    paths = [item for item in paths if item]
    if paths == [] and file_ids == ["00000000-0000-0000-0000-000000000000"]:
        return
    if not paths:
        paths = [""]
    db.execute(
        """
        DELETE FROM video_files f
        WHERE (f.id = ANY(%s::uuid[]) OR f.path = ANY(%s))
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.file_id = f.id OR f.path = ANY(m.parts))
          AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.file_id = f.id)
          AND NOT EXISTS (SELECT 1 FROM episode_copies c WHERE c.file_id = f.id)
        """,
        (file_ids, paths),
    )


def _drop_empty_sets(set_ids):
    set_ids = [item for item in set_ids if item]
    if not set_ids:
        return
    db.execute(
        """
        DELETE FROM movie_sets s
        WHERE s.id = ANY(%s::uuid[])
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.set_id = s.id)
        """,
        (set_ids,),
    )


def start_scrape_job(media, scope):
    row = db.fetchone(
        "INSERT INTO video_scrape_jobs (media, scope, status) VALUES (%s, %s, 'running') RETURNING id",
        (media, scope),
    )
    return str(row["id"]) if row else None


def finish_scrape_job(job_id, status, message, result):
    if not job_id:
        return
    db.execute(
        "UPDATE video_scrape_jobs SET status = %s, message = %s, result = %s, finished_at = NOW() WHERE id = %s",
        (status, message, Jsonb(result), job_id),
    )
