"""Library analytics (chart data) and CSV/XML export of movies and TV episodes."""
from __future__ import annotations

import copy
import csv
import io
import logging
import os
import re
import shutil
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

RANGES = ("week", "month", "year", "all")
FORMAT_ORDER = ["DV P7 FEL", "DV P7 MEL", "DV P8.1", "DV P8.4", "DV P5", "DV P10.1", "DV P10.4", "DV P10", "DV P20", "DV other",
                "HDR10+", "HDR10", "HLG", "SDR", "Unknown"]
RES_ORDER = ["8K", "4K", "1080p", "720p", "SD"]


def container_label(value):
    text = str(value or "").split(",")[0].strip()
    if not text:
        return "Unknown"
    if text.lower() in {"matroska", "mkv"}:
        return "MKV"
    return text.upper()


# Analytics

def source_bucket(video_source, source_format):
    """One chart label for a file, so Bluray and Blu-ray Remux are not both printed."""
    from curator.video.sources import canonical_source, classify_source

    for candidate in (source_format, video_source):
        label, group = canonical_source(candidate)
        if group:
            return label
    text = " ".join(part for part in (source_format, video_source) if part).replace("_", "-")
    if not text:
        return "Unknown"
    return classify_source(text) or "Unknown"


def format_bucket(row):
    """Chart label for one file's HDR format, following video-analyzer's format chart."""
    fmt = (row.get("hdr_format") or "").lower()
    if fmt == "dovi":
        profile = str(row.get("dovi_profile") or "")
        if profile.startswith("7"):
            return "DV P7 FEL" if (row.get("dovi_el_type") or "").upper() == "FEL" else "DV P7 MEL"
        if profile in ("8", "8.1"):
            return "DV P8.1"
        if profile == "8.4":
            return "DV P8.4"
        if profile == "5":
            return "DV P5"
        if profile in ("10", "10.1"):
            return "DV P10.1" if profile == "10.1" else "DV P10"
        if profile == "10.4":
            return "DV P10.4"
        if profile == "20":
            return "DV P20"
        return "DV other"
    return {"hdr10plus": "HDR10+", "hdr10": "HDR10", "hlg": "HLG", "sdr": "SDR"}.get(fmt, "Unknown")


def _main_audio(tracks):
    tracks = tracks or []
    if not tracks:
        return ""
    track = next((item for item in tracks if item.get("default")), tracks[0])
    return track.get("codec") or ""


def _root_of(path, roots):
    best = ""
    for root in roots:
        if (path == root or path.startswith(root.rstrip("/") + "/")) and len(root) > len(best):
            best = root
    return best or os.path.dirname(os.path.dirname(path))


def _ordered(counter, order=None, limit=None):
    items = list(counter.items())
    if order:
        rank = {label: index for index, label in enumerate(order)}
        items.sort(key=lambda item: (rank.get(item[0], len(order)), -item[1]))
    else:
        items.sort(key=lambda item: (-item[1], item[0]))
    if limit and len(items) > limit:
        rest = sum(count for _, count in items[limit:])
        items = items[:limit] + [("Other", rest)]
    return [{"label": label, "count": count} for label, count in items if count]


def summarize(rows, roots):
    """Chart data for a list of video_files rows."""
    formats, secondary, resolutions, codecs, audio, sources, containers = (Counter() for _ in range(7))
    by_root = {}
    size = duration = 0
    for row in rows:
        formats[format_bucket(row)] += 1
        if (row.get("hdr_format") or "") == "dovi" and row.get("hdr_secondary"):
            secondary[str(row["hdr_secondary"]).upper()] += 1
        resolutions[row.get("resolution") or "Unknown"] += 1
        codecs[row.get("video_codec") or "Unknown"] += 1
        containers[container_label(row.get("container"))] += 1
        audio[_main_audio(row.get("audio_tracks")) or "Unknown"] += 1
        sources[source_bucket(row.get("video_source"), row.get("source_format"))] += 1
        root = _root_of(row["path"], roots)
        slot = by_root.setdefault(root, {"label": root, "count": 0, "size_bytes": 0})
        slot["count"] += 1
        slot["size_bytes"] += int(row.get("size_bytes") or 0)
        size += int(row.get("size_bytes") or 0)
        duration += int(row.get("duration_seconds") or 0)
    return {
        "totals": {"files": len(rows), "size_bytes": size, "duration_seconds": duration},
        "formats": _ordered(formats, FORMAT_ORDER),
        "secondary": _ordered(secondary),
        "resolutions": _ordered(resolutions, RES_ORDER + ["Unknown"]),
        "codecs": _ordered(codecs, limit=8),
        "containers": _ordered(containers, limit=8),
        "audio": _ordered(audio, limit=10),
        "sources": _ordered(sources, limit=10),
        "roots": sorted(by_root.values(), key=lambda item: item["label"]),
    }


_FILE_SQL = ("SELECT path, size_bytes, duration_seconds, resolution, video_codec, hdr_format, hdr_secondary, "
             "dovi_profile, dovi_el_type, video_source, source_format, container, audio_tracks FROM video_files "
             "WHERE media_kind = ANY(%s)")
_OWNED = "NOT {alias}.wanted AND strpos({alias}.path, 'wanted://') <> 1"


def _file_rows(kinds, root):
    sql = _FILE_SQL
    params = [kinds]
    clause, extra = _path_clause("path", root)
    return _rows(sql + clause, params + extra)


def _owned(alias):
    return _OWNED.format(alias=alias)


_fs_local = threading.local()
_fs_lock = threading.Lock()
_fs_cache = {}
_fs_inflight = set()
_sql_cache = {}
_FS_TTL = 600
_SQL_TTL = 180


def _within(seconds, fn):
    """Run fn on a side thread. (value, timed_out). A stuck filesystem call does not hold the request."""
    done = threading.Event()
    box = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    if not done.wait(seconds):
        return None, True
    if "error" in box:
        raise box["error"]
    return box.get("value"), False


def _mark_dead(path):
    dead = getattr(_fs_local, "dead", None)
    if dead is None:
        dead = []
        _fs_local.dead = dead
    dead.append(path)


def _path_dead(path):
    text = str(path or "")
    for root in getattr(_fs_local, "dead", ()) or ():
        base = str(root).rstrip("/")
        if text == base or text.startswith(base + "/"):
            return True
    return False


def _filesystem_bundle(media, root):
    _fs_local.dead = []
    disks = disk_report(media, root)
    trailers = _trailer_report(media, root) if media != "music" else {
        "files": 0, "missing": 0, "size_bytes": 0, "linked": 0,
    }
    return {
        "disks": disks,
        "artwork": artwork_report(media, root),
        "trailers": trailers,
        "subtitles": _subtitle_report(media, root, sizes=True),
    }


def _run_filesystem(key, media, root):
    try:
        payload = _filesystem_bundle(media, root)
    except Exception:
        logger.exception("Library analytics could not count files")
        payload = {"failed": True}
    with _fs_lock:
        _fs_cache[key] = (time.monotonic(), payload)
        _fs_inflight.discard(key)


