import logging
import os
import shutil
import subprocess

from resonance import db
from resonance.errors import AppError
from resonance.paths import assert_library_writable, inside, music_roots, path_role
from resonance.quality import album_score, format_summary, higher_copy, release_kind, same_release_kind, similar_copies, upgrade_source

logger = logging.getLogger(__name__)


def refresh_stored():
    """Record upgrades, shared-release duplicates, and original years. Runs at the end of a scan, not when the library is opened.

    Listing albums under the artist stored in their tags is separate catalogue
    maintenance. Doing it here made the scan sit on this step for the whole library.
    """
    from resonance.fields import norm_name

    rows = db.fetchall(
        """
        SELECT albums.id, albums.title, albums.type, albums.edition, albums.path, albums.path_role,
               albums.quality_rank, albums.musicbrainz_release_id, albums.upgrade_source_id,
               artists.name AS artist_name
        FROM albums
        JOIN artists ON artists.id = albums.artist_id
        """
    )
    peers = [
        {
            "id": row["id"],
            "title": row.get("title"),
            "type": row.get("type"),
            "edition": row.get("edition") or "",
            "path": row.get("path") or "",
            "path_role": row.get("path_role") or "library",
            "quality_rank": row.get("quality_rank") or 0,
            "artist_name": row.get("artist_name") or "",
            "upgrade_source_id": str(row.get("upgrade_source_id") or ""),
        }
        for row in rows
    ]
    release_types = {
        str(row["album_id"]): row.get("release_type") or ""
        for row in db.fetchall(
            """
            SELECT DISTINCT ON (album_id)
                   album_id::text AS album_id, tags->>'releasetype' AS release_type
            FROM tracks
            WHERE COALESCE(tags->>'releasetype', '') <> ''
            ORDER BY album_id, disc_number, track_number
            """
        )
    }
    for peer in peers:
        peer["release_type"] = release_types.get(str(peer["id"]), "")
    by_title = {}
    peer_by_id = {}
    for peer in peers:
        peer_by_id[str(peer["id"])] = peer
        key = (norm_name(peer.get("artist_name")), norm_name(peer.get("title")))
        if not key[0] or not key[1]:
            continue
        by_title.setdefault(key, []).append(peer)
    alive = {str(peer["id"]) for peer in peers}
    same_quality = _same_quality_copies(by_title)
    chosen = {}
    for peer in peers:
        key = (norm_name(peer.get("artist_name")), norm_name(peer.get("title")))
        source = higher_copy(peer, by_title.get(key, []))
        if source:
            chosen[str(peer["id"])] = str(source["id"])
            continue
        stored = peer.get("upgrade_source_id") or ""
        match = peer_by_id.get(stored)
        if stored and stored in alive and stored != str(peer["id"]) and match and same_release_kind(peer, match):
            chosen[str(peer["id"])] = stored
    with db.transaction() as conn:
        conn.execute("UPDATE albums SET upgrade_source_id = NULL WHERE upgrade_source_id IS NOT NULL")
        if chosen:
            conn.execute(
                """
                UPDATE albums AS album
                SET upgrade_source_id = data.source_id
                FROM unnest(%s::uuid[], %s::uuid[]) AS data(album_id, source_id)
                WHERE album.id = data.album_id
                """,
                (db.uuid_array(list(chosen)), db.uuid_array(list(chosen.values()))),
            )
        conn.execute("UPDATE albums SET duplicate_release = FALSE WHERE duplicate_release IS TRUE")
        conn.execute(
            """
            UPDATE albums
            SET duplicate_release = TRUE
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           count(*) OVER (
                               PARTITION BY musicbrainz_release_id,
                                            CASE lower(btrim(COALESCE(type::text, '')))
                                                WHEN 'single' THEN 'single'
                                                WHEN 'ep' THEN 'ep'
                                                WHEN 'compilation' THEN 'compilation'
                                                WHEN 'live' THEN 'live'
                                                ELSE 'album'
                                            END
                           ) AS copies
                    FROM albums
                    WHERE musicbrainz_release_id IS NOT NULL
                ) AS grouped
                WHERE copies > 1
            )
            """
        )
        if same_quality:
            conn.execute(
                "UPDATE albums SET duplicate_release = TRUE WHERE id = ANY(%s::uuid[])",
                (db.uuid_array(list(same_quality)),),
            )
        store_original_years(conn)
        silence_dismissed_albums(conn)
    return len(chosen)


