import threading

from resonance import db
from resonance.errors import AppError


def groups(focus=None, lidarr=True):
    """Album pairs that share an AcoustID recording or an identical fingerprint, plus pairs that
    carry the Duplicate pill for another reason: the same artist and title, or the same MusicBrainz
    release. Without those, an album could show the pill and an empty window.

    Duplicate marks left behind by a copy that is gone are cleared first. The ids that lost their
    mark come back as "cleared". lidarr=False leaves out which copy Lidarr uses: the window asks for that
    afterwards (lidarr_labels), so it opens without waiting for Lidarr.
    """
    from resonance import upgrade

    if focus:
        return _focused(str(focus), lidarr)
    cleared = list(upgrade.clear_orphan_flags())
    result = {"pairs": _all_pairs()}
    if lidarr:
        _label_lidarr(result["pairs"], focus)
    result["cleared"] = cleared
    return result


def lidarr_labels(focus=None):
    """Which copy Lidarr uses, for the pairs the Duplicate window shows: {album id: label}. Read after the window
    opened, so a slow Lidarr does not hold it up. The marks are not recorded again here."""
    if focus:
        from resonance.library import require_uuid

        focus = require_uuid(focus)
        pairs = _focused_pairs(focus, set(_copy_candidates(focus)), _sharing_albums(focus))
    else:
        pairs = _all_pairs()
    _label_lidarr(pairs, focus)
    labels = {}
    for pair in pairs:
        for side in (pair.get("left") or {}, pair.get("right") or {}):
            if side.get("id") and side.get("arr"):
                labels[str(side["id"])] = side["arr"]
    return {"labels": labels}


def _all_pairs():
    pairs = _groups()["pairs"]
    return pairs + _release_pairs(pairs)


def _copy_candidates(album_id):
    from resonance import upgrade

    return upgrade._copy_candidates([album_id])


def _focused(album_id, lidarr=True):
    """The pairs of one album, for its Duplicate pill: read only that album and its possible copies.

    Its copies are the albums of an artist with the same name or with the same MusicBrainz release, and the albums
    that share a recording or a fingerprint with it. The marks of those are recorded again first, so a mark that no
    longer holds is cleared ("cleared") instead of opening an empty window. The whole library is not read."""
    from resonance import upgrade
    from resonance.library import require_uuid

    album_id = require_uuid(album_id)
    candidates = set(_copy_candidates(album_id))
    sharing = _sharing_albums(album_id)
    watched = sorted(candidates | sharing | {album_id})
    marked = lambda: {str(row["id"]) for row in db.fetchall(  # noqa: E731
        "SELECT id::text AS id FROM albums WHERE id = ANY(%s::uuid[]) AND duplicate_release", (db.uuid_array(watched),))}
    before = marked()
    upgrade.refresh_stored([album_id])
    cleared = sorted(before - marked())
    result = {"pairs": _focused_pairs(album_id, candidates, sharing)}
    if lidarr:
        _label_lidarr(result["pairs"], album_id)
    result["cleared"] = cleared
    return result


def _focused_pairs(album_id, candidates, sharing):
    pairs = _groups(sorted(sharing | {album_id}))["pairs"] if sharing else []
    return [pair for pair in pairs + _release_pairs(pairs, only=sorted(candidates | {album_id}))
            if album_id in (str((pair.get("left") or {}).get("id")), str((pair.get("right") or {}).get("id")))]


