from resonance import db
from resonance.errors import AppError
from resonance.fields import norm_name


def missing_tracks(local, expected):
    used = set()
    absent = []
    for item in expected or []:
        match = _match_local(item, local, used)
        if match is None:
            absent.append(
                {
                    "disc_number": item.get("disc_number") or 1,
                    "track_number": item.get("track_number"),
                    "title": item.get("title") or "",
                }
            )
        else:
            used.add(match)
    present = len(expected or []) - len(absent)
    return {"present": present, "expected": len(expected or []), "missing": absent}


def store(album_id, expected, local=None):
    rows = []
    for item in expected or []:
        title = str(item.get("title") or "").strip()
        number = item.get("track_number")
        if not title or not number:
            continue
        rows.append(item)
    db.execute("DELETE FROM expected_tracks WHERE album_id = %s", (album_id,))
    for item in rows:
        recording = str(item.get("recording_id") or "")
        recording = recording if len(recording) == 36 else None
        db.execute(
            """
            INSERT INTO expected_tracks (album_id, disc_number, track_number, title, recording_id, duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                album_id,
                item.get("disc_number") or 1,
                item.get("track_number"),
                item.get("title"),
                recording,
                item.get("duration_seconds") or 0,
            ),
        )
    if local is None:
        local = db.fetchall("SELECT * FROM tracks WHERE album_id = %s", (album_id,))
    summary = missing_tracks(_local_rows(local), rows)
    db.execute(
        "UPDATE albums SET gap_present = %s, gap_expected = %s WHERE id = %s",
        (summary["present"], summary["expected"], album_id),
    )
    return summary


def refresh(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    release_id = album.get("musicbrainz_release_id")
    if not release_id:
        raise AppError("Match this album before checking for missing tracks")
    from resonance.sources import musicbrainz
    from resonance.match import _release_tracks

    release = musicbrainz.get_release(str(release_id))
    return store(album_id, _release_tracks(release))


def summary(album_id):
    expected = db.fetchall(
        """
        SELECT * FROM expected_tracks
        WHERE album_id = %s
        ORDER BY disc_number, track_number
        """,
        (album_id,),
    )
    if not expected:
        return None
    local = db.fetchall("SELECT * FROM tracks WHERE album_id = %s", (album_id,))
    return missing_tracks(_local_rows(local), expected)


def _local_rows(tracks):
    rows = []
    for track in tracks or []:
        tags = track.get("tags") or {}
        rows.append(
            {
                "title": track.get("title"),
                "recording_id": tags.get("musicbrainz_recordingid") or track.get("recording_id"),
            }
        )
    return rows


def _match_local(expected, local, used):
    recording = str(expected.get("recording_id") or "")
    if recording:
        for index, track in enumerate(local):
            if index in used:
                continue
            if str(track.get("recording_id") or "") == recording:
                return index
    title = norm_name(expected.get("title"))
    if not title:
        return None
    for index, track in enumerate(local):
        if index in used:
            continue
        if norm_name(track.get("title")) == title:
            return index
    return None