def _filesystem_snapshot(media, root):
    """Cached file sizes and free space. The walk runs beside the request so the modal can open."""
    key = (media, root or "")
    with _fs_lock:
        cached = _fs_cache.get(key)
        ttl = 60 if cached and cached[1].get("failed") else _FS_TTL
        fresh = bool(cached) and time.monotonic() - cached[0] < ttl
        if key not in _fs_inflight and not fresh:
            _fs_inflight.add(key)
            threading.Thread(target=_run_filesystem, args=(key, media, root), daemon=True).start()
        if not cached:
            return None, True
        return cached[1], not fresh


def _apply_filesystem(data, media, root):
    extra, pending = _filesystem_snapshot(media, root)
    if extra and extra.get("failed"):
        data["filesystem_pending"] = False
        data["filesystem_error"] = True
        data.setdefault("disks", [])
        return data
    data["filesystem_pending"] = pending
    if not extra:
        data["disks"] = []
        return data
    data["disks"] = extra["disks"]
    data["artwork"] = extra["artwork"]
    coverage = data.setdefault("coverage", {})
    coverage["trailers"] = extra["trailers"]
    coverage["subtitles"] = extra["subtitles"]
    return data


def _library_shell(media, root):
    if media == "music":
        data = music_summary(root)
        data["media"] = "music"
        data["root"] = root or ""
        data["database_bytes"] = database_bytes()
        data["artwork"] = artwork_counts(media, root)
        data["coverage"] = coverage_report(media, root, sizes=False)
        return data
    data = {
        "media": media, "root": root or "", "disks": [],
        "database_bytes": database_bytes(), "artwork": artwork_counts(media, root),
        "coverage": coverage_report(media, root, sizes=False),
    }
    if media in ("all", "movies"):
        data["movies"] = movie_report(root)
    if media in ("all", "tv"):
        data["tv"] = tv_report(root)
    if media == "all":
        data["music"] = music_summary(root)
    return data


def present(media="all", root=None):
    """Charts for one library. File sizes and free space fill in once the share walk finishes."""
    key = (media, root or "")
    now = time.monotonic()
    with _fs_lock:
        cached = _sql_cache.get(key)
        fresh = cached and now - cached[0] < _SQL_TTL
    data = copy.deepcopy(cached[1]) if fresh else _library_shell(media, root)
    if not fresh:
        with _fs_lock:
            _sql_cache[key] = (time.monotonic(), copy.deepcopy(data))
    return _apply_filesystem(data, media, root)


def analytics(media="all", root=None):
    """Movies and TV are separate sections. All libraries includes both, plus music."""
    return present(media, root)


def movie_report(root):
    """Watched counts and file charts for movies only."""
    from curator import folders

    where, params = _path_clause("m.path", root)
    row = _rows(
        f"""
        SELECT count(*)::int AS total,
               count(*) FILTER (WHERE COALESCE(m.playcount, 0) > 0)::int AS watched,
               COALESCE(sum(f.size_bytes), 0)::bigint AS size_bytes,
               count(f.id)::int AS with_file,
               COALESCE(sum(f.duration_seconds) FILTER (WHERE COALESCE(m.playcount, 0) > 0), 0)::bigint AS watched_seconds
        FROM movies m
        LEFT JOIN video_files f ON f.id = m.file_id
        WHERE {_owned("m")} {where}
        """,
        params,
    )[0]
    total = int(row["total"] or 0)
    watched = int(row["watched"] or 0)
    size = int(row["size_bytes"] or 0)
    with_file = int(row["with_file"] or 0)
    data = summarize(_file_rows(["movie"], root), folders.mounted("movies"))
    data["library"] = {
        "watched": watched,
        "total": total,
        "size_bytes": size,
        "average_bytes": size // with_file if with_file else 0,
        "watched_seconds": int(row["watched_seconds"] or 0),
    }
    return data


def tv_report(root):
    """Series, season and episode counts, plus file charts for episode files only."""
    from curator import folders

    where, params = _path_clause("s.path", root)
    owned = _owned("s")
    row = _rows(
        f"""
        WITH shows AS (
            SELECT s.id FROM tv_shows s WHERE {owned} {where}
        ),
        eps AS (
            SELECT e.show_id, e.season_id, e.file_id,
                   (e.missing OR strpos(e.path, 'missing://') = 1) AS missing,
                   COALESCE(e.playcount, 0) > 0 AS watched
            FROM tv_episodes e
            JOIN shows s ON s.id = e.show_id
        ),
        files AS (
            SELECT DISTINCT f.id, f.size_bytes
            FROM eps e
            JOIN video_files f ON f.id = e.file_id
            WHERE NOT e.missing
        )
        SELECT
            (SELECT count(*)::int FROM shows) AS series_total,
            (SELECT count(*)::int FROM shows s WHERE
                EXISTS (SELECT 1 FROM eps e WHERE e.show_id = s.id AND NOT e.missing)
                AND NOT EXISTS (SELECT 1 FROM eps e WHERE e.show_id = s.id AND NOT e.missing AND NOT e.watched)
            ) AS series_watched,
            (SELECT count(*)::int FROM tv_seasons sn JOIN shows s ON s.id = sn.show_id) AS seasons_total,
            (SELECT count(*)::int FROM tv_seasons sn JOIN shows s ON s.id = sn.show_id WHERE
                EXISTS (SELECT 1 FROM eps e WHERE e.season_id = sn.id AND NOT e.missing)
                AND NOT EXISTS (SELECT 1 FROM eps e WHERE e.season_id = sn.id AND NOT e.missing AND NOT e.watched)
            ) AS seasons_watched,
            (SELECT count(*)::int FROM eps) AS episodes_total,
            (SELECT count(*)::int FROM eps WHERE NOT missing AND watched) AS episodes_watched,
            (SELECT count(*)::int FROM eps WHERE NOT missing AND NOT watched) AS episodes_unwatched,
            (SELECT count(*)::int FROM eps WHERE missing) AS episodes_missing,
            (SELECT count(*)::int FROM eps WHERE NOT missing) AS episodes_on_disk,
            (SELECT COALESCE(sum(size_bytes), 0)::bigint FROM files) AS size_bytes,
            (SELECT COALESCE(sum(COALESCE(ep.runtime_minutes, 0) * 60), 0)::bigint
             FROM tv_episodes ep
             JOIN shows s ON s.id = ep.show_id
             WHERE NOT (ep.missing OR strpos(ep.path, 'missing://') = 1)
               AND COALESCE(ep.playcount, 0) > 0) AS watched_seconds
        """,
        params,
    )[0]
    on_disk = int(row["episodes_on_disk"] or 0)
    size = int(row["size_bytes"] or 0)
    continuing, ended = _show_status_counts(_rows(
        f"""
        SELECT COALESCE(NULLIF(trim(s.show_status), ''), 'Unknown') AS label, count(*)::int AS count
        FROM tv_shows s WHERE {owned} {where}
        GROUP BY 1
        """,
        params,
    ))
    data = summarize(_file_rows(["episode"], root), folders.mounted("tv"))
    data["library"] = {
        "series_watched": int(row["series_watched"] or 0),
        "series_total": int(row["series_total"] or 0),
        "continuing": continuing,
        "ended": ended,
        "seasons_watched": int(row["seasons_watched"] or 0),
        "seasons_total": int(row["seasons_total"] or 0),
        "episodes_watched": int(row["episodes_watched"] or 0),
        "episodes_missing": int(row["episodes_missing"] or 0),
        "episodes_total": int(row["episodes_total"] or 0),
        "size_bytes": size,
        "average_bytes": size // on_disk if on_disk else 0,
        "watched_seconds": int(row["watched_seconds"] or 0),
    }
    return data