def _sharing_albums(album_id):
    """Albums with a track whose AcoustID recording or fingerprint one of this album's tracks has too."""
    # Two equality joins, each on its own index: one join with OR between them reads every track in the library.
    rows = db.fetchall(
        """
        SELECT other.album_id::text AS id
        FROM tracks mine
        JOIN tracks other ON other.acoustid_recording_id = mine.acoustid_recording_id AND other.album_id <> mine.album_id
        WHERE mine.album_id = %s AND mine.acoustid_recording_id IS NOT NULL
        UNION
        SELECT other.album_id::text AS id
        FROM tracks mine
        JOIN tracks other ON other.fingerprint_hash = mine.fingerprint_hash AND other.album_id <> mine.album_id
        WHERE mine.album_id = %s AND COALESCE(mine.fingerprint_hash, '') <> ''
          AND other.fingerprint_hash IS NOT NULL AND other.fingerprint_hash <> ''
        """,
        (album_id, album_id),
    )
    return {row["id"] for row in rows}


def _label_lidarr(pairs, focus=None):
    """Say which copy Lidarr uses, on every pair the window shows. A window for one album asks only about its pairs."""
    from curator import arr_ids

    if focus:
        pairs = [pair for pair in pairs if str(focus) in (str((pair.get("left") or {}).get("id")), str((pair.get("right") or {}).get("id")))]
    arr_ids.album_groups([[pair.get("left") or {}, pair.get("right") or {}] for pair in pairs])


def _release_pairs(listed, only=None):
    """Pairs of flagged albums that are copies by name or by MusicBrainz release, not yet listed. only limits the
    albums read to those ids (one album's possible copies)."""
    from resonance.fields import norm_name
    from resonance.quality import same_release_kind

    rows = db.fetchall(
        """
        SELECT albums.id, albums.title, albums.path, albums.release_year, albums.edition, albums.type,
               albums.musicbrainz_release_group_id, albums.musicbrainz_release_id::text AS mbid,
               albums.duplicate_release, artists.name AS artist_name,
               (SELECT count(*)::int FROM tracks t WHERE t.album_id = albums.id) AS track_count
        FROM albums JOIN artists ON artists.id = albums.artist_id
        """ + ("" if only is None else "WHERE albums.id = ANY(%s::uuid[])"),
        () if only is None else (db.uuid_array(list(only)),),
    )
    seen = set()
    for pair in listed:
        left, right = (pair.get("left") or {}).get("id"), (pair.get("right") or {}).get("id")
        seen.add(frozenset((str(left), str(right))))
    by_name, by_release = {}, {}
    for row in rows:
        by_name.setdefault((norm_name(row["artist_name"]), norm_name(row["title"])), []).append(row)
        if row["mbid"]:
            by_release.setdefault(row["mbid"], []).append(row)
    wanted = []
    for reason, bucket in (("Same artist and title", by_name), ("Same MusicBrainz release", by_release)):
        for group in bucket.values():
            if len(group) < 2 or not any(item["duplicate_release"] for item in group):
                continue
            for index, left in enumerate(group):
                for right in group[index + 1:]:
                    key = frozenset((str(left["id"]), str(right["id"])))
                    if key in seen or not same_release_kind(left, right, "duplicate"):        # a remix album is not a copy
                        continue
                    seen.add(key)
                    wanted.append((reason, left, right))
    if not wanted:
        return []
    ids = list({str(row["id"]) for _reason, left, right in wanted for row in (left, right)})
    tracks = db.fetchall(
        """
        SELECT id, album_id, title, disc_number, track_number, file_format, file_path,
               bit_depth, sample_rate, bitrate,
               acoustid_recording_id::text AS acoustid_recording_id, fingerprint_hash
        FROM tracks WHERE album_id = ANY(%s::uuid[])
        """,
        (db.uuid_array(ids),),
    )
    years = _original_years(ids)
    by_album = {}
    for track in tracks:
        by_album.setdefault(str(track["album_id"]), []).append(track)
    for items in by_album.values():
        items.sort(key=lambda row: (row.get("disc_number") or 1, row.get("track_number") or 0, str(row.get("id"))))
    pairs = []
    for reason, left, right in wanted:
        for album in (left, right):
            album["original_year"] = years.get(str(album["id"]))
        left_id, right_id = str(left["id"]), str(right["id"])
        left_tracks, right_tracks = by_album.get(left_id, []), by_album.get(right_id, [])
        pairs.append({
            "acoustid_matches": 0, "fingerprint_matches": 0, "reason": reason,
            "left": _album_public(left, left_id, left_tracks),
            "right": _album_public(right, right_id, right_tracks),
            "rows": _aligned_rows(left_tracks, right_tracks, [], []),
        })
    pairs.sort(key=lambda item: ((item["left"].get("artist") or "").casefold(), (item["left"].get("title") or "").casefold()))
    return pairs