def clear_orphan_flags():
    """Drop duplicate and upgrade marks that no longer point at another copy.

    A mark is stale when the album has no other album with the same artist and title, no other
    album with the same MusicBrainz release, or (for an upgrade) its source is not one of its
    copies. That happens when the other copy was removed (a changed mount, a deleted folder) and the
    marks were not recomputed. Returns the album ids whose marks were cleared.
    """
    from resonance.fields import norm_name

    flagged = db.fetchall(
        "SELECT id FROM albums WHERE duplicate_release IS TRUE OR upgrade_source_id IS NOT NULL LIMIT 1"
    )
    if not flagged:
        return []
    rows = db.fetchall(
        """
        SELECT albums.id::text AS id, albums.title, albums.musicbrainz_release_id::text AS mbid,
               albums.duplicate_release, albums.upgrade_source_id::text AS source,
               artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        """
    )
    by_title, by_release = {}, {}
    for row in rows:
        key = (norm_name(row["artist_name"]), norm_name(row["title"]))
        row["key"] = key
        by_title.setdefault(key, set()).add(row["id"])
        if row["mbid"]:
            by_release.setdefault(row["mbid"], set()).add(row["id"])
    by_id = {row["id"]: row for row in rows}
    no_duplicate, no_upgrade = [], []
    for row in rows:
        if row["duplicate_release"]:
            alone = len(by_title.get(row["key"], ())) < 2 and len(by_release.get(row["mbid"], ())) < 2
            if alone:
                no_duplicate.append(row["id"])
        if row["source"]:
            source = by_id.get(row["source"])
            if not source or source["id"] == row["id"] or source["key"] != row["key"]:
                no_upgrade.append(row["id"])
    if no_duplicate:
        db.execute("UPDATE albums SET duplicate_release = FALSE WHERE id = ANY(%s::uuid[])", (db.uuid_array(no_duplicate),))
    if no_upgrade:
        db.execute("UPDATE albums SET upgrade_source_id = NULL WHERE id = ANY(%s::uuid[])", (db.uuid_array(no_upgrade),))
    cleared = list(dict.fromkeys(no_duplicate + no_upgrade))
    if cleared:
        logger.info("cleared stale duplicate or upgrade marks on %d albums", len(cleared))
    return cleared


def clear_marks(album_id, duplicate=True, upgrade=True):
    """Clear the marks on one album, for a window that turned up empty."""
    parts = []
    if duplicate:
        parts.append("duplicate_release = FALSE")
    if upgrade:
        parts.append("upgrade_source_id = NULL")
    if parts:
        db.execute(f"UPDATE albums SET {', '.join(parts)} WHERE id = %s", (album_id,))


def album_groups_after_delete(album, rows):
    """Copies that share this album's title, and copies that share its MusicBrainz release."""
    from resonance.fields import norm_name

    deleted = str(album.get("id") or "")
    key = (norm_name(album.get("artist_name")), norm_name(album.get("title")))
    mbid = str(album.get("musicbrainz_release_id") or "").strip()
    title_rows, mbid_rows = [], []
    for row in rows or []:
        if str(row.get("id") or "") == deleted:
            continue
        peer_key = (norm_name(row.get("artist_name")), norm_name(row.get("title")))
        if key[0] and key[1] and peer_key == key:
            title_rows.append(row)
        if mbid and str(row.get("musicbrainz_release_id") or "").strip() == mbid:
            mbid_rows.append(row)
    return title_rows, mbid_rows


def _album_type_bucket(value):
    token = str(value or "").strip().lower()
    if token in {"single", "ep", "compilation", "live"}:
        return token
    return "album"


def _album_peer(row, release_types):
    peer = {
        "id": row["id"],
        "title": row.get("title"),
        "type": row.get("type"),
        "edition": row.get("edition") or "",
        "path": row.get("path") or "",
        "path_role": row.get("path_role") or "library",
        "quality_rank": row.get("quality_rank") or 0,
        "artist_name": row.get("artist_name") or "",
        "upgrade_source_id": str(row.get("upgrade_source_id") or ""),
        "musicbrainz_release_id": str(row.get("musicbrainz_release_id") or ""),
    }
    peer["release_type"] = release_types.get(str(row["id"]), "")
    return peer


def _mbid_membership(mbid):
    """Remaining albums that still share a MusicBrainz release, split into groups of two or more and the last one."""
    if not mbid:
        return set(), set()
    buckets = {}
    for row in db.fetchall(
        """
        SELECT id::text AS id, lower(btrim(coalesce(type::text, ''))) AS kind
        FROM albums WHERE musicbrainz_release_id = %s
        """,
        (mbid,),
    ):
        buckets.setdefault(_album_type_bucket(row.get("kind")), []).append(row["id"])
    dupes, alone = set(), set()
    for ids in buckets.values():
        if len(ids) > 1:
            dupes.update(ids)
        elif len(ids) == 1:
            alone.add(ids[0])
    return dupes, alone


