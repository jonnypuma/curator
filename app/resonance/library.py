import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime

from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from resonance import completeness, db, tags
from resonance.errors import AppError
from resonance.fields import clean_text, contains_pattern, genre_name, mbid_list, normalize_track_update, opt_uuid, opt_uuid_loose, release_type
from resonance.paths import assert_readable

logger = logging.getLogger(__name__)

_progress_lock = threading.Lock()
_progress = {"phase": "idle", "done": 0, "total": 0, "label": "Filtering…"}


def note_filter(phase, done=0, total=0, label="Filtering…"):
    """Where a library filter is, so the loading screen can fill a bar."""
    with _progress_lock:
        _progress["phase"] = phase
        _progress["done"] = int(done or 0)
        _progress["total"] = int(total or 0)
        _progress["label"] = label


def filter_progress():
    with _progress_lock:
        return dict(_progress)


LIBRARY_FILTERS = {
    "all",
    "new",
    "missing-art",
    "missing-nfo",
    "nfo-changes",
    "missing-info",
    "missing-review",
    "gold",
    "silver",
    "unmatched",
    "incomplete",
    "missing-tracks",
    "duplicates",
    "upgrade",
    "prune-held",
    "locked",
    "case-folders",
    "missing-releases",
    "type-album",
    "type-ep",
    "type-single",
    "type-live",
    "type-compilation",
}

TYPE_FILTERS = {
    "type-album": "album",
    "type-ep": "ep",
    "type-single": "single",
    "type-live": "live",
    "type-compilation": "compilation",
}


_totals_cache = {"at": 0.0, "value": None}


def totals():
    now = time.monotonic()
    cached = _totals_cache["value"]
    if cached is not None and now - _totals_cache["at"] < 10:
        return cached
    row = db.fetchone(
        """
        SELECT
            (SELECT COUNT(*)::int FROM artists) AS artists,
            (SELECT COUNT(*)::int FROM albums) AS albums,
            (SELECT COUNT(*)::int FROM tracks) AS tracks,
            (SELECT COALESCE(SUM(file_size), 0)::bigint FROM tracks) AS bytes,
            (SELECT COALESCE(SUM(duration_seconds), 0)::bigint FROM tracks) AS seconds
        """
    )
    value = {
        "artists": int(row["artists"] or 0) if row else 0,
        "albums": int(row["albums"] or 0) if row else 0,
        "tracks": int(row["tracks"] or 0) if row else 0,
        "bytes": int(row["bytes"] or 0) if row and "bytes" in row else 0,
        "seconds": int(row["seconds"] or 0) if row and "seconds" in row else 0,
    }
    _totals_cache["at"] = now
    _totals_cache["value"] = value
    return value


_count_cache = {"at": 0.0, "value": None}


def filter_counts():
    """How many items each library preset currently matches. Cached for a short while."""
    now = time.monotonic()
    cached = _count_cache["value"]
    if cached is not None and now - _count_cache["at"] < 30:
        return cached
    row = db.fetchone(
        """
        SELECT
            (SELECT COUNT(*)::int FROM albums) AS all_count,
            (SELECT COUNT(*)::int FROM albums WHERE type = 'album') AS type_album,
            (SELECT COUNT(*)::int FROM albums WHERE type = 'ep') AS type_ep,
            (SELECT COUNT(*)::int FROM albums WHERE type = 'single') AS type_single,
            (SELECT COUNT(*)::int FROM albums WHERE type = 'live') AS type_live,
            (SELECT COUNT(*)::int FROM albums WHERE type = 'compilation') AS type_compilation,
            (SELECT COUNT(*)::int FROM albums WHERE status = 'NEW') AS new,
            (SELECT COUNT(*)::int FROM albums WHERE match_tier = 'gold') AS gold,
            (SELECT COUNT(*)::int FROM albums WHERE match_tier = 'silver') AS silver,
            (SELECT COUNT(*)::int FROM albums WHERE COALESCE(match_tier, 'unmatched') = 'unmatched') AS unmatched,
            (SELECT COUNT(*)::int FROM albums WHERE has_artwork = FALSE) AS missing_art,
            (SELECT COUNT(*)::int FROM albums WHERE has_nfo = FALSE) AS missing_nfo,
            (SELECT COUNT(*)::int FROM albums WHERE has_nfo AND COALESCE(nfo_digest, '') <> '') AS nfo_changes,
            (SELECT COUNT(DISTINCT album_id)::int FROM tracks WHERE COALESCE(tag_completeness_percent, 0) < 100) AS incomplete,
            (SELECT COUNT(*)::int FROM albums WHERE COALESCE(gap_expected, 0) > 0 AND COALESCE(gap_present, 0) < gap_expected) AS missing_tracks,
            (SELECT COUNT(*)::int FROM artists WHERE biography IS NULL OR btrim(biography) = '' OR sortname IS NULL OR btrim(sortname) = '' OR years_active IS NULL OR btrim(years_active) = '') AS missing_info,
            (SELECT COUNT(*)::int FROM albums WHERE review IS NULL OR btrim(review) = '') AS missing_review,
            (SELECT COUNT(*)::int FROM albums WHERE duplicate_release IS TRUE) AS duplicates,
            (SELECT COUNT(*)::int FROM albums WHERE upgrade_source_id IS NOT NULL) AS upgrade,
            (SELECT COUNT(*)::int FROM albums WHERE prune_held IS TRUE) AS prune_held,
            (SELECT COUNT(*)::int FROM albums al JOIN artists a ON a.id = al.artist_id WHERE al.locked IS TRUE OR a.locked IS TRUE) AS locked,
            (SELECT COUNT(*)::int FROM artists a WHERE a.path IS NOT NULL AND EXISTS (
                SELECT 1 FROM artists other
                WHERE other.id <> a.id AND other.path IS NOT NULL
                  AND lower(other.path) = lower(a.path) AND other.path IS DISTINCT FROM a.path
            )) AS case_folders,
            (SELECT COUNT(*)::int FROM artists WHERE discography IS NOT NULL AND discography <> '[]'::jsonb) AS missing_releases
        """
    ) or {}
    value = {
        "all": int(row.get("all_count") or 0),
        "type-album": int(row.get("type_album") or 0),
        "type-ep": int(row.get("type_ep") or 0),
        "type-single": int(row.get("type_single") or 0),
        "type-live": int(row.get("type_live") or 0),
        "type-compilation": int(row.get("type_compilation") or 0),
        "new": int(row.get("new") or 0),
        "gold": int(row.get("gold") or 0),
        "silver": int(row.get("silver") or 0),
        "unmatched": int(row.get("unmatched") or 0),
        "missing-art": int(row.get("missing_art") or 0),
        "missing-nfo": int(row.get("missing_nfo") or 0),
        "nfo-changes": int(row.get("nfo_changes") or 0),
        "incomplete": int(row.get("incomplete") or 0),
        "missing-tracks": int(row.get("missing_tracks") or 0),
        "missing-info": int(row.get("missing_info") or 0),
        "missing-review": int(row.get("missing_review") or 0),
        "duplicates": int(row.get("duplicates") or 0),
        "upgrade": int(row.get("upgrade") or 0),
        "prune-held": int(row.get("prune_held") or 0),
        "locked": int(row.get("locked") or 0),
        "case-folders": int(row.get("case_folders") or 0),
        "missing-releases": int(row.get("missing_releases") or 0),
    }
    _count_cache["at"] = now
    _count_cache["value"] = value
    return value


_LEADING_ARTICLE = re.compile(r"^(?:the|an|a)\s+", re.IGNORECASE)


def sort_ignore_the():
    """True when a leading The, A, or An is left out of the library sort. On unless turned off."""
    from resonance.settings import load

    return load().get("sort_ignore_the", True) is not False


def artist_sort_key(name, ignore_the=True):
    """Sort text for an artist. A leading The, A, or An is dropped when ignore_the is on."""
    text = str(name or "").strip()
    if ignore_the:
        stripped = _LEADING_ARTICLE.sub("", text).strip()
        if stripped:
            text = stripped
    return text.lower()


def library(filter_name="all", query=""):
    filter_name = filter_name if filter_name in LIBRARY_FILTERS else "all"
    clauses = []
    params = []
    # A library path that holds many artists is not an artist itself, so a row sitting on it
    # (left over from an earlier layout) is never listed.
    from resonance.paths import music_roots, path_kind

    many = [root.rstrip("/") for root in music_roots() if path_kind(root) != "artist"]
    if many:
        clauses.append("(a.path IS NULL OR rtrim(a.path, '/') <> ALL(%s))")
        params.append(many)
    if query:
        pattern = contains_pattern(query)
        clauses.append(
            """
            (
                a.name ILIKE %s ESCAPE '\\'
                OR EXISTS (
                    SELECT 1 FROM albums al
                    WHERE al.artist_id = a.id AND al.title ILIKE %s ESCAPE '\\'
                )
            )
            """
        )
        params.extend([pattern, pattern])
    if filter_name == "new":
        clauses.append(
            "(a.status = 'NEW' OR EXISTS (SELECT 1 FROM albums al WHERE al.artist_id = a.id AND al.status = 'NEW'))"
        )
    elif filter_name == "missing-art":
        clauses.append(
            "(a.has_artwork = FALSE OR EXISTS (SELECT 1 FROM albums al WHERE al.artist_id = a.id AND al.has_artwork = FALSE))"
        )
    elif filter_name == "missing-nfo":
        clauses.append(
            "(a.has_nfo = FALSE OR EXISTS (SELECT 1 FROM albums al WHERE al.artist_id = a.id AND al.has_nfo = FALSE))"
        )
    elif filter_name == "nfo-changes":
        clauses.append(
            """
            (
                (a.has_nfo AND COALESCE(a.nfo_digest, '') <> '')
                OR EXISTS (
                    SELECT 1 FROM albums al
                    WHERE al.artist_id = a.id
                      AND al.has_nfo
                      AND COALESCE(al.nfo_digest, '') <> ''
                )
            )
            """
        )
    elif filter_name == "missing-info":
        clauses.append(
            """
            (
                a.biography IS NULL OR btrim(a.biography) = ''
                OR a.sortname IS NULL OR btrim(a.sortname) = ''
                OR a.years_active IS NULL OR btrim(a.years_active) = ''
            )
            """
        )
    elif filter_name == "missing-review":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id
                  AND (al.review IS NULL OR btrim(al.review) = '')
            )
            """
        )
    elif filter_name == "missing-tracks":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id
                  AND COALESCE(al.gap_expected, 0) > 0
                  AND COALESCE(al.gap_present, 0) < al.gap_expected
            )
            """
        )
    elif filter_name == "duplicates":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id
                  AND al.musicbrainz_release_id IS NOT NULL
                  AND al.duplicate_release IS TRUE
            )
            """
        )
    elif filter_name == "prune-held":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id
                  AND al.prune_held IS TRUE
            )
            """
        )
    elif filter_name == "locked":
        clauses.append(
            "(a.locked IS TRUE OR EXISTS (SELECT 1 FROM albums al WHERE al.artist_id = a.id AND al.locked IS TRUE))"
        )
    elif filter_name == "upgrade":
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id
                  AND al.upgrade_source_id IS NOT NULL
            )
            """
        )
    elif filter_name == "case-folders":
        clauses.append(
            """
            a.path IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM artists other
                WHERE other.id <> a.id
                  AND other.path IS NOT NULL
                  AND lower(other.path) = lower(a.path)
                  AND other.path IS DISTINCT FROM a.path
            )
            """
        )
    elif filter_name == "missing-releases":
        clauses.append("a.discography IS NOT NULL AND a.discography <> '[]'::jsonb")
    elif filter_name in TYPE_FILTERS:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM albums al
                WHERE al.artist_id = a.id AND al.type = %s::release_type
            )
            """
        )
        params.append(TYPE_FILTERS[filter_name])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    discography_column = ", a.discography" if filter_name == "missing-releases" else ""
    note_filter("artists", label="Reading artists")
    t_start = time.monotonic()
    artists = db.fetchall(
        f"""
        SELECT a.id, a.name, a.status, a.locked, a.type, a.genres, a.musicbrainz_artist_id, a.path,
               a.has_nfo, a.has_artwork, a.artwork_width, a.artwork_height,
               a.formed, a.origin, a.years_active, a.website, a.discogs_url,
               a.wikipedia_url, a.created_at, a.updated_at{discography_column}
        FROM artists a
        {where}
        ORDER BY lower(a.name)
        """,
        params,
    )
    if not artists:
        note_filter("done", 1, 1, "Done")
        return []
    t_artists = time.monotonic()
    note_filter("albums", label="Reading albums")
    albums = db.fetchall(
        """
        SELECT albums.id, albums.artist_id, albums.title, albums.release_year,
               albums.total_discs, albums.total_tracks, albums.duration_seconds,
               albums.type, albums.edition, albums.status, albums.locked, albums.path,
               albums.has_nfo, albums.has_artwork, albums.artwork_width, albums.artwork_height,
               albums.musicbrainz_release_group_id, albums.musicbrainz_release_id,
               albums.match_tier, albums.match_ratio, albums.path_role, albums.quality_rank,
               albums.cue_image, albums.gap_present, albums.gap_expected, albums.country,
               albums.label, albums.catalog, albums.barcode, albums.release_status, albums.review,
               albums.upgrade_source_id, albums.duplicate_release, albums.prune_held, albums.original_year, albums.created_at, albums.updated_at,
               src.id AS upgrade_album_id,
               src.title AS upgrade_title,
               src.path AS upgrade_path,
               src.path_role AS upgrade_role,
               src.quality_rank AS upgrade_rank,
               src.type AS upgrade_type,
               src.edition AS upgrade_edition
        FROM albums
        LEFT JOIN albums AS src ON src.id = albums.upgrade_source_id
        WHERE albums.artist_id = ANY(%s::uuid[])
        ORDER BY COALESCE(albums.original_year, albums.release_year) NULLS LAST, lower(albums.title)
        """,
        (db.uuid_array([row["id"] for row in artists]),),
    )
    t_albums = time.monotonic()
    for album in albums:
        album["upgrade"] = _joined_upgrade(album)
    if filter_name == "nfo-changes":
        note_filter("nfo", 0, len(albums), "Checking album.nfo files")
        _attach_album_nfo_stale(albums, on_progress=lambda done, total: note_filter("nfo", done, total, "Checking album.nfo files"))
        _attach_artist_nfo_stale(artists)
    by_artist = {}
    for album in albums:
        by_artist.setdefault(str(album["artist_id"]), []).append(album)
    result = []
    # The same band listed once per library path: those entries carry the Duplicate pill.
    duplicate_names = {
        str(row["name"] or "").casefold()
        for row in db.fetchall(
            "SELECT lower(name) AS name FROM artists GROUP BY lower(name) HAVING count(*) > 1"
        )
    }
    seen_albums = 0
    album_total = len(albums)
    note_filter("matching", 0, album_total, "Filtering albums")
    for artist in artists:
        artist_hit = bool(query) and contains_hit(artist["name"], query)
        albums_out = []
        for album in by_artist.get(str(artist["id"]), []):
            seen_albums += 1
            if album_total and seen_albums % 400 == 0:
                note_filter("matching", seen_albums, album_total, "Filtering albums")
            title_hit = (not query) or query.lower() in (album["title"] or "").lower()
            if query and not artist_hit and not title_hit:
                continue
            if not _album_visible(album, filter_name) and not (filter_name == "locked" and artist.get("locked")):
                continue
            albums_out.append(_album_brief(album))
        missing = []
        if filter_name == "missing-releases":
            from resonance.discography import missing_studio

            missing = missing_studio(artist.get("discography") or [], by_artist.get(str(artist["id"]), []))
            if query and not artist_hit:
                needle = query.lower()
                missing = [row for row in missing if needle in (row["title"] or "").lower()]
            if not missing:
                continue
        elif not albums_out and not _artist_visible(artist, filter_name):
            continue
        if query and not artist_hit and not albums_out and not missing:
            continue
        payload = _artist_brief(artist)
        payload["duplicate"] = str(artist.get("name") or "").casefold() in duplicate_names
        payload["albums"] = albums_out
        if missing:
            payload["missing_releases"] = missing
        result.append(payload)
    note_filter("sort", album_total, album_total, "Sorting the list")
    ignore_the = sort_ignore_the()
    result.sort(key=lambda row: artist_sort_key(row.get("name"), ignore_the))
    note_filter("done", album_total, album_total or 1, "Done")
    t_end = time.monotonic()
    if t_end - t_start > 3.0:
        logging.getLogger(__name__).info(
            "library list: artists query %.1fs (%d), albums query %.1fs (%d), building the list %.1fs",
            t_artists - t_start, len(artists), t_albums - t_artists, len(albums), t_end - t_albums)
    return result


