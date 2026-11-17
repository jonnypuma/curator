"""Postgres reads and writes for movies, movie sets, TV shows, seasons, episodes and video files."""
from __future__ import annotations

import json
import logging
import os

from psycopg.types.json import Jsonb

from curator.video import health, integrity
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
EDITABLE_ID_KEYS = (*ID_COLUMNS, "ofdbcc", "wikidata")
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


def keep_sources(old, new):
    """An artwork map rebuilt from the files on disk (a scan) has no _sources, the online picture each file was
    downloaded from. Keep the source of every type whose file is still the same path, so the artwork window still marks
    that picture In use. A map that brings its own _sources (a pick or Clean artwork) is kept as it is."""
    if not isinstance(new, dict) or "_sources" in new or not isinstance(old, dict):
        return new
    files = {(extra, os.path.basename(value)) for key, value in new.items() for extra in ("extrafanart", "extrathumbs")
             if str(key).startswith(extra) and isinstance(value, str)}
    kept = {kind: url for kind, url in (old.get("_sources") or {}).items()
            if (isinstance(new.get(kind), str) and new.get(kind) == old.get(kind))
            or (":" in str(kind) and tuple(str(kind).split(":", 1)) in files)}
    return {**new, "_sources": kept} if kept else new


def _upsert(conn, table, keys, values):
    if table in ("movies", "tv_shows", "tv_episodes"):
        values = project_source_columns(table, dict(values))
    if "artwork" in values and table in ("movies", "tv_shows", "tv_seasons", "tv_episodes") and all(key in values for key in keys):
        from curator.video import art_sizes

        found = conn.execute(f"SELECT artwork FROM {table} WHERE {' AND '.join(f'{key} = %s' for key in keys)}",
                             [values[key] for key in keys]).fetchone()
        art = values["artwork"]
        if found:
            art = keep_sources(found.get("artwork"), art)
        # Width and height of each file, kept while the file is unchanged.
        art = art_sizes.with_sizes((found or {}).get("artwork"), art)
        values = {**values, "artwork": art}
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


def movie_file_paths(row):
    """Every video file of a movie row that carries file_path (video_files.path) and parts.

    movies.path is the movie's folder, not its file. Players, playlists and the apps all name the file."""
    parts = row.get("parts") if isinstance(row.get("parts"), list) else []
    return [path for path in dict.fromkeys([row.get("file_path"), *parts]) if path]


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
            mediainfo_xml.write(path, payload, size, kind)
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
    if isinstance(art, dict):
        from curator.video import art_sizes

        found = db.fetchone(f"SELECT artwork FROM {table} WHERE id = %s", (row_id,))
        old = (found or {}).get("artwork")
        if "_sources" not in art:
            art = keep_sources(old, art)
        # The width and height of each file, read only for a new or changed file (shape checks read these).
        art = art_sizes.with_sizes(old, art)
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
        "SELECT id, path, nfo_path, nfo_mtime, artwork, updated_at, tvdb_id FROM tv_shows WHERE root = ANY(%s)", (list(roots),)
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
        SELECT e.show_id::text AS show_id, e.season_number, e.episode_number, e.path, e.locked_fields
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
               title, plot, ratings, rating, votes, guest_stars, mpaa, certifications, missing, locked_fields
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