def _same_quality_album(album_id):
    """True when this album still has a same-quality copy of its own title."""
    from resonance.fields import norm_name

    row = db.fetchone(
        """
        SELECT albums.id, albums.title, albums.type, albums.edition, albums.path, albums.path_role,
               albums.quality_rank, albums.musicbrainz_release_id, albums.upgrade_source_id,
               albums.artist_id, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (album_id,),
    )
    if not row:
        return False
    mates = db.fetchall(
        """
        SELECT albums.id, albums.title, albums.type, albums.edition, albums.path, albums.path_role,
               albums.quality_rank, albums.musicbrainz_release_id, albums.upgrade_source_id,
               artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.artist_id = %s OR lower(btrim(artists.name)) = lower(btrim(%s))
        """,
        (row["artist_id"], row.get("artist_name") or ""),
    )
    title_rows, _mbid_rows = album_groups_after_delete(row, mates)
    group = [row] + title_rows
    types = _release_types([item["id"] for item in group])
    peers = [_album_peer(item, types) for item in group]
    key = (norm_name(row.get("artist_name")), norm_name(row.get("title")))
    return str(album_id) in _same_quality_copies({key: peers})


def refresh_album_peers(album):
    """Recompute marks for copies of one deleted album. Other albums stay as they are."""
    from resonance.fields import norm_name

    artist_id = album.get("artist_id")
    artist_name = album.get("artist_name") or ""
    mbid = str(album.get("musicbrainz_release_id") or "").strip()
    if not artist_id and not mbid:
        return []
    rows = db.fetchall(
        """
        SELECT albums.id, albums.title, albums.type, albums.edition, albums.path, albums.path_role,
               albums.quality_rank, albums.musicbrainz_release_id, albums.upgrade_source_id,
               artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.artist_id = %s
           OR lower(btrim(artists.name)) = lower(btrim(%s))
           OR (%s <> '' AND albums.musicbrainz_release_id = %s)
        """,
        (artist_id, artist_name, mbid, mbid),
    )
    title_rows, mbid_rows = album_groups_after_delete(album, rows)
    if not title_rows and not mbid_rows:
        return []
    types = _release_types([row["id"] for row in title_rows])
    peers = [_album_peer(row, types) for row in title_rows]
    key = (norm_name(artist_name), norm_name(album.get("title")))
    same_quality = _same_quality_copies({key: peers}) if peers else set()
    chosen = {}
    alive = {str(peer["id"]) for peer in peers}
    peer_by_id = {str(peer["id"]): peer for peer in peers}
    for peer in peers:
        source = higher_copy(peer, peers)
        if source:
            chosen[str(peer["id"])] = str(source["id"])
            continue
        stored = str(peer.get("upgrade_source_id") or "")
        match = peer_by_id.get(stored)
        if stored and stored in alive and stored != str(peer["id"]) and match and same_release_kind(peer, match):
            chosen[str(peer["id"])] = stored
    title_ids = [str(peer["id"]) for peer in peers]
    title_set = set(title_ids)
    mbid_dupes, mbid_alone = _mbid_membership(mbid)
    duplicates = {item for item in same_quality if item in title_set}
    duplicates.update(item for item in mbid_dupes if item in title_set)
    outside_dupes = [item for item in mbid_dupes if item not in title_set]
    outside_alone = []
    for item in mbid_alone:
        if item in title_set:
            continue
        if _same_quality_album(item):
            outside_dupes.append(item)
        else:
            outside_alone.append(item)
    with db.transaction() as conn:
        if title_ids:
            conn.execute(
                """
                UPDATE albums
                SET upgrade_source_id = NULL, duplicate_release = FALSE
                WHERE id = ANY(%s::uuid[])
                """,
                (db.uuid_array(title_ids),),
            )
        if chosen:
            conn.execute(
                """
                UPDATE albums AS album
                SET upgrade_source_id = data.source_id
                FROM unnest(%s::uuid[], %s::uuid[]) AS data(album_id, source_id)
                WHERE album.id = data.album_id
                """,
                (db.uuid_array(list(chosen)), db.uuid_array(list(chosen.values()))),
            )
        marked = list(duplicates)
        if marked:
            conn.execute(
                "UPDATE albums SET duplicate_release = TRUE WHERE id = ANY(%s::uuid[])",
                (db.uuid_array(marked),),
            )
        if outside_dupes:
            conn.execute(
                "UPDATE albums SET duplicate_release = TRUE WHERE id = ANY(%s::uuid[])",
                (db.uuid_array(outside_dupes),),
            )
        if outside_alone:
            conn.execute(
                "UPDATE albums SET duplicate_release = FALSE WHERE id = ANY(%s::uuid[])",
                (db.uuid_array(outside_alone),),
            )
        cleared = silence_dismissed_albums(conn, list(title_ids) + list(outside_dupes) + list(outside_alone))
    touched = list(dict.fromkeys(title_ids + outside_dupes + outside_alone + list(cleared or [])))
    return _album_flags(touched)


def _album_flags(ids):
    """The duplicate and upgrade flags now stored on these albums."""
    ids = [str(item) for item in ids or [] if item]
    if not ids:
        return []
    rows = db.fetchall(
        """
        SELECT id::text AS id, duplicate_release, upgrade_source_id
        FROM albums
        WHERE id = ANY(%s::uuid[])
        """,
        (db.uuid_array(ids),),
    )
    return [
        {
            "id": row["id"],
            "duplicate_release": bool(row.get("duplicate_release")),
            "upgrade": bool(row.get("upgrade_source_id")),
            "upgrade_path": "",
        }
        for row in rows
    ]


def duplicate_ids_after_dismiss(groups, pairs):
    """Album ids that still have a copy the user has not called off.

    A group of two loses the pill on both. A third copy that was not dismissed
    keeps the pill on itself and on the copies it still matches.
    """
    keep = set()
    for group in groups or []:
        ids = []
        seen = set()
        for item in group or []:
            text = str(item or "")
            if not text or text in seen:
                continue
            seen.add(text)
            ids.append(text)
        if len(ids) < 2:
            continue
        for item in ids:
            for other in ids:
                if other != item and frozenset((item, other)) not in pairs:
                    keep.add(item)
                    break
    return keep


def _dismissed_album_pairs(run):
    rows = run(
        "SELECT album_a::text AS album_a, album_b::text AS album_b FROM dismissed_album_duplicates"
    ).fetchall()
    return {frozenset((row["album_a"], row["album_b"])) for row in rows}


def _duplicate_peer_rows(run, album_ids):
    """Albums that can share a Duplicate pill with these ids, including a retitled remaster."""
    ids = [str(item) for item in album_ids or [] if item]
    if not ids:
        return []
    anchors = run(
        """
        SELECT albums.artist_id::text AS artist_id,
               albums.musicbrainz_release_id::text AS mbid,
               artists.name AS artist_name
        FROM albums
        JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = ANY(%s::uuid[])
        """,
        (db.uuid_array(ids),),
    ).fetchall()
    artist_ids = sorted({row["artist_id"] for row in anchors if row.get("artist_id")})
    mbids = sorted({row["mbid"] for row in anchors if row.get("mbid")})
    names = sorted({
        str(row.get("artist_name") or "").strip().lower()
        for row in anchors
        if str(row.get("artist_name") or "").strip()
    })
    clauses = ["albums.id = ANY(%s::uuid[])"]
    params = [db.uuid_array(ids)]
    if artist_ids:
        clauses.append("albums.artist_id = ANY(%s::uuid[])")
        params.append(db.uuid_array(artist_ids))
    if mbids:
        clauses.append("albums.musicbrainz_release_id = ANY(%s::uuid[])")
        params.append(db.uuid_array(mbids))
    if names:
        clauses.append("lower(btrim(artists.name)) = ANY(%s::text[])")
        params.append(db.text_array(names))
    return run(
        f"""
        SELECT albums.id::text AS id, albums.title, albums.type, albums.edition, albums.path,
               albums.path_role, albums.quality_rank, albums.musicbrainz_release_id,
               artists.name AS artist_name
        FROM albums
        JOIN artists ON artists.id = albums.artist_id
        WHERE {" OR ".join(clauses)}
        """,
        tuple(params),
    ).fetchall()


def _groups_touching(groups, album_ids):
    """Groups of two or more that contain one of these albums."""
    focus = {str(item) for item in album_ids or [] if item}
    related = []
    for group in groups or []:
        ids = []
        seen = set()
        for item in group or []:
            text = str(item or "")
            if not text or text in seen:
                continue
            seen.add(text)
            ids.append(text)
        if len(ids) > 1 and focus.intersection(ids):
            related.append(ids)
    return related


def reapply_album_duplicates(conn, album_ids):
    """Set the Duplicate pill from the same groups a scan uses, after a dismiss or an undo."""
    run = conn.execute
    ids = [str(item) for item in album_ids or [] if item]
    if not ids:
        return [], []
    rows = _duplicate_peer_rows(run, ids)
    pairs = _dismissed_album_pairs(run)
    related = _groups_touching(_duplicate_groups(rows), ids)
    keep = duplicate_ids_after_dismiss(related, pairs)
    touched = {item for group in related for item in group}
    marked = [item for item in touched if item in keep]
    cleared = [item for item in touched if item not in keep]
    if marked:
        run(
            "UPDATE albums SET duplicate_release = TRUE WHERE id = ANY(%s::uuid[])",
            (db.uuid_array(marked),),
        )
    if cleared:
        run(
            "UPDATE albums SET duplicate_release = FALSE WHERE id = ANY(%s::uuid[])",
            (db.uuid_array(cleared),),
        )
    return marked, cleared


def silence_dismissed_albums(conn=None, limit=None):
    """Take the Duplicate pill off dismissed albums that no longer match another copy.

    limit restricts the work to albums a delete just rewrote. A scan passes no limit
    and still only loads the artists those dismissed albums belong to.
    """
    if conn is None:
        with db.transaction() as owned:
            return silence_dismissed_albums(owned, limit)
    if limit is not None and not list(limit):
        return []
    run = conn.execute
    pairs = _dismissed_album_pairs(run)
    if not pairs:
        return []
    involved = {item for pair in pairs for item in pair}
    if limit is not None:
        involved &= {str(item) for item in limit}
    if not involved:
        return []
    rows = _duplicate_peer_rows(run, sorted(involved))
    related = _groups_touching(_duplicate_groups(rows), involved)
    keep = duplicate_ids_after_dismiss(related, pairs)
    cleared = [item for group in related for item in group if item in involved and item not in keep]
    cleared = list(dict.fromkeys(cleared))
    if cleared:
        run(
            "UPDATE albums SET duplicate_release = FALSE WHERE id = ANY(%s::uuid[])",
            (db.uuid_array(cleared),),
        )
    return cleared


def _duplicate_groups(rows, release_types=None):
    """MusicBrainz release groups and same-quality title groups that earn a Duplicate pill."""
    from resonance.fields import norm_name

    groups = []
    buckets = {}
    for row in rows or []:
        mbid = str(row.get("musicbrainz_release_id") or "").strip()
        if not mbid:
            continue
        buckets.setdefault((mbid, _album_type_bucket(row.get("type"))), []).append(str(row["id"]))
    groups.extend(ids for ids in buckets.values() if len(ids) > 1)
    types = release_types if release_types is not None else _release_types([row["id"] for row in rows or []])
    by_title = {}
    for row in rows or []:
        peer = _album_peer(row, types)
        key = (norm_name(peer.get("artist_name")), norm_name(peer.get("title")))
        if not key[0] or not key[1]:
            continue
        by_title.setdefault(key, []).append(peer)
    for group in by_title.values():
        by_kind = {}
        for peer in group:
            by_kind.setdefault(release_kind(peer), []).append(peer)
        for kind_group in by_kind.values():
            if len(kind_group) < 2:
                continue
            ranks = {int(peer.get("quality_rank") or 0) for peer in kind_group}
            if len(ranks) != 1:
                continue
            groups.append([str(peer["id"]) for peer in kind_group])
    return groups


def _same_quality_copies(by_title):
    """Copies of one title and release kind whose sound quality matches.

    A better-sounding copy is an upgrade. These are the pairs that would
    otherwise show neither pill, including a title such as ( ).
    """
    marked = set()
    for group in by_title.values():
        by_kind = {}
        for peer in group:
            by_kind.setdefault(release_kind(peer), []).append(peer)
        for kind_group in by_kind.values():
            if len(kind_group) < 2:
                continue
            ranks = {int(peer.get("quality_rank") or 0) for peer in kind_group}
            if len(ranks) != 1:
                continue
            for peer in kind_group:
                marked.add(str(peer["id"]))
    return marked


def store_original_years(conn=None):
    """Copy the first track originaldate or originalyear onto the album."""
    execute = conn.execute if conn is not None else db.execute
    execute(
        """
        /* curator-original-year */
        UPDATE albums AS album
        SET original_year = src.original_year
        FROM (
            SELECT DISTINCT ON (album_id)
                   album_id,
                   substring(
                       COALESCE(NULLIF(tags->>'originaldate', ''), NULLIF(tags->>'originalyear', ''))
                       from '^[0-9]{4}'
                   )::int AS original_year
            FROM tracks
            WHERE COALESCE(NULLIF(tags->>'originaldate', ''), NULLIF(tags->>'originalyear', '')) ~ '^[0-9]{4}'
            ORDER BY album_id, disc_number, track_number
        ) AS src
        WHERE album.id = src.album_id
          AND album.original_year IS DISTINCT FROM src.original_year
        """
    )
    execute(
        """
        /* curator-original-year */
        UPDATE albums
        SET original_year = NULL
        WHERE original_year IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM tracks
              WHERE tracks.album_id = albums.id
                AND COALESCE(NULLIF(tags->>'originaldate', ''), NULLIF(tags->>'originalyear', '')) ~ '^[0-9]{4}'
          )
        """
    )


def comparison_source(album, peers):
    """The better copy to show, including one already stored on the album.

    A scan can record an upgrade, and a later edit can make that copy a different
    edition or the same quality. The pill still opens the comparison.
    """
    source = upgrade_source(album, peers)
    if source:
        return source
    source_id = str(album.get("upgrade_source_id") or "")
    if not source_id or source_id == str(album.get("id")):
        return None
    for peer in peers or []:
        if str(peer.get("id")) == source_id and same_release_kind(album, peer):
            return peer
    return None


def compare(album_id):
    album, tracks, peers = _subject(album_id)
    _note_release_types(album, tracks, peers)
    source = comparison_source(album, peers)
    if not source:
        _drop_other_kind(album, peers)
        # Nothing to compare with: the Upgrade mark is stale.
        clear_marks(album["id"], duplicate=False, upgrade=True)
        return {"upgrade": None, "cleared": True}
    ordered = similar_copies(album, peers)
    if not any(str(peer.get("id")) == str(album.get("id")) for peer in ordered):
        ordered = [album] + list(ordered)
    if not any(str(peer.get("id")) == str(source.get("id")) for peer in ordered):
        ordered.append(source)
    grouped = _tracks_by_album([row["id"] for row in ordered])
    grouped.setdefault(str(album["id"]), tracks)
    current_card = release_card(album, grouped.get(str(album["id"]), tracks))
    current_rank = int(album.get("quality_rank") or 0)
    copies = []
    for peer in ordered:
        peer_tracks = grouped.get(str(peer["id"]), [])
        card = current_card if str(peer["id"]) == str(album["id"]) else release_card(peer, peer_tracks)
        rank = int(peer.get("quality_rank") or 0)
        relation = {"same_edition": True} if str(peer["id"]) == str(album["id"]) else edition_notice(current_card, card)
        copies.append({
            "album": _public(peer),
            "audio": format_summary(peer_tracks),
            "path": peer.get("path") or "",
            "release_group": str(peer.get("musicbrainz_release_group_id") or ""),
            "release": card,
            "current": str(peer["id"]) == str(album["id"]),
            "better": rank > current_rank,
            "quality_rank": rank,
            "same_edition": relation["same_edition"],
        })
    edition = group_notice(current_card, [copy["release"] for copy in copies if not copy["current"]])
    from curator import arr_ids

    arr_ids.albums(copies)
    return {
        "upgrade": _upgrade_payload(source),
        "same_edition": edition["same_edition"],
        "notice": edition["notice"],
        "copies": copies,
    }


def replace(album_id, source_id, purge=False):
    album = db.fetchone(
        """
        SELECT albums.*, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (album_id,),
    )
    source = db.fetchone(
        """
        SELECT albums.*, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (source_id,),
    )
    if not album or not source:
        raise AppError("Album not found", 404)
    if not upgrade_source(album, [album, source]):
        raise AppError("That copy is not a better release of this album")
    assert_library_writable(album["path"])
    root = _library_root(album["path"])
    if not root:
        raise AppError("The album is outside the music library")
    library_tracks = db.fetchall("SELECT * FROM tracks WHERE album_id = %s", (album_id,))
    source_tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (source_id,),
    )
    if not source_tracks:
        raise AppError("The better copy has no audio files")
    created = []
    committed = False
    try:
        for track in source_tracks:
            src = track["file_path"]
            if not os.path.isfile(src):
                raise AppError("A file from the better copy is missing")
            dest = _destination(album["path"], source["path"], src)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not inside(root, dest):
                raise AppError("The upgraded file would leave the music folder")
            incoming = dest + ".incoming" if os.path.exists(dest) else dest
            shutil.copy2(src, incoming)
            created.append((incoming, dest, incoming != dest, src))
            if not _verified(src, incoming):
                raise AppError(f"The copied file failed verification: {os.path.basename(dest)}")
        finals = []
        for incoming, dest, replacing, src in created:
            if replacing:
                _retire(dest, album, root, purge)
                os.replace(incoming, dest)
            finals.append((src, dest))
        _carry_lyrics(library_tracks, source_tracks, finals)
        for track in library_tracks:
            path = track["file_path"]
            if path and os.path.isfile(path) and path not in {dest for _src, dest in finals}:
                _retire(path, album, root, purge)
        committed = True
    except Exception:
        if not committed:
            for incoming, dest, replacing, _src in created:
                if os.path.isfile(incoming) and (replacing or incoming == dest):
                    try:
                        os.remove(incoming)
                    except OSError:
                        logger.info("could not remove unfinished copy %s", incoming)
        raise
    from resonance.scanner import _scan_album
    from resonance.settings import load as load_settings

    artist_path = os.path.dirname(album["path"])
    _scan_album(album["artist_id"], artist_path, album["path"], load_settings(), "incremental")
    removed_source = None
    warning = ""
    if purge:
        removed_source, warning = _drop_source_copy(source, album)
    refresh_stored()
    result = compare(album_id)
    if removed_source:
        result["removed_source"] = removed_source
    if warning:
        result["warning"] = warning
    return result


def _upgrade_payload(source):
    return {
        "album_id": str(source["id"]),
        "title": source.get("title"),
        "path": source.get("path"),
        "path_role": source.get("path_role") or "library",
        "quality_rank": int(source.get("quality_rank") or 0),
    }


def _public(album):
    return {
        "id": str(album["id"]),
        "title": album.get("title"),
        "artist": album.get("artist_name") or "",
        "path_role": album.get("path_role") or "library",
    }


def shared_folder_block(target, others):
    """Refuse a delete that would remove another indexed album."""
    target_real = os.path.normcase(os.path.abspath(target or ""))
    if not target_real:
        return "The album folder is missing"
    for other in others or []:
        other_real = os.path.normcase(os.path.abspath(other or ""))
        if not other_real:
            continue
        if other_real == target_real:
            return "Another indexed album uses this same folder"
        if other_real.startswith(target_real + os.sep):
            return "Another indexed album is inside this folder"
    return ""


def discard(album_id):
    """Permanently delete one album folder and drop it from the index."""
    album = db.fetchone(
        """
        SELECT albums.*, artists.name AS artist_name, artists.musicbrainz_artist_id
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (album_id,),
    )
    if not album:
        raise AppError("Album not found", 404)
    path = album.get("path") or ""
    assert_library_writable(path)
    root = _library_root(path)
    if not root or not inside(root, path):
        raise AppError("The album is outside the music library")
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    if os.path.normcase(real_path) == os.path.normcase(real_root):
        raise AppError("Refusing to delete a music library root")
    others = db.fetchall("SELECT path FROM albums WHERE id <> %s", (album_id,))
    blocked = shared_folder_block(real_path, [row.get("path") or "" for row in others])
    if blocked:
        raise AppError(blocked)
    track_ids = [
        row["id"] for row in db.fetchall("SELECT id::text AS id FROM tracks WHERE album_id = %s", (album_id,))
    ]
    if os.path.isdir(real_path):
        shutil.rmtree(real_path)
    elif os.path.isfile(real_path):
        os.remove(real_path)
    db.execute("DELETE FROM albums WHERE id = %s", (album_id,))
    peers = refresh_album_peers(album)
    _rescan_lidarr_after_discard(album)
    return {
        "deleted": str(album["id"]),
        "title": album.get("title") or "",
        "artist": album.get("artist_name") or "",
        "peers": peers or [],
        "track_ids": track_ids,
    }


