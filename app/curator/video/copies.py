"""Duplicate and upgrade marks for movies and episodes.

A movie matches another movie when they share a TMDB id, or an IMDb id when TMDB
is missing. An episode matches another episode of the same show identity
(TVDB, otherwise TMDB, otherwise that one show folder) and the same season and
episode number. A second file of that episode in the same show is stored as a
copy.

Two of those copies are duplicates only when they are the same kind of release:
the same source (a Blu-ray rip with another Blu-ray rip, not a Blu-ray rip with
a remux), the same resolution and HDR, and about the same file size. A better
release is an upgrade of the weaker one. The upgrade pill is on the weaker copy.
The stronger copy is not marked as a duplicate of it. A 3D copy is only compared
with other 3D copies. A flat copy and a 3D copy stay as separate versions.
"""

import os

from resonance import db
from resonance.paths import display_path, display_path_fast


_SOURCE_RANK = (
    ("complete uhd", 8),
    ("remux", 7),
    ("br-disk", 6),
    ("uhd", 5),
    ("bluray", 5),
    ("blu-ray", 5),
    ("web-dl", 4),
    ("webdl", 4),
    ("bd-rip", 3),
    ("web-rip", 2),
    ("webrip", 2),
    ("hdtv", 1),
    ("dvd", 1),
)