def prune_placeholders(show_id, keep):
    """Drop the missing-episode placeholders a source no longer lists, and the seasons left empty.

    Used after Fix Match, when the show now has another identity and its old placeholders (seasons and episodes of
    the wrong show) would otherwise stay. Locks do not matter, the old identity is gone. Only database entries go; episodes with a file are never touched.
    Returns the number of placeholders removed.
    """
    numbers = sorted(keep)
    with db.transaction() as conn:
        removed = conn.execute(
            """
            DELETE FROM tv_episodes e
            WHERE e.show_id = %s AND e.missing AND e.path LIKE 'missing://%%'
              AND NOT EXISTS (
                SELECT 1 FROM unnest(%s::int[], %s::int[]) AS k(s, n)
                WHERE k.s = e.season_number AND k.n = e.episode_number
              )
            RETURNING id
            """,
            (show_id, [item[0] for item in numbers], [item[1] for item in numbers]),
        ).fetchall()
        if removed:
            conn.execute(
                """
                DELETE FROM tv_seasons x
                WHERE x.show_id = %s
                  AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = x.id)
                """,
                (show_id,),
            )
    return len(removed)


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
              AND NOT EXISTS (SELECT 1 FROM music_videos v WHERE v.file_id = f.id)
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
    f.video_source, f.source_format, f.probed_at, f.fps, f.aspect_ratio, f.max_cll, f.max_fall, f.mtime,
    f.integrity, f.integrity_size, f.integrity_mtime
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
    if isinstance(row.get("parts"), list) and row["parts"]:
        row["display_parts"] = [display_path(str(part)) for part in row["parts"] if part]
    nested = row.get("file")
    if isinstance(nested, dict):
        _annotate_display(nested)
    return row