def clock():
    row = db.fetchone("SELECT clock_timestamp() AS now")
    return row["now"] if row else None


def changes(since):
    """Artists and albums updated after `since`, for a tree refresh during a scan."""
    moment = _since(since)
    as_of = clock()
    albums = db.fetchall(
        """
        SELECT albums.id, albums.artist_id, albums.title, albums.release_year,
               albums.total_discs, albums.total_tracks, albums.duration_seconds,
               albums.type, albums.edition, albums.status, albums.locked, albums.path,
               albums.has_nfo, albums.has_artwork, albums.artwork_width, albums.artwork_height,
               albums.musicbrainz_release_group_id, albums.musicbrainz_release_id,
               albums.match_tier, albums.match_ratio, albums.path_role, albums.quality_rank,
               albums.cue_image, albums.gap_present, albums.gap_expected, albums.country,
               albums.label, albums.catalog, albums.barcode, albums.release_status, albums.review,
               albums.upgrade_source_id, albums.duplicate_release, albums.prune_held, albums.original_year, albums.created_at, albums.updated_at,
               src.id AS upgrade_album_id,
               src.title AS upgrade_title,
               src.path AS upgrade_path,
               src.path_role AS upgrade_role,
               src.quality_rank AS upgrade_rank,
               src.type AS upgrade_type,
               src.edition AS upgrade_edition
        FROM albums
        LEFT JOIN albums AS src ON src.id = albums.upgrade_source_id
        WHERE albums.updated_at > %s AND albums.updated_at <= %s
        """,
        (moment, as_of),
    )
    for album in albums:
        album["upgrade"] = _joined_upgrade(album)
    _attach_album_nfo_stale(albums)
    artist_ids = {str(album["artist_id"]) for album in albums if album.get("artist_id")}
    artists = db.fetchall(
        """
        SELECT a.id, a.name, a.status, a.locked, a.type, a.genres, a.musicbrainz_artist_id, a.path,
               a.has_nfo, a.has_artwork, a.artwork_width, a.artwork_height,
               a.formed, a.origin, a.years_active, a.website, a.discogs_url,
               a.wikipedia_url, a.created_at, a.updated_at
        FROM artists a
        WHERE (a.updated_at > %s AND a.updated_at <= %s) OR a.id = ANY(%s::uuid[])
        """,
        (moment, as_of, db.uuid_array(artist_ids)),
    )
    return {
        "artists": [_artist_brief(artist) for artist in artists],
        "albums": [_album_brief(album) for album in albums],
        "as_of": as_of,
    }


def _since(value):
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AppError("since must be a timestamp") from exc
    if moment.tzinfo is None:
        raise AppError("since must include a timezone")
    return moment


def store_missing_release_fields():
    """Copy blank album release fields from tags already stored on tracks."""
    store_missing_countries()
    _fill_majority_text("label", "label")
    _fill_majority_text("catalog", "catalognumber")
    _fill_majority_text("barcode", "barcode")
    _fill_majority_text("release_status", "releasestatus")
    _fill_majority_text("release_status", "musicbrainz_albumstatus")
    _fill_majority_uuid("musicbrainz_release_group_id", "musicbrainz_releasegroupid")
    _fill_majority_uuid("musicbrainz_release_id", "musicbrainz_albumid")


def _fill_majority_text(column, tag_key):
    # One tag expression for SELECT, WHERE, and GROUP BY. Repeated placeholders
    # are different SQL expressions, so PostgreSQL rejects the selected tags value.
    db.execute(
        f"""
        UPDATE albums AS album
        SET {column} = picked.value
        FROM (
            SELECT album_id, value
            FROM (
                SELECT album_id,
                       value,
                       ROW_NUMBER() OVER (
                           PARTITION BY album_id
                           ORDER BY votes DESC, value
                       ) AS rank
                FROM (
                    SELECT album_id,
                           btrim(tags->>key.tag) AS value,
                           COUNT(*) AS votes
                    FROM tracks
                    CROSS JOIN (SELECT %s::text AS tag) AS key
                    WHERE COALESCE(btrim(tags->>key.tag), '') <> ''
                    GROUP BY album_id, value
                ) AS counted
            ) AS ranked
            WHERE rank = 1
        ) AS picked
        WHERE album.id = picked.album_id
          AND COALESCE(btrim(album.{column}), '') = ''
        """,
        (tag_key,),
    )


def _fill_majority_uuid(column, tag_key):
    # One tag expression for SELECT, WHERE, and GROUP BY. The same release id
    # may be stored on more than one album: those copies are duplicates.
    sql = f"""
        UPDATE albums AS album
        SET {column} = picked.value::uuid
        FROM (
            SELECT album_id, value
            FROM (
                SELECT album_id,
                       value,
                       ROW_NUMBER() OVER (
                           PARTITION BY album_id
                           ORDER BY votes DESC, value
                       ) AS rank
                FROM (
                    SELECT album_id,
                           lower(btrim(tags->>key.tag)) AS value,
                           COUNT(*) AS votes
                    FROM tracks
                    CROSS JOIN (SELECT %s::text AS tag) AS key
                    WHERE btrim(tags->>key.tag) ~* '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
                    GROUP BY album_id, value
                ) AS counted
            ) AS ranked
            WHERE rank = 1
        ) AS picked
        WHERE album.id = picked.album_id
          AND album.{column} IS NULL
        """
    try:
        db.execute(sql, (tag_key,))
    except UniqueViolation:
        if column == "musicbrainz_release_id":
            from resonance.db import allow_shared_release_ids

            allow_shared_release_ids()
            db.execute(sql, (tag_key,))
            return
        logger.info("%s is still unique; copying each tag id on its own", column)
        rows = db.fetchall(
            f"""
            SELECT album_id, value
            FROM (
                SELECT album_id,
                       value,
                       ROW_NUMBER() OVER (
                           PARTITION BY album_id
                           ORDER BY votes DESC, value
                       ) AS rank
                FROM (
                    SELECT tracks.album_id,
                           lower(btrim(tracks.tags->>key.tag)) AS value,
                           COUNT(*) AS votes
                    FROM tracks
                    JOIN albums ON albums.id = tracks.album_id
                    CROSS JOIN (SELECT %s::text AS tag) AS key
                    WHERE albums.{column} IS NULL
                      AND btrim(tracks.tags->>key.tag) ~* '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
                    GROUP BY tracks.album_id, value
                ) AS counted
            ) AS ranked
            WHERE rank = 1
            """,
            (tag_key,),
        )
        for row in rows:
            try:
                db.execute(
                    f"UPDATE albums SET {column} = %s::uuid WHERE id = %s AND {column} IS NULL",
                    (row["value"], row["album_id"]),
                )
            except UniqueViolation:
                logger.info("left %s blank; %s is already stored on another album", column, row["value"])


def store_missing_countries():
    """Fill a blank album country from tags already stored on its tracks. Used by a scan."""
    db.execute(
        """
        UPDATE albums AS album
        SET country = picked.country
        FROM (
            SELECT album_id, country
            FROM (
                SELECT album_id,
                       upper(btrim(tags->>'releasecountry')) AS country,
                       ROW_NUMBER() OVER (
                           PARTITION BY album_id
                           ORDER BY COUNT(*) DESC, upper(btrim(tags->>'releasecountry'))
                       ) AS rank
                FROM tracks
                WHERE COALESCE(btrim(tags->>'releasecountry'), '') <> ''
                GROUP BY album_id, upper(btrim(tags->>'releasecountry'))
            ) AS ranked
            WHERE rank = 1 AND length(country) <= 8
        ) AS picked
        WHERE album.id = picked.album_id
          AND COALESCE(btrim(album.country), '') = ''
        """
    )


def _joined_upgrade(album):
    source_id = album.get("upgrade_album_id")
    if not source_id:
        return None
    from resonance.quality import same_release_kind

    if not same_release_kind(album, {"type": album.get("upgrade_type"), "edition": album.get("upgrade_edition")}):
        return None
    return {
        "album_id": str(source_id),
        "title": album.get("upgrade_title"),
        "path": album.get("upgrade_path") or "",
        "path_role": album.get("upgrade_role") or "library",
        "quality_rank": int(album.get("upgrade_rank") or 0),
    }


def _stored_upgrade(album):
    source_id = album.get("upgrade_source_id")
    if not source_id:
        return None
    source = db.fetchone(
        """
        SELECT id, title, path, path_role, quality_rank, type, edition,
               (
                   SELECT tags->>'releasetype'
                   FROM tracks
                   WHERE album_id = albums.id
                     AND COALESCE(tags->>'releasetype', '') <> ''
                   ORDER BY disc_number, track_number
                   LIMIT 1
               ) AS release_type
        FROM albums
        WHERE id = %s
        """,
        (source_id,),
    )
    if not source:
        return None
    from resonance.quality import same_release_kind

    if not same_release_kind(album, source):
        return None
    return {
        "album_id": str(source["id"]),
        "title": source.get("title"),
        "path": source.get("path") or "",
        "path_role": source.get("path_role") or "library",
        "quality_rank": int(source.get("quality_rank") or 0),
    }


