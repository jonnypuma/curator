from uuid import UUID

from resonance import db
from resonance.fields import opt_uuid_loose


def _present(value):
    return bool(value is not None and str(value).strip())


def _uuid_ok(value):
    if not _present(value):
        return False
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


def _tag(track, key):
    tags = track.get("tags") or {}
    if not isinstance(tags, dict):
        return ""
    return str(tags.get(key) or "").strip()


def score(track, album, artist):
    release_group = track.get("musicbrainz_release_group_id") or album.get("musicbrainz_release_group_id")
    width = album.get("artwork_width") or 0
    height = album.get("artwork_height") or 0
    checks = [
        _present(track.get("title")),
        (track.get("track_number") or 0) >= 1,
        (track.get("disc_number") or 0) >= 1,
        track.get("year") is not None,
        _present(track.get("genre")),
        _uuid_ok(track.get("musicbrainz_track_id")),
        _uuid_ok(release_group),
        _uuid_ok(_tag(track, "musicbrainz_albumid") or album.get("musicbrainz_release_id")),
        _present(_tag(track, "catalognumber") or album.get("catalog")),
        _present(_tag(track, "label") or album.get("label")),
        _present(_tag(track, "releasecountry") or album.get("country")),
        _present(_tag(track, "releasestatus") or album.get("release_status")),
        _present(_tag(track, "releasetype")),
        bool(artist.get("has_nfo")),
        bool(album.get("has_nfo")),
        bool(album.get("has_artwork")) and width >= 800 and height >= 800,
    ]
    percent = int(round(100 * sum(1 for item in checks if item) / len(checks)))
    return max(0, min(100, percent))


def recompute_album(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        return
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    if not artist:
        return
    tracks = db.fetchall("SELECT * FROM tracks WHERE album_id = %s", (album_id,))
    for track in tracks:
        percent = score(track, album, artist)
        db.execute(
            "UPDATE tracks SET tag_completeness_percent = %s WHERE id = %s",
            (percent, track["id"]),
        )


def recompute_artist_albums(artist_id):
    rows = db.fetchall("SELECT id FROM albums WHERE artist_id = %s", (artist_id,))
    for row in rows:
        recompute_album(row["id"])


def columns_from_tags(raw):
    def grab(*keys):
        for key in keys:
            value = raw.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    from resonance.fields import clean_text, leading_int, year_from

    title = clean_text(grab("title"), 255) or "Unknown"
    return {
        "title": title,
        "artist_name": clean_text(grab("artist"), 255),
        "album_name": clean_text(grab("album"), 255),
        "genre": clean_text(grab("genre"), 255),
        "year": year_from(grab("date", "year", "originaldate")),
        "track_number": leading_int(grab("tracknumber"), 1) or 1,
        "disc_number": leading_int(grab("discnumber"), 1) or 1,
        "musicbrainz_track_id": opt_uuid_loose(grab("musicbrainz_trackid")),
        "musicbrainz_release_group_id": opt_uuid_loose(grab("musicbrainz_releasegroupid")),
        "tags": {key: value for key, value in raw.items() if not str(key).startswith("_")},
    }