def _movie_rows(where="", params=()):
    import time

    from curator.video import nfo_digest

    started = time.monotonic()
    rows = db.fetchall(
        f"""
        SELECT m.id, m.title, m.sort_title, m.original_title, m.english_title, m.year, m.edition, m.runtime_minutes, m.mpaa,
               m.genres, m.studios, m.countries, m.directors, m.rating, m.votes, m.imdb_id, m.tmdb_id,
               m.status, m.playcount, m.path, m.folder, m.root, m.nfo_path, m.nfo_digest, m.nfo_path IS NOT NULL AS has_nfo,
               m.tags, m.trailer, m.has_local_trailer, m.has_local_theme, {nfo_digest.sig_sql("movies", "m")},
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
    from curator.video import copies

    movies = copies.library_rows(movies)
    deduped = time.monotonic()
    nfo_digest.apply("movies", movies)
    finished = time.monotonic()
    if finished - started > 3.0:
        logger.info("movie rows: query %.1fs, paths and fields %.1fs, duplicate check %.1fs, .nfo check %.1fs (%d rows)",
                    queried - started, shaped - queried, deduped - shaped, finished - deduped, len(rows))
    for movie in movies:
        movie["has_trailer"] = bool(movie.get("trailer"))
        for key in ("tagline", "outline", "plot", "premiered", "tags", "writers", "trailer", "nfo_digest", "english_title", "nfo_sig"):
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
    from curator.video import match_undo

    movie["match_undo"] = match_undo.available(movie_id)
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
               m.folder, {FILE_BRIEF}
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


def _family_nfo_shows(show_ids=None):
    """Show ids whose season.nfo or episode.nfo no longer matches the database.

    show_ids limits the check to those shows (a refresh while a scan runs); None checks every show."""
    from curator.video import nfo_digest

    only, params = "", ()
    if show_ids is not None:
        if not show_ids:
            return set()
        only, params = " AND show_id = ANY(%s::uuid[])", ([str(item) for item in show_ids],)
    seasons = [
        db.clean(dict(row)) for row in db.fetchall(
            """
            SELECT id, show_id, nfo_path, nfo_digest, """ + nfo_digest.sig_sql("tv_seasons", "tv_seasons") + """
            FROM tv_seasons WHERE nfo_path IS NOT NULL""" + only,
            params,
        )
    ]
    episodes = [
        db.clean(dict(row)) for row in db.fetchall(
            """
            SELECT id, show_id, nfo_path, nfo_digest, """ + nfo_digest.sig_sql("tv_episodes", "tv_episodes") + """
            FROM tv_episodes WHERE nfo_path IS NOT NULL AND NOT missing""" + only,
            params,
        )
    ]
    nfo_digest.apply("tv_seasons", seasons)
    nfo_digest.apply("tv_episodes", episodes)
    return {str(row["show_id"]) for row in seasons + episodes if row.get("nfo_stale")}


GAP_KEYS = ("no_imdb_count", "no_subs_count", "no_en_subs_count", "multi_audio_count",
            "unknown_audio_count", "unknown_subs_count", "no_thumb_count", "no_nfo_count",
            "uhd_count", "fhd_count", "fel_count", "dv_count", "hdr10plus_count", "hdr10_count", "hlg_count", "sdr_count",
            "corrupt_count")
# Per-show quality totals and the episode filter each one counts.
QUALITY_GAPS = {"uhd_count": "uhd", "fhd_count": "fhd", "fel_count": "fel", "dv_count": "dv",
                "hdr10plus_count": "hdr10plus", "hdr10_count": "hdr10", "hlg_count": "hlg", "sdr_count": "sdr"}


def _episode_gaps(show_ids=None):
    """Per show, how many of its episodes on disk lack a score, subtitles, a thumb and so on.

    The list filters (No IMDb rating, No subtitles ...) need this for a show whose episodes the page has not
    loaded yet, so they match only shows that really have such an episode."""
    where = "WHERE NOT e.missing"
    params = ()
    if show_ids is not None:
        if not show_ids:
            return {}
        where += " AND e.show_id = ANY(%s)"
        params = (list(show_ids),)
    rows = db.fetchall(
        f"""
        SELECT e.show_id, e.rating_imdb, e.artwork, e.nfo_path, f.audio_tracks, f.subtitle_tracks, f.external_subtitles,
               f.resolution, f.hdr_format, f.hdr_secondary, f.dovi_profile, f.dovi_el_type,
               f.integrity, f.integrity_size, f.integrity_mtime, f.size_bytes, f.mtime
        FROM tv_episodes e LEFT JOIN video_files f ON f.id = e.file_id
        {where}
        """,
        params,
    )
    totals = {}
    for row in rows:
        brief = brief_file({
            "audio_tracks": row.get("audio_tracks"), "subtitle_tracks": row.get("subtitle_tracks"),
            "external_subtitles": row.get("external_subtitles"), "artwork": row.get("artwork"),
        })
        count = totals.setdefault(str(row["show_id"]), dict.fromkeys(GAP_KEYS, 0))
        if not (_number(row.get("rating_imdb")) > 0):
            count["no_imdb_count"] += 1
        if not brief["sub_langs"]:
            count["no_subs_count"] += 1
        if not any(str(lang).lower().startswith("en") for lang in brief["sub_langs"]):
            count["no_en_subs_count"] += 1
        if len(brief["audio_langs"]) > 1:
            count["multi_audio_count"] += 1
        if brief["audio_unknown"] > 0:
            count["unknown_audio_count"] += 1
        if brief["sub_unknown"] > 0:
            count["unknown_subs_count"] += 1
        if "thumb" not in brief["artwork"]:
            count["no_thumb_count"] += 1
        if not row.get("nfo_path"):
            count["no_nfo_count"] += 1
        if integrity.corrupt(row):
            count["corrupt_count"] += 1
        for key, name in QUALITY_GAPS.items():
            if EPISODE_FILTERS[name](row):
                count[key] += 1
    return totals


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# What each episode filter means for one episode, so a selection made under a filter can be worked out in one query.
# The page has the same tests for rows it already holds (TV_RIBBONS in tv.js).
EPISODE_FILTERS = {
    "noimdb": lambda f: not (_number(f.get("rating_imdb")) > 0),
    "nosubs": lambda f: not f["sub_langs"],
    "noen_subs": lambda f: not any(str(lang).lower().startswith("en") for lang in f["sub_langs"]),
    "multi_audio": lambda f: len(f["audio_langs"]) > 1,
    "unknown_audio": lambda f: f["audio_unknown"] > 0,
    "unknown_subs": lambda f: f["sub_unknown"] > 0,
    "nothumb": lambda f: "thumb" not in f["artwork"],
    "nonfo": lambda f: not f.get("nfo_path"),
    "locked": lambda f: bool(f.get("locked")),
    "upgrade": lambda f: bool(f.get("upgrade_source_id") or (f.get("upgrade_copy_path") or "")),
    "duplicate": lambda f: bool(f.get("duplicate_release")),
    "new": lambda f: f.get("status") == "NEW",
    "ignored": lambda f: f.get("status") == "IGNORED",
    "scrapefail": lambda f: bool(f.get("scrape_error")),
    "unscraped": lambda f: not f.get("scraped_at"),
    "probefail": lambda f: bool(f.get("probe_error")),
    "corrupt": lambda f: integrity.corrupt(f),
    "uhd": lambda f: f.get("resolution") in ("4K", "8K"),
    "fhd": lambda f: f.get("resolution") == "1080p",
    "fel": lambda f: str(f.get("dovi_profile") or "").startswith("7") and f.get("dovi_el_type") == "FEL",
    "dv": lambda f: f.get("hdr_format") == "dovi",
    "hdr10plus": lambda f: f.get("hdr_format") == "hdr10plus" or f.get("hdr_secondary") == "HDR10+",
    "hdr10": lambda f: f.get("hdr_format") == "hdr10" or f.get("hdr_secondary") == "HDR10",
    "hlg": lambda f: f.get("hdr_format") == "hlg" or f.get("hdr_secondary") == "HLG",
    "sdr": lambda f: f.get("hdr_format") == "sdr",
    "multi": lambda f: len(_span(f.get("file_span"))) > 1,
}
# Filters that are about the show or the season, never about an episode: no episode passes them.
SHOW_ONLY_FILTERS = {"noposter", "notrailer", "missing_trailer", "missing_theme", "unmatched"}
SEASON_FILTERS = {"noposter"}          # a show-level filter that a season can match too (no poster)


def _span(value):
    if isinstance(value, str):
        try:
            import json

            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def tv_selection(show_ids, filters=None):
    """The seasons and episodes that go with ticked shows, in one pass.

    Only episodes that are on disk and pass every active filter are picked. A season is picked when it holds a picked
    episode (or, with no filter, always). Filters this cannot judge come back as `unsupported`; the page then works
    them out itself from the opened shows."""
    ids = [str(item) for item in (show_ids or []) if item]
    names = [str(item) for item in (filters or []) if item]
    unsupported = [name for name in names if name not in EPISODE_FILTERS and name not in SHOW_ONLY_FILTERS]
    if unsupported:
        return {"unsupported": unsupported}
    if not ids:
        return {"seasons": [], "episodes": [], "by_show": {}}
    tests = [EPISODE_FILTERS[name] for name in names if name in EPISODE_FILTERS]
    no_episode_passes = any(name in SHOW_ONLY_FILTERS for name in names)
    by_show = {}

    def bucket(show_id):
        return by_show.setdefault(str(show_id), {"seasons": [], "episodes": []})

    if not names:
        for row in db.fetchall("SELECT id, show_id FROM tv_seasons WHERE show_id = ANY(%s)", (ids,)):
            bucket(row["show_id"])["seasons"].append(str(row["id"]))
        for row in db.fetchall("SELECT id, show_id FROM tv_episodes WHERE NOT missing AND show_id = ANY(%s)", (ids,)):
            bucket(row["show_id"])["episodes"].append(str(row["id"]))
    elif not no_episode_passes:
        rows = db.fetchall(
            """
            SELECT e.id, e.show_id, e.season_id, e.rating_imdb, e.artwork, e.nfo_path, e.locked, e.status, e.scrape_error,
                   e.scraped_at, e.duplicate_release, e.upgrade_source_id, e.upgrade_copy_path, e.file_span,
                   f.audio_tracks, f.subtitle_tracks, f.external_subtitles, f.resolution, f.hdr_format, f.hdr_secondary,
                   f.dovi_profile, f.dovi_el_type, f.probe_error,
                   f.integrity, f.integrity_size, f.integrity_mtime, f.size_bytes, f.mtime
            FROM tv_episodes e LEFT JOIN video_files f ON f.id = e.file_id
            WHERE NOT e.missing AND e.show_id = ANY(%s)
            """,
            (ids,),
        )
        seasons = {}
        for row in rows:
            facts = dict(row)
            facts.update(brief_file(dict(row)))
            if all(test(facts) for test in tests):
                bucket(row["show_id"])["episodes"].append(str(row["id"]))
                seasons.setdefault(str(row["show_id"]), set()).add(str(row["season_id"]))
        for show_id, picked in seasons.items():
            bucket(show_id)["seasons"] = sorted(picked)
    elif set(names) <= SEASON_FILTERS:
        # No poster alone: the seasons without a poster, and no episodes.
        for row in db.fetchall("SELECT id, show_id FROM tv_seasons WHERE NOT (artwork ? 'poster') AND show_id = ANY(%s)", (ids,)):
            bucket(row["show_id"])["seasons"].append(str(row["id"]))
    return {
        "seasons": [item for kids in by_show.values() for item in kids["seasons"]],
        "episodes": [item for kids in by_show.values() for item in kids["episodes"]],
        "by_show": by_show,
    }


def _show_rows(where="", params=()):
    from curator.video import nfo_digest

    rows = db.fetchall(
        f"""
        SELECT s.id, s.title, s.sort_title, s.original_title, s.year, s.show_status, s.genres, s.studios, s.countries,
               s.directors, s.mpaa, s.rating, s.runtime_minutes, s.premiered, {nfo_digest.sig_sql("tv_shows", "s")},
               s.tags, s.trailer, s.has_local_trailer, s.has_local_theme, s.nfo_digest, s.user_rating, s.top250, s.playcount, s.last_played,
               s.original_language, s.english_title,
               concat_ws(' ', array_to_string(s.tags, ' '),
                         (SELECT string_agg(e->>'name', ' ') FROM jsonb_array_elements(COALESCE(s.actors, '[]'::jsonb)) e)) AS search_extra,
               s.imdb_id, s.tvdb_id, s.tmdb_id, s.status, s.path, s.root, s.nfo_path, s.nfo_path IS NOT NULL AS has_nfo,
               {source_column_sql("s")},
               (s.plot IS NOT NULL AND btrim(s.plot) <> '') AS has_plot,
               s.artwork, s.created_at, s.locked, s.scraped_at, s.scrape_error, s.wanted, s.prune_held,
               GREATEST(s.created_at, ep.last_added) AS last_added,
               (SELECT count(*)::int FROM tv_seasons x WHERE x.show_id = s.id) AS season_count,
               COALESCE(ep.episode_count, 0) AS episode_count,
               COALESCE(ep.new_count, 0) AS new_count,
               COALESCE(ep.missing_count, 0) AS missing_count,
               COALESCE(ep.duplicate_release, FALSE) AS duplicate_release,
               COALESCE(ep.upgrade, FALSE) AS upgrade,
               COALESCE(ep.multi_count, 0) AS multi_count
        FROM tv_shows s
        -- One pass over a show's episodes for every count, instead of a separate pass for each.
        LEFT JOIN LATERAL (
            SELECT max(e.created_at) FILTER (WHERE NOT e.missing) AS last_added,
                   count(*)::int AS episode_count,
                   (count(*) FILTER (WHERE e.status = 'NEW' AND NOT e.missing))::int AS new_count,
                   (count(*) FILTER (WHERE e.missing))::int AS missing_count,
                   bool_or(e.duplicate_release) AS duplicate_release,
                   bool_or(e.upgrade_source_id IS NOT NULL OR COALESCE(e.upgrade_copy_path, '') <> '') AS upgrade,
                   (count(*) FILTER (WHERE jsonb_typeof(e.file_span) = 'array' AND jsonb_array_length(e.file_span) > 1))::int AS multi_count
            FROM tv_episodes e WHERE e.show_id = s.id
        ) ep ON TRUE
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
    scoped = [show["id"] for show in shows] if where else None
    gaps = _episode_gaps(scoped)
    for show in shows:
        show.update(gaps.get(str(show["id"])) or dict.fromkeys(GAP_KEYS, 0))
    nfo_digest.apply("tv_shows", shows)
    # A refresh of a few changed shows checks only their seasons and episodes, and only their twins.
    family = _family_nfo_shows(scoped)
    from curator.video.copies import show_twins

    try:
        twins = show_twins(scoped)
    except Exception:
        logger.exception("could not look for show folders that hold the same show")
        twins = {}
    for show in shows:
        others = twins.get(str(show["id"])) or []
        show["duplicate_show"] = len(others)
        if others:
            show["duplicate_release"] = True
    for show in shows:
        show["nfo_family_stale"] = bool(show.get("nfo_stale")) or str(show["id"]) in family
        show["has_trailer"] = bool(show.get("trailer"))
        for key in ("plot", "outline", "tagline", "runtime_minutes", "premiered", "tags", "trailer", "nfo_digest", "original_title",
                    "user_rating", "top250", "playcount", "last_played", "original_language", "english_title", "nfo_sig"):
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
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id AND e.status = 'NEW' AND NOT e.missing) AS new_count,
               (SELECT count(*)::int FROM tv_episodes e WHERE e.season_id = s.id
                    AND jsonb_typeof(e.file_span) = 'array' AND jsonb_array_length(e.file_span) > 1) AS multi_count,
               EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = s.id
                    AND (e.upgrade_source_id IS NOT NULL OR COALESCE(e.upgrade_copy_path, '') <> '')) AS upgrade,
               EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = s.id AND e.duplicate_release) AS duplicate_release
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
    _attach_episode_versions(show["episodes"])
    # A missing-episode placeholder has no file of its own, so an .nfo left on it is never a change.
    nfo_digest.apply("tv_episodes", [item for item in show["episodes"] if not item.get("missing")])
    for item in show["episodes"]:
        if item.get("missing"):
            item["nfo_stale"] = False
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

    show["network_icons"] = brands.icons(show.get("studios"), "network", show.get("countries"))
    by_season = {}
    for episode in show["episodes"]:
        episode_flags = mediaflags.cards(episode)
        by_season.setdefault(episode.get("season_id"), []).append(episode_flags)
    show["media_flags"] = mediaflags.unique(flag for flags in by_season.values() for flag in flags)
    for season in show["seasons"]:
        season["media_flags"] = mediaflags.unique(by_season.get(season.get("id")) or [])
        season["network_icons"] = show["network_icons"]
    from curator.video import match_undo

    show["match_undo"] = match_undo.available(show_id)
    return _with_local_art(show, show.get("path"))


