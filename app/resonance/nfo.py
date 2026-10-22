import hashlib
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

from resonance.errors import AppError
from resonance.fields import website_url
from resonance.paths import assert_readable, atomic_write

logger = logging.getLogger(__name__)


def _text(parent, tag, value, keep_empty=False):
    if value is None or str(value).strip() == "":
        if keep_empty:
            ET.SubElement(parent, tag)
        return
    element = ET.SubElement(parent, tag)
    element.text = str(value)


def _parts(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,;/]", text) if part.strip()]


def _flag(value):
    return "true" if value else "false"


def _kodi_rating(value):
    """AllMusic scores are stored out of 5. Kodi's album rating is out of 10."""
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    scaled = number * 2 if number <= 5 else number
    if scaled > 10:
        return ""
    return f"{scaled:.1f}".rstrip("0").rstrip(".")


def _vote_count(value):
    if value in (None, ""):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _rated(parent, tag, value):
    shown = _kodi_rating(value)
    if not shown:
        return
    element = ET.SubElement(parent, tag, {"max": "10"})
    element.text = shown


def _kodi_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        if day > 12 and month <= 12:
            return f"{year:04d}-{month:02d}-{day:02d}"
        if month > 12 and day <= 12:
            return f"{year:04d}-{day:02d}-{month:02d}"
        return f"{year:04d}-{month:02d}-{day:02d}"
    if re.match(r"^\d{4}$", text):
        return text
    return ""


def _first_tag_date(tracks, keys):
    for track in tracks or []:
        tags = track.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        for key in keys:
            found = _kodi_date(tags.get(key))
            if found:
                return found
    return ""


def release_date(album, tracks):
    found = _first_tag_date(tracks, ("date", "originaldate", "year"))
    if found:
        return found
    return _kodi_date(album.get("release_year"))


def original_release_date(tracks, released):
    found = _first_tag_date(tracks, ("originaldate",))
    if found and found != released:
        return found
    return ""


def album_context(album, artist):
    """Album row plus the artist fields the album nfo is allowed to copy."""
    payload = dict(album or {})
    artist = artist or {}
    payload["artist_name"] = artist.get("name") or payload.get("artist_name") or ""
    payload["artist_mbid"] = artist.get("musicbrainz_artist_id") or ""
    payload["artist_biography"] = artist.get("biography") or ""
    if payload.get("genres") is None:
        payload["genres"] = artist.get("genres") or []
        payload["genres_from_artist"] = True
    return payload


def prettify(element):
    raw = ET.tostring(element, encoding="utf-8")
    parsed = minidom.parseString(raw)
    text = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def artist_filename(profile):
    return "folder.nfo" if profile == "emby" else "artist.nfo"


def album_filename(profile):
    return "folder.nfo" if profile == "emby" else "album.nfo"


