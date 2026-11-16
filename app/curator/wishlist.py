"""The upgrade wishlist: what falls short of the quality you want, and a way to ask the apps to search for it.

Targets are set per library under Settings, Files: a minimum resolution and optionally HDR for movies and TV, lossless
or hi-res for music. A title that already has a better copy in the library (Upgrade available) is left out, because the
upgrade is already on disk. Searching goes through the same ARR queue as every other search.
"""
from __future__ import annotations

from resonance import db
from resonance.errors import AppError

RESOLUTION_RANK = {"SD": 1, "720p": 2, "1080p": 3, "4K": 4, "8K": 5}
LOSSLESS = ("flac", "alac", "wav", "aiff", "aif", "ape", "wv", "dsd", "dsf", "dff")
SEARCH_LIMIT = 100


def targets():
    from curator.video import config

    cfg = config.current()
    return {
        "movies": {"resolution": cfg.get("wish_movie_resolution") or "", "hdr": bool(cfg.get("wish_movie_hdr"))},
        "tv": {"resolution": cfg.get("wish_tv_resolution") or "", "hdr": bool(cfg.get("wish_tv_hdr"))},
        "music": {"quality": cfg.get("wish_music") or ""},
    }


def video_shortfall(row, target):
    """Why this file falls short of the target, or "" when it meets it. An unprobed file is not judged."""
    if not row.get("resolution"):
        return ""
    wanted = target.get("resolution") or ""
    reasons = []
    if wanted and RESOLUTION_RANK.get(row["resolution"], 0) < RESOLUTION_RANK.get(wanted, 0):
        reasons.append(f"{row['resolution']}, wanted {wanted}")
    if target.get("hdr") and str(row.get("hdr_format") or "").lower() in {"", "sdr", "none"}:
        reasons.append("no HDR")
    return ", ".join(reasons)


def album_shortfall(row, wanted):
    if not wanted or not row.get("tracks"):
        return ""
    if not row.get("all_lossless"):
        return "not lossless"
    if wanted == "hires" and int(row.get("bit_depth") or 0) < 24:
        return f"{int(row.get('bit_depth') or 0) or 16}-bit, wanted 24-bit"
    return ""


def listing():
    wanted = targets()
    items = []
    if wanted["movies"]["resolution"] or wanted["movies"]["hdr"]:
        for row in db.fetchall(
            """
            SELECT m.id::text AS id, m.title, m.year, m.tmdb_id, m.path, f.resolution, f.hdr_format
            FROM movies m JOIN video_files f ON f.id = m.file_id
            WHERE NOT COALESCE(m.wanted, FALSE) AND m.upgrade_source_id IS NULL
            """
        ):
            reason = video_shortfall(row, wanted["movies"])
            if reason:
                label = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
                items.append({"kind": "movie", "id": row["id"], "label": label, "path": row["path"], "reason": reason,
                              "searchable": bool(row.get("tmdb_id"))})
    if wanted["tv"]["resolution"] or wanted["tv"]["hdr"]:
        shows = {}
        for row in db.fetchall(
            """
            SELECT e.id::text AS id, s.id::text AS show_id, s.title, s.path, s.tvdb_id, s.tmdb_id, f.resolution, f.hdr_format
            FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id JOIN video_files f ON f.id = e.file_id
            WHERE NOT e.missing AND e.upgrade_source_id IS NULL AND COALESCE(e.upgrade_copy_path, '') = ''
            """
        ):
            reason = video_shortfall(row, wanted["tv"])
            if reason:
                entry = shows.setdefault(row["show_id"], {
                    "kind": "show", "id": row["show_id"], "label": row["title"], "path": row["path"], "episodes": 0,
                    "reason": reason, "searchable": bool(row.get("tvdb_id") or row.get("tmdb_id"))})
                entry["episodes"] += 1
        for entry in shows.values():
            entry["reason"] = f"{entry['episodes']} episode{'s' if entry['episodes'] != 1 else ''}: {entry['reason']}"
            items.append(entry)
    music = wanted["music"]["quality"]
    if music:
        for row in db.fetchall(
            """
            SELECT al.id::text AS id, al.title, al.path, al.artist_id::text AS artist_id, ar.name AS artist_name,
                   al.musicbrainz_release_group_id::text AS release_group, al.release_year,
                   count(t.id)::int AS tracks, COALESCE(min(t.bit_depth), 0) AS bit_depth,
                   bool_and(lower(COALESCE(t.file_format, '')) = ANY(%s)) AS all_lossless
            FROM albums al JOIN artists ar ON ar.id = al.artist_id JOIN tracks t ON t.album_id = al.id
            WHERE al.upgrade_source_id IS NULL
            GROUP BY al.id, ar.name
            """,
            (list(LOSSLESS),),
        ):
            reason = album_shortfall(row, music)
            if reason:
                items.append({"kind": "album", "id": row["id"], "label": f"{row['artist_name']} — {row['title']}",
                              "path": row["path"], "reason": reason, "searchable": bool(row.get("release_group"))})
    items.sort(key=lambda item: (item["kind"], item["label"].casefold()))
    return {"targets": wanted, "items": items}