def _tag_countries(album_ids):
    """Most common embedded release country for albums that have none stored yet."""
    if not album_ids:
        return {}
    rows = db.fetchall(
        """
        SELECT album_id, upper(btrim(tags->>'releasecountry')) AS country, COUNT(*)::int AS votes
        FROM tracks
        WHERE album_id = ANY(%s::uuid[])
          AND COALESCE(btrim(tags->>'releasecountry'), '') <> ''
        GROUP BY album_id, upper(btrim(tags->>'releasecountry'))
        """,
        (db.uuid_array(album_ids),),
    )
    best = {}
    for row in rows:
        key = str(row["album_id"])
        votes = int(row["votes"] or 0)
        if key not in best or votes > best[key][0]:
            best[key] = (votes, row["country"] or "")
    return {key: value[1] for key, value in best.items()}


def _with_tag_country(album, tagged):
    if str(album.get("country") or "").strip():
        return album
    found = (tagged or {}).get(str(album["id"])) or ""
    if not found:
        return album
    copy = dict(album)
    copy["country"] = found
    return copy


def contains_hit(name, query):
    return query.lower() in (name or "").lower()


def _artist_visible(artist, filter_name):
    if filter_name in {"case-folders", "missing-releases"}:
        return True
    if filter_name in {"all", "gold", "silver", "unmatched", "incomplete", "missing-tracks", "duplicates", "upgrade", "prune-held"}:
        return filter_name == "all"
    if filter_name == "new":
        return artist["status"] == "NEW"
    if filter_name == "missing-art":
        return not artist["has_artwork"]
    if filter_name == "missing-nfo":
        return not artist["has_nfo"]
    if filter_name == "locked":
        return bool(artist.get("locked"))
    if filter_name == "nfo-changes":
        return bool(artist.get("nfo_stale"))
    if filter_name == "missing-info":
        return True
    if filter_name in TYPE_FILTERS:
        return False
    return True


def _album_visible(album, filter_name):
    tier = album.get("match_tier") or "unmatched"
    if filter_name == "gold":
        return tier == "gold"
    if filter_name == "silver":
        return tier == "silver"
    if filter_name == "unmatched":
        return tier == "unmatched"
    if filter_name == "incomplete":
        return _album_incomplete(album["id"])
    if filter_name == "missing-tracks":
        expected = int(album.get("gap_expected") or 0)
        present = int(album.get("gap_present") or 0)
        return expected > 0 and present < expected
    if filter_name == "missing-info":
        return True
    if filter_name == "missing-review":
        return not str(album.get("review") or "").strip()
    if filter_name == "duplicates":
        return bool(album.get("duplicate_release"))
    if filter_name == "upgrade":
        return bool(album.get("upgrade"))
    if filter_name == "prune-held":
        return bool(album.get("prune_held"))
    if filter_name == "locked":
        return bool(album.get("locked"))
    if filter_name == "case-folders":
        return True
    if filter_name == "missing-releases":
        return False
    if filter_name == "nfo-changes":
        return bool(album.get("nfo_stale"))
    if filter_name in TYPE_FILTERS:
        return str(album.get("type") or "") == TYPE_FILTERS[filter_name]
    return _artist_visible(
        {
            "status": album["status"],
            "has_artwork": album["has_artwork"],
            "has_nfo": album["has_nfo"],
        },
        filter_name,
    )


def _album_incomplete(album_id):
    row = db.fetchone(
        """
        SELECT 1 AS hit FROM tracks
        WHERE album_id = %s AND COALESCE(tag_completeness_percent, 0) < 100
        LIMIT 1
        """,
        (album_id,),
    )
    return bool(row)


def album_detail(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        """
        SELECT * FROM tracks
        WHERE album_id = %s
        ORDER BY disc_number, track_number
        """,
        (album_id,),
    )
    from resonance import gaps, nfo

    for track in tracks:
        release_type = str((track.get("tags") or {}).get("releasetype") or "").strip()
        if release_type:
            album["release_type"] = release_type
            break
    album["upgrade"] = _stored_upgrade(album)
    album_brief = _album_brief(album, full=True)
    album_brief["label_icons"] = _label_icons(album_brief.get("label"))
    payload = nfo.album_context(album, artist)
    digest = nfo.album_digest(payload, tracks)
    stale = nfo_is_stale("albums", album, digest)
    if stale:
        try:
            _name, text = nfo.read_text(album["path"], ("album.nfo", "folder.nfo"))
            changes = nfo.album_nfo_diff(text, payload, tracks).get("changes") or []
        except AppError:
            changes = ["missing"]
        stale = _clear_false_nfo("albums", album["id"], album.get("nfo_digest"), digest, changes)
    album_brief["nfo_stale"] = stale
    artist_brief = _artist_brief(artist) if artist else None
    if artist_brief is not None:
        digest = nfo.artist_digest(artist)
        stale = nfo_is_stale("artists", artist, digest)
        if stale:
            try:
                _name, text = nfo.read_text(artist["path"], ("artist.nfo", "folder.nfo"))
                changes = nfo.artist_nfo_diff(text, artist).get("changes") or []
            except AppError:
                changes = ["missing"]
            stale = _clear_false_nfo("artists", artist["id"], artist.get("nfo_digest"), digest, changes)
        artist_brief["nfo_stale"] = stale
        from resonance import artwork

        artist_brief["assets"] = artwork.artist_assets(artist["id"])
    detail = {
        "album": album_brief,
        "artist": artist_brief,
        "tracks": [_track_out(track) for track in tracks],
    }
    detail["gap"] = gaps.summary(album_id)
    asset_rows = db.fetchall(
        """
        SELECT DISTINCT asset_type
        FROM artwork_pool
        WHERE album_id = %s AND is_selected = TRUE
        """,
        (album_id,),
    )
    detail["assets"] = [row["asset_type"] for row in asset_rows]
    return detail


def _label_icons(label):
    """Logos from media/recordlabels for the album's label name."""
    from curator.video import brands

    names = [part.strip() for part in re.split(r"\s*(?:,|/|;|\s&\s)\s*", str(label or "")) if part.strip()]
    return brands.icons(names, "recordlabels")


def get_track(track_id):
    track = db.fetchone("SELECT * FROM tracks WHERE id = %s", (track_id,))
    if not track:
        raise AppError("Track not found", 404)
    return track


def _write_track_file(track_id, body):
    from resonance import undo
    from resonance.paths import assert_library_writable

    track = get_track(track_id)
    path = assert_readable(track["file_path"])
    assert_library_writable(path)
    normalized = normalize_track_update(body, track.get("tags") or {})
    before, _info = tags.read_easy(path)
    skipped = tags.write_easy(path, normalized["file_map"])
    undo.snapshot_tags(track["id"], path, before)
    raw, _info = tags.read_easy(path)
    columns = completeness.columns_from_tags(raw)
    if columns["track_number"] < 1:
        columns["track_number"] = normalized["columns"].get("track_number") or track["track_number"]
    if columns["disc_number"] < 1:
        columns["disc_number"] = normalized["columns"].get("disc_number") or track["disc_number"]
    return track, columns, columns["tags"], skipped, path


def save_track_edits(items):
    """Write tag edits, then store every disc and track number in one step.

    Each number is unique on the album. Saving one song at a time rejects a
    number another song still holds, even when that song is about to move.
    """
    from resonance import undo
    from resonance.match import _store_written_indexes

    edits = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {
            key: value for key, value in item.items() if key != "id"
        }
        edits.append((str(require_uuid(item["id"])), fields))
    if not edits:
        raise AppError("Choose the tracks to save")
    undo.hold()
    written = []
    warnings = []
    paths = []
    album_ids = []
    try:
        for track_id, fields in edits:
            track, columns, stored, skipped, path = _write_track_file(track_id, fields)
            written.append((track, columns, stored))
            paths.append(path)
            album_ids.append(track["album_id"])
            if skipped:
                title = track.get("title") or "Track"
                warnings.append(f"{title} did not store: {', '.join(skipped)}")
        _store_written_indexes(written, warnings)
        seen = []
        for album_id in album_ids:
            if album_id in seen:
                continue
            seen.append(album_id)
            db.execute("UPDATE albums SET updated_at = NOW() WHERE id = %s", (album_id,))
            completeness.recompute_album(album_id)
    finally:
        undo.release()
    for path in paths:
        try:
            from resonance import pictures

            pictures.embed_track(path)
        except Exception:
            pass
    try:
        from resonance import webhooks

        webhooks.fire("tags")
    except Exception:
        pass
    warnings = [item for item in warnings if "collided" not in item]
    tracks = [_track_out(get_track(track["id"])) for track, _columns, _stored in written]
    return {"saved": len(tracks), "tracks": tracks, "warnings": warnings}


def update_track(track_id, body):
    result = save_track_edits([{"id": track_id, "fields": body}])
    return {"track": result["tracks"][0], "warnings": result["warnings"]}


def update_tracks(track_ids, fields, numbers=None):
    from resonance.fields import clean_text, leading_int, year_from

    ids = [str(require_uuid(item)) for item in track_ids or []]
    if numbers is not None:
        return _renumber_tracks(ids, numbers)
    if len(ids) < 2:
        raise AppError("Select at least two tracks")
    allowed = {}
    if "year" in fields and str(fields.get("year") or "").strip():
        year = year_from(fields.get("year"))
        if year is None:
            raise AppError("Year must be a four-digit year")
        allowed["year"] = year
    if "genre" in fields and str(fields.get("genre") or "").strip():
        allowed["genre"] = clean_text(fields.get("genre"), 255)
    if "albumartist" in fields and str(fields.get("albumartist") or "").strip():
        allowed["albumartist"] = clean_text(fields.get("albumartist"), 255)
    if "disc_number" in fields and str(fields.get("disc_number") or "").strip():
        number = leading_int(fields.get("disc_number"), None)
        if not number or number < 1:
            raise AppError("Disc number must be 1 or greater")
        allowed["disc_number"] = number
    if not allowed:
        raise AppError("Enter a year, genre, album artist, or disc number")
    edits = []
    for track_id in ids:
        current = get_track(track_id)
        body = {}
        if "year" in allowed:
            body["year"] = allowed["year"]
        if "genre" in allowed:
            body["genre"] = allowed["genre"]
        if "albumartist" in allowed:
            body["albumartist"] = allowed["albumartist"]
        if "disc_number" in allowed:
            body["disc_number"] = allowed["disc_number"]
            body["track_number"] = current["track_number"]
        edits.append({"id": track_id, "fields": body})
    return {"tracks": save_track_edits(edits)["tracks"]}


def _renumber_tracks(ids, numbers):
    from resonance.fields import leading_int
    from resonance import undo

    if len(ids) < 2:
        raise AppError("Select at least two tracks")
    if not isinstance(numbers, list) or len(numbers) != len(ids):
        raise AppError("Choose the tracks to number")
    parsed = []
    for raw in numbers:
        number = leading_int(raw, None)
        if not number or number < 1:
            raise AppError("Track number must be 1 or greater")
        parsed.append(number)
    undo.hold()
    updated = []
    try:
        for index, track_id in enumerate(ids):
            db.execute(
                "UPDATE tracks SET track_number = %s WHERE id = %s",
                (50000 + index + 1, track_id),
            )
        for track_id, number in zip(ids, parsed):
            updated.append(update_track(track_id, {"track_number": number})["track"])
        return {"tracks": updated}
    finally:
        undo.release()


def compilation_albumartist(folder_name):
    folder = folder_name or ""
    lowered = folder.lower()
    if "soundtrack" in lowered or lowered in {"score", "ost"}:
        return folder
    return "Various Artists"


def treat_compilation(album_id, enabled=True):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    albumartist = compilation_albumartist((artist or {}).get("name") or "")
    if not enabled:
        db.execute("UPDATE albums SET type = 'album'::release_type, updated_at = NOW() WHERE id = %s", (album_id,))
        return album_detail(album_id)
    db.execute(
        "UPDATE albums SET type = 'compilation'::release_type, updated_at = NOW() WHERE id = %s",
        (album_id,),
    )
    from resonance import undo

    tracks = db.fetchall("SELECT id FROM tracks WHERE album_id = %s", (album_id,))
    undo.hold()
    try:
        for track in tracks:
            update_track(track["id"], {"albumartist": albumartist})
        return album_detail(album_id)
    finally:
        undo.release()