def _rescan_lidarr_after_discard(album):
    """Trigger Lidarr rescan and clear cache if artist still has surviving albums."""
    try:
        from curator import arr_ids

        arr_ids.clear_cache("lidarr")
        mbid = str(album.get("musicbrainz_artist_id") or "").strip()
        artist_id = album.get("artist_id")
        if mbid and artist_id:
            surviving = db.fetchone("SELECT id FROM albums WHERE artist_id = %s LIMIT 1", (artist_id,))
            if surviving:
                from resonance import lidarr

                lidarr.rescan_artist(artist_mbid=mbid)
    except Exception as exc:
        logger.warning("Failed triggering Lidarr rescan after discard: %s", exc)



def release_card(album, tracks):
    """Year, country, track count, and edition text for one indexed copy."""
    tags = _release_tags(tracks)
    edition = str(album.get("edition") or "").strip()
    release_type = tags.get("releasetype") or ""
    year = album.get("release_year")
    return {
        "title": album.get("title") or "",
        "year": year if year else None,
        "original_year": _original_year(tracks),
        "country": str(album.get("country") or tags.get("releasecountry") or "").strip(),
        "tracks": len(tracks) if tracks else int(album.get("total_tracks") or 0),
        "version": version_label(edition, release_type, album.get("type")),
        "edition": edition,
        "catalog": str(album.get("catalog") or tags.get("catalognumber") or "").strip(),
        "label": str(album.get("label") or tags.get("label") or "").strip(),
        "release_id": str(album.get("musicbrainz_release_id") or ""),
    }