def _groups(album_ids=None):
    """Album pairs that share an AcoustID recording or an identical fingerprint. album_ids skips the library-wide
    search for such albums and pairs only those."""
    dismissed = {
        (str(row["track_a"]), str(row["track_b"]))
        for row in db.fetchall("SELECT track_a, track_b FROM dismissed_duplicates")
    }
    album_ids = list(album_ids) if album_ids is not None else _shared_album_ids()
    if not album_ids:
        return {"pairs": []}
    albums = db.fetchall(
        """
        SELECT al.id, al.title, al.path, al.release_year, al.edition, al.type,
               al.musicbrainz_release_group_id, ar.name AS artist_name
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE al.id = ANY(%s::uuid[])
        """,
        (db.uuid_array(album_ids),),
    )
    years = _original_years(album_ids)
    for album in albums:
        album["original_year"] = years.get(str(album["id"]))
    tracks = db.fetchall(
        """
        SELECT id, album_id, title, disc_number, track_number, file_format, file_path,
               bit_depth, sample_rate, bitrate,
               acoustid_recording_id::text AS acoustid_recording_id, fingerprint_hash
        FROM tracks
        WHERE album_id = ANY(%s::uuid[])
        """,
        (db.uuid_array(album_ids),),
    )
    return {"pairs": album_pairs(albums, tracks, dismissed)}


def _track_pairs(pairs, left_id=None, right_id=None):
    from resonance.library import require_uuid

    incoming = list(pairs or [])
    if not incoming and left_id and right_id:
        incoming = [{"left_id": left_id, "right_id": right_id}]
    stored = []
    for item in incoming:
        if not isinstance(item, dict):
            continue
        pair = sorted([str(require_uuid(item.get("left_id"))), str(require_uuid(item.get("right_id")))])
        if pair[0] == pair[1]:
            raise AppError("Choose two different tracks")
        stored.append(pair)
    if not stored:
        raise AppError("Choose two different tracks")
    return stored


def dismiss(left_id, right_id, pairs=None):
    stored = _track_pairs(pairs, left_id, right_id)
    with db.transaction() as conn:
        for pair in stored:
            conn.execute(
                """
                INSERT INTO dismissed_duplicates (track_a, track_b)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (pair[0], pair[1]),
            )
        cleared = _dismiss_albums(conn, stored)
    return {"dismissed": len(stored), "cleared": cleared, "pairs": [{"left_id": pair[0], "right_id": pair[1]} for pair in stored]}


def restore(pairs=None):
    """Put a Not duplicates choice back, including the pills it removed."""
    stored = _track_pairs(pairs)
    with db.transaction() as conn:
        album_ids = _album_pairs_for(conn, stored)
        for pair in stored:
            conn.execute(
                "DELETE FROM dismissed_duplicates WHERE track_a = %s AND track_b = %s",
                (pair[0], pair[1]),
            )
        for left, right in album_ids:
            conn.execute(
                "DELETE FROM dismissed_album_duplicates WHERE album_a = %s AND album_b = %s",
                (left, right),
            )
        from resonance.upgrade import reapply_album_duplicates

        marked, _cleared = reapply_album_duplicates(conn, [item for pair in album_ids for item in pair])
    return {"restored": len(stored), "marked": marked}


def _album_pairs_for(conn, track_pairs):
    track_ids = [item for pair in track_pairs for item in pair]
    rows = conn.execute(
        "SELECT id::text AS id, album_id::text AS album_id FROM tracks WHERE id = ANY(%s::uuid[])",
        (db.uuid_array(track_ids),),
    ).fetchall()
    album_of = {row["id"]: row["album_id"] for row in rows if row.get("album_id")}
    found = set()
    for left, right in track_pairs:
        albums = sorted({album_of.get(left) or "", album_of.get(right) or ""} - {""})
        if len(albums) == 2:
            found.add(tuple(albums))
    return found


def _dismiss_albums(conn, track_pairs):
    """Remember the albums behind a Not duplicates click and drop their pills when no other copy remains."""
    stored = _album_pairs_for(conn, track_pairs)
    for left, right in stored:
        conn.execute(
            """
            INSERT INTO dismissed_album_duplicates (album_a, album_b)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (left, right),
        )
    if not stored:
        return []
    from resonance.upgrade import reapply_album_duplicates

    album_ids = [item for pair in stored for item in pair]
    _marked, cleared = reapply_album_duplicates(conn, album_ids)
    return cleared