def _show_status_counts(rows):
    """Continuing covers a show that is still airing. Ended covers ended and cancelled."""
    continuing = ended = 0
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        count = int(row.get("count") or 0)
        if label in ("continuing", "returning series"):
            continuing += count
        elif label in ("ended", "canceled", "cancelled"):
            ended += count
    return continuing, ended


def _path_clause(column, root):
    if not root:
        return "", []
    prefix = root.rstrip("/").replace("%", r"\%").replace("_", r"\_") + "/%"
    return f" AND ({column} = %s OR {column} LIKE %s)", [root, prefix]


def _rows(sql, params=()):
    return [dict(row) for row in db.fetchall(sql, params)]


def _counter_query(sql, params, order=None, limit=None):
    counter = Counter()
    for row in _rows(sql, params):
        counter[row["label"] or "Unknown"] = int(row["count"] or 0)
    return _ordered(counter, order, limit)


def music_summary(root=None):
    """Artists, albums and tracks, grouped for the music charts."""
    where, params = _path_clause("file_path", root)
    album_where, album_params = _path_clause("path", root)
    totals = _rows(
        f"""
        SELECT count(*)::int AS tracks,
               COALESCE(sum(file_size), 0)::bigint AS size_bytes,
               COALESCE(sum(duration_seconds), 0)::bigint AS duration_seconds
        FROM tracks WHERE TRUE {where}
        """,
        params,
    )[0]
    library = _rows(
        f"""
        SELECT count(DISTINCT artist_id)::int AS artists, count(*)::int AS albums
        FROM albums WHERE TRUE {album_where}
        """,
        album_params,
    )[0]
    formats = _counter_query(
        f"SELECT upper(file_format) AS label, count(*)::int AS count FROM tracks WHERE TRUE {where} GROUP BY 1",
        params, limit=10,
    )
    depths = _counter_query(
        f"""
        SELECT CASE WHEN bit_depth IS NULL OR bit_depth = 0 THEN 'Unknown' ELSE bit_depth::text || '-bit' END AS label,
               count(*)::int AS count
        FROM tracks WHERE TRUE {where} GROUP BY 1
        """,
        params,
    )
    rates = _counter_query(
        f"""
        SELECT CASE
            WHEN sample_rate IS NULL OR sample_rate = 0 THEN 'Unknown'
            ELSE (round(sample_rate / 1000.0, 1))::text || ' kHz'
        END AS label, count(*)::int AS count
        FROM tracks WHERE TRUE {where} GROUP BY 1
        """,
        params, limit=8,
    )
    lyrics = _counter_query(
        f"""
        SELECT CASE COALESCE(lyrics_type, 'none')
            WHEN 'none' THEN 'No lyrics' WHEN 'lrc' THEN 'Synced lyrics' WHEN 'txt' THEN 'Plain lyrics'
            ELSE initcap(lyrics_type) END AS label,
               count(*)::int AS count
        FROM tracks WHERE TRUE {where} GROUP BY 1
        """,
        params,
    )
    matches = _counter_query(
        f"""
        SELECT COALESCE(NULLIF(match_tier, ''), 'unmatched') AS label, count(*)::int AS count
        FROM albums WHERE TRUE {album_where} GROUP BY 1
        """,
        album_params,
    )
    genres = _counter_query(
        f"""
        SELECT COALESCE(NULLIF(genre, ''), 'Unknown') AS label, count(*)::int AS count
        FROM tracks WHERE TRUE {where} GROUP BY 1
        """,
        params, limit=12,
    )
    from curator import folders

    music_roots = folders.mounted("music")
    case_sql, case_params = "'Other'", []
    if music_roots:
        branches = []
        for item in music_roots:
            branches.append("WHEN file_path = %s OR file_path LIKE %s THEN %s")
            prefix = item.rstrip("/").replace("%", r"\%").replace("_", r"\_") + "/%"
            case_params.extend([item, prefix, item])
        case_sql = "CASE " + " ".join(branches) + " ELSE 'Other' END"
    roots = []
    for row in _rows(
        f"""
        SELECT {case_sql} AS label, count(*)::int AS count, COALESCE(sum(file_size), 0)::bigint AS size_bytes
        FROM tracks WHERE TRUE {where}
        GROUP BY 1 ORDER BY 1
        """,
        case_params + params,
    ):
        roots.append({"label": row["label"] or "Unknown", "count": int(row["count"]), "size_bytes": int(row["size_bytes"] or 0)})
    return {
        "totals": {
            "artists": int(library["artists"] or 0),
            "albums": int(library["albums"] or 0),
            "tracks": int(totals["tracks"] or 0),
            "size_bytes": int(totals["size_bytes"] or 0),
            "duration_seconds": int(totals["duration_seconds"] or 0),
        },
        "formats": formats,
        "depths": depths,
        "rates": rates,
        "lyrics": lyrics,
        "matches": matches,
        "genres": genres,
        "roots": roots,
    }


def database_bytes():
    """Size of this Postgres database, including indexes."""
    try:
        row = db.fetchone("SELECT pg_database_size(current_database())::bigint AS bytes")
    except Exception:
        return 0
    return int((row or {}).get("bytes") or 0)


def _file_size(path, sizes, measured):
    """Byte size of one local file. None when the path is empty, remote, or missing."""
    text = str(path or "").strip()
    if not text or text.lower().startswith(("http://", "https://")) or _path_dead(text):
        return None
    key = os.path.normcase(text)
    if key in measured:
        return measured[key]
    size = int((sizes or {}).get(text) or 0)
    if size <= 0:
        try:
            size = os.path.getsize(text)
        except OSError:
            measured[key] = None
            return None
    measured[key] = size
    return size


def _art_files(paths, sizes=None):
    """Unique image files that are still on disk, and their total size."""
    measured = {}
    seen = set()
    count = total = 0
    for path in paths:
        key = os.path.normcase(str(path or "").strip())
        if not key or key in seen:
            continue
        size = _file_size(path, sizes, measured)
        if size is None:
            continue
        seen.add(key)
        count += 1
        total += size
    return count, total


def _json_art_rows(sql, params):
    return [{
        "kind": row.get("kind") or "",
        "path": row.get("path") or "",
        "season": bool(row.get("season")),
    } for row in _rows(sql, params)]