def _attach_episode_versions(episodes):
    """Give each episode the other video files stored for it, as brief file rows, best first.

    An episode row holds one file. A second file of the same episode is an episode copy. The list shows it as
    another version of that episode, the way two files of one movie are versions.
    """
    ids = [item["id"] for item in episodes if item.get("id")]
    if not ids:
        return
    rows = db.fetchall(
        f"""
        SELECT c.episode_id, c.path, f.path AS file_path, {FILE_BRIEF}
        FROM episode_copies c
        LEFT JOIN video_files f ON f.id = c.file_id
        WHERE c.episode_id = ANY(%s::uuid[])
        ORDER BY c.path
        """,
        (db.uuid_array([str(item) for item in ids]),),
    )
    if not rows:
        return
    from curator.video import copies as marks
    from resonance.paths import display_path

    by_episode = {}
    for row in rows:
        by_episode.setdefault(str(row["episode_id"]), []).append(row)
    for episode in episodes:
        extras = by_episode.get(str(episode.get("id")))
        if not extras:
            continue
        mine = marks.score(episode)
        built = []
        for extra in extras:
            data = db.clean(brief_file(dict(extra)))
            path = data.pop("path", "") or ""
            data.pop("file_path", None)
            data.pop("episode_id", None)
            data["copy_path"] = display_path(path) if path else ""
            data["copy_score"] = marks.score(data)
            built.append(data)
        built.sort(key=lambda item: (-item["copy_score"], item["copy_path"]))
        best = max([mine] + [item["copy_score"] for item in built])
        for item in built:
            item["upgrade"] = item["copy_score"] < best
        episode["copies"] = built
        episode["copy_score"] = mine
        episode["copy_path"] = episode.get("display_path") or display_path(episode.get("path") or "")


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

    episode["network_icons"] = brands.icons(episode.get("show_studios"), "network", episode.get("show_countries"))
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