def score(row):
    """Higher means a better video file. Resolution wins, then source, HDR, bitrate, and size."""
    height = _int(row.get("height"))
    if height >= 4000:
        resolution = 5
    elif height >= 1600:
        resolution = 4
    elif height >= 1200:
        resolution = 3
    elif height >= 900:
        resolution = 2
    elif height >= 600:
        resolution = 1
    else:
        resolution = 0
    text = f"{row.get('source_format') or ''} {row.get('video_source') or ''}".lower()
    source = 0
    for token, rank in _SOURCE_RANK:
        if token in text:
            source = max(source, rank)
    hdr = str(row.get("hdr_format") or "").lower()
    hdr_rank = 0 if hdr in {"", "sdr", "none"} else 1
    bitrate = _int(round(_float(row.get("bitrate_mbps")) * 100))
    size = min(_int(row.get("size_bytes")) // 1_000_000, 99999)
    return resolution * 10**12 + source * 10**9 + hdr_rank * 10**8 + bitrate * 10**5 + size


def movie_key(row):
    tmdb = str(row.get("tmdb_id") or "").strip()
    if tmdb:
        return ("tmdb", tmdb)
    imdb = str(row.get("imdb_id") or "").strip().lower()
    if imdb:
        return ("imdb", imdb)
    title = str(row.get("title") or "").strip().lower()
    if title and row.get("year"):
        return ("title", title, _int(row.get("year")))
    return None


def episode_key(row):
    tvdb = str(row.get("tvdb_id") or "").strip()
    tmdb = str(row.get("tmdb_id") or "").strip()
    if tvdb:
        identity = ("tvdb", tvdb)
    elif tmdb:
        identity = ("tmdb", tmdb)
    else:
        title = str(row.get("show_title") or "").strip().lower()
        identity = ("title", title, _int(row.get("show_year"))) if title else ("show", str(row.get("show_id") or ""))
    return identity + (_int(row.get("season_number")), _int(row.get("episode_number")))


def file_key(path):
    """The file as the library shows it. Two mounts of one file share this key."""
    text = str(path or "").strip()
    if not text:
        return ""
    shown = display_path_fast(text) or text
    return os.path.normcase(os.path.normpath(shown))


def library_rows(movies):
    """Drop a second library row when it is the same video file as one already shown.

    The same folder mounted at /movies and again under a longer library path is one
    movie. Different files that share a title stay as versions.
    """
    buckets = {}
    for index, movie in enumerate(movies):
        key = movie_key(movie) or ("id", str(movie.get("id") or index))
        buckets.setdefault(key, []).append(index)
    drop = set()
    for indexes in buckets.values():
        if len(indexes) < 2:
            continue
        chosen = {}
        for index in indexes:
            movie = movies[index]
            ident = file_key(movie.get("file_path") or "") or f"id:{movie.get('id') or index}"
            movie["_file_key"] = ident
            current = chosen.get(ident)
            if current is None or _prefer_library_row(movie, movies[current]):
                chosen[ident] = index
        keep = set(chosen.values())
        drop.update(index for index in indexes if index not in keep)
    visible = []
    for index, movie in enumerate(movies):
        movie.pop("file_path", None)
        movie.pop("_file_key", None)
        if index in drop:
            continue
        visible.append(movie)
    return visible


def _prefer_library_row(candidate, current):
    """Keep the row stored at the path the file is shown as."""
    key = candidate.get("_file_key") or ""
    cand = os.path.normcase(os.path.normpath(str(candidate.get("file_path") or "")))
    curr = os.path.normcase(os.path.normpath(str(current.get("file_path") or "")))
    cand_exact = bool(key) and cand == key
    curr_exact = bool(key) and curr == key
    if cand_exact != curr_exact:
        return cand_exact
    return len(cand) > len(curr)


def _distinct_files(rows):
    """One database row per displayed video file, preferring the path that is shown."""
    chosen = {}
    order = []
    for row in rows:
        ident = file_key(row.get("file_path") or "") or f"id:{row.get('id')}"
        current = chosen.get(ident)
        if current is None:
            chosen[ident] = row
            order.append(ident)
            continue
        candidate = dict(row)
        held = dict(current)
        candidate["_file_key"] = ident
        held["_file_key"] = ident
        if _prefer_library_row(candidate, held):
            chosen[ident] = row
    return [chosen[ident] for ident in order]


def _one_file_each(rows):
    """Every library row stays. The same file mounted twice is a duplicate pair."""
    return list(rows)


_RELEASE_FAMILY = {
    "uhd remux": "uhd-remux",
    "uhd blu-ray": "uhd",
    "complete uhd blu-ray": "uhd-disc",
    "uhd rip": "uhd",
    "blu-ray remux": "bluray-remux",
    "blu-ray": "bluray",
    "blu-ray rip": "bluray",
    "complete blu-ray": "bluray-disc",
    "hd-dvd remux": "hddvd-remux",
    "hd-dvd": "hddvd",
    "web-dl": "web-dl",
    "web": "web-dl",
    "webrip": "webrip",
    "webcap": "webrip",
    "hdtv": "hdtv",
    "pdtv": "hdtv",
    "dsr": "hdtv",
    "tvrip": "hdtv",
    "dvd": "dvd",
    "dvdrip": "dvd",
    "hdrip": "hdrip",
    "vhs": "vhs",
    "vhsrip": "vhs",
}


def release_family(row):
    """The source bucket used to tell a duplicate from an upgrade.

    A Blu-ray rip and another Blu-ray rip share a bucket. A Blu-ray rip and a
    Blu-ray remux do not, and neither do a DVD and a WEB-DL.
    """
    from curator.video.sources import canonical_source

    label, _group = canonical_source(row.get("source_format") or "")
    if not label:
        label, _group = canonical_source(row.get("video_source") or "")
    key = str(label or "").strip().lower()
    video = str(row.get("video_source") or "").lower()
    if key in _RELEASE_FAMILY:
        family = _RELEASE_FAMILY[key]
    elif "remux" in key and ("uhd" in key or "uhd" in video or "4k" in video):
        family = "uhd-remux"
    elif "remux" in key and ("blu" in key or "blu" in video):
        family = "bluray-remux"
    elif "remux" in key:
        family = "remux"
    elif "uhd" in key or "uhd" in video:
        family = "uhd"
    elif "blu" in key or "blu" in video:
        family = "bluray"
    else:
        family = key
    return family


def _resolution_bucket(height):
    height = _int(height)
    if height >= 2000:
        return "4k"
    if height >= 900:
        return "1080"
    if height >= 600:
        return "720"
    if height >= 400:
        return "480"
    if height > 0:
        return "sd"
    return ""


def _hdr_bucket(value):
    text = str(value or "").strip().lower()
    if text in {"", "sdr", "none"}:
        return "sdr"
    return "hdr"


def _probed(row):
    return bool(
        _int(row.get("height")) or _int(row.get("size_bytes"))
        or row.get("source_format") or row.get("video_source") or row.get("hdr_format")
    )


def _similar_size(left, right):
    """True when neither size is known, or the larger file is at most twice the smaller one."""
    low = _int(left.get("size_bytes"))
    high = _int(right.get("size_bytes"))
    if low <= 0 or high <= 0:
        return True
    low, high = sorted((low, high))
    return high <= low * 2


def _is_3d(row):
    """3D is its own release. A flat copy is never a duplicate or an upgrade of a 3D copy."""
    if not row:
        return False
    if row.get("is_3d"):
        return True
    return bool(str(row.get("stereo_mode") or "").strip())


def _same_picture(left, right):
    return _is_3d(left) == _is_3d(right)


def same_release(left, right):
    """True when two copies are the same quality, so they are duplicates of each other."""
    if not _same_picture(left, right):
        return False
    if not _probed(left) and not _probed(right):
        return left.get("score") == right.get("score")
    if release_family(left) != release_family(right):
        return False
    if _resolution_bucket(left.get("height")) != _resolution_bucket(right.get("height")):
        return False
    if _hdr_bucket(left.get("hdr_format")) != _hdr_bucket(right.get("hdr_format")):
        return False
    return _similar_size(left, right)


def _upgrade_choice(row, group):
    """The strongest different release, as (id, path). Same-quality copies are not upgrades."""
    best_score = row.get("score") or 0
    best_id = None
    best_path = None
    for peer in group:
        candidates = []
        if peer.get("id") != row.get("id"):
            candidates.append(peer)
        candidates.extend(peer.get("copies") or [])
        for other in candidates:
            if not _same_picture(row, other):
                continue
            score_value = other.get("score") or 0
            if score_value <= best_score or same_release(row, other):
                continue
            best_score = score_value
            best_id = other.get("id") or None
            best_path = None if best_id else other.get("path")
    return best_id, best_path


def assign_marks(rows):
    """Return id -> {duplicate, upgrade_id, upgrade_path} for one media type."""
    groups = {}
    marks = {}
    for row in rows:
        marks[row["id"]] = {"duplicate": False, "upgrade_id": None, "upgrade_path": None}
    for row in _one_file_each(rows):
        key = row.get("key")
        if key:
            groups.setdefault(key, []).append(row)
    for group in groups.values():
        if len(group) < 2 and not any(row.get("copies") for row in group):
            continue
        for row in group:
            twins = any(peer.get("id") != row.get("id") and same_release(row, peer) for peer in group)
            same_file = any(same_release(row, copy) for copy in (row.get("copies") or []))
            if twins or same_file:
                marks[row["id"]]["duplicate"] = True
            best_id, best_path = _upgrade_choice(row, group)
            own = row.get("path") or ""
            if best_id:
                marks[row["id"]]["upgrade_id"] = best_id
            elif best_path and best_path != own:
                marks[row["id"]]["upgrade_path"] = best_path
    return marks


def present(row, table):
    """Fill upgrade and upgrade_path on a detail row that already has the stored columns."""
    if not row:
        return row
    source = row.get("upgrade_source_id")
    path = row.get("upgrade_path") or row.get("upgrade_copy_path") or ""
    if source and not row.get("upgrade_path"):
        other = db.fetchone(f"SELECT path FROM {table} WHERE id = %s", (source,))
        path = (other or {}).get("path") or path
    row["upgrade_path"] = path or ""
    row["upgrade"] = bool(source or row.get("upgrade_copy_path"))
    row["duplicate_release"] = bool(row.get("duplicate_release"))
    return row


def silence_dismissed(marks, rows, pairs):
    """A dismissed pair stays in the library and loses the Duplicate mark."""
    by_key = {}
    for row in rows:
        if row.get("key"):
            by_key.setdefault(row["key"], []).append(row["id"])
    for ids in by_key.values():
        if len(ids) < 2:
            continue
        for item_id in ids:
            others = [other for other in ids if other != item_id]
            if others and all(frozenset((item_id, other)) in pairs for other in others):
                marks[item_id]["duplicate"] = False
    return marks


def _dismissed_pairs(kind):
    try:
        rows = db.fetchall(
            "SELECT left_id::text AS left_id, right_id::text AS right_id FROM video_dismissed_duplicates WHERE kind = %s",
            (kind,),
        )
    except Exception:
        return set()
    return {frozenset((row["left_id"], row["right_id"])) for row in rows}


_MOVIE_ROWS = """
    SELECT m.id, m.title, m.year, m.tmdb_id, m.imdb_id, m.path,
           f.path AS file_path, f.height, f.bitrate_mbps, f.size_bytes, f.source_format, f.video_source, f.hdr_format,
           f.is_3d, f.stereo_mode
    FROM movies m
    LEFT JOIN video_files f ON f.id = m.file_id
"""

_EPISODE_ROWS = """
    SELECT e.id, e.show_id, e.season_number, e.episode_number, e.path,
           s.title AS show_title, s.year AS show_year, s.tmdb_id, s.tvdb_id,
           f.height, f.bitrate_mbps, f.size_bytes, f.source_format, f.video_source, f.hdr_format,
           f.is_3d, f.stereo_mode
    FROM tv_episodes e
    JOIN tv_shows s ON s.id = e.show_id
    LEFT JOIN video_files f ON f.id = e.file_id
"""

_EPISODE_SEEDS = """
    SELECT e.show_id, e.season_number, e.episode_number,
           s.title AS show_title, s.year AS show_year, s.tmdb_id, s.tvdb_id
    FROM tv_episodes e
    JOIN tv_shows s ON s.id = e.show_id
"""


def movie_peer_keys(seeds):
    """Identity keys whose duplicate and upgrade marks a change can affect."""
    found = []
    seen = set()
    for seed in seeds or []:
        key = movie_key(seed)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found


def episode_peer_keys(seeds):
    """Show, season, and episode keys whose marks a change can affect."""
    found = []
    seen = set()
    for seed in seeds or []:
        key = episode_key(seed)
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(key)
    return found


def movie_seed_rows(ids):
    if not ids:
        return []
    return db.fetchall(
        "SELECT title, year, tmdb_id, imdb_id FROM movies WHERE id = ANY(%s::uuid[])",
        (list(ids),),
    )


def episode_seed_rows(ids):
    """The episodes about to be removed, including other rows that share their file."""
    if not ids:
        return []
    return db.fetchall(
        _EPISODE_SEEDS + """
        WHERE e.id = ANY(%s::uuid[])
           OR (e.show_id, e.path) IN (
                SELECT show_id, path FROM tv_episodes
                WHERE id = ANY(%s::uuid[]) AND COALESCE(path, '') <> ''
           )
        """,
        (list(ids), list(ids)),
    )


def episode_seeds_for_shows(ids):
    if not ids:
        return []
    return db.fetchall(_EPISODE_SEEDS + " WHERE e.show_id = ANY(%s::uuid[])", (list(ids),))


def episode_seeds_for_seasons(ids):
    if not ids:
        return []
    return db.fetchall(_EPISODE_SEEDS + " WHERE e.season_id = ANY(%s::uuid[])", (list(ids),))


def _movie_peer_where(seeds):
    clauses, params = [], []
    for key in movie_peer_keys(seeds):
        if key[0] == "tmdb":
            clauses.append("btrim(m.tmdb_id) = %s")
            params.append(key[1])
        elif key[0] == "imdb":
            clauses.append("(lower(btrim(m.imdb_id)) = %s AND btrim(coalesce(m.tmdb_id, '')) = '')")
            params.append(key[1])
        else:
            clauses.append(
                "(lower(btrim(m.title)) = %s AND m.year = %s"
                " AND btrim(coalesce(m.tmdb_id, '')) = '' AND btrim(coalesce(m.imdb_id, '')) = '')"
            )
            params.extend([key[1], key[2]])
    return clauses, params


def _episode_peer_where(seeds):
    clauses, params = [], []
    for key in episode_peer_keys(seeds):
        if key[0] == "tvdb":
            clauses.append("(btrim(s.tvdb_id) = %s AND e.season_number = %s AND e.episode_number = %s)")
            params.extend([key[1], key[2], key[3]])
        elif key[0] == "tmdb":
            clauses.append(
                "(btrim(s.tmdb_id) = %s AND btrim(coalesce(s.tvdb_id, '')) = ''"
                " AND e.season_number = %s AND e.episode_number = %s)"
            )
            params.extend([key[1], key[2], key[3]])
        elif key[0] == "title":
            clauses.append(
                "(lower(btrim(s.title)) = %s AND coalesce(s.year, 0) = %s"
                " AND btrim(coalesce(s.tvdb_id, '')) = '' AND btrim(coalesce(s.tmdb_id, '')) = ''"
                " AND e.season_number = %s AND e.episode_number = %s)"
            )
            params.extend([key[1], key[2], key[3], key[4]])
        else:
            clauses.append(
                "(e.show_id = %s AND btrim(coalesce(s.title, '')) = ''"
                " AND e.season_number = %s AND e.episode_number = %s)"
            )
            params.extend([key[1], key[2], key[3]])
    return clauses, params


def _prepare_movies(rows):
    return [
        {
            "id": str(row["id"]),
            "key": movie_key(row),
            "score": score(row),
            "path": row.get("path") or "",
            "file_key": file_key(row.get("file_path") or ""),
            "height": row.get("height"),
            "size_bytes": row.get("size_bytes"),
            "source_format": row.get("source_format") or "",
            "video_source": row.get("video_source") or "",
            "hdr_format": row.get("hdr_format") or "",
            "is_3d": bool(row.get("is_3d")),
            "stereo_mode": row.get("stereo_mode") or "",
            "copies": [],
        }
        for row in rows
    ]


def _prepare_episodes(rows, copies):
    return [
        {
            "id": str(row["id"]),
            "key": episode_key(row),
            "score": score(row),
            "path": row.get("path") or "",
            "height": row.get("height"),
            "size_bytes": row.get("size_bytes"),
            "source_format": row.get("source_format") or "",
            "video_source": row.get("video_source") or "",
            "hdr_format": row.get("hdr_format") or "",
            "is_3d": bool(row.get("is_3d")),
            "stereo_mode": row.get("stereo_mode") or "",
            "copies": copies.get(str(row["id"]), []),
        }
        for row in rows
    ]


def _copy_map(episode_ids=None):
    sql = """
        SELECT c.episode_id, c.path,
               f.height, f.bitrate_mbps, f.size_bytes, f.source_format, f.video_source, f.hdr_format,
               f.is_3d, f.stereo_mode
        FROM episode_copies c
        LEFT JOIN video_files f ON f.id = c.file_id
    """
    params = ()
    if episode_ids is not None:
        if not episode_ids:
            return {}
        sql += " WHERE c.episode_id = ANY(%s::uuid[])"
        params = (list(episode_ids),)
    copies = {}
    for copy in db.fetchall(sql, params):
        copies.setdefault(str(copy["episode_id"]), []).append({
            "path": copy["path"], "score": score(copy),
            "height": copy.get("height"), "size_bytes": copy.get("size_bytes"),
            "source_format": copy.get("source_format") or "", "video_source": copy.get("video_source") or "",
            "hdr_format": copy.get("hdr_format") or "",
            "is_3d": bool(copy.get("is_3d")),
            "stereo_mode": copy.get("stereo_mode") or "",
        })
    return copies


def _apply_movie_marks(rows, scoped):
    prepared = _prepare_movies(rows)
    if not prepared:
        return 0
    marks = silence_dismissed(assign_marks(prepared), prepared, _dismissed_pairs("movie"))
    _store_marks("movies", marks, [item["id"] for item in prepared] if scoped else None)
    return sum(1 for mark in marks.values() if mark["upgrade_id"])


def _apply_episode_marks(rows, scoped):
    if not rows:
        return 0
    copies = _copy_map([row["id"] for row in rows] if scoped else None)
    prepared = _prepare_episodes(rows, copies)
    marks = silence_dismissed(assign_marks(prepared), prepared, _dismissed_pairs("episode"))
    _store_marks("tv_episodes", marks, [item["id"] for item in prepared] if scoped else None)
    return sum(1 for mark in marks.values() if mark["upgrade_id"] or mark["upgrade_path"])


def refresh_movies():
    return _apply_movie_marks(db.fetchall(_MOVIE_ROWS), False)


def refresh_movie_seeds(seeds):
    """Recompute marks for the movies that share an identity with these rows."""
    clauses, params = _movie_peer_where(seeds)
    if not clauses:
        return 0
    rows = db.fetchall(_MOVIE_ROWS + " WHERE " + " OR ".join(clauses), tuple(params))
    return _apply_movie_marks(rows, True)


def peer_flags(kind, seeds):
    """The duplicate and upgrade flags now stored on the copies that share these identities."""
    if kind == "movie":
        clauses, params = _movie_peer_where(seeds)
        if not clauses:
            return []
        rows = db.fetchall(
            f"""
            SELECT m.id::text AS id,
                   m.duplicate_release,
                   m.upgrade_source_id IS NOT NULL AS upgrade,
                   COALESCE(src.path, '') AS upgrade_path
            FROM movies m
            LEFT JOIN movies src ON src.id = m.upgrade_source_id
            WHERE {" OR ".join(clauses)}
            """,
            tuple(params),
        )
    elif kind == "episode":
        clauses, params = _episode_peer_where(seeds)
        if not clauses:
            return []
        rows = db.fetchall(
            f"""
            SELECT e.id::text AS id,
                   e.duplicate_release,
                   (e.upgrade_source_id IS NOT NULL OR COALESCE(e.upgrade_copy_path, '') <> '') AS upgrade,
                   COALESCE(src.path, NULLIF(e.upgrade_copy_path, ''), '') AS upgrade_path
            FROM tv_episodes e
            JOIN tv_shows s ON s.id = e.show_id
            LEFT JOIN tv_episodes src ON src.id = e.upgrade_source_id
            WHERE {" OR ".join(clauses)}
            """,
            tuple(params),
        )
    else:
        return []
    return [
        {
            "id": row["id"],
            "duplicate_release": bool(row.get("duplicate_release")),
            "upgrade": bool(row.get("upgrade")),
            "upgrade_path": row.get("upgrade_path") or "",
        }
        for row in rows
    ]


def refresh_episodes():
    return _apply_episode_marks(db.fetchall(_EPISODE_ROWS), False)


def refresh_episode_seeds(seeds):
    """Recompute marks for the episodes that share a show, season, and number with these rows."""
    clauses, params = _episode_peer_where(seeds)
    if not clauses:
        return 0
    rows = db.fetchall(_EPISODE_ROWS + " WHERE " + " OR ".join(clauses), tuple(params))
    return _apply_episode_marks(rows, True)


def replace_show_copies(show_id, rows):
    """Replace extra episode files for one show. rows are episode_id, path, file_id."""
    with db.transaction() as conn:
        conn.execute(
            """
            DELETE FROM episode_copies
            WHERE episode_id IN (SELECT id FROM tv_episodes WHERE show_id = %s)
            """,
            (show_id,),
        )
        for row in rows:
            if not row.get("episode_id") or not row.get("path"):
                continue
            conn.execute(
                """
                INSERT INTO episode_copies (episode_id, path, file_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (episode_id, path) DO UPDATE SET file_id = EXCLUDED.file_id
                """,
                (row["episode_id"], row["path"], row.get("file_id")),
            )


def _store_marks(table, marks, only=None):
    """Write duplicate and upgrade marks. only limits the write to those ids."""
    allowed = None
    if only is not None:
        allowed = {str(item) for item in only}
        if not allowed:
            return
        marks = {item_id: mark for item_id, mark in marks.items() if str(item_id) in allowed}
    duplicates = [item_id for item_id, mark in marks.items() if mark["duplicate"]]
    upgrades = {item_id: mark["upgrade_id"] for item_id, mark in marks.items() if mark["upgrade_id"]}
    paths = {item_id: mark["upgrade_path"] for item_id, mark in marks.items() if mark["upgrade_path"]}
    with db.transaction() as conn:
        if allowed is None:
            conn.execute(
                f"""
                UPDATE {table}
                SET duplicate_release = FALSE, upgrade_source_id = NULL
                WHERE duplicate_release IS TRUE OR upgrade_source_id IS NOT NULL
                """
            )
            if table == "tv_episodes":
                conn.execute(
                    "UPDATE tv_episodes SET upgrade_copy_path = NULL WHERE upgrade_copy_path IS NOT NULL"
                )
        else:
            conn.execute(
                f"""
                UPDATE {table}
                SET duplicate_release = FALSE, upgrade_source_id = NULL
                WHERE id = ANY(%s::uuid[])
                """,
                (db.uuid_array(list(allowed)),),
            )
            if table == "tv_episodes":
                conn.execute(
                    "UPDATE tv_episodes SET upgrade_copy_path = NULL WHERE id = ANY(%s::uuid[])",
                    (db.uuid_array(list(allowed)),),
                )
        if duplicates:
            conn.execute(
                f"UPDATE {table} SET duplicate_release = TRUE WHERE id = ANY(%s::uuid[])",
                (db.uuid_array(duplicates),),
            )
        if upgrades:
            conn.execute(
                f"""
                UPDATE {table} AS item
                SET upgrade_source_id = data.source_id
                FROM unnest(%s::uuid[], %s::uuid[]) AS data(item_id, source_id)
                WHERE item.id = data.item_id
                """,
                (db.uuid_array(list(upgrades)), db.uuid_array(list(upgrades.values()))),
            )
        if paths and table == "tv_episodes":
            conn.execute(
                """
                UPDATE tv_episodes AS item
                SET upgrade_copy_path = data.copy_path
                FROM unnest(%s::uuid[], %s::text[]) AS data(item_id, copy_path)
                WHERE item.id = data.item_id
                """,
                (db.uuid_array(list(paths)), list(paths.values())),
            )


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


_FILE = """
    f.resolution, f.height, f.bitrate_mbps, f.size_bytes, f.duration_seconds, f.container,
    f.source_format, f.video_source, f.hdr_format, f.video_codec, f.audio_tracks,
    f.is_3d, f.stereo_mode, f.probe_error
"""


def _poster(row):
    art = row.get("artwork") if isinstance(row.get("artwork"), dict) else {}
    show = row.get("show_artwork") if isinstance(row.get("show_artwork"), dict) else {}
    return art.get("poster") or art.get("thumb") or show.get("poster") or ""


def _file_paths(row):
    """Video files for one copy. The movie folder is used only when no file is known."""
    found = []
    file_path = str(row.get("file_path") or "").strip()
    if file_path:
        found.append(file_path)
    parts = row.get("parts") if isinstance(row.get("parts"), list) else []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in found:
            found.append(text)
    if not found:
        folder = str(row.get("path") or "").strip()
        if folder:
            found.append(folder)
    return found


def _release_group(row):
    stored = str(row.get("release_group") or "").strip()
    if stored:
        return stored
    from curator.video import naming

    for path in _file_paths(row):
        group = naming.release_group(path)
        if group:
            return group
    return ""


def _edition_label(value):
    from curator.video.sources import canonical_edition

    return canonical_edition(value) or ""


def _card(row, current_id, current_score):
    rank = score(row)
    files = _file_paths(row)
    return {
        "poster": _poster(row),
        "id": str(row["id"]) if row.get("id") else "",
        "title": row.get("title") or "",
        "year": row.get("year"),
        "edition": _edition_label(row.get("edition")),
        "path": row.get("path") or "",
        "file_path": files[0] if files else "",
        "tmdb_id": str(row.get("tmdb_id") or ""),
        "tvdb_id": str(row.get("tvdb_id") or ""),
        "filepath": "\n".join(display_path(path) for path in files),
        "release_group": _release_group(row),
        "resolution": row.get("resolution") or "",
        "source": " ".join(part for part in (row.get("video_source"), row.get("source_format")) if part),
        "source_format": row.get("source_format") or "",
        "video_source": row.get("video_source") or "",
        "bitrate_mbps": row.get("bitrate_mbps"),
        "size_bytes": row.get("size_bytes"),
        "duration_seconds": row.get("duration_seconds") or 0,
        "audio": _duplicate_audio(row.get("audio_tracks")),
        "hdr_format": row.get("hdr_format") or "",
        "container": row.get("container") or "",
        "codec": row.get("video_codec") or "",
        "video_codec": row.get("video_codec") or "",
        "date_added": row.get("date_added") or row.get("created_at") or "",
        "probe_error": row.get("probe_error") or "",
        "score": rank,
        "current": str(row.get("id") or "") == str(current_id) and not row.get("extra"),
        "better": rank > current_score,
        "extra": bool(row.get("extra")),
    }


def movie_copies(movie_id):
    rows = db.fetchall(
        f"""
        SELECT m.id, m.title, m.year, m.edition, m.path, m.parts, m.artwork, m.tmdb_id, m.imdb_id,
               m.date_added, m.created_at,
               f.path AS file_path, f.release_group, {_FILE}
        FROM movies m LEFT JOIN video_files f ON f.id = m.file_id
        """
    )
    current = next((row for row in rows if str(row["id"]) == str(movie_id)), None)
    if not current:
        return {"copies": []}
    key = movie_key(current)
    group = [row for row in rows if key and movie_key(row) == key and _same_picture(row, current)]
    group = _distinct_files(group)
    if len(group) < 2:
        group = [current]
    current_score = score(current)
    copies = [_card(row, movie_id, current_score) for row in group]
    copies.sort(key=lambda item: (-item["score"], item["path"]))
    from curator import arr_ids

    arr_ids.movies(copies)
    return {"kind": "movie", "id": str(movie_id), "copies": copies, "cleared": _clear_lonely("movies", movie_id, copies)}


def episode_copies(episode_id):
    rows = db.fetchall(
        f"""
        SELECT e.id, e.show_id, e.season_number, e.episode_number, e.path, e.title, e.artwork,
               e.created_at,
               s.title AS show_title, s.year AS show_year, s.artwork AS show_artwork, s.tmdb_id, s.tvdb_id,
               f.path AS file_path, f.release_group, {_FILE}
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        LEFT JOIN video_files f ON f.id = e.file_id
        """
    )
    current = next((row for row in rows if str(row["id"]) == str(episode_id)), None)
    if not current:
        return {"copies": []}
    key = episode_key(current)
    group = [row for row in rows if episode_key(row) == key and _same_picture(row, current)]
    extras = db.fetchall(
        f"""
        SELECT c.episode_id, c.path, f.path AS file_path, f.release_group, {_FILE}
        FROM episode_copies c
        LEFT JOIN video_files f ON f.id = c.file_id
        WHERE c.episode_id = ANY(%s::uuid[])
        """,
        (db.uuid_array([str(row["id"]) for row in group]),),
    ) if group else []
    current_score = score(current)
    copies = [_card(row, episode_id, current_score) for row in group]
    for extra in extras:
        owner = next(row for row in group if str(row["id"]) == str(extra["episode_id"]))
        if not _same_picture(extra, owner):
            continue
        card = _card({
            **extra, "id": "", "title": owner.get("title") or "", "extra": True,
            "tvdb_id": owner.get("tvdb_id") or "",
            "artwork": owner.get("artwork"), "show_artwork": owner.get("show_artwork"),
        }, episode_id, current_score)
        card["owner_id"] = str(extra["episode_id"])
        card["id"] = f"file:{extra['path']}"
        card["current"] = False
        card["extra"] = True
        copies.append(card)
    copies.sort(key=lambda item: (-item["score"], item["path"]))
    from curator import arr_ids

    arr_ids.episodes(copies)
    return {"kind": "episode", "id": str(episode_id), "copies": copies, "cleared": _clear_lonely("tv_episodes", episode_id, copies)}


def _clear_lonely(table, item_id, copies):
    """No other copy exists, so a Duplicate or Upgrade mark left on this item is stale. True when one was cleared."""
    if len(copies) > 1:
        return False
    rows = db.fetchall(
        f"UPDATE {table} SET duplicate_release = FALSE, upgrade_source_id = NULL "
        "WHERE id = %s AND (duplicate_release IS TRUE OR upgrade_source_id IS NOT NULL) RETURNING id",
        (item_id,),
    )
    return bool(rows)


def copies_for(kind, item_id):
    if kind == "movie":
        return movie_copies(item_id)
    if kind == "episode":
        return episode_copies(item_id)
    raise ValueError(kind)


def replace_copy(kind, item_id, keep_id, purge):
    """Delete every copy except the one the user keeps."""
    from curator.video import delete
    from resonance.errors import AppError

    if not purge:
        raise AppError("Turn on deleting the other copies to replace this one")
    found = copies_for(kind, item_id)
    copies = found.get("copies") or []
    keep = next((item for item in copies if item["id"] == keep_id), None)
    if not keep:
        raise AppError("Choose the copy to keep")
    removed = []
    doomed = [
        item["id"] for item in copies
        if item["id"] != keep["id"] and not item.get("extra") and not (keep.get("extra") and item["id"] == keep.get("owner_id"))
    ]
    if kind == "movie":
        seeds = movie_seed_rows(doomed)
    else:
        owner = keep.get("owner_id") or item_id
        seed_ids = list(doomed)
        if owner not in seed_ids:
            seed_ids.append(owner)
        seeds = episode_seed_rows(seed_ids)
    if keep.get("extra"):
        owner_id = keep.get("owner_id") or item_id
        old_primary_row = db.fetchone("SELECT path FROM tv_episodes WHERE id = %s", (owner_id,))
        old_primary_path = (old_primary_row or {}).get("path")
        _promote_extra(owner_id, keep["path"])
        if old_primary_path and old_primary_path != keep["path"]:
            delete._remove_files([old_primary_path])
    for item in copies:
        if item["id"] == keep["id"]:
            continue
        if keep.get("extra") and item["id"] == keep.get("owner_id"):
            continue
        if item.get("extra"):
            _drop_extra(item["path"])
            removed.append(item["id"])
            continue
        if kind == "movie":
            delete.delete_movie(item["id"])
        else:
            delete.delete_episode(item["id"])
        removed.append(item["id"])
    if kind == "movie":
        refresh_movie_seeds(seeds)
        peers = peer_flags("movie", seeds)
    else:
        refresh_episode_seeds(seeds)
        peers = peer_flags("episode", seeds)
    delete.rescan_arr_after_delete(kind, seeds)
    return {"kept": keep["owner_id"] if keep.get("extra") else keep["id"], "removed": removed, "peers": peers}


def _promote_extra(episode_id, path):
    row = db.fetchone("SELECT file_id FROM episode_copies WHERE episode_id = %s AND path = %s", (episode_id, path))
    file_id = (row or {}).get("file_id")
    db.execute(
        "UPDATE tv_episodes SET path = %s, file_id = %s, updated_at = NOW() WHERE id = %s",
        (path, file_id, episode_id),
    )
    db.execute("DELETE FROM episode_copies WHERE episode_id = %s AND path = %s", (episode_id, path))


def _drop_extra(path):
    import os

    db.execute("DELETE FROM episode_copies WHERE path = %s", (path,))
    if path and os.path.isfile(path):
        os.remove(path)


def duplicate_groups():
    """Movie and episode groups that carry the Duplicate mark."""
    movies = db.fetchall(
        """
        SELECT m.id, m.title, m.year, m.edition, m.path, m.parts, m.artwork, m.tmdb_id, m.imdb_id,
               m.date_added, m.created_at,
               f.path AS file_path, f.release_group, f.bitrate_mbps, f.container,
               f.resolution, f.video_codec, f.hdr_format, f.video_source, f.source_format,
               f.audio_tracks, f.size_bytes, f.duration_seconds, f.is_3d, f.stereo_mode, f.probe_error
        FROM movies m LEFT JOIN video_files f ON f.id = m.file_id
        WHERE m.duplicate_release IS TRUE
        ORDER BY lower(m.title), m.year
        """
    )
    episodes = db.fetchall(
        """
        SELECT e.id, e.title, e.season_number, e.episode_number, e.path, e.artwork, e.created_at,
               s.title AS show_title, s.year AS show_year, s.tmdb_id, s.tvdb_id,
               f.path AS file_path, f.release_group, f.bitrate_mbps, f.container,
               f.resolution, f.video_codec, f.hdr_format, f.video_source, f.source_format,
               f.audio_tracks, f.size_bytes, f.duration_seconds, f.is_3d, f.stereo_mode, f.probe_error
        FROM tv_episodes e
        JOIN tv_shows s ON s.id = e.show_id
        LEFT JOIN video_files f ON f.id = e.file_id
        WHERE e.duplicate_release IS TRUE
        ORDER BY lower(s.title), e.season_number, e.episode_number
        """
    )
    from curator import arr_ids

    packed_movies = _pack(movies, _picture_key(movie_key), lambda row: f"{row.get('title') or 'Movie'}" + (f" ({row['year']})" if row.get("year") else ""))
    packed_episodes = _pack(episodes, _picture_key(episode_key), lambda row: (
        f"{row.get('show_title') or 'Show'} S{int(row.get('season_number') or 0):02d}E{int(row.get('episode_number') or 0):02d}"
    ))
    arr_ids.movie_groups([group.get("items") or [] for group in packed_movies])
    arr_ids.episode_groups([group.get("items") or [] for group in packed_episodes])
    return {"movies": packed_movies, "episodes": packed_episodes}


def _picture_key(key_fn):
    """Keep flat copies and 3D copies in separate duplicate groups."""
    def keyed(row):
        base = key_fn(row)
        if not base:
            return None
        return tuple(base) + ("3d" if _is_3d(row) else "2d",)
    return keyed


def _duplicate_audio(tracks):
    if not isinstance(tracks, list) or not tracks:
        return ""
    track = next((item for item in tracks if isinstance(item, dict) and item.get("default")), None)
    track = track or (tracks[0] if isinstance(tracks[0], dict) else {})
    return " ".join(part for part in (track.get("codec"), track.get("channels")) if part)


def _pack(rows, key_fn, label_fn):
    groups = {}
    for row in rows:
        key = key_fn(row)
        if not key:
            continue
        art = row.get("artwork") if isinstance(row.get("artwork"), dict) else {}
        groups.setdefault(key, []).append({
            "id": str(row["id"]),
            "title": row.get("title") or row.get("show_title") or "",
            "path": display_path(row.get("path") or ""),
            "file_path": (_file_paths(row) or [""])[0],
            "tmdb_id": str(row.get("tmdb_id") or ""),
            "tvdb_id": str(row.get("tvdb_id") or ""),
            "filepath": "\n".join(display_path(path) for path in _file_paths(row)),
            "release_group": _release_group(row),
            "bitrate_mbps": row.get("bitrate_mbps"),
            "poster": art.get("poster") or art.get("thumb") or "",
            "resolution": row.get("resolution") or "",
            "edition": _edition_label(row.get("edition")),
            "video_codec": row.get("video_codec") or "",
            "hdr_format": row.get("hdr_format") or "",
            "container": row.get("container") or "",
            "video_source": row.get("video_source") or "",
            "source_format": row.get("source_format") or "",
            "audio": _duplicate_audio(row.get("audio_tracks")),
            "size_bytes": row.get("size_bytes") or 0,
            "duration_seconds": row.get("duration_seconds") or 0,
            "date_added": row.get("date_added") or row.get("created_at") or "",
            "probe_error": row.get("probe_error") or "",
        })
    packed = []
    for key, items in groups.items():
        seen = set()
        unique = []
        for item in items:
            identity = item.get("id") or item.get("filepath")
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(item)
        items = unique
        if len(items) < 2:
            continue
        packed.append({"key": "|".join(str(part) for part in key), "label": label_fn(next(row for row in rows if key_fn(row) == key)), "items": items})
    return packed


def dismiss_pair(kind, left_id, right_id):
    from resonance.errors import AppError

    if kind not in {"movie", "episode"}:
        raise AppError("Unknown item type")
    pair = sorted([str(left_id), str(right_id)])
    if pair[0] == pair[1]:
        raise AppError("Choose two different copies")
    db.execute(
        """
        INSERT INTO video_dismissed_duplicates (kind, left_id, right_id)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (kind, pair[0], pair[1]),
    )
    table = "movies" if kind == "movie" else "tv_episodes"
    if kind == "movie":
        refresh_movie_seeds(movie_seed_rows([left_id, right_id]))
    else:
        refresh_episode_seeds(episode_seed_rows([left_id, right_id]))
    cleared = db.fetchall(
        f"SELECT id::text AS id FROM {table} WHERE id = ANY(%s::uuid[]) AND duplicate_release IS FALSE",
        (db.uuid_array([left_id, right_id]),),
    )
    return {
        "dismissed": True,
        "cleared": [row["id"] for row in cleared],
        "kind": kind,
        "left_id": pair[0],
        "right_id": pair[1],
    }


def restore_pair(kind, left_id, right_id):
    """Put a Not duplicates choice back and return the copies whose pill returns."""
    from resonance.errors import AppError

    if kind not in {"movie", "episode"}:
        raise AppError("Unknown item type")
    pair = sorted([str(left_id), str(right_id)])
    db.execute(
        "DELETE FROM video_dismissed_duplicates WHERE kind = %s AND left_id = %s AND right_id = %s",
        (kind, pair[0], pair[1]),
    )
    table = "movies" if kind == "movie" else "tv_episodes"
    if kind == "movie":
        refresh_movie_seeds(movie_seed_rows([left_id, right_id]))
    else:
        refresh_episode_seeds(episode_seed_rows([left_id, right_id]))
    rows = db.fetchall(
        f"SELECT id::text AS id, duplicate_release FROM {table} WHERE id = ANY(%s::uuid[])",
        (db.uuid_array([left_id, right_id]),),
    )
    return {
        "restored": True,
        "marked": [row["id"] for row in rows if row.get("duplicate_release")],
        "cleared": [row["id"] for row in rows if not row.get("duplicate_release")],
    }