_EDITION_NAMES = {
    "remaster": "Remastered edition",
    "remastered": "Remastered edition",
    "anniversary": "Anniversary edition",
    "deluxe": "Deluxe edition",
    "super deluxe": "Super deluxe edition",
    "expanded": "Expanded edition",
    "special edition": "Special edition",
    "mono": "Mono edition",
    "stereo": "Stereo edition",
}

_TYPE_NAMES = {
    "album": "Original studio album",
    "live": "Live album",
    "compilation": "Compilation",
    "ep": "EP",
    "single": "Single",
}


def version_label(edition, release_type, album_type):
    text = str(edition or "").strip()
    kind = str(release_type or "").strip()
    if not kind and album_type and str(album_type) not in {"", "unknown"}:
        kind = str(album_type)
    named = _EDITION_NAMES.get(text.lower())
    if named:
        return named
    if text:
        return text
    lowered = kind.lower()
    if "anniversary" in lowered:
        return "Anniversary edition"
    if "remaster" in lowered:
        return "Remastered edition"
    if "deluxe" in lowered:
        return "Deluxe edition"
    if "expanded" in lowered:
        return "Expanded edition"
    if "live" in lowered:
        return "Live album"
    if "compilation" in lowered:
        return "Compilation"
    return _TYPE_NAMES.get(lowered, kind or "Studio album")