def search(items):
    """Queue a search per item. Returns how many were queued and why others were not."""
    from curator.arr_queue import enqueue, search_title
    from resonance import lidarr

    picked = list(items or [])[:SEARCH_LIMIT]
    if not picked:
        raise AppError("Pick something to search for", 400)
    queued, errors = 0, []
    if len(items or []) > SEARCH_LIMIT:
        errors.append(f"Only the first {SEARCH_LIMIT} items were searched. Search again for the rest.")
    movies = [str(item.get("id")) for item in picked if item.get("kind") == "movie"]
    if movies:
        rows = db.fetchall("SELECT title, tmdb_id FROM movies WHERE id = ANY(%s::uuid[]) AND COALESCE(tmdb_id, '') <> ''", (movies,))
        if rows:
            enqueue("radarr", search_title("radarr", [row["title"] for row in rows]), "radarr",
                    {"tmdb_ids": [row["tmdb_id"] for row in rows]})
            queued += len(rows)
    for item in picked:
        try:
            if item.get("kind") == "show":
                # Only what falls short, not the whole show.
                rows = _short_episodes(str(item.get("id")), targets()["tv"])
                # A show with more short episodes than one search holds is searched in several queue items, not cut short.
                for start in range(0, len(rows), SEARCH_LIMIT):
                    enqueue("sonarr", search_title("sonarr", [rows[0]["show_title"]]), "sonarr",
                            {"episodes": rows[start:start + SEARCH_LIMIT]})
                    queued += 1
            elif item.get("kind") == "album":
                row = db.fetchone(
                    "SELECT artist_id::text AS artist_id, title, release_year, musicbrainz_release_group_id::text AS release_group "
                    "FROM albums WHERE id = %s", (str(item.get("id")),))
                if row and row.get("release_group"):
                    lidarr.queue_releases(row["artist_id"], [{"release_group_id": row["release_group"], "title": row["title"],
                                                              "year": row.get("release_year") or "", "owned": True}])
                    queued += 1
                else:
                    errors.append(f"{item.get('label')}: needs a MusicBrainz id")
        except AppError as exc:
            errors.append(f"{item.get('label')}: {exc}")
    return {"queued": queued, "errors": errors}


def _short_episodes(show_id, target):
    rows = db.fetchall(
        """
        SELECT e.title, e.season_number, e.episode_number, s.tvdb_id, s.tmdb_id, s.title AS show_title, f.resolution, f.hdr_format
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id JOIN video_files f ON f.id = e.file_id
        WHERE e.show_id = %s AND NOT e.missing AND e.upgrade_source_id IS NULL
        ORDER BY e.season_number, e.episode_number
        """,
        (show_id,),
    )
    return [{key: row.get(key) for key in ("title", "season_number", "episode_number", "tvdb_id", "tmdb_id", "show_title")}
            for row in rows if video_shortfall(row, target)]