def start_scan():
    if not _lock.acquire(blocking=False):
        return current_job(), False
    try:
        row = db.fetchone(
            """
            INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at)
            VALUES ('fingerprint', 'running', 'Fingerprinting tracks', 0, 0, '', NOW())
            RETURNING *
            """
        )
    except Exception:
        _lock.release()
        raise

    def run():
        try:
            _fingerprint_missing(row["id"])
        except Exception as exc:
            db.execute(
                """
                UPDATE work_jobs
                SET status = 'failed', message = %s, finished_at = NOW()
                WHERE id = %s AND status = 'running'
                """,
                (str(exc)[:300], row["id"]),
            )
        finally:
            _lock.release()

    threading.Thread(target=run, name="fingerprint-duplicates", daemon=True).start()
    return row, True


def current_job():
    row = db.fetchone(
        """
        SELECT * FROM work_jobs
        WHERE kind = 'fingerprint'
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
        """
    )
    return row or {"status": "idle", "message": "Idle", "processed": 0, "total": 0}


def _fingerprint_missing(job_id):
    from resonance.sources import fingerprint

    tracks = db.fetchall(
        """
        SELECT id, file_path FROM tracks
        WHERE fingerprint_hash IS NULL
        ORDER BY file_path
        """
    )
    db.execute("UPDATE work_jobs SET total = %s WHERE id = %s", (len(tracks), job_id))
    processed = 0
    for track in tracks:
        result = fingerprint.fingerprint_tracks([track["file_path"]], limit=None)
        for item in result.get("files") or []:
            db.execute(
                """
                UPDATE tracks
                SET fingerprint_hash = COALESCE(%s, fingerprint_hash),
                    acoustid_recording_id = COALESCE(%s, acoustid_recording_id),
                    acoustid_score = COALESCE(%s, acoustid_score)
                WHERE file_path = %s
                """,
                (item.get("fingerprint_hash"), item.get("recording_id"), item.get("score"), item.get("path")),
            )
        processed += 1
        if processed % 5 == 0:
            db.execute("UPDATE work_jobs SET processed = %s WHERE id = %s", (processed, job_id))
    db.execute(
        """
        UPDATE work_jobs
        SET status = 'completed', message = %s, processed = %s, finished_at = NOW()
        WHERE id = %s
        """,
        (f"Fingerprinted {processed} tracks", processed, job_id),
    )


def _shared_album_ids():
    rows = db.fetchall(
        """
        SELECT DISTINCT album_id FROM tracks
        WHERE acoustid_recording_id IN (
            SELECT acoustid_recording_id FROM tracks
            WHERE acoustid_recording_id IS NOT NULL
            GROUP BY acoustid_recording_id
            HAVING COUNT(DISTINCT album_id) > 1
        )
        UNION
        SELECT DISTINCT album_id FROM tracks
        WHERE fingerprint_hash IN (
            SELECT fingerprint_hash FROM tracks
            WHERE fingerprint_hash IS NOT NULL AND fingerprint_hash <> ''
            GROUP BY fingerprint_hash
            HAVING COUNT(DISTINCT album_id) > 1
        )
        """
    )
    return [row["album_id"] for row in rows]