_ART_LABELS = {
    "poster": "Poster", "fanart": "Fanart", "clearlogo": "Clearlogo", "clearart": "Clearart",
    "discart": "Disc", "banner": "Banner", "landscape": "Landscape", "keyart": "Keyart",
    "characterart": "Character art", "squareart": "Square", "thumb": "Thumb",
    "extrafanart": "Extra fanart", "extrathumbs": "Extra thumbs", "music": "Music",
}


def _art_label(kind, season=False):
    text = re.sub(r"\d+$", "", str(kind or "").lower())
    if season and text == "poster":
        return "Season poster"
    return _ART_LABELS.get(text, text.replace("_", " ").title() or "Other")


def _art_groups(rows):
    total = 0
    types = {}
    for row in rows:
        count = int(row.get("count") or 0)
        if not count:
            continue
        total += count
        kind = _art_label(row.get("kind") or "", bool(row.get("season")))
        slot = types.setdefault(kind, {"count": 0, "size_bytes": None})
        slot["count"] += count
    return total, types


def artwork_counts(media, root=None):
    """How many artwork files are recorded. Sizes wait for the share walk."""
    media_rows = []
    types = {}
    total = 0

    def take(label, sql, params):
        nonlocal total
        count, grouped = _art_groups(_rows(sql, params))
        if not count:
            return
        media_rows.append({"label": label, "count": count, "size_bytes": None})
        for kind, row in grouped.items():
            slot = types.setdefault(kind, {"count": 0, "size_bytes": None})
            slot["count"] += row["count"]
        total += count

    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        take("Movies", f"""
            SELECT e.key AS kind, count(*)::int AS count
            FROM movies m
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(m.artwork, '{{}}'::jsonb)) e
            WHERE {_owned("m")} {where} AND btrim(e.value) <> ''
            GROUP BY 1
        """, params)
        if not root:
            take("Movie sets", """
                SELECT e.key AS kind, count(*)::int AS count
                FROM movie_sets s
                CROSS JOIN LATERAL jsonb_each_text(COALESCE(s.artwork, '{}'::jsonb)) e
                WHERE btrim(e.value) <> ''
                GROUP BY 1
            """, [])
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        take("TV", f"""
            SELECT kind, season, count(*)::int AS count FROM (
                SELECT e.key AS kind, FALSE AS season
                FROM tv_shows s
                CROSS JOIN LATERAL jsonb_each_text(COALESCE(s.artwork, '{{}}'::jsonb)) e
                WHERE {owned} {where} AND btrim(e.value) <> ''
                UNION ALL
                SELECT e.key, TRUE
                FROM tv_seasons sn
                JOIN tv_shows s ON s.id = sn.show_id
                CROSS JOIN LATERAL jsonb_each_text(COALESCE(sn.artwork, '{{}}'::jsonb)) e
                WHERE {owned} {where} AND btrim(e.value) <> ''
                UNION ALL
                SELECT e.key, FALSE
                FROM tv_episodes ep
                JOIN tv_shows s ON s.id = ep.show_id
                CROSS JOIN LATERAL jsonb_each_text(COALESCE(ep.artwork, '{{}}'::jsonb)) e
                WHERE {owned} {where} AND btrim(e.value) <> ''
            ) art
            GROUP BY 1, 2
        """, params + params + params)
    if media in ("all", "music"):
        album_where, album_params = _path_clause("al.path", root)
        artist_where, artist_params = _path_clause("ar.path", root)
        if root:
            scope = f"AND ((al.id IS NOT NULL {album_where}) OR (al.id IS NULL {artist_where}))"
            scope_params = album_params + artist_params
        else:
            scope, scope_params = "", []
        row = _rows(f"""
            SELECT count(*)::int AS count
            FROM artwork_pool p
            LEFT JOIN albums al ON al.id = p.album_id
            LEFT JOIN artists ar ON ar.id = p.artist_id
            WHERE COALESCE(p.local_path, '') <> '' {scope}
        """, scope_params)
        count = int((row[0] if row else {}).get("count") or 0)
        if count:
            media_rows.append({"label": "Music", "count": count, "size_bytes": None})
            types["Music"] = {"count": count, "size_bytes": None}
            total += count
    type_rows = [{"label": label, "count": row["count"], "size_bytes": None}
                 for label, row in sorted(types.items(), key=lambda item: (-item[1]["count"], item[0]))]
    return {"count": total, "size_bytes": None, "media": media_rows, "types": type_rows}


def artwork_report(media, root=None):
    """Image files Curator has recorded, counted and sized per library."""
    groups = []
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        groups.append(("Movies", _json_art_rows(
            f"""
            SELECT e.key AS kind, e.value AS path
            FROM movies m
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(m.artwork, '{{}}'::jsonb)) e
            WHERE {_owned("m")} {where} AND btrim(e.value) <> ''
            """,
            params,
        ), {}))
        if not root:
            groups.append(("Movie sets", _json_art_rows(
                """
                SELECT e.key AS kind, e.value AS path
                FROM movie_sets s
                CROSS JOIN LATERAL jsonb_each_text(COALESCE(s.artwork, '{}'::jsonb)) e
                WHERE btrim(e.value) <> ''
                """,
                [],
            ), {}))
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        groups.append(("TV", _json_art_rows(
            f"""
            SELECT e.key AS kind, e.value AS path, FALSE AS season
            FROM tv_shows s
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(s.artwork, '{{}}'::jsonb)) e
            WHERE {owned} {where} AND btrim(e.value) <> ''
            UNION ALL
            SELECT e.key, e.value, TRUE
            FROM tv_seasons sn
            JOIN tv_shows s ON s.id = sn.show_id
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(sn.artwork, '{{}}'::jsonb)) e
            WHERE {owned} {where} AND btrim(e.value) <> ''
            UNION ALL
            SELECT e.key, e.value, FALSE
            FROM tv_episodes ep
            JOIN tv_shows s ON s.id = ep.show_id
            CROSS JOIN LATERAL jsonb_each_text(COALESCE(ep.artwork, '{{}}'::jsonb)) e
            WHERE {owned} {where} AND btrim(e.value) <> ''
            """,
            params + params + params,
        ), {}))
    if media in ("all", "music"):
        album_where, album_params = _path_clause("al.path", root)
        artist_where, artist_params = _path_clause("ar.path", root)
        if root:
            scope = f"AND ((al.id IS NOT NULL {album_where}) OR (al.id IS NULL {artist_where}))"
            scope_params = album_params + artist_params
        else:
            scope, scope_params = "", []
        rows = _rows(
            f"""
            SELECT p.local_path AS path, COALESCE(p.file_size_bytes, 0)::bigint AS size
            FROM artwork_pool p
            LEFT JOIN albums al ON al.id = p.album_id
            LEFT JOIN artists ar ON ar.id = p.artist_id
            WHERE COALESCE(p.local_path, '') <> '' {scope}
            """,
            scope_params,
        )
        groups.append(("Music", [{"kind": "music", "path": row.get("path") or ""} for row in rows], {row.get("path") or "": int(row.get("size") or 0) for row in rows}))
    media_rows = []
    type_rows = {}
    measured = {}
    total_count = total_size = 0
    for label, rows, sizes in groups:
        seen = set()
        count = size = 0
        for row in rows:
            path = row.get("path") if isinstance(row, dict) else row
            key = os.path.normcase(str(path or "").strip())
            if not key or key in seen:
                continue
            bytes_ = _file_size(path, sizes, measured)
            if bytes_ is None:
                continue
            seen.add(key)
            count += 1
            size += bytes_
            kind = _art_label(row.get("kind") if isinstance(row, dict) else "", bool(row.get("season")) if isinstance(row, dict) else False)
            slot = type_rows.setdefault(kind, {"count": 0, "size_bytes": 0})
            slot["count"] += 1
            slot["size_bytes"] += bytes_
        if not count:
            continue
        media_rows.append({"label": label, "count": count, "size_bytes": size})
        total_count += count
        total_size += size
    actors = _actor_images(media, root)
    if actors["count"]:
        media_rows.append({"label": "Actor portraits", "count": actors["count"], "size_bytes": actors["size_bytes"]})
        type_rows["Actor portraits"] = {"count": actors["count"], "size_bytes": actors["size_bytes"]}
        total_count += actors["count"]
        total_size += actors["size_bytes"]
    types = [{"label": label, "count": row["count"], "size_bytes": row["size_bytes"]}
             for label, row in sorted(type_rows.items(), key=lambda item: (-item[1]["count"], item[0]))
             if row["count"]]
    return {"count": total_count, "size_bytes": total_size, "media": media_rows, "types": types}