def group_notice(current, others):
    cards = list(others or [])
    if len(cards) == 1:
        return edition_notice(current, cards[0])
    different = sum(1 for card in cards if not edition_notice(current, card)["same_edition"])
    total = len(cards) + 1
    if not different:
        return {
            "same_edition": True,
            "notice": (
                f"{total} copies of this album are indexed. They are the same edition. "
                "Choose which copy replaces the open album. Close this dialog to keep every copy."
            ),
        }
    differ = "differs" if different == 1 else "differ"
    return {
        "same_edition": False,
        "notice": (
            f"{total} copies of this album are indexed. {different} {differ} in year, country, edition, catalog, or track count. "
            "Choose which copy replaces the open album. Close this dialog to keep every copy."
        ),
    }


def edition_notice(current, other):
    reasons = []
    left_id = str(current.get("release_id") or "")
    right_id = str(other.get("release_id") or "")
    if left_id and right_id and left_id != right_id:
        reasons.append("a different MusicBrainz release")
    labels = (
        ("year", "a different year"),
        ("country", "a different country"),
        ("version", "a different edition"),
        ("catalog", "a different catalog number"),
        ("tracks", "a different track count"),
    )
    for key, phrase in labels:
        left = current.get(key)
        right = other.get(key)
        if left in (None, "") or right in (None, ""):
            continue
        if str(left) != str(right):
            reasons.append(phrase)
    if not reasons:
        return {
            "same_edition": True,
            "notice": "This is the same edition at higher audio quality.",
        }
    return {
        "same_edition": False,
        "notice": (
            "This is "
            + _phrase_list(reasons)
            + ". Replacing the current copy archives those files. Close this dialog to keep both editions."
        ),
    }