def album_pairs(albums, tracks, dismissed):
    """Side-by-side album pairs. Matching files share a row and the rest of each album follows."""
    by_album = {}
    for track in tracks or []:
        by_album.setdefault(str(track["album_id"]), []).append(track)
    for rows in by_album.values():
        rows.sort(key=lambda row: (row.get("disc_number") or 1, row.get("track_number") or 0, str(row.get("id"))))
    album_by_id = {str(row["id"]): row for row in albums or []}
    matches = {}
    _add_matches(matches, _index(tracks, "acoustid_recording_id"), "acoustid", dismissed, {})
    used = {
        pair: {str(track["id"]) for couple in rows for track in couple}
        for pair, rows in ((key, value["acoustid"]) for key, value in matches.items())
    }
    _add_matches(matches, _index(tracks, "fingerprint_hash"), "fingerprint", dismissed, used)
    pairs = []
    for (left_id, right_id), kinds in matches.items():
        acoustid = kinds["acoustid"]
        fingerprint = [
            couple
            for couple in kinds["fingerprint"]
            if str(couple[0]["id"]) not in used.get((left_id, right_id), set())
            and str(couple[1]["id"]) not in used.get((left_id, right_id), set())
        ]
        if not acoustid and not fingerprint:
            continue
        left_album = album_by_id.get(left_id)
        right_album = album_by_id.get(right_id)
        from resonance.quality import same_release_kind

        if not same_release_kind(left_album, right_album, "duplicate"):
            continue
        left_tracks = by_album.get(left_id, [])
        right_tracks = by_album.get(right_id, [])
        pairs.append({
            "acoustid_matches": len(acoustid),
            "fingerprint_matches": len(fingerprint),
            "left": _album_public(album_by_id.get(left_id), left_id, left_tracks),
            "right": _album_public(album_by_id.get(right_id), right_id, right_tracks),
            "rows": _aligned_rows(left_tracks, right_tracks, acoustid, fingerprint),
        })
    pairs.sort(key=lambda item: (
        -item["acoustid_matches"],
        -item["fingerprint_matches"],
        (item["left"].get("artist") or "").casefold(),
        (item["left"].get("title") or "").casefold(),
        (item["right"].get("artist") or "").casefold(),
        (item["right"].get("title") or "").casefold(),
    ))
    return pairs


def _index(tracks, field):
    buckets = {}
    for track in tracks or []:
        key = str(track.get(field) or "").strip()
        if not key:
            continue
        buckets.setdefault(key, []).append(track)
    return buckets


def _add_matches(matches, buckets, kind, dismissed, used):
    for rows in buckets.values():
        per_album = {}
        for track in rows:
            per_album.setdefault(str(track["album_id"]), []).append(track)
        album_ids = sorted(per_album)
        if len(album_ids) < 2:
            continue
        for index, left_id in enumerate(album_ids):
            for right_id in album_ids[index + 1:]:
                taken = used.get((left_id, right_id), set())
                used_right = set()
                for left in per_album[left_id]:
                    if str(left["id"]) in taken:
                        continue
                    for right in per_album[right_id]:
                        right_id_text = str(right["id"])
                        if right_id_text in taken or right_id_text in used_right or _hidden(left, right, dismissed):
                            continue
                        used_right.add(right_id_text)
                        matches.setdefault((left_id, right_id), {"acoustid": [], "fingerprint": []})[kind].append((left, right))
                        break