def group_compilation(album_ids):
    ids = [str(require_uuid(item)) for item in album_ids or []]
    if len(ids) < 2:
        raise AppError("Select at least two albums")
    albums = db.fetchall("SELECT * FROM albums WHERE id = ANY(%s::uuid[])", (db.uuid_array(ids),))
    if len(albums) < 2:
        raise AppError("Select at least two albums")
    titles = {str(item["title"] or "").strip().lower() for item in albums}
    if len(titles) != 1:
        raise AppError("Selected albums need the same album title")
    primary = albums[0]
    for other in albums[1:]:
        db.execute("UPDATE tracks SET album_id = %s WHERE album_id = %s", (primary["id"], other["id"]))
        db.execute("DELETE FROM albums WHERE id = %s", (other["id"],))
    db.execute(
        "UPDATE albums SET type = 'compilation'::release_type, updated_at = NOW() WHERE id = %s",
        (primary["id"],),
    )
    return treat_compilation(primary["id"], True)


def nfo_is_stale(table, row, digest):
    """True when an nfo file exists and its last write does not match the database.

    The first time an existing file is seen, the current database is recorded as
    the baseline so the library does not all turn purple at once.
    """
    if table not in {"artists", "albums"} or not row or not row.get("has_nfo"):
        return False
    stored = row.get("nfo_digest") or ""
    if not stored:
        db.execute(
            f"UPDATE {table} SET nfo_digest = %s WHERE id = %s AND (nfo_digest IS NULL OR nfo_digest = '')",
            (digest, row["id"]),
        )
        return False
    return stored != digest


def _clear_false_nfo(table, row_id, stored, current, changes):
    """A fingerprint can move when the visible file did not. Keep the file clear."""
    if not stored or stored == current:
        return False
    if changes:
        return True
    db.execute(f"UPDATE {table} SET nfo_digest = %s WHERE id = %s", (current, row_id))
    return False


_MUSIC_KEEP = {
    "artist": {
        "biography": "text",
        "name": "text",
        "sortname": "text",
        "type": "text",
        "gender": "text",
        "disambiguation": "text",
        "genres": "list",
        "style": "text",
        "mood": "text",
        "years_active": "text",
        "instruments": "text",
        "born": "text",
        "formed": "text",
        "disbanded": "text",
        "website": "text",
        "discogs_url": "text",
        "wikipedia_url": "text",
        "musicbrainz_artist_id": "text",
    },
    "album": {
        "title": "text",
        "release_year": "year",
        "type": "text",
        "release_status": "text",
        "label": "text",
        "catalog": "text",
        "barcode": "text",
        "country": "text",
        "review": "text",
        "style": "text",
        "mood": "text",
        "theme": "text",
        "genres": "list",
        "allmusic_url": "text",
        "musicbrainz_release_id": "text",
        "musicbrainz_release_group_id": "text",
    },
}

_ALBUM_FILE_KEYS = {
    "biography": "artist_biography",
    "name": "artist_name",
    "musicbrainz_artist_id": "artist_mbid",
}