def _original_year(tracks):
    from resonance.fields import year_from

    for track in tracks or []:
        raw = track.get("tags") or {}
        if not isinstance(raw, dict):
            continue
        for key in ("originaldate", "originalyear"):
            year = year_from(raw.get(key))
            if year:
                return year
    return None


def _release_tags(tracks):
    found = {}
    keys = ("releasetype", "catalognumber", "label", "releasecountry", "releasestatus", "barcode", "media")
    for track in tracks or []:
        raw = track.get("tags") or {}
        if not isinstance(raw, dict):
            continue
        for key in keys:
            value = str(raw.get(key) or "").strip()
            if value and key not in found:
                found[key] = value
    return found


def _phrase_list(items):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _tracks_by_album(album_ids):
    grouped = {}
    if not album_ids:
        return grouped
    rows = db.fetchall("SELECT * FROM tracks WHERE album_id = ANY(%s)", (list(album_ids),))
    for track in rows:
        grouped.setdefault(str(track["album_id"]), []).append(track)
    return grouped


def _note_release_types(album, tracks, peers):
    """Copy the release-type tag onto the open album and the copies it might be paired with."""
    from resonance.fields import norm_name

    album["release_type"] = _tag_release_type(tracks)
    artist = norm_name(album.get("artist_name"))
    title = norm_name(album.get("title"))
    stored = str(album.get("upgrade_source_id") or "")
    wanted = []
    for peer in peers or []:
        if str(peer.get("id")) == stored or (
            norm_name(peer.get("artist_name")) == artist and norm_name(peer.get("title")) == title
        ):
            wanted.append(peer)
    types = _release_types([peer.get("id") for peer in wanted])
    for peer in wanted:
        peer["release_type"] = types.get(str(peer.get("id")), "")