def _digest(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _artist_biography(artist):
    return str((artist or {}).get("biography") or "").strip()


def _is_boxset(album):
    edition = str(album.get("edition") or "")
    discs = album.get("total_discs") or album.get("discs") or 0
    return bool(album.get("boxset") or (discs or 0) > 1 or "box" in edition.lower())


def artist_digest(artist):
    """Fingerprint of the artist.nfo fields the comparison can show."""
    artist = artist or {}
    payload = {key: _folded(_artist_form_value(artist, key)) for key, _tag, _label in _ARTIST_FORM}
    return _digest(payload)


def album_digest(album, tracks):
    """Fingerprint of the album.nfo fields the comparison can show.

    Whitespace is folded the same way as the NFO diff, so a biography that only
    gained or lost a line break does not mark every album for that artist.
    """
    album = album or {}
    payload = {key: _folded(_form_value(album, key, tracks)) for key, _tag, _label in _ALBUM_FORM}
    payload["tracks"] = _track_fingerprint(tracks)
    return _digest(payload)


def _track_fingerprint(tracks):
    rows = []
    for track in tracks or []:
        duration = track.get("duration_seconds") or 0
        rows.append({
            "disc": str(track.get("disc_number") or "").strip() or "1",
            "number": str(track.get("track_number") or "").strip(),
            "title": _folded(track.get("title")),
            "duration": "" if not duration else str(duration),
            "subtitle": _folded(track.get("discsubtitle") or (track.get("tags") or {}).get("discsubtitle")),
            "mbid": _folded(track.get("musicbrainz_track_id")),
        })
    rows.sort(key=lambda item: (_as_int(item["disc"]), _as_int(item["number"]), item["disc"], item["number"]))
    return rows


_ALBUM_FORM = (
    ("title", "title", "Title"),
    ("release_year", "year", "Year"),
    ("type", "type", "Type"),
    ("release_status", "releasestatus", "Release status"),
    ("label", "label", "Label"),
    ("catalog", "catalognumber", "Catalog number"),
    ("release_group", "releasegroup", "Release group"),
    ("barcode", "barcode", "Barcode"),
    ("country", "country", "Country"),
    ("boxset", "boxset", "Box set"),
    ("review", "review", "Review"),
    ("style", "style", "Style"),
    ("mood", "mood", "Mood"),
    ("theme", "theme", "Theme"),
    ("allmusic_rating", "allmusicrating", "AllMusic rating"),
    ("allmusic_user_rating", "allmusicuserrating", "AllMusic user rating"),
    ("kodi_rating", "rating", "Rating"),
    ("kodi_userrating", "userrating", "User rating"),
    ("allmusic_votes", "votes", "Votes"),
    ("allmusic_url", "allmusic", "AllMusic"),
    ("musicbrainz_release_id", "musicbrainzalbumid", "MusicBrainz release id"),
    ("musicbrainz_release_group_id", "musicbrainzreleasegroupid", "MusicBrainz release group id"),
    ("genres", "genre", "Genres"),
    ("artist_name", "artist", "Artist"),
    ("artist_mbid", "musicbrainzartistid", "Artist MusicBrainz id"),
    ("artist_biography", "artistdesc", "Artist biography"),
    ("releasedate", "releasedate", "Release date"),
    ("originalreleasedate", "originalreleasedate", "Original release date"),
    ("compilation", "compilation", "Compilation"),
    ("discs", "discs", "Discs"),
    ("duration_seconds", "duration", "Duration"),
)


_ARTIST_FORM = (
    ("name", "name", "Name"),
    ("musicbrainz_artist_id", "musicbrainzartistid", "MusicBrainz artist id"),
    ("sortname", "sortname", "Sort name"),
    ("type", "type", "Type"),
    ("gender", "gender", "Gender"),
    ("disambiguation", "disambiguation", "Disambiguation"),
    ("genres", "genre", "Genres"),
    ("style", "style", "Style"),
    ("mood", "mood", "Mood"),
    ("years_active", "yearsactive", "Years active"),
    ("instruments", "instruments", "Instruments"),
    ("born", "born", "Born"),
    ("formed", "formed", "Formed"),
    ("biography", "biography", "Biography"),
    ("died", "died", "Died"),
    ("disbanded", "disbanded", "Disbanded"),
    ("website", "website", "Website"),
    ("discogs_url", "discogs", "Discogs"),
    ("wikipedia_url", "wikipedia", "Wikipedia"),
)


_ALBUM_ARTIST_FIELDS = {
    "artist_biography": "biography",
    "artist_name": "name",
    "artist_mbid": "musicbrainz_artist_id",
}


def _nfo_change(label, file_value, database_value, kind, row_id, field, from_kind="", from_id=""):
    row = {
        "label": label,
        "file": file_value,
        "database": database_value,
        "field": field,
        "kind": kind,
        "id": str(row_id or ""),
    }
    if from_kind:
        row["from_kind"] = from_kind
        row["from_id"] = str(from_id or "")
    return row


def _album_change(album, key, label, file_value, database_value):
    """Artist biography and shared genres live on the artist, and the value is read from album.nfo."""
    album = album or {}
    artist_field = _ALBUM_ARTIST_FIELDS.get(key)
    shared_genres = key == "genres" and bool(album.get("genres_from_artist"))
    if artist_field or shared_genres:
        return _nfo_change(
            label, file_value, database_value, "artist", album.get("artist_id"),
            artist_field or "genres", from_kind="album", from_id=album.get("id"),
        )
    return _nfo_change(label, file_value, database_value, "album", album.get("id"), key)


def artist_nfo_diff(text, artist):
    """Fields in artist.nfo that do not match the database values written into the file."""
    parsed = _parse_artist_nfo(text)
    if parsed is None:
        return {"fields": [], "file": {}, "labels": [], "notes": ["artist.nfo could not be read"], "changes": []}
    artist = artist or {}
    changes = []
    for key, _tag, label in _ARTIST_FORM:
        current = _artist_form_value(artist, key)
        stored = parsed.get(key, "")
        if _same_value(stored, current):
            continue
        changes.append(_nfo_change(label, stored, current, "artist", artist.get("id"), key))
    return {
        "fields": [row["label"] for row in changes],
        "file": {row["label"]: row["file"] for row in changes},
        "labels": [row["label"] for row in changes],
        "notes": [],
        "changes": changes,
    }


def _parse_artist_nfo(text):
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    values = {}
    for key, tag, _label in _ARTIST_FORM:
        if key in {"genres", "style", "mood", "instruments"}:
            values[key] = ", ".join(_ci_texts(root, tag))
        else:
            values[key] = _ci_text(root, tag)
    if not values.get("biography"):
        values["biography"] = _ci_text(root, "artistdesc")
    return values


def _artist_form_value(artist, key):
    if key == "name":
        return str(artist.get("nfo_name") or artist.get("name") or "").strip()
    if key == "type":
        return str(artist.get("type") or "Group").strip()
    if key == "born":
        return str(artist.get("born") or artist.get("origin") or "").strip()
    if key == "biography":
        return _artist_biography(artist)
    if key in {"genres", "style", "mood", "instruments"}:
        source = artist.get("genres") if key == "genres" else artist.get({"style": "style", "mood": "mood", "instruments": "instruments"}[key])
        return ", ".join(_parts(source))
    if key == "years_active":
        return str(artist.get("years_active") or "").strip()
    if key == "discogs_url":
        return str(artist.get("discogs_url") or "").strip()
    if key == "wikipedia_url":
        return str(artist.get("wikipedia_url") or "").strip()
    return str(artist.get(key) or "").strip()


def _nested_text(root, parent_tag, child_tag):
    want = parent_tag.lower()
    for node in list(root):
        if str(node.tag).lower() == want:
            return _ci_text(node, child_tag)
    return ""


def _ci_text(root, tag):
    want = tag.lower()
    for node in list(root):
        if str(node.tag).lower() == want and node.text and node.text.strip():
            return node.text.strip()
    return ""


def _ci_texts(root, tag):
    want = tag.lower()
    return [node.text.strip() for node in list(root) if str(node.tag).lower() == want and node.text and node.text.strip()]


def album_nfo_diff(text, album, tracks):
    """Fields in album.nfo that do not match the database values written into the form."""
    parsed = _parse_album_nfo(text)
    if parsed is None:
        return {"fields": [], "file": {}, "labels": [], "tracks": 0, "notes": ["album.nfo could not be read"], "changes": []}
    album = album or {}
    fields, file, labels = [], {}, []
    for key, _tag, label in _ALBUM_FORM:
        current = _form_value(album, key, tracks)
        stored = parsed.get(key, "")
        if _same_value(stored, current):
            continue
        fields.append(key)
        labels.append(label)
        file[key] = stored
    changes = [
        _album_change(album, key, label, file[key], _form_value(album, key, tracks))
        for key, label in zip(fields, labels)
    ]
    changes.extend(_track_changes(parsed.get("tracks") or [], tracks))
    return {
        "fields": fields,
        "file": file,
        "labels": labels,
        "tracks": sum(1 for row in changes if str(row["label"]).startswith("Track") or str(row["label"]).startswith("Disc")),
        "notes": [],
        "changes": changes,
    }


def _parse_album_nfo(text):
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    values = {}
    nested = {"artist_name", "artist_mbid"}
    for key, tag, _label in _ALBUM_FORM:
        if key in nested:
            continue
        if key in {"style", "mood", "theme", "genres"}:
            values[key] = ", ".join(_direct_texts(root, tag))
        elif key in {"boxset", "compilation"}:
            values[key] = (_direct_text(root, tag) or "false").lower()
        else:
            values[key] = _direct_text(root, tag)
    values["artist_name"] = _nested_text(root, "albumartistcredits", "artist") or _ci_text(root, "artist")
    values["artist_mbid"] = _nested_text(root, "albumartistcredits", "musicbrainzartistid")
    values["tracks"] = []
    for node in root.findall("track"):
        values["tracks"].append({
            "disc": _direct_text(node, "disc"),
            "number": _direct_text(node, "position"),
            "title": _direct_text(node, "title"),
            "duration": _direct_text(node, "duration"),
            "subtitle": _direct_text(node, "discsubtitle"),
            "mbid": _direct_text(node, "musicbrainztrackid"),
        })
    return values


def _form_value(album, key, tracks=None):
    if key == "boxset":
        return _flag(_is_boxset(album))
    if key == "compilation":
        return _flag((album.get("type") or "") == "compilation")
    if key == "artist_name":
        return str(album.get("artist_name") or "").strip()
    if key == "artist_mbid":
        return str(album.get("artist_mbid") or "").strip()
    if key == "artist_biography":
        return str(album.get("artist_biography") or "").strip()
    if key == "releasedate":
        return release_date(album, tracks)
    if key == "originalreleasedate":
        return original_release_date(tracks, release_date(album, tracks))
    if key == "discs":
        discs = album.get("total_discs") or album.get("discs") or ""
        return "" if discs in (None, "") else str(discs)
    if key == "duration_seconds":
        duration = album.get("duration_seconds") or 0
        return "" if not duration else str(duration)
    if key == "kodi_rating":
        return _kodi_rating(album.get("allmusic_rating")) or ""
    if key == "kodi_userrating":
        return _kodi_rating(album.get("allmusic_user_rating")) or ""
    if key == "allmusic_votes":
        count = _vote_count(album.get("allmusic_votes"))
        return "" if count is None else str(count)
    if key == "genres":
        return ", ".join(_parts(album.get("genres")))
    if key in {"style", "mood", "theme"}:
        return ", ".join(_parts(album.get(key)))
    if key == "release_year":
        year = album.get("release_year")
        return "" if year in (None, "") else str(year)
    return str(album.get(key) or "").strip()


def _same_value(stored, current):
    """Equal when the text Curator would write matches the text in the file.

    Line breaks and repeated spaces count as the same gap. A saved biography and the
    copy in album.nfo often differ only there, and the comparison would show both.
    """
    return _folded(stored) == _folded(current)


def _folded(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _direct_text(node, tag):
    found = node.find(tag)
    if found is None:
        return ""
    return _folded("".join(found.itertext()))


def _direct_texts(node, tag):
    return [item.text.strip() for item in node.findall(tag) if item.text and item.text.strip()]


def _track_changes(file_tracks, tracks):
    """Pair file tracks with database tracks. A file that omits <disc> is disc 1."""
    file_tracks = file_tracks or []
    assume_disc = all(not str(item.get("disc") or "").strip() for item in file_tracks)

    def disc_of(value):
        text = str(value or "").strip()
        return "1" if not text and assume_disc else text

    def sort_key(item):
        disc, number = item
        return (_as_int(disc), _as_int(number), disc, number)

    def blank(value):
        return str(value or "").strip()

    def pack(track, file_side):
        if file_side:
            duration = blank(track.get("duration"))
            return {
                "title": blank(track.get("title")),
                "duration": "" if duration in {"", "0"} else duration,
                "subtitle": blank(track.get("subtitle")),
                "mbid": blank(track.get("mbid")),
            }
        duration = track.get("duration_seconds") or 0
        return {
            "title": blank(track.get("title")),
            "duration": "" if not duration else str(duration),
            "subtitle": blank(track.get("discsubtitle") or (track.get("tags") or {}).get("discsubtitle")),
            "mbid": blank(track.get("musicbrainz_track_id")),
        }

    current = {}
    for track in tracks or []:
        key = (disc_of(track.get("disc_number")), str(track.get("track_number") or "").strip())
        current[key] = pack(track, False)
    stored = {}
    for track in file_tracks:
        key = (disc_of(track.get("disc")), str(track.get("number") or "").strip())
        stored[key] = pack(track, True)
    rows = []
    pieces = (
        ("title", ""),
        ("duration", " duration"),
        ("subtitle", " disc title"),
        ("mbid", " MusicBrainz id"),
    )
    for key in sorted(set(current) | set(stored), key=sort_key):
        left = stored.get(key) or {}
        right = current.get(key) or {}
        disc, number = key
        base = f"Disc {disc} track {number}" if disc and disc != "1" else f"Track {number or '?'}"
        for field, suffix in pieces:
            file_value = left.get(field, "")
            database_value = right.get(field, "")
            if file_value == database_value:
                continue
            rows.append({"label": f"{base}{suffix}", "file": file_value, "database": database_value})
    return rows


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _changed_tracks(file_tracks, tracks):
    return len(_track_changes(file_tracks, tracks))


def website_from_text(text):
    """The first <website> value in an artist or album nfo."""
    if not text:
        return ""
    match = re.search(r"<website>\s*([^<]+?)\s*</website>", text, re.IGNORECASE)
    if not match:
        return ""
    return website_url(match.group(1))


def read_text(directory, names):
    if not directory:
        raise AppError("Folder is missing", 404)
    for name in names:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        safe = assert_readable(path)
        with open(safe, encoding="utf-8", errors="replace") as handle:
            return name, handle.read()
    raise AppError("NFO file was not found", 404)


def _dialect(root, dialect, mbid, locked=False):
    """Emby / Jellyfin keep saved values with lockdata; Plex reads a guid built from the MusicBrainz id."""
    if dialect == "emby":
        _text(root, "lockdata", "true" if locked else "false")
    elif dialect == "plex" and mbid:
        _text(root, "guid", f"musicbrainz://{mbid}")


def artist_document(artist, dialect="kodi"):
    """Kodi artist.nfo. artistdesc and biography both carry the saved biography."""
    artist = artist or {}
    bio = _artist_biography(artist)
    root = ET.Element("artist")
    _text(root, "name", artist.get("nfo_name") or artist.get("name"))
    _text(root, "musicBrainzArtistID", artist.get("musicbrainz_artist_id"))
    _text(root, "sortname", artist.get("sortname"))
    _text(root, "type", artist.get("type") or "Group")
    _text(root, "gender", artist.get("gender"))
    _text(root, "disambiguation", artist.get("disambiguation"))
    for genre in artist.get("genres") or []:
        _text(root, "genre", genre)
    for style in _parts(artist.get("style")):
        _text(root, "style", style)
    for mood in _parts(artist.get("mood")):
        _text(root, "mood", mood)
    _text(root, "yearsactive", artist.get("years_active"))
    for instrument in _parts(artist.get("instruments")):
        _text(root, "instruments", instrument)
    _text(root, "born", artist.get("born") or artist.get("origin"))
    _text(root, "formed", artist.get("formed"))
    _text(root, "artistdesc", bio, keep_empty=True)
    _text(root, "biography", bio)
    _text(root, "died", artist.get("died"))
    _text(root, "disbanded", artist.get("disbanded"))
    _text(root, "website", artist.get("website"))
    _text(root, "discogs", artist.get("discogs_url"))
    _text(root, "wikipedia", artist.get("wikipedia_url"))
    _dialect(root, dialect, artist.get("musicbrainz_artist_id"))
    return prettify(root)


def album_document(album, tracks, dialect="kodi"):
    """Kodi album.nfo. artistdesc is the saved artist biography, or an empty tag."""
    album = album or {}
    bio = str(album.get("artist_biography") or "").strip()
    released = release_date(album, tracks)
    root = ET.Element("album")
    _text(root, "title", album.get("title"))
    _text(root, "musicbrainzalbumid", album.get("musicbrainz_release_id"))
    _text(root, "musicbrainzreleasegroupid", album.get("musicbrainz_release_group_id"))
    _text(root, "artistdesc", bio, keep_empty=True)
    for genre in album.get("genres") or []:
        _text(root, "genre", genre)
    for style in _parts(album.get("style")):
        _text(root, "style", style)
    for mood in _parts(album.get("mood")):
        _text(root, "mood", mood)
    for theme in _parts(album.get("theme")):
        _text(root, "theme", theme)
    _text(root, "compilation", _flag((album.get("type") or "") == "compilation"))
    _text(root, "boxset", _flag(_is_boxset(album)))
    _text(root, "review", album.get("review"))
    _text(root, "allmusic", album.get("allmusic_url"))
    _text(root, "allmusicrating", album.get("allmusic_rating"))
    _text(root, "allmusicuserrating", album.get("allmusic_user_rating"))
    _rated(root, "rating", album.get("allmusic_rating"))
    _rated(root, "userrating", album.get("allmusic_user_rating"))
    _text(root, "votes", _vote_count(album.get("allmusic_votes")))
    _text(root, "type", album.get("type"))
    _text(root, "releasestatus", album.get("release_status"))
    _text(root, "releasedate", released)
    _text(root, "originalreleasedate", original_release_date(tracks, released))
    _text(root, "year", album.get("release_year"))
    _text(root, "label", album.get("label"))
    duration = album.get("duration_seconds") or 0
    if duration:
        _text(root, "duration", duration)
    _text(root, "catalognumber", album.get("catalog"))
    _text(root, "releasegroup", album.get("release_group"))
    _text(root, "barcode", album.get("barcode"))
    _text(root, "country", album.get("country"))
    discs = album.get("total_discs") or album.get("discs")
    _text(root, "discs", discs)
    if album.get("artist_name") or album.get("artist_mbid"):
        credit = ET.SubElement(root, "albumArtistCredits")
        _text(credit, "artist", album.get("artist_name"))
        _text(credit, "musicBrainzArtistID", album.get("artist_mbid"))
    _text(root, "releasetype", album.get("type"))
    for track in tracks or []:
        node = ET.SubElement(root, "track")
        _text(node, "position", track.get("track_number"))
        _text(node, "disc", track.get("disc_number"))
        _text(node, "title", track.get("title"))
        subtitle = track.get("discsubtitle") or (track.get("tags") or {}).get("discsubtitle")
        _text(node, "discsubtitle", subtitle)
        _text(node, "duration", track.get("duration_seconds"))
        _text(node, "musicbrainztrackid", track.get("musicbrainz_track_id"))
    _dialect(root, dialect, album.get("musicbrainz_release_id"))
    return prettify(root)


def _backup(path):
    """Copy an .nfo that is about to be replaced to .nfo.bak."""
    if os.path.isfile(path):
        import shutil

        shutil.copy2(path, path + ".bak")


def write_artist(directory, profile, artist, dialect="kodi", backup=True):
    from resonance.paths import assert_library_writable

    assert_library_writable(directory)
    path = os.path.join(directory, artist_filename(profile))
    if backup:
        _backup(path)
    atomic_write(path, artist_document(artist, dialect))
    return path


_DISC_DIR = re.compile(r"^(?:cd|disc|disk)\s*0*\d+$", re.IGNORECASE)


def album_root(directory):
    """A CD or Disc folder keeps its album.nfo in the parent album folder."""
    if not directory:
        return directory
    folder = os.path.basename(str(directory).rstrip("\\/"))
    parent = os.path.dirname(str(directory).rstrip("\\/"))
    if _DISC_DIR.match(folder) and parent and parent != directory:
        return parent
    return directory


def write_album(directory, profile, album, tracks, dialect="kodi", backup=True):
    from resonance.paths import assert_library_writable

    root = album_root(directory)
    assert_library_writable(root)
    path = os.path.join(root, album_filename(profile))
    if backup:
        _backup(path)
    atomic_write(path, album_document(album, tracks, dialect))
    _remove_disc_nfos(root, path)
    return path


def _remove_disc_nfos(root, written):
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if not _DISC_DIR.match(name):
            continue
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        for filename in ("album.nfo", "folder.nfo"):
            path = os.path.join(folder, filename)
            if os.path.isfile(path) and os.path.normcase(path) != os.path.normcase(written):
                try:
                    os.remove(path)
                except OSError:
                    logger.info("could not remove disc folder nfo %s", path)


def sidecar_names(profile):
    names = {"artist.nfo", "album.nfo", "folder.nfo"}
    names.add(artist_filename(profile))
    names.add(album_filename(profile))
    return names