def keep_music_field(kind, item_id, field, from_kind="", from_id=""):
    """Copy one album.nfo or artist.nfo value into the database and leave the file alone."""
    from resonance import nfo

    table = {"artist": "artists", "album": "albums"}.get(kind)
    columns = _MUSIC_KEEP.get(kind) or {}
    if not table or field not in columns:
        raise AppError("That field stays in the .nfo", 400)
    row = db.fetchone(f"SELECT * FROM {table} WHERE id = %s", (item_id,))
    if not row:
        raise AppError("That item is not in the library any more", 404)
    if row.get("locked"):
        raise AppError("This item is locked. Unlock it to keep the .nfo value.", 409)
    source_kind = from_kind if from_kind in {"artist", "album"} else kind
    source_id = from_id or item_id
    value = _music_file_value(source_kind, source_id, field)
    stored = _coerce_nfo_value(columns[field], value)
    if kind == "artist" and field == "biography":
        db.execute(
            """
            UPDATE artists
            SET biography = %s, biography_custom = TRUE, biography_checked_at = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (stored, item_id),
        )
    elif kind == "artist" and field == "genres":
        db.execute(
            """
            UPDATE artists
            SET genres = %s::text[], genres_custom = TRUE, genres_from_tags = FALSE, updated_at = NOW()
            WHERE id = %s
            """,
            (db.text_array(stored), item_id),
        )
    elif columns[field] == "list":
        db.execute(
            f"UPDATE {table} SET {field} = %s::text[], updated_at = NOW() WHERE id = %s",
            (db.text_array(stored), item_id),
        )
    elif kind == "album" and field == "type":
        db.execute(
            "UPDATE albums SET type = %s::release_type, updated_at = NOW() WHERE id = %s",
            (stored, item_id),
        )
    else:
        db.execute(
            f"UPDATE {table} SET {field} = %s, updated_at = NOW() WHERE id = %s",
            (stored, item_id),
        )
    if kind == "artist":
        read_artist_nfo(item_id)
    else:
        read_album_nfo(item_id)
    if source_kind == "album" and source_id and str(source_id) != str(item_id):
        read_album_nfo(source_id)
    return {"ok": True}


def _music_file_value(kind, item_id, field):
    from resonance import nfo

    if kind == "album":
        album = db.fetchone("SELECT * FROM albums WHERE id = %s", (item_id,))
        if not album:
            raise AppError("Album not found", 404)
        _name, text = nfo.read_text(album["path"], ("album.nfo", "folder.nfo"))
        parsed = nfo._parse_album_nfo(text)
        key = _ALBUM_FILE_KEYS.get(field, field)
    else:
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (item_id,))
        if not artist:
            raise AppError("Artist not found", 404)
        _name, text = nfo.read_text(artist["path"], ("artist.nfo", "folder.nfo"))
        parsed = nfo._parse_artist_nfo(text)
        key = field
    if not text or parsed is None:
        raise AppError("No .nfo file for this item", 404)
    if key not in parsed:
        raise AppError("That field is not in the .nfo", 400)
    return parsed.get(key) or ""


def _coerce_nfo_value(kind, value):
    if kind == "list":
        return [part.strip() for part in str(value or "").split(",") if part.strip()]
    if kind == "year":
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return int(digits[:4]) if len(digits) >= 4 else None
    text = str(value or "").strip()
    return text or None


def read_artist_nfo(artist_id):
    from resonance import nfo

    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    name, text = nfo.read_text(artist["path"], ("artist.nfo", "folder.nfo"))
    digest = nfo.artist_digest(artist)
    diff = nfo.artist_nfo_diff(text, artist)
    return {
        "name": name,
        "text": text,
        "stale": _clear_false_nfo("artists", artist["id"], artist.get("nfo_digest"), digest, diff.get("changes") or []),
        "diff": diff,
    }


def read_album_nfo(album_id):
    from resonance import nfo

    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    payload = nfo.album_context(album, artist)
    name, text = nfo.read_text(album["path"], ("album.nfo", "folder.nfo"))
    digest = nfo.album_digest(payload, tracks)
    diff = nfo.album_nfo_diff(text, payload, tracks)
    return {
        "name": name,
        "text": text,
        "stale": _clear_false_nfo("albums", album["id"], album.get("nfo_digest"), digest, diff.get("changes") or []),
        "diff": diff,
    }


def artist_detail(artist_id):
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    albums = db.fetchall(
        """
        SELECT * FROM albums
        WHERE artist_id = %s
        ORDER BY COALESCE(original_year, release_year) NULLS LAST, lower(title)
        """,
        (artist_id,),
    )
    from resonance import artwork, nfo

    brief = _artist_brief(artist)
    brief["assets"] = artwork.artist_assets(artist["id"])
    digest = nfo.artist_digest(artist)
    stale = nfo_is_stale("artists", artist, digest)
    if stale:
        try:
            _name, text = nfo.read_text(artist["path"], ("artist.nfo", "folder.nfo"))
            changes = nfo.artist_nfo_diff(text, artist).get("changes") or []
        except AppError:
            changes = ["missing"]
        stale = _clear_false_nfo("artists", artist["id"], artist.get("nfo_digest"), digest, changes)
    brief["nfo_stale"] = stale
    return {"artist": brief, "albums": [_album_brief(album) for album in albums]}


def write_artist_nfo(artist_id):
    from resonance import nfo
    from resonance.settings import load as load_settings

    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    cfg = load_settings()
    payload = dict(artist)
    path = nfo.write_artist(artist["path"], cfg["nfo_profile"], payload, cfg["nfo_dialect"], cfg["nfo_backup"])
    db.execute(
        "UPDATE artists SET has_nfo = TRUE, nfo_digest = %s, updated_at = NOW() WHERE id = %s",
        (nfo.artist_digest(payload), artist_id),
    )
    return {"path": path, "artist": _artist_brief(db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,)))}


_ARTIST_PROFILE = {
    "type": 50,
    "sortname": 255,
    "gender": 40,
    "disambiguation": 255,
    "formed": 80,
    "origin": 255,
    "years_active": 255,
    "died": 80,
    "disbanded": 80,
    "website": 500,
    "discogs_url": 500,
    "wikipedia_url": 500,
    "style": 500,
    "mood": 500,
    "instruments": 500,
}


def _genre_list(values):
    names = []
    for item in values or []:
        text = genre_name(item)
        if text and text.lower() not in {name.lower() for name in names}:
            names.append(text)
    return names


def _optional_mbid(value, label):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = opt_uuid_loose(text)
    if not parsed:
        raise AppError(f"{label} must be a MusicBrainz id")
    return parsed


def store_artist_fields(artist_id, body):
    """Write the artist.nfo fields onto the artist row. Does not touch the nfo file."""
    artist_id = require_uuid(artist_id)
    body = body or {}
    current = db.fetchone("SELECT genres, type, musicbrainz_artist_id FROM artists WHERE id = %s", (artist_id,))
    new_genres = _genre_list(body.get("genres"))
    old_genres = _genre_list((current or {}).get("genres"))
    assignments = ["genres = %s::text[]"]
    params = [db.text_array(new_genres)]
    if [item.lower() for item in new_genres] != [item.lower() for item in old_genres]:
        assignments.append("genres_custom = TRUE")
        assignments.append("genres_from_tags = FALSE")
    for key, limit in _ARTIST_PROFILE.items():
        if key not in body:
            continue
        value = clean_text(body.get(key), limit)
        if key == "type" and not value:
            value = "Group"
        if key == "type":
            stored_type = clean_text((current or {}).get("type"), limit) or ""
            if value != stored_type:
                assignments.append("type_custom = TRUE")
        assignments.append(f"{key} = %s")
        params.append(value)
    if "musicbrainz_artist_id" in body:
        mbid = _optional_mbid(body.get("musicbrainz_artist_id"), "MusicBrainz artist id")
        assignments.append("musicbrainz_artist_id = %s")
        params.append(mbid)
        previous = str((current or {}).get("musicbrainz_artist_id") or "")
        if previous != str(mbid or ""):
            assignments.append("discography = '[]'::jsonb")
            assignments.append("discography_fetched_at = NULL")
    params.append(artist_id)
    try:
        if "musicbrainz_artist_id" in body and _optional_mbid(body.get("musicbrainz_artist_id"), "MusicBrainz artist id"):
            if db.artist_mbid_blocked(
                _optional_mbid(body.get("musicbrainz_artist_id"), "MusicBrainz artist id"),
                (current or {}).get("name"), artist_id,
            ):
                raise UniqueViolation()
        db.execute(
            f"UPDATE artists SET {', '.join(assignments)}, updated_at = NOW() WHERE id = %s",
            tuple(params),
        )
    except UniqueViolation:
        mbid = _optional_mbid(body.get("musicbrainz_artist_id"), "MusicBrainz artist id")
        other = db.fetchone("SELECT * FROM artists WHERE musicbrainz_artist_id = %s", (mbid,)) if mbid else None
        current = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
        error = AppError("That MusicBrainz artist id is already used by another artist", 409)
        error.conflict = {
            "conflict": "musicbrainz_artist_id",
            "current": _artist_merge_card(current),
            "other": _artist_merge_card(other),
        }
        raise error


def _artist_merge_card(row):
    if not row:
        return {}
    count = db.fetchone("SELECT COUNT(*)::int AS total FROM albums WHERE artist_id = %s", (row["id"],))
    return {
        "id": str(row["id"]),
        "name": row.get("name") or "",
        "path": row.get("path") or "",
        "album_count": count["total"] if count else 0,
        "has_mbid": bool(row.get("musicbrainz_artist_id")),
    }


def artist_candidates(artist_id, query):
    """Other library artists whose name or folder matches the search."""
    artist_id = require_uuid(artist_id)
    text = " ".join(str(query or "").split())
    if len(text) < 1:
        return []
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    rows = db.fetchall(
        """
        SELECT a.id, a.name, a.path, a.musicbrainz_artist_id,
               (SELECT COUNT(*)::int FROM albums al WHERE al.artist_id = a.id) AS album_count
        FROM artists a
        WHERE a.id <> %s
          AND (a.name ILIKE %s ESCAPE '\\' OR a.path ILIKE %s ESCAPE '\\')
        ORDER BY lower(a.name), a.path
        LIMIT 25
        """,
        (artist_id, like, like),
    )
    return [
        {
            "id": str(row["id"]),
            "name": row.get("name") or "",
            "path": row.get("path") or "",
            "album_count": row.get("album_count") or 0,
            "has_mbid": bool(row.get("musicbrainz_artist_id")),
        }
        for row in rows
    ]


def merge_preview(keep_id, drop_id, move_folders=True, remove_empty=False):
    """Describe the folders a merge would move, without changing anything."""
    keep_id = require_uuid(keep_id)
    drop_id = require_uuid(drop_id)
    if str(keep_id) == str(drop_id):
        raise AppError("Choose two different artists")
    keep = db.fetchone("SELECT id, name, path FROM artists WHERE id = %s", (keep_id,))
    drop = db.fetchone("SELECT id, name, path FROM artists WHERE id = %s", (drop_id,))
    if not keep or not drop:
        raise AppError("Artist not found", 404)
    albums = db.fetchall(
        "SELECT id, title, path FROM albums WHERE artist_id = %s ORDER BY path",
        (drop_id,),
    )
    kept_albums = db.fetchall(
        "SELECT id, title, path FROM albums WHERE artist_id = %s",
        (keep_id,),
    )
    return merge_plan(
        keep, drop, albums,
        move_folders=move_folders,
        remove_empty=remove_empty,
        kept_albums=kept_albums,
    )


def _free_folder(parent, name, reserved):
    """A folder name under parent that is not on disk and not already reserved."""
    number = 2
    while number < 100:
        candidate = f"{name} ({number})"
        dest = os.path.normpath(os.path.join(parent, candidate))
        if not os.path.exists(dest) and os.path.normcase(dest) not in reserved:
            return candidate, dest
        number += 1
    raise AppError(f"No free folder name for {name}.")


def merge_plan(keep, drop, albums, move_folders=True, remove_empty=False, kept_albums=None):
    """The folder moves and the note shown before a merge is confirmed."""
    keep_path = (keep or {}).get("path") or ""
    drop_path = (drop or {}).get("path") or ""
    same = same_directory(drop_path, keep_path)
    moves = []
    stays = []
    conflicts = []
    reserved = set()
    kept_by_path = {}
    for row in kept_albums or []:
        path = os.path.normpath(row.get("path") or "")
        if not path:
            continue
        key = os.path.normcase(path)
        reserved.add(key)
        kept_by_path[key] = row
    artist_root = os.path.normpath(drop_path) if drop_path else ""
    keep_name = (keep or {}).get("name") or "The master artist"
    for album in albums or []:
        old = os.path.normpath(album.get("path") or "")
        title = album.get("title") or "Album"
        album_id = str(album.get("id") or "")
        if not move_folders or same or (artist_root and os.path.normcase(old) == os.path.normcase(artist_root)):
            stays.append({"album_id": album_id, "title": title, "path": old})
            continue
        name = os.path.basename(old.rstrip(os.sep)) or "album"
        dest = os.path.normpath(os.path.join(keep_path, name))
        key = os.path.normcase(dest)
        if os.path.exists(dest):
            duplicate_name, duplicate_dest = _free_folder(keep_path, name, reserved)
            existing = kept_by_path.get(key) or {}
            conflicts.append({
                "album_id": album_id,
                "title": title,
                "name": name,
                "source": old,
                "dest": dest,
                "message": f"{keep_name} already has a folder named {name}.",
                "existing_album_id": str(existing.get("id") or ""),
                "existing_title": existing.get("title") or "",
                "duplicate_name": duplicate_name,
                "duplicate_dest": duplicate_dest,
            })
            reserved.add(key)
            reserved.add(os.path.normcase(duplicate_dest))
            continue
        renamed = False
        if key in reserved:
            name, dest = _free_folder(keep_path, name, reserved)
            renamed = True
        reserved.add(os.path.normcase(dest))
        moves.append({
            "album_id": album_id,
            "title": title,
            "source": old,
            "dest": dest,
            "name": name,
            "renamed": renamed,
        })
    lines = []
    if same:
        shown = keep_path or drop_path or "the artist folder"
        lines.append(f"Both artists use the same folder ({shown}), so nothing will be moved and that folder will not be deleted.")
    elif not move_folders:
        lines.append("Album folders will stay where they are.")
    elif moves:
        noun = "album folder" if len(moves) == 1 else "album folders"
        lines.append(f"{len(moves)} {noun} will move from {drop_path} into {keep_path}.")
        names = ", ".join(item["title"] for item in moves[:8])
        extra = len(moves) - 8
        if extra > 0:
            names += f", and {extra} more"
        lines.append(f"{names}.")
        renamed = [item["title"] for item in moves if item.get("renamed")]
        if renamed:
            shown = ", ".join(renamed[:8])
            lines.append(f"{shown} will use a new folder name so it does not overwrite another album being moved.")
        if stays:
            held = "album stays" if len(stays) == 1 else "albums stay"
            lines.append(f"{len(stays)} {held} in the artist folder and will not be moved.")
    elif conflicts:
        noun = "album folder already exists" if len(conflicts) == 1 else "album folders already exist"
        lines.append(f"{len(conflicts)} {noun} in the artist you keep.")
    else:
        lines.append("No album folders will move.")
    if conflicts:
        for conflict in conflicts:
            lines.append(conflict["message"])
        lines.append("Choose which copy to keep, or keep both.")
    if same:
        pass
    elif remove_empty:
        lines.append("The other artist folder will be deleted only when no audio files are left in it.")
    else:
        lines.append("The other artist folder will be left on disk.")
    return {
        "same_folder": same,
        "moves": moves,
        "stays": stays,
        "conflicts": conflicts,
        "lines": lines,
        "summary": " ".join(lines),
    }


def _check_merge_choices(plan, folder_choices):
    """Refuse a merge that would overwrite a folder the user has not decided on."""
    chosen = {str(key): str(value or "") for key, value in (folder_choices or {}).items()}
    for conflict in (plan or {}).get("conflicts") or []:
        action = chosen.get(str(conflict.get("album_id") or ""))
        message = conflict.get("message") or "That artist already has this album folder."
        if action not in {"both", "keep-existing", "keep-incoming"}:
            raise AppError(message)
        if action == "keep-incoming" and not conflict.get("existing_album_id"):
            raise AppError(
                f"{message} That folder is not an album in the library, so keep both copies or leave the folders where they are."
            )


def merge_artists(keep_id, drop_id, move_folders=True, remove_empty=False, folder_choices=None):
    """Move the other artist's albums under the master and keep one MusicBrainz id.

    move_folders copies album directories onto the master's folder. Leave it off
    to keep both folders on disk and remember the extra folder for later scans.
    remove_empty deletes the other artist folder only when no audio files remain.
    folder_choices says what to do when the master already has that album folder:
    both keeps a renamed copy, keep-existing deletes the incoming folder, and
    keep-incoming deletes the folder already there.
    """
    from resonance.paths import mount_writable

    keep_id = require_uuid(keep_id)
    drop_id = require_uuid(drop_id)
    if str(keep_id) == str(drop_id):
        raise AppError("Choose two different artists")
    keep = db.fetchone("SELECT * FROM artists WHERE id = %s", (keep_id,))
    drop = db.fetchone("SELECT * FROM artists WHERE id = %s", (drop_id,))
    if not keep or not drop:
        raise AppError("Artist not found", 404)
    albums = db.fetchall("SELECT * FROM albums WHERE artist_id = %s ORDER BY path", (drop_id,))
    kept_albums = db.fetchall("SELECT id, title, path FROM albums WHERE artist_id = %s", (keep_id,))
    plan = merge_plan(
        keep, drop, albums,
        move_folders=move_folders,
        remove_empty=remove_empty,
        kept_albums=kept_albums,
    )
    _check_merge_choices(plan, folder_choices)
    warnings = []
    if plan["same_folder"] and move_folders:
        warnings.append("Both artists use the same folder, so nothing was moved.")
    by_id = {str(album["id"]): album for album in albums}
    chosen = {str(key): str(value or "") for key, value in (folder_choices or {}).items()}
    artist_root = os.path.normpath(drop.get("path") or "")

    def reassign(album):
        db.execute(
            "UPDATE albums SET artist_id = %s, updated_at = NOW() WHERE id = %s",
            (keep_id, album["id"]),
        )

    def relocate(album, dest):
        old = os.path.normpath(album["path"])
        if os.path.normcase(old) == os.path.normcase(dest):
            return
        if not mount_writable(old) or not mount_writable(keep["path"]):
            raise AppError("The music folder is mounted read-only, so the albums cannot be moved.")
        if os.path.exists(dest):
            name = os.path.basename(dest.rstrip(os.sep)) or "album"
            raise AppError(f"{keep.get('name') or 'The master artist'} already has a folder named {name}.")
        shutil.move(old, dest)
        _retarget_album_path(album["id"], old, dest)

    for item in plan["stays"]:
        album = by_id.get(item.get("album_id") or "")
        if not album:
            continue
        reassign(album)
        old = os.path.normpath(album["path"])
        if move_folders and artist_root and os.path.normcase(old) == os.path.normcase(artist_root):
            warnings.append(f"{album.get('title') or 'Album'} stays in the artist folder and was not moved.")
    for item in plan["moves"]:
        album = by_id.get(item.get("album_id") or "")
        if not album:
            continue
        relocate(album, item["dest"])
        reassign(album)
        if item.get("renamed"):
            warnings.append(f"{item.get('title') or 'Album'} was kept as {item.get('name')}.")
    for item in plan["conflicts"]:
        album = by_id.get(item.get("album_id") or "")
        if not album:
            continue
        action = chosen.get(str(item.get("album_id") or ""))
        title = item.get("title") or "Album"
        if action == "keep-existing":
            from resonance.upgrade import discard
            discard(album["id"])
            warnings.append(f"{title} was deleted so the existing folder named {item.get('name')} could stay.")
            continue
        if action == "keep-incoming":
            from resonance.upgrade import discard
            discard(item["existing_album_id"])
            relocate(album, item["dest"])
            reassign(album)
            warnings.append(f"The folder named {item.get('name')} was replaced by the incoming copy of {title}.")
            continue
        relocate(album, item["duplicate_dest"])
        reassign(album)
        warnings.append(f"{title} was kept as {item.get('duplicate_name')} so both copies remain.")
    folder_left = False
    if remove_empty:
        reason = _remove_merged_folder(drop.get("path"), keep.get("path"))
        if reason:
            warnings.append(reason)
            folder_left = True
    if not move_folders or folder_left:
        _remember_artist_folders(keep, drop)
    db.execute("UPDATE artwork_pool SET artist_id = %s WHERE artist_id = %s", (keep_id, drop_id))
    _copy_blank_artist(keep, drop)
    if not keep.get("musicbrainz_artist_id") and drop.get("musicbrainz_artist_id"):
        mbid = drop["musicbrainz_artist_id"]
        db.execute("UPDATE artists SET musicbrainz_artist_id = NULL WHERE id = %s", (drop_id,))
        db.execute(
            "UPDATE artists SET musicbrainz_artist_id = %s, updated_at = NOW() WHERE id = %s",
            (mbid, keep_id),
        )
    db.execute("DELETE FROM artists WHERE id = %s", (drop_id,))
    detail = artist_detail(keep_id)
    detail["merge_warnings"] = warnings
    return detail


def same_directory(left, right):
    """True when both paths name one directory, including a difference in capital letters."""
    first = os.path.normpath(left or "")
    second = os.path.normpath(right or "")
    if not first or not second:
        return False
    if os.path.normcase(first) == os.path.normcase(second):
        return True
    try:
        if os.path.exists(first) and os.path.exists(second):
            return os.path.samefile(first, second)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def folder_has_audio(path):
    """True when any audio file remains under path, at any depth."""
    from resonance.scanner import AUDIO_EXTS

    if not path or not os.path.isdir(path):
        return False
    for root, dirs, files in os.walk(path):
        dirs[:] = [name for name in dirs if name not in {".", ".."} and not name.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                return True
    return False


def _remove_merged_folder(drop_path, keep_path):
    """Delete the other artist folder when it has no audio left. Return a warning otherwise."""
    from resonance.paths import allowed, inside, mount_writable

    folder = os.path.normpath(drop_path or "")
    master = os.path.normpath(keep_path or "")
    if not folder or not os.path.isdir(folder):
        return ""
    if master and (
        same_directory(folder, master)
        or inside(folder, master)
        or inside(master, folder)
    ):
        return "The other artist folder was left in place because it is the same folder as the artist you kept."
    if not allowed(folder) or not mount_writable(folder):
        return "The other artist folder was left in place because it is outside a writable music folder."
    if folder_has_audio(folder):
        return (
            "The other artist folder was left in place because it still has audio files. "
            "Those may be albums the scan has not indexed."
        )
    shutil.rmtree(folder)
    return ""


def _remember_artist_folders(keep, drop):
    """Remember the removed artist's folder so a later scan stays on this artist."""
    paths = []
    for item in [drop.get("path"), *(drop.get("folder_aliases") or [])]:
        text = str(item or "").strip()
        if not text or text in paths or text == keep.get("path"):
            continue
        paths.append(text)
    if not paths:
        return
    db.execute(
        """
        UPDATE artists
        SET folder_aliases = (
            SELECT ARRAY(
                SELECT DISTINCT path
                FROM unnest(COALESCE(folder_aliases, ARRAY[]::text[]) || %s::text[]) AS path
                WHERE path <> artists.path
            )
        ),
            updated_at = NOW()
        WHERE id = %s
        """,
        (db.text_array(paths), keep["id"]),
    )


def _copy_blank_artist(keep, drop):
    sets = []
    params = []
    for key in ("biography", "style", "mood", "website", "discogs_url", "wikipedia_url"):
        if str(keep.get(key) or "").strip() or not str(drop.get(key) or "").strip():
            continue
        sets.append(f"{key} = %s")
        params.append(drop.get(key))
    if not keep.get("discography") and drop.get("discography"):
        sets.append("discography = %s")
        params.append(Json(drop.get("discography")))
        sets.append("discography_fetched_at = %s")
        params.append(drop.get("discography_fetched_at"))
    if not sets:
        return
    params.append(keep["id"])
    db.execute(
        f"UPDATE artists SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
        tuple(params),
    )


def _retarget_album_path(album_id, old, new):
    old_n = os.path.normpath(old)
    new_n = os.path.normpath(new)
    db.execute("UPDATE albums SET path = %s WHERE id = %s", (new_n, album_id))
    rows = db.fetchall("SELECT id, file_path FROM tracks WHERE album_id = %s", (album_id,))
    prefix = old_n + os.sep
    for row in rows:
        path = os.path.normpath(row["file_path"] or "")
        if path == old_n or path.startswith(prefix):
            db.execute(
                "UPDATE tracks SET file_path = %s WHERE id = %s",
                (new_n + path[len(old_n):], row["id"]),
            )
    arts = db.fetchall(
        "SELECT id, local_path FROM artwork_pool WHERE album_id = %s AND local_path IS NOT NULL",
        (album_id,),
    )
    for row in arts:
        path = os.path.normpath(row["local_path"] or "")
        if path == old_n or path.startswith(prefix):
            db.execute(
                "UPDATE artwork_pool SET local_path = %s WHERE id = %s",
                (new_n + path[len(old_n):], row["id"]),
            )


def rename_artist(artist_id, name):
    """Store a name the user typed. Later scans leave that name in place."""
    artist_id = require_uuid(artist_id)
    text = clean_text(name, 255)
    if not text:
        raise AppError("Artist name cannot be empty")
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    db.execute(
        "UPDATE artists SET name = %s, name_custom = TRUE, updated_at = NOW() WHERE id = %s",
        (text, artist_id),
    )
    written = False
    warning = ""
    if artist.get("has_nfo"):
        try:
            write_artist_nfo(artist_id)
            written = True
        except AppError as exc:
            warning = str(exc)
    detail = artist_detail(artist_id)
    detail["nfo_written"] = written
    detail["nfo_warning"] = warning
    return detail


def rename_album(album_id, title):
    """Store an album title the user typed. Later scans leave that title in place."""
    album_id = require_uuid(album_id)
    text = clean_text(title, 255)
    if not text:
        raise AppError("Album title cannot be empty")
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    db.execute(
        "UPDATE albums SET title = %s, title_custom = TRUE, updated_at = NOW() WHERE id = %s",
        (text, album_id),
    )
    written = False
    warning = ""
    if album.get("has_nfo"):
        try:
            write_album_nfo(album_id)
            written = True
        except AppError as exc:
            warning = str(exc)
    detail = album_detail(album_id)
    detail["nfo_written"] = written
    detail["nfo_warning"] = warning
    return detail


def save_artist_profile(artist_id, body):
    """Store the artist.nfo fields, then rewrite artist.nfo when the folder is writable."""
    artist_id = require_uuid(artist_id)
    artist = db.fetchone("SELECT id FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    store_artist_fields(artist_id, body)
    written = False
    warning = ""
    try:
        write_artist_nfo(artist_id)
        written = True
    except AppError as exc:
        warning = str(exc)
    detail = artist_detail(artist_id)
    detail["nfo_written"] = written
    detail["nfo_warning"] = warning
    return detail


def write_album_nfo(album_id):
    from resonance import nfo
    from resonance.settings import load as load_settings

    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    cfg = load_settings()
    payload = nfo.album_context(album, artist)
    path = nfo.write_album(album["path"], cfg["nfo_profile"], payload, tracks, cfg["nfo_dialect"], cfg["nfo_backup"])
    db.execute(
        "UPDATE albums SET has_nfo = TRUE, nfo_digest = %s, updated_at = NOW() WHERE id = %s",
        (nfo.album_digest(payload, tracks), album_id),
    )
    return {"path": path}


_ALBUM_BATCH = ("type", "edition", "label", "country", "genres", "mood", "style", "theme", "release_status", "boxset")


def batch_edit_albums(ids, fields):
    """Set the same shared album fields. Titles, years, and catalog numbers stay put."""
    incoming = fields or {}
    unknown = [key for key in incoming if key not in _ALBUM_BATCH]
    if unknown:
        raise AppError(f"{unknown[0]} cannot be edited on a batch", 400)
    values = {}
    if "type" in incoming:
        values["type"] = release_type(incoming.get("type"))
    if "edition" in incoming:
        values["edition"] = clean_text(incoming.get("edition"), 100)
    if "label" in incoming:
        values["label"] = clean_text(incoming.get("label"), 255)
    if "country" in incoming:
        values["country"] = clean_text(incoming.get("country"), 8)
    if "genres" in incoming:
        names = []
        for item in incoming.get("genres") or []:
            name = genre_name(item)
            if name and name not in names:
                names.append(name)
        values["genres"] = names
    for key in ("mood", "style", "theme", "release_status"):
        if key in incoming:
            values[key] = clean_text(incoming.get(key), 500)
    if "boxset" in incoming:
        values["boxset"] = bool(incoming.get("boxset"))
    if not values:
        raise AppError("Nothing to save", 400)
    updated = skipped = nfo_errors = 0
    previous = {}
    for album_id in [str(require_uuid(item)) for item in ids or []][:5000]:
        row = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
        if not row or row["locked"]:
            skipped += 1
            continue
        previous[album_id] = {key: (row.get(key).value if hasattr(row.get(key), "value") else row.get(key)) for key in values}
        sets, params = [], []
        for key, value in values.items():
            if key == "type":
                sets.append("type = %s::release_type")
            elif key == "genres":
                sets.append("genres = %s::text[]")
            else:
                sets.append(f"{key} = %s")
            params.append(value)
        params.append(album_id)
        db.execute(
            f"UPDATE albums SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s AND NOT locked",
            params,
        )
        updated += 1
        try:
            write_album_nfo(album_id)
        except (OSError, AppError):
            nfo_errors += 1
    if not updated:
        raise AppError("Every selected album is locked or gone", 409)
    return {"updated": updated, "skipped": skipped, "nfo_errors": nfo_errors, "previous": previous}


def _scene_group(value):
    """A scene release group such as FraMeSToR. This is not a MusicBrainz id."""
    text = clean_text(value, 40)
    if not text:
        return None
    text = text.replace("/", "").replace("\\", "").strip()
    return text or None


def _rating_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 5:
        return None
    return round(number, 1)


def _vote_number(value):
    if value in (None, ""):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def save_album_profile(album_id, body):
    """Store the album.nfo fields, then rewrite album.nfo when the folder is writable."""
    album_id = require_uuid(album_id)
    album = db.fetchone("SELECT id FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    body = body or {}
    title = clean_text(body.get("title"), 255)
    if not title:
        raise AppError("An album needs a title")
    year_text = str(body.get("release_year") or "").strip()
    year = int(year_text) if year_text.isdigit() else None
    genres = body.get("genres")
    stored_genres = _genre_list(genres) if isinstance(genres, list) else None
    assignments = [
        "title = %s",
        "release_year = %s",
        "type = %s::release_type",
        "release_status = %s",
        "label = %s",
        "catalog = %s",
        "barcode = %s",
        "country = %s",
        "edition = %s",
        "release_group = %s",
        "review = %s",
        "review_checked_at = NULL",
        "mood = %s",
        "style = %s",
        "theme = %s",
        "allmusic_url = %s",
        "allmusic_rating = %s",
        "allmusic_user_rating = %s",
        "allmusic_votes = %s",
        "boxset = %s",
        "musicbrainz_release_id = %s",
        "musicbrainz_release_group_id = %s",
    ]
    params = [
        title,
        year,
        release_type(body.get("type")),
        clean_text(body.get("release_status"), 40),
        clean_text(body.get("label"), 255),
        clean_text(body.get("catalog"), 255),
        clean_text(body.get("barcode"), 40),
        clean_text(body.get("country"), 8),
        clean_text(body.get("edition"), 100),
        _scene_group(body.get("release_group")),
        clean_text(body.get("review"), 20000),
        clean_text(body.get("mood"), 500),
        clean_text(body.get("style"), 500),
        clean_text(body.get("theme"), 500),
        clean_text(body.get("allmusic_url"), 500),
        _rating_number(body.get("allmusic_rating")),
        _rating_number(body.get("allmusic_user_rating")),
        _vote_number(body.get("allmusic_votes")),
        bool(body.get("boxset")),
        _optional_mbid(body.get("musicbrainz_release_id"), "MusicBrainz release id"),
        _optional_mbid(body.get("musicbrainz_release_group_id"), "MusicBrainz release group id"),
    ]
    if stored_genres is not None:
        assignments.append("genres = %s::text[]")
        params.append(db.text_array(stored_genres))
    params.append(album_id)
    db.execute(
        f"UPDATE albums SET {', '.join(assignments)}, updated_at = NOW() WHERE id = %s",
        tuple(params),
    )
    written = False
    warning = ""
    try:
        write_album_nfo(album_id)
        written = True
    except AppError as exc:
        warning = str(exc)
    detail = album_detail(album_id)
    detail["nfo_written"] = written
    detail["nfo_warning"] = warning
    return detail


def rewrite_nfos(album_ids):
    """Rewrite artist and album .nfo files from the library rows for each album."""
    from resonance import match
    from resonance.paths import mount_writable
    from resonance.settings import load as load_settings

    ids = []
    for item in album_ids or []:
        ids.append(require_uuid(item))
    if not ids:
        raise AppError("Choose at least one album")
    cfg = load_settings()
    written = 0
    written_ids = []
    skipped = []
    errors = []
    for album_id in ids:
        album = db.fetchone("SELECT id, title, path FROM albums WHERE id = %s", (album_id,))
        if not album:
            errors.append(f"{album_id} was not found")
            continue
        if not mount_writable(album["path"]):
            skipped.append(album["title"] or album["path"])
            continue
        try:
            match._write_nfos(album["id"], cfg)
            written += 1
            written_ids.append(str(album["id"]))
        except AppError as exc:
            errors.append(f"{album['title']}: {exc}")
        except Exception as exc:
            errors.append(f"{album['title']}: {exc}")
    return {"written": written, "ids": written_ids, "skipped": skipped, "errors": errors}


def mark_many(ids, status):
    mapping = {"processed": "PROCESSED", "ignored": "IGNORED", "new": "NEW"}
    if status not in mapping:
        raise AppError("Status must be processed, ignored, or new")
    wanted = [require_uuid(item) for item in ids or []]
    if not wanted:
        return {"updated": [], "status": mapping[status]}
    rows = db.fetchall(
        """
        UPDATE albums
        SET status = %s::asset_status, updated_at = NOW()
        WHERE id = ANY(%s::uuid[])
        RETURNING id
        """,
        (mapping[status], db.uuid_array(wanted)),
    )
    return {"updated": [row["id"] for row in rows], "status": mapping[status]}


def held_album_ids():
    """Albums a scan left in place under prune safety (marked Not found)."""
    return [str(row["id"]) for row in db.fetchall("SELECT id FROM albums WHERE prune_held IS TRUE")]


def forget_albums(ids):
    """Drop albums from the index. Files on disk stay."""
    from resonance.upgrade import refresh_album_peers

    removed, peers, track_ids = [], [], []
    for item in ids or []:
        album_id = require_uuid(item)
        album = _album_for_peers(album_id)
        if not album:
            continue
        track_ids.extend(_album_track_ids(album_id))
        db.execute("DELETE FROM albums WHERE id = %s", (album_id,))
        peers = _merge_peer_flags(peers, refresh_album_peers(album))
        removed.append(str(album_id))
    _count_cache["at"] = 0.0
    return {"removed": removed, "peers": peers, "track_ids": track_ids}


def forget_artists(ids):
    """Drop artists and their albums from the index. Files on disk stay."""
    from resonance.upgrade import refresh_album_peers

    removed, peers, track_ids = [], [], []
    for item in ids or []:
        artist_id = require_uuid(item)
        row = db.fetchone("SELECT id FROM artists WHERE id = %s", (artist_id,))
        if not row:
            continue
        albums = db.fetchall(
            """
            SELECT albums.*, artists.name AS artist_name
            FROM albums JOIN artists ON artists.id = albums.artist_id
            WHERE albums.artist_id = %s
            """,
            (artist_id,),
        )
        for album in albums:
            track_ids.extend(_album_track_ids(album["id"]))
        db.execute("DELETE FROM artists WHERE id = %s", (artist_id,))
        for album in albums:
            peers = _merge_peer_flags(peers, refresh_album_peers(album))
        removed.append(str(artist_id))
    return {"removed": removed, "peers": peers, "track_ids": track_ids}


def _album_for_peers(album_id):
    return db.fetchone(
        """
        SELECT albums.*, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (album_id,),
    )


def _album_track_ids(album_id):
    rows = db.fetchall("SELECT id::text AS id FROM tracks WHERE album_id = %s", (album_id,))
    return [row["id"] for row in rows]


def _merge_peer_flags(found, extra):
    by_id = {row["id"]: row for row in found or [] if row.get("id")}
    for row in extra or []:
        if row.get("id"):
            by_id[row["id"]] = row
    return list(by_id.values())


def delete_albums_from_disk(ids):
    """Delete album folders from disk and drop those albums from the index."""
    from resonance.upgrade import discard

    deleted, errors, peers, track_ids = [], [], [], []
    for item in ids or []:
        try:
            result = discard(require_uuid(item))
            deleted.append(result.get("deleted") or str(item))
            peers = _merge_peer_flags(peers, result.get("peers"))
            track_ids.extend(result.get("track_ids") or [])
        except AppError as exc:
            errors.append(str(exc))
    return {"deleted": deleted, "errors": errors, "peers": peers, "track_ids": track_ids}


def delete_artists_from_disk(ids):
    """Delete each artist's albums and artist folder, then drop the artist from the index."""
    import os
    import shutil

    from resonance.paths import assert_library_writable, inside, music_roots
    from resonance.upgrade import discard

    deleted, errors, peers, track_ids = [], [], [], []
    roots = music_roots()
    for item in ids or []:
        artist_id = require_uuid(item)
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
        if not artist:
            continue
        albums = db.fetchall("SELECT id, title FROM albums WHERE artist_id = %s", (artist_id,))
        blocked = False
        for album in albums:
            try:
                result = discard(album["id"])
                peers = _merge_peer_flags(peers, result.get("peers"))
                track_ids.extend(result.get("track_ids") or [])
            except AppError as exc:
                errors.append(f"{album.get('title') or 'Album'}: {exc}")
                blocked = True
        if blocked:
            continue
        path = artist.get("path") or ""
        if path and os.path.isdir(path):
            try:
                assert_library_writable(path)
                real = os.path.realpath(path)
                if any(os.path.normcase(real) == os.path.normcase(os.path.realpath(root)) for root in roots if root):
                    errors.append(f"Refusing to delete a music library root: {path}")
                    continue
                if any(inside(root, path) for root in roots):
                    shutil.rmtree(real)
            except AppError as exc:
                errors.append(str(exc))
                continue
        db.execute("DELETE FROM artists WHERE id = %s", (artist_id,))
        deleted.append(str(artist_id))
    return {"deleted": deleted, "errors": errors, "peers": peers, "track_ids": track_ids}


def refresh_match_tier(album_id):
    row = db.fetchone(
        """
        SELECT
            COUNT(t.id)::int AS total,
            COUNT(t.musicbrainz_track_id)::int AS matched,
            a.musicbrainz_release_id,
            a.musicbrainz_release_group_id
        FROM albums a
        LEFT JOIN tracks t ON t.album_id = a.id
        WHERE a.id = %s
        GROUP BY a.id
        """,
        (album_id,),
    )
    if not row:
        return
    total = int(row["total"] or 0)
    matched = int(row["matched"] or 0)
    linked = bool(row["musicbrainz_release_id"] or row["musicbrainz_release_group_id"])
    ratio = int(100 * matched / total) if total else 0
    if total and matched == total and linked:
        tier = "gold"
    elif matched or linked:
        tier = "silver"
    else:
        tier = "unmatched"
    db.execute(
        "UPDATE albums SET match_tier = %s, match_ratio = %s WHERE id = %s",
        (tier, ratio, album_id),
    )


def guard_editable(row, noun="This item"):
    """Locked and ignored items stay out of metadata lookups and scrapes."""
    if not row:
        return
    if row.get("locked"):
        raise AppError(f"{noun} is locked. Unlock it before a scrape or a metadata lookup.", 409)
    if row.get("status") == "IGNORED":
        raise AppError(f"{noun} is ignored. Stop ignoring it before a scrape or a metadata lookup.", 409)


def set_locks(kind, ids, locked):
    tables = {"artist": "artists", "album": "albums"}
    if kind not in tables:
        raise AppError("Unknown item type")
    wanted = [require_uuid(item) for item in ids or []]
    if not wanted:
        return {"updated": [], "locked": bool(locked)}
    rows = db.fetchall(
        f"UPDATE {tables[kind]} SET locked = %s, updated_at = NOW() WHERE id = ANY(%s::uuid[]) RETURNING id",
        (bool(locked), db.uuid_array(wanted)),
    )
    return {"updated": [row["id"] for row in rows], "locked": bool(locked)}


def toggle_field_lock(kind, item_id, field, locked=None):
    tables = {"artist": "artists", "album": "albums"}
    if kind not in tables:
        raise AppError("Unknown item type")
    item_id = require_uuid(item_id)
    field_name = str(field or "").strip()
    if not field_name:
        raise AppError("Field name is required")
    table = tables[kind]
    row = db.fetchone(f"SELECT locked_fields FROM {table} WHERE id = %s", (item_id,))
    if not row:
        raise AppError("Item not found", 404)
    current = list(row.get("locked_fields") or [])
    if locked is None:
        locked = field_name not in current
    if locked:
        if field_name not in current:
            current.append(field_name)
    else:
        current = [f for f in current if f != field_name]
    db.execute(
        f"UPDATE {table} SET locked_fields = %s::text[], updated_at = NOW() WHERE id = %s",
        (db.text_array(current), item_id),
    )
    return {"id": str(item_id), "locked_fields": current, "locked": bool(locked)}


def mark(kind, item_id, status):
    mapping = {"processed": "PROCESSED", "ignored": "IGNORED", "new": "NEW"}
    tables = {"artist": "artists", "album": "albums"}
    if status not in mapping:
        raise AppError("Status must be processed, ignored, or new")
    if kind not in tables:
        raise AppError("Unknown item type")
    table = tables[kind]
    row = db.fetchone(
        f"UPDATE {table} SET status = %s::asset_status, updated_at = NOW() WHERE id = %s RETURNING id",
        (mapping[status], item_id),
    )
    if not row:
        raise AppError("Item not found", 404)
    return {"id": row["id"], "status": mapping[status]}


def require_uuid(value):
    return opt_uuid(value, "id")


def loaded_matches():
    rows = db.fetchall("SELECT album_id, proposal FROM loaded_matches ORDER BY updated_at")
    return {str(row["album_id"]): row["proposal"] for row in rows}


def store_loaded_match(album_id, proposal):
    require_uuid(album_id)
    if not isinstance(proposal, dict) or not proposal:
        raise AppError("Expected a match proposal")
    album = db.fetchone("SELECT id FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    db.execute(
        """
        INSERT INTO loaded_matches (album_id, proposal, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (album_id) DO UPDATE
        SET proposal = EXCLUDED.proposal, updated_at = NOW()
        """,
        (album_id, Json(proposal)),
    )
    return {"album_id": str(album_id)}


def drop_loaded_match(album_id):
    require_uuid(album_id)
    db.execute("DELETE FROM loaded_matches WHERE album_id = %s", (album_id,))
    return {"album_id": str(album_id)}


_MBID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def release_artist_mbid(tracks):
    """One MusicBrainz album-artist id when every file names that same artist.

    A credit with several ids stays in the tags and is not reduced to one artist.
    A compilation whose tracks name different artists stays in the folder it was scanned from.
    """
    album_sets = []
    track_sets = []
    total = 0
    for track in tracks or []:
        total += 1
        raw = track.get("tags") if isinstance(track.get("tags"), dict) else None
        if raw is None and isinstance(track.get("raw"), dict):
            raw = track["raw"]
        raw = raw or {}
        album_ids = tuple(mbid_list(raw.get("musicbrainz_albumartistid")))
        artist_ids = tuple(mbid_list(raw.get("musicbrainz_artistid")))
        if album_ids:
            album_sets.append(album_ids)
        if artist_ids:
            track_sets.append(artist_ids)
    if album_sets:
        agreed = set(album_sets)
        if len(agreed) == 1 and len(album_sets[0]) == 1:
            return album_sets[0][0]
        return None
    if total and len(track_sets) == total and len(set(track_sets)) == 1 and len(track_sets[0]) == 1:
        return track_sets[0][0]
    return None


def _rehome_sql(limit_albums):
    track_filter = "WHERE album_id = ANY(%s::uuid[])" if limit_albums else ""
    return f"""
        /* curator-album-rehome */
        WITH tagged AS (
            SELECT
                album_id,
                NULLIF(btrim(tags->>'musicbrainz_albumartistid'), '') AS album_mbid,
                NULLIF(btrim(tags->>'musicbrainz_artistid'), '') AS track_mbid
            FROM tracks
            {track_filter}
        ),
        album_choice AS (
            SELECT album_id, lower(min(album_mbid)) AS mbid
            FROM tagged
            WHERE album_mbid ~ '{_MBID_RE}'
            GROUP BY album_id
            HAVING count(DISTINCT lower(album_mbid)) = 1
        ),
        track_choice AS (
            SELECT t.album_id, lower(min(t.track_mbid)) AS mbid
            FROM tagged t
            JOIN (
                SELECT album_id, count(*) AS total
                FROM tagged
                GROUP BY album_id
            ) totals ON totals.album_id = t.album_id
            WHERE t.track_mbid ~ '{_MBID_RE}'
              AND NOT EXISTS (
                    SELECT 1 FROM tagged other
                    WHERE other.album_id = t.album_id
                      AND other.album_mbid ~ '{_MBID_RE}'
              )
            GROUP BY t.album_id, totals.total
            HAVING count(DISTINCT lower(t.track_mbid)) = 1
               AND count(t.track_mbid) = totals.total
        ),
        chosen AS (
            SELECT album_id, mbid FROM album_choice
            UNION ALL
            SELECT album_id, mbid FROM track_choice
        )
        UPDATE albums
        SET artist_id = artists.id, updated_at = NOW()
        FROM chosen
        JOIN artists ON artists.musicbrainz_artist_id = chosen.mbid::uuid
        WHERE albums.id = chosen.album_id
          AND albums.artist_id IS DISTINCT FROM artists.id
    """


def _rehome_batch(conn, last):
    rows = conn.execute(
        """
        SELECT id FROM albums
        WHERE %s::uuid IS NULL OR id > %s::uuid
        ORDER BY id
        LIMIT 400
        """,
        (last, last),
    ).fetchall()
    if not rows:
        return None
    ids = [row["id"] for row in rows]
    changed = conn.execute(_rehome_sql(True), (db.uuid_array(ids),)).rowcount
    return changed, ids[-1]


def _scan_is_running():
    if db.pool is None:
        return False
    row = db.fetchone("SELECT 1 AS hit FROM scan_jobs WHERE status = 'running' LIMIT 1")
    return bool(row)


def rehome_tagged_artists(conn=None):
    """List an album under the artist whose MusicBrainz id is stored on its files.

    The files stay in their folder. This only changes which artist the album is
    listed under, and only when that other artist is already in the library.
    Albums are updated a few hundred at a time so a library scan can remove
    missing folders while this is running.
    """
    if conn is not None and not conn.autocommit:
        return conn.execute(_rehome_sql(False)).rowcount
    moved = 0
    last = None
    while True:
        if conn is not None:
            batch = _rehome_batch(conn, last)
        else:
            with db.transaction() as owned:
                batch = _rehome_batch(owned, last)
        if batch is None:
            return moved
        changed, last = batch
        moved += changed
        while _scan_is_running():
            time.sleep(2)


def _artist_brief(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "locked": bool(row.get("locked")),
        "locked_fields": list(row.get("locked_fields") or []),
        "type": row["type"],
        "genres": row["genres"] or [],
        "biography": row.get("biography"),
        "musicbrainz_artist_id": row["musicbrainz_artist_id"],
        "path": row["path"],
        "folder_aliases": list(row.get("folder_aliases") or []),
        "has_nfo": row["has_nfo"],
        "has_artwork": row["has_artwork"],
        "artwork_width": row["artwork_width"],
        "artwork_height": row["artwork_height"],
        "formed": row.get("formed"),
        "origin": row.get("origin"),
        "years_active": row.get("years_active"),
        "website": row.get("website"),
        "sortname": row.get("sortname"),
        "gender": row.get("gender"),
        "disambiguation": row.get("disambiguation"),
        "style": row.get("style"),
        "mood": row.get("mood"),
        "instruments": row.get("instruments"),
        "died": row.get("died"),
        "disbanded": row.get("disbanded"),
        "discogs_url": row.get("discogs_url"),
        "wikipedia_url": row.get("wikipedia_url"),
        "nfo_stale": bool(row.get("nfo_stale")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def shared_release_ids(rows):
    """MusicBrainz release ids that belong to more than one album."""
    counts = {}
    for row in rows or []:
        release_id = str(row.get("musicbrainz_release_id") or "").strip()
        if not release_id:
            continue
        counts[release_id] = counts.get(release_id, 0) + 1
    return {release_id for release_id, count in counts.items() if count > 1}


def _attach_artist_nfo_stale(artists):
    """Mark artists whose artist.nfo was last saved from an older copy of the database."""
    from resonance import nfo

    pending = [artist for artist in artists if artist.get("has_nfo")]
    if not pending:
        return
    ids = [artist["id"] for artist in pending]
    stored = db.fetchall("SELECT id, nfo_digest FROM artists WHERE id = ANY(%s::uuid[])", (db.uuid_array(ids),))
    digest_of = {str(row["id"]): row.get("nfo_digest") or "" for row in stored}
    stale_ids = [artist["id"] for artist in pending if digest_of.get(str(artist["id"]))]
    full_of = {}
    if stale_ids:
        full = db.fetchall("SELECT * FROM artists WHERE id = ANY(%s::uuid[])", (db.uuid_array(stale_ids),))
        full_of = {str(row["id"]): row for row in full}
    for artist in artists:
        digest = digest_of.get(str(artist["id"])) or ""
        row = full_of.get(str(artist["id"]))
        current = nfo.artist_digest(row) if row else ""
        if not digest or not row or current == digest:
            artist["nfo_stale"] = False
            continue
        try:
            _name, text = nfo.read_text(row.get("path"), ("artist.nfo", "folder.nfo"))
            changes = nfo.artist_nfo_diff(text, row).get("changes") or []
        except AppError:
            changes = ["missing"]
        artist["nfo_stale"] = _clear_false_nfo("artists", row["id"], digest, current, changes)


def _attach_album_nfo_stale(albums, on_progress=None):
    """Mark albums whose album.nfo was last saved from an older copy of the database.

    A scan can store new album and track details without rewriting album.nfo. The tree
    reads that here, so the purple pill is present as soon as the library loads.
    """
    from resonance import nfo

    pending = [album for album in albums if album.get("has_nfo")]
    if not pending:
        return
    ids = [album["id"] for album in pending]
    stored = db.fetchall("SELECT id, nfo_digest FROM albums WHERE id = ANY(%s::uuid[])", (db.uuid_array(ids),))
    digest_of = {str(row["id"]): row.get("nfo_digest") or "" for row in stored}
    stale_ids = [album["id"] for album in pending if digest_of.get(str(album["id"]))]
    if not stale_ids:
        for album in albums:
            album["nfo_stale"] = False
        return
    full = db.fetchall("SELECT * FROM albums WHERE id = ANY(%s::uuid[])", (db.uuid_array(stale_ids),))
    full_of = {str(row["id"]): row for row in full}
    artist_ids = [row["artist_id"] for row in full if row.get("artist_id")]
    artists = db.fetchall(
        "SELECT id, name, musicbrainz_artist_id, biography, genres FROM artists WHERE id = ANY(%s::uuid[])",
        (db.uuid_array(artist_ids),),
    ) if artist_ids else []
    artist_of = {str(row["id"]): row for row in artists}
    tracks = db.fetchall(
        """
        SELECT * FROM tracks
        WHERE album_id = ANY(%s::uuid[])
        ORDER BY disc_number, track_number
        """,
        (db.uuid_array(stale_ids),),
    )
    tracks_of = {}
    for track in tracks:
        tracks_of.setdefault(str(track["album_id"]), []).append(track)
    for index, album in enumerate(albums):
        if on_progress and index % 25 == 0:
            on_progress(index, len(albums))
        digest = digest_of.get(str(album["id"])) or ""
        row = full_of.get(str(album["id"]))
        if not digest or not row:
            album["nfo_stale"] = False
            continue
        artist = artist_of.get(str(row.get("artist_id"))) or {}
        context = nfo.album_context(row, artist)
        tracks = tracks_of.get(str(album["id"]), [])
        current = nfo.album_digest(context, tracks)
        if current == digest:
            album["nfo_stale"] = False
            continue
        try:
            _name, text = nfo.read_text(row.get("path"), ("album.nfo", "folder.nfo"))
            changes = nfo.album_nfo_diff(text, context, tracks).get("changes") or []
        except AppError:
            changes = ["missing"]
        album["nfo_stale"] = _clear_false_nfo("albums", row["id"], digest, current, changes)


def _album_brief(row, full=False):
    from resonance.upgrade import version_label
    payload = {
        "id": row["id"],
        "artist_id": row["artist_id"],
        "title": row["title"],
        "release_year": row["release_year"],
        "original_year": row.get("original_year"),
        "total_discs": row["total_discs"],
        "total_tracks": row["total_tracks"],
        "duration_seconds": row["duration_seconds"],
        "type": row["type"],
        "edition": row["edition"],
        "version": version_label(row.get("edition"), "", row.get("type")),
        "duplicate_release": bool(row.get("duplicate_release")),
        "prune_held": bool(row.get("prune_held")),
        "status": row["status"],
        "locked": bool(row.get("locked")),
        "locked_fields": list(row.get("locked_fields") or []),
        "path": row["path"],
        "has_nfo": row["has_nfo"],
        "has_artwork": row["has_artwork"],
        "artwork_width": row["artwork_width"],
        "artwork_height": row["artwork_height"],
        "musicbrainz_release_group_id": row["musicbrainz_release_group_id"],
        "musicbrainz_release_id": row["musicbrainz_release_id"],
        "match_tier": row.get("match_tier") or "unmatched",
        "match_ratio": row.get("match_ratio") or 0,
        "path_role": row.get("path_role") or "library",
        "quality_rank": row.get("quality_rank") or 0,
        "cue_image": bool(row.get("cue_image")),
        "gap_present": row.get("gap_present"),
        "gap_expected": row.get("gap_expected"),
        "country": row.get("country") or "",
        "label": row.get("label") or "",
        "catalog": row.get("catalog") or "",
        "barcode": row.get("barcode") or "",
        "release_status": row.get("release_status") or "",
        "upgrade": row.get("upgrade"),
        "nfo_stale": bool(row.get("nfo_stale")),
        "created_at": row.get("created_at"),
        "updated_at": row["updated_at"],
    }
    if full:
        payload["review"] = row.get("review") or ""
        payload["mood"] = row.get("mood") or ""
        payload["style"] = row.get("style") or ""
        payload["theme"] = row.get("theme") or ""
        payload["allmusic_url"] = row.get("allmusic_url") or ""
        payload["allmusic_rating"] = row.get("allmusic_rating")
        payload["allmusic_user_rating"] = row.get("allmusic_user_rating")
        payload["allmusic_votes"] = row.get("allmusic_votes")
        payload["boxset"] = bool(row.get("boxset"))
        payload["genres"] = row.get("genres")
    return payload


def _track_out(row):
    return {
        "id": row["id"],
        "album_id": row["album_id"],
        "title": row["title"],
        "artist_name": row["artist_name"],
        "album_name": row["album_name"],
        "genre": row["genre"],
        "year": row["year"],
        "track_number": row["track_number"],
        "disc_number": row["disc_number"],
        "duration_seconds": row["duration_seconds"],
        "file_format": row["file_format"],
        "sample_rate": row["sample_rate"],
        "bit_depth": row["bit_depth"],
        "bitrate": row.get("bitrate"),
        "acoustid_score": row.get("acoustid_score"),
        "file_path": row["file_path"],
        "musicbrainz_track_id": row["musicbrainz_track_id"],
        "musicbrainz_release_group_id": row["musicbrainz_release_group_id"],
        "tag_completeness_percent": row["tag_completeness_percent"],
        "lyrics_type": row["lyrics_type"],
        "audio_flag": row.get("audio_flag"),
        "fingerprint_hash": row.get("fingerprint_hash"),
        "acoustid_recording_id": row.get("acoustid_recording_id"),
        "tags": row["tags"] or {},
    }


def artist_folder_name(name):
    """A single folder name. Characters that break a path become hyphens."""
    cleaned = "".join("-" if char in '\\/:*?"<>|' else char for char in str(name or ""))
    cleaned = cleaned.strip().rstrip(". ")
    return cleaned[:120] or "Unknown Artist"


def _new_artist_root():
    from resonance.paths import mount_writable, music_roots, path_role

    library_roots = [root for root in music_roots() if path_role(root) != "inbox" and mount_writable(root)]
    if not library_roots:
        library_roots = [root for root in music_roots() if mount_writable(root)]
    if not library_roots:
        raise AppError("Add a writable music path in Settings before adding an artist.", 400)
    return library_roots[0]


def add_remote_artist(mbid):
    """Create an artist folder from MusicBrainz, fill metadata and artwork, and add them to Lidarr."""
    from resonance import artwork, lidarr, profile
    from resonance.paths import assert_library_writable
    from resonance.settings import load
    from resonance.sources import musicbrainz

    artist_mbid = str(require_uuid(mbid))
    local = db.fetchone(
        "SELECT id, name FROM artists WHERE musicbrainz_artist_id = %s",
        (artist_mbid,),
    )
    remote = lidarr.stored_artist(artist_mbid)
    places = []
    if local:
        places.append("the library")
    if remote:
        places.append("Lidarr")
    if places:
        raise AppError(f"That artist is already in {' and '.join(places)}.", 409)
    try:
        looked = musicbrainz.get_artist(artist_mbid) or {}
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    name = clean_text(looked.get("name"), 255) or "Unknown Artist"
    root = _new_artist_root()
    assert_library_writable(root)
    folder = artist_folder_name(name)
    path = os.path.join(root, folder)
    if os.path.exists(path) or db.fetchone("SELECT id FROM artists WHERE path = %s", (path,)):
        raise AppError(f"An artist folder named {folder} already exists.", 409)
    os.makedirs(path, exist_ok=False)
    try:
        row = db.fetchone(
            """
            INSERT INTO artists (name, path, status, musicbrainz_artist_id)
            VALUES (%s, %s, 'NEW', %s)
            RETURNING id
            """,
            (name, path, artist_mbid),
        )
    except UniqueViolation as exc:
        try:
            os.rmdir(path)
        except OSError:
            pass
        raise AppError("That artist is already in the library.", 409) from exc
    artist_id = row["id"]
    warnings = []
    try:
        scraped = profile.scrape(artist_id, mbid=artist_mbid)
        profile.save_biography(artist_id, scraped.get("biography") or "", scraped.get("fields") or {})
    except Exception as exc:
        warnings.append(str(exc))
    try:
        saved = artwork.deploy_missing_artist(artist_id)
        warnings.extend(saved.get("warnings") or [])
    except Exception as exc:
        warnings.append(str(exc))
    added = False
    try:
        lidarr.add_artist(artist_mbid)
        added = True
    except Exception as exc:
        warnings.append(str(exc))
    monitored = load().get("lidarr_monitor_new", True) is not False
    if not added:
        message = f"Added {name} to the library. Lidarr was not updated."
    elif monitored:
        message = f"Added {name}. Lidarr is monitoring their albums."
    else:
        message = f"Added {name}. Lidarr has the artist, and their albums are not monitored."
    return {"artist_id": artist_id, "name": name, "path": path, "message": message, "warnings": warnings}