def _tag_release_type(tracks):
    ordered = sorted(tracks or [], key=lambda row: (row.get("disc_number") or 1, row.get("track_number") or 0))
    for track in ordered:
        text = str((track.get("tags") or {}).get("releasetype") or "").strip()
        if text:
            return text
    return ""


def _release_types(album_ids):
    ids = [str(item) for item in album_ids or [] if item]
    if not ids:
        return {}
    rows = db.fetchall(
        """
        SELECT DISTINCT ON (album_id)
               album_id::text AS album_id, tags->>'releasetype' AS release_type
        FROM tracks
        WHERE album_id = ANY(%s::uuid[])
          AND COALESCE(tags->>'releasetype', '') <> ''
        ORDER BY album_id, disc_number, track_number
        """,
        (db.uuid_array(ids),),
    )
    return {str(row["album_id"]): row.get("release_type") or "" for row in rows}


def _drop_other_kind(album, peers):
    """Forget an upgrade that pairs two different release types."""
    stored = str(album.get("upgrade_source_id") or "")
    if not stored or stored == str(album.get("id")):
        return
    match = next((peer for peer in peers or [] if str(peer.get("id")) == stored), None)
    if not match or same_release_kind(album, match):
        return
    db.execute(
        "UPDATE albums SET upgrade_source_id = NULL WHERE id = %s AND upgrade_source_id = %s",
        (album["id"], stored),
    )
    album["upgrade_source_id"] = None


def _subject(album_id):
    album = db.fetchone(
        """
        SELECT albums.*, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        WHERE albums.id = %s
        """,
        (album_id,),
    )
    if not album:
        raise AppError("Album not found", 404)
    tracks = db.fetchall("SELECT * FROM tracks WHERE album_id = %s", (album_id,))
    peers = db.fetchall(
        """
        SELECT albums.*, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        """
    )
    return album, tracks, peers


def _destination(library_path, source_root, source_file):
    relative = os.path.relpath(source_file, source_root)
    if relative.startswith(".."):
        relative = os.path.basename(source_file)
    relative = relative.replace("\\", "/")
    parts = [part for part in relative.split("/") if part and part not in {".", ".."}]
    return os.path.join(library_path, *parts)


def _verified(source, copy):
    try:
        if os.path.getsize(copy) != os.path.getsize(source):
            return False
    except OSError:
        return False
    if copy.lower().endswith(".flac") and shutil.which("flac"):
        completed = subprocess.run(["flac", "-t", "-s", copy], capture_output=True, check=False)
        return completed.returncode == 0
    return True


def _drop_source_copy(source, album):
    """Remove the copy the files came from, once those files are in the library album."""
    source_path = os.path.realpath(source.get("path") or "") if source.get("path") else ""
    album_path = os.path.realpath(album.get("path") or "") if album.get("path") else ""
    if not source_path or not album_path or paths_overlap(source_path, album_path):
        return None, "The other copy shares this album folder, so it is still in the library."
    try:
        return discard(source["id"]), ""
    except AppError as exc:
        return None, str(exc)


def paths_overlap(left, right):
    left_real = os.path.normcase(os.path.abspath(left or ""))
    right_real = os.path.normcase(os.path.abspath(right or ""))
    if not left_real or not right_real:
        return True
    if left_real == right_real:
        return True
    return left_real.startswith(right_real + os.sep) or right_real.startswith(left_real + os.sep)


def _retire(path, album, root, purge):
    if not path or not os.path.isfile(path):
        return
    if purge:
        os.remove(path)
        return
    folder = os.path.join(root, "_archive", _safe(album.get("artist_name")), _safe(album.get("title")))
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, os.path.basename(path))
    if os.path.exists(dest):
        stem, ext = os.path.splitext(dest)
        dest = f"{stem}-2{ext}"
    if not inside(root, dest):
        raise AppError("The archive folder would leave the music folder")
    shutil.move(path, dest)


def _carry_lyrics(library_tracks, source_tracks, finals):
    from resonance.fields import norm_name

    by_title = {}
    for track in library_tracks:
        by_title.setdefault(norm_name(track.get("title")), track["file_path"])
    sources = {track["file_path"]: track for track in source_tracks}
    for src, dest in finals:
        track = sources.get(src) or {}
        old = by_title.get(norm_name(track.get("title")))
        if not old:
            continue
        old_stem, _ext = os.path.splitext(old)
        new_stem, _ext = os.path.splitext(dest)
        for suffix in (".lrc", ".txt"):
            sidecar = old_stem + suffix
            target = new_stem + suffix
            if os.path.isfile(sidecar) and not os.path.isfile(target):
                shutil.copy2(sidecar, target)


def _library_root(path):
    real = os.path.realpath(path)
    matches = [os.path.realpath(root) for root in music_roots() if inside(root, real) and path_role(root) != "inbox"]
    if not matches:
        matches = [os.path.realpath(root) for root in music_roots() if inside(root, real)]
    if not matches:
        return ""
    return max(matches, key=len)


def _safe(name):
    cleaned = "".join("-" if char in '\\/:*?"<>|' else char for char in str(name or "")).strip()
    return cleaned[:120] or "unknown"


def rank_for(tracks):
    return album_score(tracks)