def _dir_images(folder):
    """Image files in one directory, and their total size."""
    count = size = 0
    if not folder or _path_dead(folder) or not os.path.isdir(folder):
        return 0, 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                if os.path.splitext(entry.name)[1].lower() not in {".jpg", ".jpeg", ".png", ".webp", ".tbn"}:
                    continue
                try:
                    size += entry.stat().st_size
                except OSError:
                    continue
                count += 1
    except OSError:
        return 0, 0
    return count, size


def _actor_images(media, root):
    """Portraits saved in `.actors` next to movies and shows. Those files are not in the artwork map."""
    folders = []
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        folders.extend(row.get("folder") or "" for row in _rows(
            f"SELECT DISTINCT m.folder FROM movies m WHERE {_owned('m')} {where} AND COALESCE(m.folder, '') <> ''",
            params,
        ))
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        folders.extend(row.get("path") or "" for row in _rows(
            f"SELECT s.path FROM tv_shows s WHERE {owned} {where}",
            params,
        ))
        folders.extend(row.get("path") or "" for row in _rows(
            f"""
            SELECT sn.path FROM tv_seasons sn
            JOIN tv_shows s ON s.id = sn.show_id
            WHERE {owned} {where} AND COALESCE(sn.path, '') <> ''
            """,
            params,
        ))
    count = size = 0
    seen = set()
    for folder in folders:
        key = os.path.normcase(folder)
        if not key or key in seen:
            continue
        seen.add(key)
        found, bytes_ = _dir_images(os.path.join(folder, ".actors"))
        count += found
        size += bytes_
    return {"count": count, "size_bytes": size}


def _missing_art(media, root):
    """Items whose stored artwork is missing one of the usual images."""
    checks = []
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        row = _rows(
            f"""
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE COALESCE(m.artwork->>'poster', '') = '')::int AS poster,
                   count(*) FILTER (WHERE COALESCE(m.artwork->>'fanart', '') = '')::int AS fanart,
                   count(*) FILTER (WHERE COALESCE(m.artwork->>'clearlogo', '') = '')::int AS clearlogo,
                   count(*) FILTER (WHERE COALESCE(m.artwork->>'discart', '') = '')::int AS disc,
                   count(*) FILTER (WHERE COALESCE(m.artwork->>'banner', '') = '')::int AS banner
            FROM movies m WHERE {_owned("m")} {where}
            """,
            params,
        )[0]
        total = int(row["total"] or 0)
        for key, label in (("poster", "Movie poster"), ("fanart", "Movie fanart"), ("clearlogo", "Movie clearlogo"),
                           ("disc", "Movie disc"), ("banner", "Movie banner")):
            checks.append({"label": label, "missing": int(row[key] or 0), "total": total})
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        row = _rows(
            f"""
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE COALESCE(s.artwork->>'poster', '') = '')::int AS poster,
                   count(*) FILTER (WHERE COALESCE(s.artwork->>'fanart', '') = '')::int AS fanart,
                   count(*) FILTER (WHERE COALESCE(s.artwork->>'clearlogo', '') = '')::int AS clearlogo,
                   count(*) FILTER (WHERE COALESCE(s.artwork->>'banner', '') = '')::int AS banner
            FROM tv_shows s WHERE {owned} {where}
            """,
            params,
        )[0]
        total = int(row["total"] or 0)
        for key, label in (("poster", "Show poster"), ("fanart", "Show fanart"), ("clearlogo", "Show clearlogo"),
                           ("banner", "Show banner")):
            checks.append({"label": label, "missing": int(row[key] or 0), "total": total})
        seasons = _rows(
            f"""
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE COALESCE(sn.artwork->>'poster', '') = '')::int AS poster
            FROM tv_seasons sn
            JOIN tv_shows s ON s.id = sn.show_id
            WHERE {owned} {where}
            """,
            params,
        )[0]
        checks.append({"label": "Season poster", "missing": int(seasons["poster"] or 0), "total": int(seasons["total"] or 0)})
    return [item for item in checks if item["total"]]


def _trailer_bytes(folder):
    """Trailer videos in a folder: how many, and their total size."""
    from curator.video import naming

    if not folder or _path_dead(folder) or not os.path.isdir(folder):
        return 0, 0
    found = size = 0
    seen = set()

    def take(directory, named):
        nonlocal found, size
        key = os.path.normcase(os.path.abspath(directory))
        if key in seen:
            return
        seen.add(key)
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not entry.is_file() or not naming.is_video(entry.name):
                        continue
                    stem = os.path.splitext(entry.name)[0].lower()
                    if named and stem != "trailer" and not stem.endswith("-trailer"):
                        continue
                    try:
                        size += entry.stat().st_size
                    except OSError:
                        continue
                    found += 1
        except OSError:
            return

    take(folder, True)
    for name in ("Trailers", "trailers"):
        take(os.path.join(folder, name), False)
    return found, size


def _trailer_report(media, root):
    folders = []
    linked = 0
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        for row in _rows(
            f"SELECT m.folder, COALESCE(m.trailer, '') AS trailer FROM movies m WHERE {_owned('m')} {where}",
            params,
        ):
            folders.append(row.get("folder") or "")
            if str(row.get("trailer") or "").strip():
                linked += 1
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        for row in _rows(
            f"SELECT s.path AS folder, COALESCE(s.trailer, '') AS trailer FROM tv_shows s WHERE {owned} {where}",
            params,
        ):
            folders.append(row.get("folder") or "")
            if str(row.get("trailer") or "").strip():
                linked += 1
        for row in _rows(
            f"""
            SELECT sn.path AS folder, COALESCE(sn.trailer, '') AS trailer
            FROM tv_seasons sn JOIN tv_shows s ON s.id = sn.show_id
            WHERE {owned} {where} AND COALESCE(sn.path, '') <> ''
            """,
            params,
        ):
            folders.append(row.get("folder") or "")
            if str(row.get("trailer") or "").strip():
                linked += 1
    files = missing = size = 0
    seen = {}
    for folder in folders:
        key = os.path.normcase(folder)
        if not key:
            missing += 1
            continue
        if key not in seen:
            seen[key] = _trailer_bytes(folder)
            files += seen[key][0]
            size += seen[key][1]
        if not seen[key][0]:
            missing += 1
    return {"files": files, "missing": missing, "size_bytes": size, "linked": linked}


