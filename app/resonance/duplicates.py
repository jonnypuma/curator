import threading

from resonance import db
from resonance.errors import AppError


def groups(focus=None):
    """Album pairs that share an AcoustID recording or an identical fingerprint, plus pairs that
    carry the Duplicate pill for another reason: the same artist and title, or the same MusicBrainz
    release. Without those, an album could show the pill and an empty window.

    Duplicate marks left behind by a copy that is gone are cleared first. The ids that lost their
    mark come back as "cleared".
    """
    from resonance import upgrade

    cleared = list(upgrade.clear_orphan_flags())
    result = _groups()
    result["pairs"] = result["pairs"] + _release_pairs(result["pairs"])
    result["cleared"] = cleared
    return result


def _release_pairs(listed):
    """Pairs of flagged albums that are copies by name or by MusicBrainz release, not yet listed."""
    from resonance.fields import norm_name

    rows = db.fetchall(
        """
        SELECT albums.id, albums.title, albums.path, albums.release_year, albums.edition, albums.type,
               albums.musicbrainz_release_group_id, albums.musicbrainz_release_id::text AS mbid,
               albums.duplicate_release, artists.name AS artist_name
        FROM albums JOIN artists ON artists.id = albums.artist_id
        """
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
                    if key in seen:
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


def _groups():
    """Album pairs that share an AcoustID recording or an identical fingerprint."""
    dismissed = {
        (str(row["track_a"]), str(row["track_b"]))
        for row in db.fetchall("SELECT track_a, track_b FROM dismissed_duplicates")
    }
    album_ids = _shared_album_ids()
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
    pairs = album_pairs(albums, tracks, dismissed)
    from curator import arr_ids

    arr_ids.album_groups([[pair.get("left") or {}, pair.get("right") or {}] for pair in pairs])
    return {"pairs": pairs}


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

        if not same_release_kind(left_album, right_album):
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
    for track in left_tracks:
        if str(track["id"]) not in used_left:
            emit(None, track, None)
    for track in right_tracks:
        if str(track["id"]) not in used_right:
            emit(None, None, track)
    return rows


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