_NAME_SQL = {
    "movie": "SELECT id::text AS id, title, year FROM movies WHERE id = ANY(%s::uuid[])",
    "show": "SELECT id::text AS id, title, year FROM tv_shows WHERE id = ANY(%s::uuid[])",
    "set": "SELECT id::text AS id, name AS title, NULL::int AS year FROM movie_sets WHERE id = ANY(%s::uuid[])",
    "episode": ("SELECT e.id::text AS id, s.title || ' S' || lpad(e.season_number::text, 2, '0') || 'E' "
                "|| lpad(e.episode_number::text, 2, '0') AS title, NULL::int AS year "
                "FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE e.id = ANY(%s::uuid[])"),
}


def item_names(kind, ids, limit=25):
    """'Heat (1995)', 'Landman S01E03' … for the first `limit` ids, in their order. Ids that are gone are left out."""
    import re

    wanted = [str(item) for item in dict.fromkeys(ids or ()) if re.fullmatch(r"[0-9a-fA-F-]{36}", str(item or ""))][:limit]
    sql = _NAME_SQL.get(kind)
    if not wanted or not sql:
        return []
    rows = {row["id"]: row for row in db.fetchall(sql, (wanted,))}
    names = []
    for item in wanted:
        row = rows.get(item)
        if row and row.get("title"):
            names.append(f"{row['title']} ({row['year']})" if row.get("year") else str(row["title"]))
    return names


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
                              AND e.path NOT LIKE 'missing://%%'
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
            "AND COALESCE(e.path, '') <> '' AND e.path NOT LIKE 'missing://%%' AND ("
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
    if isinstance(art, dict):
        from curator.video import art_sizes

        found = db.fetchone("SELECT artwork FROM movie_sets WHERE id = %s", (set_id,))
        art = art_sizes.with_sizes((found or {}).get("artwork"), art)
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