def _subtitle_report(media, root, sizes=True):
    kinds = []
    if media in ("all", "movies"):
        kinds.append("movie")
    if media in ("all", "tv"):
        kinds.append("episode")
    if not kinds:
        return {"videos": 0, "none": 0, "embedded": 0, "external_files": 0, "external_bytes": 0}
    where, params = _path_clause("f.path", root)
    row = _rows(
        f"""
-- COALESCE only replaces SQL NULL, not JSON null / scalars / objects, and
        -- jsonb_array_length throws "cannot get array length of a scalar" on any of those.
        -- CASE WHEN is used rather than guarded ORs because PostgreSQL does not promise to
        -- short-circuit OR operands - the planner can reorder them and call
        -- jsonb_array_length on a scalar. The SQL spec does guarantee CASE evaluation order.
        SELECT count(*)::int AS videos,
               count(*) FILTER (
                   WHERE (CASE WHEN jsonb_typeof(f.subtitle_tracks) = 'array'
                               THEN jsonb_array_length(f.subtitle_tracks) ELSE 0 END) = 0
                     AND (CASE WHEN jsonb_typeof(f.external_subtitles) = 'array'
                               THEN jsonb_array_length(f.external_subtitles) ELSE 0 END) = 0
               )::int AS none,
               count(*) FILTER (
                   WHERE (CASE WHEN jsonb_typeof(f.subtitle_tracks) = 'array'
                               THEN jsonb_array_length(f.subtitle_tracks) ELSE 0 END) > 0
               )::int AS embedded,
               COALESCE(sum(CASE WHEN jsonb_typeof(f.external_subtitles) = 'array'
                                 THEN jsonb_array_length(f.external_subtitles) ELSE 0 END), 0)::int AS external_files
        FROM video_files f
        WHERE f.media_kind = ANY(%s) {where}
        """,
        [kinds] + params,
    )[0]
    files = _rows(
        f"""
        SELECT f.path, f.external_subtitles
        FROM video_files f
        WHERE f.media_kind = ANY(%s) {where}
          AND jsonb_typeof(f.external_subtitles) = 'array'
          AND jsonb_array_length(f.external_subtitles) > 0
        """,
        [kinds] + params,
    )
    external_bytes = 0
    seen = set()
    if not sizes:
        return {
            "videos": int(row["videos"] or 0),
            "none": int(row["none"] or 0),
            "embedded": int(row["embedded"] or 0),
            "external_files": int(row["external_files"] or 0),
            "external_bytes": None,
        }
    for item in files:
        folder = os.path.dirname(item.get("path") or "")
        for track in item.get("external_subtitles") or []:
            name = track.get("file") if isinstance(track, dict) else ""
            path = os.path.join(folder, name) if name else ""
            key = os.path.normcase(path)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                external_bytes += os.path.getsize(path)
            except OSError:
                continue
    return {
        "videos": int(row["videos"] or 0),
        "none": int(row["none"] or 0),
        "embedded": int(row["embedded"] or 0),
        "external_files": int(row["external_files"] or 0),
        "external_bytes": external_bytes,
    }


def _count_pair(sql, params):
    row = _rows(sql, params)
    return int((row[0] if row else {}).get("n") or 0)


def _trailer_linked(media, root):
    """How many movies and shows already have a trailer URL or path. No folder walk."""
    linked = 0
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        linked += _count_pair(
            f"SELECT count(*)::int AS n FROM movies m WHERE {_owned('m')} AND btrim(COALESCE(m.trailer, '')) <> '' {where}",
            params,
        )
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        linked += _count_pair(
            f"SELECT count(*)::int AS n FROM tv_shows s WHERE {owned} AND btrim(COALESCE(s.trailer, '')) <> '' {where}",
            params,
        )
        linked += _count_pair(
            f"""
            SELECT count(*)::int AS n FROM tv_seasons sn
            JOIN tv_shows s ON s.id = sn.show_id
            WHERE {owned} AND btrim(COALESCE(sn.trailer, '')) <> '' {where}
            """,
            params,
        )
    return {"files": None, "missing": None, "size_bytes": None, "linked": linked}


def coverage_report(media, root=None, sizes=True):
    """Artwork gaps, trailers, subtitles, probe failures, duplicates, and upgrades."""
    duplicates = []
    upgrades = []
    probe = []
    if media in ("all", "movies"):
        where, params = _path_clause("m.path", root)
        owned = _owned("m")
        duplicates.append({"label": "Movies", "count": _count_pair(
            f"SELECT count(*)::int AS n FROM movies m WHERE {owned} AND m.duplicate_release IS TRUE {where}", params)})
        upgrades.append({"label": "Movies", "count": _count_pair(
            f"SELECT count(*)::int AS n FROM movies m WHERE {owned} AND m.upgrade_source_id IS NOT NULL {where}", params)})
        probe.append({"label": "Movies", "count": _count_pair(
            f"""
            SELECT count(*)::int AS n FROM movies m
            JOIN video_files f ON f.id = m.file_id
            WHERE {owned} AND COALESCE(f.probe_error, '') <> '' {where}
            """,
            params,
        )})
    if media in ("all", "tv"):
        where, params = _path_clause("s.path", root)
        owned = _owned("s")
        duplicates.append({"label": "Episodes", "count": _count_pair(
            f"""
            SELECT count(*)::int AS n FROM tv_episodes e
            JOIN tv_shows s ON s.id = e.show_id
            WHERE {owned} AND e.duplicate_release IS TRUE {where}
            """,
            params,
        )})
        upgrades.append({"label": "Episodes", "count": _count_pair(
            f"""
            SELECT count(*)::int AS n FROM tv_episodes e
            JOIN tv_shows s ON s.id = e.show_id
            WHERE {owned} AND e.upgrade_source_id IS NOT NULL {where}
            """,
            params,
        )})
        probe.append({"label": "Episodes", "count": _count_pair(
            f"""
            SELECT count(*)::int AS n FROM tv_episodes e
            JOIN tv_shows s ON s.id = e.show_id
            JOIN video_files f ON f.id = e.file_id
            WHERE {owned} AND COALESCE(f.probe_error, '') <> '' {where}
            """,
            params,
        )})
    if media in ("all", "music"):
        where, params = _path_clause("path", root)
        duplicates.append({"label": "Albums", "count": _count_pair(
            f"SELECT count(*)::int AS n FROM albums WHERE duplicate_release IS TRUE {where}", params)})
        upgrades.append({"label": "Albums", "count": _count_pair(
            f"SELECT count(*)::int AS n FROM albums WHERE upgrade_source_id IS NOT NULL {where}", params)})
    return {
        "missing_art": _missing_art(media, root),
        "trailers": (_trailer_report(media, root) if sizes else _trailer_linked(media, root)) if media != "music" else {"files": 0, "missing": 0, "size_bytes": 0, "linked": 0},
        "subtitles": _subtitle_report(media, root, sizes=sizes),
        "probe_failed": [item for item in probe if item["count"]],
        "duplicates": [item for item in duplicates if item["count"]],
        "upgrades": [item for item in upgrades if item["count"]],
    }


