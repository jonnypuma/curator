import re
from uuid import UUID

from resonance.errors import AppError

RELEASE_TYPES = {"album", "single", "ep", "compilation", "live", "unknown"}

FILE_MAP = {
    "title": "title",
    "artist_name": "artist",
    "album_name": "album",
    "albumartist": "albumartist",
    "artists": "artists",
    "albumartists": "albumartists",
    "artistsort": "artistsort",
    "albumartistsort": "albumartistsort",
    "genre": "genre",
    "year": "date",
    "track_number": "tracknumber",
    "disc_number": "discnumber",
    "composer": "composer",
    "conductor": "conductor",
    "bpm": "bpm",
    "initialkey": "initialkey",
    "replaygain_track_gain": "replaygain_track_gain",
    "comment": "comment",
    "musicbrainz_track_id": "musicbrainz_trackid",
    "musicbrainz_recordingid": "musicbrainz_recordingid",
    "musicbrainz_albumid": "musicbrainz_albumid",
    "musicbrainz_release_group_id": "musicbrainz_releasegroupid",
    "musicbrainz_artistid": "musicbrainz_artistid",
}

EDITOR_FIELDS = list(FILE_MAP.keys())
UUID_FIELDS = {
    "musicbrainz_track_id",
    "musicbrainz_recordingid",
    "musicbrainz_albumid",
    "musicbrainz_release_group_id",
    "musicbrainz_artistid",
}


def clean_text(value, limit=None):
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    if not text:
        return None
    if limit:
        text = text[:limit]
    return text


def genre_name(value):
    """A genre label. Bare ID3 genre numbers such as 17 are not names."""
    text = clean_text(value, 80)
    if not text or text.isdigit():
        return ""
    return text


def genre_label(value):
    """Capitalize the first letter of each word in a genre name."""
    text = clean_text(value)
    if not text:
        return ""
    return " ".join(word[:1].upper() + word[1:] for word in text.split())


def website_url(value):
    """A website address. A bare domain gets https://."""
    text = clean_text(value, 500)
    if not text or text.lower() in {"null", "none"}:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    if "." in text and " " not in text:
        return "https://" + text.lstrip("/")
    return ""


def year_from(value):
    if value is None or value == "":
        return None
    match = re.search(r"(?:19|20)\d{2}", str(value))
    if not match:
        return None
    year = int(match.group(0))
    if year < 1000 or year > 3000:
        return None
    return year


def leading_int(value, default=None):
    if value is None or value == "":
        return default
    match = re.search(r"\d+", str(value))
    if not match:
        return default
    return int(match.group(0))


def opt_uuid(value, field):
    if value is None or str(value).strip() == "":
        return None
    try:
        return str(UUID(str(value).strip()))
    except (ValueError, AttributeError) as exc:
        raise AppError(f"{field} must be a UUID", 400) from exc