def forget_listed_episode(season_id, number):
    """Take one episode number out of the list a season expects, so it stops showing as missing.
    The next scrape may list it again if the source still does. Returns False when the season is unknown."""
    row = db.fetchone("SELECT season_number, tmdb_episode_count, tmdb_episode_numbers FROM tv_seasons WHERE id = %s", (season_id,))
    if not row:
        return False
    keep = sorted(expected_episode_numbers(row) - {int(number)})
    db.execute(
        "UPDATE tv_seasons SET tmdb_episode_numbers = %s::int[], tmdb_episode_count = %s, updated_at = NOW() WHERE id = %s",
        (keep, len(keep) or None, season_id),
    )
    return True


def reset_season_listings(show_id):
    """Forget the episode counts and numbers a source listed for the seasons (Fix Match, locks do not matter)."""
    db.execute(
        "UPDATE tv_seasons SET tmdb_episode_count = NULL, tmdb_episode_numbers = ARRAY[]::INT[] WHERE show_id = %s",
        (show_id,),
    )


from curator.video.store_edits import (  # noqa: E402,F401  kept in store_edits.py; every old name still works
    SeasonExists,
    _PREF_TABLES,
    _drop_empty_sets,
    _drop_released_files,
    _fold_episode,
    _removal_seeds,
    _settle_removed_flags,
    drop_empty_seasons,
    edit,
    link_set,
    lock_fields,
    match_ids,
    merge_season_name,
    move_episode,
    remove,
    renumber_season,
    save_nfo_state,
    save_scrape_prefs,
    save_season_meta,
    scrape_prefs,
    set_episode_number,
    set_lock,
    set_match,
    set_watched,
    unlock_fields,
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