def disk_report(media, root=None):
    """Free and total space for each library folder, one row per filesystem."""
    from curator import folders

    kinds = {"music": ["music"], "movies": ["movies"], "tv": ["tv"]}.get(media, ["music", "movies", "tv"])
    labels = {"music": "Music", "movies": "Movies", "tv": "TV"}
    groups = {}
    order = []
    for kind in kinds:
        for path in folders.configured(kind):
            if root and path != root and not path.startswith(root.rstrip("/") + "/") and not root.startswith(path.rstrip("/") + "/"):
                continue
            key = None
            usage = None
            def probe(folder=path):
                try:
                    if not os.path.isdir(folder):
                        return None
                    return os.stat(folder).st_dev, shutil.disk_usage(folder)
                except OSError:
                    return None

            usage_row, timed_out = _within(2, probe)
            if timed_out:
                _mark_dead(path)
            mounted = usage_row is not None
            if mounted:
                key, usage = usage_row
            if key is None:
                key = ("missing", path)
            if key not in groups:
                groups[key] = {
                    "paths": [], "libraries": [], "mounted": mounted,
                    "total": int(usage.total) if usage else 0,
                    "used": int(usage.used) if usage else 0,
                    "free": int(usage.free) if usage else 0,
                }
                order.append(key)
            slot = groups[key]
            if path not in slot["paths"]:
                slot["paths"].append(path)
            name = labels[kind]
            if name not in slot["libraries"]:
                slot["libraries"].append(name)
    return [{
        "label": ", ".join(groups[key]["paths"]),
        "libraries": groups[key]["libraries"],
        "mounted": groups[key]["mounted"],
        "total": groups[key]["total"],
        "used": groups[key]["used"],
        "free": groups[key]["free"],
    } for key in order]


def _month_start(day):
    return day.replace(day=1)