def opt_uuid_loose(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return str(UUID(str(value).strip()))
    except (ValueError, AttributeError):
        return None


def mbid_list(value):
    """Every MusicBrainz id in a tag, including a collaboration stored as several ids."""
    parts = []
    if isinstance(value, (list, tuple)):
        for item in value:
            parts.extend(str(item or "").split(";"))
    else:
        parts = str(value or "").split(";")
    found = []
    for part in parts:
        item = opt_uuid_loose(part)
        if item and item not in found:
            found.append(item)
    return found


# Picard joins several artist names with a semicolon. Slash is a path separator
# and appears inside names such as AC/DC. Pipe is illegal in a Windows filename.
ARTIST_SEPARATOR = "; "
HYPHEN_KEYS = {
    "album",
    "title",
    "artist",
    "artists",
    "artistsort",
    "albumartist",
    "albumartists",
    "albumartistsort",
}


def ascii_hyphen(value):
    """Replace Unicode HYPHEN (U+2010) with ASCII HYPHEN-MINUS (U+002D)."""
    if value is None:
        return None
    return str(value).replace("\u2010", "-")


_DISC_IN_ALBUM = re.compile(
    r"(?:\s*[\(\[]\s*(?:cd|disc|disk)\s*0*\d+\s*[\)\]]|\s+-\s+(?:cd|disc|disk)\s*0*\d+|\s+(?:cd|disc|disk)\s*0*\d+)\s*$",
    re.IGNORECASE,
)


def album_title_without_disc(title):
    """Drop a trailing disc marker so every disc keeps the same album name."""
    text = str(title or "").strip()
    cleaned = _DISC_IN_ALBUM.sub("", text).strip(" -")
    return cleaned or text


def split_artists(value):
    text = str(value or "").replace("\x00", ";").replace(" \\ ", ";").replace(" / ", ";")
    return [part.strip() for part in text.split(";") if part.strip()]


def join_artists(names):
    found = []
    for name in names or []:
        text = str(ascii_hyphen(name) or "").strip()
        if text and text not in found:
            found.append(text)
    return ARTIST_SEPARATOR.join(found)


_EDITION_BRACKET = re.compile(r"(\([^(]*?\)|\[[^[]*?\])")
_EDITION_KEYWORD = re.compile(
    r"\b("
    r"remaster\w*"
    r"|remix\w*"
    r"|mix(?:es)?"
    r"|deluxe"
    r"|expanded"
    r"|anniversary"
    r"|bonus(?:\s+tracks?)?"
    r"|reissue"
    r"|edition"
    r"|version"
    r"|mono"
    r"|stereo"
    r"|clean"
    r"|explicit"
    r"|edit"
    r"|(?:19\d\d|20\d\d)"
    r")\b",
    re.IGNORECASE,
)


def _drop_edition_note(text):
    def _replace(m):
        inner = m.group(0)
        if _EDITION_KEYWORD.search(inner):
            return " "
        return inner

    prev = None
    while prev != text:
        prev = text
        text = _EDITION_BRACKET.sub(_replace, text)
    return text


def norm_name(value):
    """Letters and digits used to compare names. A name that is only punctuation stays.

    Parenthetical notes with edition keywords such as (Remaster) are dropped when
    the rest of the name still has letters. Subtitles such as (Blue Album) stay so
    distinct releases are not grouped as duplicates. Sigur Rós ( ) is the whole
    title, so the parentheses stay.
    """
    original = str(value or "").strip().lower()
    text = _drop_edition_note(original)
    compact = re.sub(r"[^a-z0-9]+", "", text)
    if compact:
        return compact
    return re.sub(r"\s+", "", original)


_TYPE_SUFFIX = re.compile(r"\s*\((album|single|ep|compilation|live)\)\s*$", re.IGNORECASE)
_TYPE_LABELS = {
    "album": "album",
    "single": "single",
    "ep": "EP",
    "compilation": "compilation",
    "live": "live",
}


def title_without_type(title):
    """Drop a trailing release type such as (single) or (EP)."""
    return _TYPE_SUFFIX.sub("", str(title or "")).strip()


def title_with_type(title, album_type, enabled=False):
    """Append a type such as (EP) when that type is selected in settings.

    ``enabled`` may be a bool, which applies to every type, or a mapping of
    album, single, ep, live, and compilation.
    """
    text = str(title or "").strip()
    if not text:
        return text
    kind = release_type(album_type)
    label = _TYPE_LABELS.get(kind)
    if not label:
        return text
    if isinstance(enabled, dict):
        chosen = bool(enabled.get(kind))
    else:
        chosen = bool(enabled)
    if not chosen:
        return text
    base = _TYPE_SUFFIX.sub("", text).strip()
    return f"{base} ({label})"


def release_type(value):
    text = (value or "unknown").strip().lower()
    aliases = {
        "album": "album",
        "single": "single",
        "ep": "ep",
        "compilation": "compilation",
        "live": "live",
        "broadcast": "unknown",
        "other": "unknown",
        "unknown": "unknown",
    }
    return aliases.get(text, "unknown")


def scalar(value):
    if isinstance(value, list):
        parts = [scalar(item) for item in value]
        parts = [item for item in parts if item]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return "; ".join(parts)
    return clean_text(value)


def contains_pattern(query):
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def normalize_track_update(body, existing_tags=None):
    if not isinstance(body, dict):
        raise AppError("Expected a JSON object")
    tags = dict(existing_tags or {})
    file_map = {}
    columns = {}
    for field in EDITOR_FIELDS:
        if field not in body and field not in (body.get("tags") or {}):
            continue
        raw = body[field] if field in body else body["tags"].get(field)
        easy = FILE_MAP[field]
        if field == "musicbrainz_artistid":
            text = "" if raw is None else str(raw).strip()
            parts = [part.strip() for part in text.split(";") if part.strip()]
            if any(not opt_uuid_loose(part) for part in parts):
                raise AppError("MusicBrainz artist id must be one or more UUIDs separated by semicolons")
            value = ARTIST_SEPARATOR.join(mbid_list(text)) or None
        elif field in UUID_FIELDS:
            value = opt_uuid(raw, field)
        elif field == "year":
            if raw is None or str(raw).strip() == "":
                value = None
            else:
                value = year_from(raw)
                if value is None:
                    raise AppError("Year must be a four-digit year")
        elif field in {"track_number", "disc_number"}:
            number = leading_int(raw, None)
            if not number or number < 1:
                raise AppError(f"{field.replace('_', ' ')} must be 1 or greater")
            value = number
        else:
            limit = 255 if field in {"title", "artist_name", "album_name", "genre"} else None
            value = clean_text(raw, limit)
        columns[field] = value
        if value is None or value == "":
            tags.pop(easy, None)
            file_map[easy] = ""
        else:
            tags[easy] = str(value)
            file_map[easy] = str(value)
    extra = body.get("extra") if isinstance(body.get("extra"), dict) else {}
    for key, raw in extra.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+", str(key)) or str(key).startswith("_"):
            continue
        value = clean_text(raw)
        if value is None:
            tags.pop(key, None)
            file_map[key] = ""
        else:
            tags[key] = value
            file_map[key] = value
    if "title" in columns and not columns["title"]:
        raise AppError("Title is required")
    return {"columns": columns, "tags": tags, "file_map": file_map}