def _aligned_rows(left_tracks, right_tracks, acoustid, fingerprint):
    used_left = set()
    used_right = set()
    rows = []

    def emit(kind, left, right):
        rows.append({
            "match": kind,
            "left": _track_public(left) if left else None,
            "right": _track_public(right) if right else None,
        })
        if left:
            used_left.add(str(left["id"]))
        if right:
            used_right.add(str(right["id"]))

    ordered_acoustid = sorted(acoustid, key=lambda couple: (
        couple[0].get("disc_number") or 1,
        couple[0].get("track_number") or 0,
        str(couple[0].get("id")),
    ))
    ordered_fingerprint = sorted(fingerprint, key=lambda couple: (
        couple[0].get("disc_number") or 1,
        couple[0].get("track_number") or 0,
        str(couple[0].get("id")),
    ))
    for left, right in ordered_acoustid:
        emit("acoustid", left, right)
    for left, right in ordered_fingerprint:
        if str(left["id"]) in used_left or str(right["id"]) in used_right:
            continue
        emit("fingerprint", left, right)
    # Tracks without a sound match still sit side by side: same disc and track number first, then the same title.
    spare_left = [track for track in left_tracks if str(track["id"]) not in used_left]
    spare_right = [track for track in right_tracks if str(track["id"]) not in used_right]
    for key in (_position_key, _title_key):
        waiting = {}
        for track in spare_right:
            if key(track) is not None:
                waiting.setdefault(key(track), []).append(track)
        for track in spare_left:
            peers = waiting.get(key(track)) if key(track) is not None else None
            if peers:
                emit(None, track, peers.pop(0))
        spare_left = [track for track in spare_left if str(track["id"]) not in used_left]
        spare_right = [track for track in spare_right if str(track["id"]) not in used_right]
    for track in spare_left:
        emit(None, track, None)
    for track in spare_right:
        emit(None, None, track)
    rows.sort(key=_row_order)
    return rows


def _position_key(track):
    number = track.get("track_number")
    if not number:
        return None
    return (track.get("disc_number") or 1, int(number))


def _title_key(track):
    import re

    title = re.sub(r"[^a-z0-9]+", "", str(track.get("title") or "").lower())
    return title or None


def _row_order(row):
    """Rows in the left album's order; a row with only a right track goes where its number would be."""
    track = row.get("left") or row.get("right") or {}
    return (track.get("disc") or 1, track.get("number") or 0, 0 if row.get("left") else 1)


def _original_years(album_ids):
    rows = db.fetchall(
        """
        SELECT id AS album_id, original_year
        FROM albums
        WHERE id = ANY(%s::uuid[])
          AND original_year IS NOT NULL
        """,
        (db.uuid_array(album_ids),),
    )
    return {str(row["album_id"]): row["original_year"] for row in rows if row.get("original_year")}


def _album_public(album, album_id, tracks):
    from resonance.quality import format_summary
    from resonance.upgrade import version_label

    album = album or {}
    return {
        "id": str(album.get("id") or album_id),
        "title": album.get("title") or "",
        "artist": album.get("artist_name") or "",
        "path": album.get("path") or "",
        "release_group": str(album.get("musicbrainz_release_group_id") or ""),
        "year": album.get("release_year") or None,
        "original_year": album.get("original_year") or None,
        "track_count": len(tracks),
        "version": version_label(album.get("edition"), "", album.get("type")),
        "audio": format_summary(tracks),
    }


def _track_public(track):
    return {
        "id": str(track["id"]),
        "disc": int(track.get("disc_number") or 1),
        "number": int(track.get("track_number") or 0),
        "title": track.get("title") or "",
        "format": track.get("file_format") or "",
        "bit_depth": track.get("bit_depth"),
        "sample_rate": track.get("sample_rate"),
        "bitrate": track.get("bitrate"),
    }


def _hidden(left, right, dismissed):
    pair = tuple(sorted([str(left["id"]), str(right["id"])]))
    return pair in dismissed


_lock = threading.Lock()