def _add_month(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def bucket_labels(range_name, today, first=None):
    """Bucket start dates for a range: days for week/month, months for year/all."""
    if range_name == "week":
        return [today - timedelta(days=offset) for offset in range(6, -1, -1)], "day"
    if range_name == "month":
        return [today - timedelta(days=offset) for offset in range(29, -1, -1)], "day"
    end = _month_start(today)
    if range_name == "year":
        start = end
        for _ in range(11):
            start = (start - timedelta(days=1)).replace(day=1)
    else:
        start = _month_start(first or today)
    months = []
    current = start
    while current <= end:
        months.append(current)
        current = _add_month(current)
    return months, "month"


def scan_series(jobs, range_name, today=None):
    """Scan counts per bucket and media. jobs are (media, started_at datetime)."""
    if range_name not in RANGES:
        raise AppError(f"Unknown range {range_name}", 400)
    today = today or date.today()
    days = [started.date() for _, started in jobs if started]
    buckets, unit = bucket_labels(range_name, today, min(days) if days else None)
    index = {bucket: position for position, bucket in enumerate(buckets)}
    series = {"music": [0] * len(buckets), "movies": [0] * len(buckets), "tv": [0] * len(buckets)}
    for media, started in jobs:
        if not started or media not in series:
            continue
        key = started.date() if unit == "day" else _month_start(started.date())
        if key in index:
            series[media][index[key]] += 1
    labels = [bucket.isoformat() if unit == "day" else bucket.strftime("%Y-%m") for bucket in buckets]
    return {"range": range_name, "unit": unit, "labels": labels, "series": series,
            "total": sum(sum(values) for values in series.values())}


def scans(range_name="month"):
    rows = db.fetchall(
        "SELECT 'music' AS media, started_at FROM scan_jobs WHERE started_at IS NOT NULL "
        "UNION ALL SELECT media, started_at FROM video_scan_jobs WHERE started_at IS NOT NULL"
    )
    jobs = [(row["media"], row["started_at"]) for row in rows if isinstance(row["started_at"], datetime)]
    data = scan_series(jobs, range_name)
    data["added"] = additions(range_name)
    return data


def additions(range_name="month"):
    """Movies, episodes, and albums by the day or month they were added."""
    rows = db.fetchall(
        """
        SELECT 'movies' AS media, created_at FROM movies
        WHERE created_at IS NOT NULL AND NOT wanted AND strpos(path, 'wanted://') <> 1
        UNION ALL
        SELECT 'tv', e.created_at FROM tv_episodes e
        WHERE e.created_at IS NOT NULL AND NOT e.missing AND strpos(e.path, 'missing://') <> 1
        UNION ALL
        SELECT 'music', created_at FROM albums WHERE created_at IS NOT NULL
        """
    )
    jobs = [(row["media"], row["created_at"]) for row in rows if isinstance(row["created_at"], datetime)]
    return scan_series(jobs, range_name)


# Export

FILE_COLUMNS = ["container", "size_bytes", "duration_seconds", "bitrate_mbps", "video_codec", "video_profile",
                "width", "height", "resolution", "fps", "aspect_ratio", "bit_depth", "hdr_format", "hdr_secondary",
                "is_hybrid", "dovi_profile", "dovi_el_type", "dovi_bl_compat", "max_cll", "max_fall", "is_3d",
                "video_source", "source_format", "file_edition", "probe_error"]
TRACK_COLUMNS = ["audio_codecs", "audio_langs", "audio_channels", "subtitle_langs", "external_subtitle_langs"]
MOVIE_COLUMNS = (["title", "original_title", "sort_title", "year", "edition", "set_name", "genres", "studios",
                  "countries", "directors", "mpaa", "runtime_minutes", "rating", "votes", "top250", "imdb_id",
                  "tmdb_id", "tags", "playcount", "last_played", "status", "scrape_error", "locked", "has_nfo", "artwork",
                  "trailer", "date_added", "path", "folder", "root"] + FILE_COLUMNS + TRACK_COLUMNS)
EPISODE_COLUMNS = (["show_title", "show_year", "show_imdb_id", "show_tmdb_id", "show_tvdb_id", "season", "episode",
                    "episode_title", "aired", "runtime_minutes", "rating", "playcount", "last_played", "status", "scrape_error",
                    "locked", "has_nfo", "path", "root"] + FILE_COLUMNS + TRACK_COLUMNS)
SET_COLUMNS = ["name", "tmdb_collection_id", "movie_count", "part_count", "missing_count", "first_year", "last_year",
               "status", "has_nfo", "artwork", "scrape_error", "folder", "overview"]
MUSIC_COLUMNS = ["artist_name", "artist_mbid", "album_title", "album_mbid", "release_year", "original_year", "type",
                 "edition", "label", "country", "catalog", "barcode", "genres", "match_tier", "match_ratio",
                 "total_discs", "total_tracks", "duration_seconds", "status", "has_nfo", "has_artwork", "path"]
_FILE_SELECT = ", ".join(f"f.{column}" for column in FILE_COLUMNS if column != "file_edition")


def _tracks(row):
    audio = row.pop("audio_tracks", None) or []
    subs = row.pop("subtitle_tracks", None) or []
    external = row.pop("external_subtitles", None) or []
    row["audio_codecs"] = [track.get("codec") or "" for track in audio]
    row["audio_langs"] = [track.get("lang") or "" for track in audio]
    row["audio_channels"] = [track.get("channels") or "" for track in audio]
    row["subtitle_langs"] = [track.get("lang") or "" for track in subs]
    row["external_subtitle_langs"] = [track.get("lang") or "" for track in external]
    return row


def _under(path, roots):
    return not roots or any(path == root or path.startswith(root.rstrip("/") + "/") for root in roots)


def export_rows(media, ids, roots=None):
    ids = list(ids)
    if media == "movies":
        rows = db.fetchall(
            f"""
            SELECT m.title, m.original_title, m.sort_title, m.year, m.edition, s.name AS set_name, m.genres,
                   m.studios, m.countries, m.directors, m.mpaa, m.runtime_minutes, m.rating, m.votes, m.top250,
                   m.imdb_id, m.tmdb_id, m.tags, m.playcount, m.last_played, m.status::text AS status, m.scrape_error, m.locked,
                   m.nfo_path IS NOT NULL AS has_nfo, m.artwork, m.trailer, m.date_added, m.path, m.folder, m.root,
                   {_FILE_SELECT}, f.edition AS file_edition, f.audio_tracks, f.subtitle_tracks, f.external_subtitles
            FROM movies m
            LEFT JOIN video_files f ON f.id = m.file_id
            LEFT JOIN movie_sets s ON s.id = m.set_id
            WHERE m.id = ANY(%s::uuid[])
            ORDER BY array_position(%s::uuid[], m.id)
            """,
            (ids, ids),
        )
        columns = MOVIE_COLUMNS
    elif media == "tv":
        rows = db.fetchall(
            f"""
            SELECT sh.title AS show_title, sh.year AS show_year, sh.imdb_id AS show_imdb_id,
                   sh.tmdb_id AS show_tmdb_id, sh.tvdb_id AS show_tvdb_id, e.season_number AS season,
                   e.episode_number AS episode, e.title AS episode_title, e.aired, e.runtime_minutes, e.rating,
                   e.playcount, e.last_played, e.status::text AS status, e.scrape_error, e.locked,
                   e.nfo_path IS NOT NULL AS has_nfo, e.path, sh.root,
                   {_FILE_SELECT}, f.edition AS file_edition, f.audio_tracks, f.subtitle_tracks, f.external_subtitles
            FROM tv_episodes e
            JOIN tv_shows sh ON sh.id = e.show_id
            LEFT JOIN video_files f ON f.id = e.file_id
            WHERE e.show_id = ANY(%s::uuid[])
            ORDER BY array_position(%s::uuid[], e.show_id), e.season_number, e.episode_number
            """,
            (ids, ids),
        )
        columns = EPISODE_COLUMNS
    elif media == "sets":
        rows = db.fetchall(
            """
            SELECT s.name, s.tmdb_collection_id, count(m.id)::int AS movie_count,
                   (SELECT count(*)::int FROM movie_set_parts p WHERE p.set_id = s.id) AS part_count,
                   (SELECT count(*)::int FROM movie_set_parts p WHERE p.set_id = s.id
                      AND NOT EXISTS (SELECT 1 FROM movies o WHERE o.tmdb_id = p.tmdb_id)) AS missing_count,
                   min(m.year) AS first_year, max(m.year) AS last_year,
                   s.status::text AS status, s.nfo_path IS NOT NULL AS has_nfo,
                   s.artwork, s.scrape_error, s.folder, s.overview
            FROM movie_sets s
            LEFT JOIN movies m ON m.set_id = s.id
            WHERE s.id = ANY(%s::uuid[])
            GROUP BY s.id
            ORDER BY array_position(%s::uuid[], s.id)
            """,
            (ids, ids),
        )
        columns = SET_COLUMNS
    elif media == "music":
        rows = db.fetchall(
            """
            SELECT ar.name AS artist_name, ar.musicbrainz_artist_id::text AS artist_mbid,
                   al.title AS album_title, al.musicbrainz_release_id::text AS album_mbid,
                   al.release_year, al.original_year, al.type::text AS type, al.edition, al.label,
                   al.country, al.catalog, al.barcode, al.genres, al.match_tier, al.match_ratio,
                   al.total_discs, al.total_tracks, al.duration_seconds, al.status::text AS status,
                   al.has_nfo, al.has_artwork, al.path
            FROM albums al
            JOIN artists ar ON ar.id = al.artist_id
            WHERE al.id = ANY(%s::uuid[])
            ORDER BY array_position(%s::uuid[], al.id)
            """,
            (ids, ids),
        )
        columns = MUSIC_COLUMNS
    else:
        raise AppError("Export works for movies, TV shows, movie sets, and music", 400)
    found = []
    for row in rows:
        item = _tracks(dict(row)) if media in ("movies", "tv") else dict(row)
        if isinstance(item.get("artwork"), dict):
            item["artwork"] = sorted(item["artwork"])
        if media not in ("movies", "tv") or _under(item.get("path") or "", roots):
            found.append(item)
    return columns, found


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


def to_csv(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in columns])
    return "\ufeff" + out.getvalue()


_XML_INVALID_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _clean_xml(val):
    if val is None:
        return ""
    return _XML_INVALID_CONTROL_CHARS.sub("", str(val))


def to_xml(media, columns, rows):
    root = ET.Element("curator_export", {"media": media, "exported": datetime.now().isoformat(timespec="seconds"),
                                         "count": str(len(rows))})
    tag = {"movies": "movie", "tv": "episode", "sets": "set", "music": "album"}.get(media, "item")
    for row in rows:
        item = ET.SubElement(root, tag)
        for column in columns:
            value = row.get(column)
            node = ET.SubElement(item, column)
            if isinstance(value, (list, tuple)):
                for entry in value:
                    ET.SubElement(node, "value").text = _clean_xml(entry)
            else:
                node.text = _clean_xml(_cell(value))
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def export(media, ids, fmt="csv", roots=None):
    """(filename, media type, body, row count) for a download."""
    if fmt not in ("csv", "xml"):
        raise AppError("Export as csv or xml", 400)
    columns, rows = export_rows(media, ids, roots)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"curator-{media}-{stamp}.{fmt}"
    if fmt == "csv":
        return name, "text/csv; charset=utf-8", to_csv(columns, rows), len(rows)
    return name, "application/xml; charset=utf-8", to_xml(media, columns, rows), len(rows)
