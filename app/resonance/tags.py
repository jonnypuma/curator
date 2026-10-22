import logging

import mutagen

from resonance.errors import AppError
from resonance.fields import FILE_MAP, HYPHEN_KEYS, ascii_hyphen, mbid_list, scalar

logger = logging.getLogger(__name__)

# Picard-compatible frames. FLAC stores these as Vorbis comments; MP3 needs the EasyID3 map.
_EASY_TEXT = {
    "catalognumber": "TXXX:CATALOGNUMBER",
    "barcode": "TXXX:BARCODE",
    "label": "TPUB",
    "releasecountry": "TXXX:MusicBrainz Album Release Country",
    "media": "TXXX:MEDIA",
    "asin": "TXXX:ASIN",
}
# MP3 and M4A already store these under MusicBrainz's TXXX / freeform names.
# Registering releasestatus as a raw "TXXX:…" text frame fails, so the write is skipped.
_TAG_ALIAS = {
    "releasestatus": "musicbrainz_albumstatus",
    "releasetype": "musicbrainz_albumtype",
}
# A collaboration is several artist ids. Picard stores each id as its own value.
_MULTI_MBID = {"musicbrainz_artistid", "musicbrainz_albumartistid"}
_MULTI_ARTIST = {"artist", "artists", "albumartist", "albumartists"}

_TXXX = {
    "totaltracks": "TOTALTRACKS",
    "totaldiscs": "TOTALDISCS",
    "artists": "ARTISTS",
    "albumartists": "ALBUMARTISTS",
    "musicbrainz_originalalbumid": "MusicBrainz Original Album Id",
    "musicbrainz_originalartistid": "MusicBrainz Original Artist Id",
}


def _register_easy_keys():
    try:
        from mutagen.easyid3 import EasyID3
    except Exception:
        return
    for key, frame in _EASY_TEXT.items():
        if key in EasyID3.Get:
            continue
        try:
            EasyID3.RegisterTextKey(key, frame)
        except Exception:
            logger.info("could not register tag %s", key)
    for key, desc in _TXXX.items():
        if key in EasyID3.Get:
            continue
        try:
            EasyID3.RegisterTXXXKey(key, desc)
        except Exception:
            logger.info("could not register tag %s", key)
    if "discsubtitle" not in EasyID3.Get:
        try:
            EasyID3.RegisterTextKey("discsubtitle", "TSST")
        except Exception:
            logger.info("could not register tag discsubtitle")


def _register_recording_id():
    """Picard stores the recording MBID as a UFID frame on ID3."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import UFID
    except Exception:
        return
    if "musicbrainz_recordingid" in EasyID3.Get:
        return

    def _get(id3, _key):
        frame = id3.get("UFID:http://musicbrainz.org")
        if frame is None:
            return []
        data = frame.data
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data or "")
        return [text] if text else []

    def _set(id3, _key, value):
        text = value[0] if isinstance(value, (list, tuple)) else value
        id3.add(UFID(owner="http://musicbrainz.org", data=str(text).encode("utf-8")))

    def _delete(id3, _key):
        try:
            del id3["UFID:http://musicbrainz.org"]
        except KeyError:
            return

    try:
        EasyID3.RegisterKey("musicbrainz_recordingid", _get, _set, _delete)
    except Exception:
        logger.info("could not register musicbrainz_recordingid")


def _register_comment():
    """MP3 comments are COMM frames. EasyID3 does not map that key itself."""
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import COMM, Encoding
    except Exception:
        return
    if "comment" in EasyID3.Get:
        return

    def _get(id3, _key):
        frames = [frame for frame in id3.getall("COMM") if not (frame.desc or "")]
        if not frames:
            frames = id3.getall("COMM")
        texts = []
        for frame in frames:
            texts.extend(frame.text or [])
        return [text for text in texts if str(text).strip()]

    def _set(id3, _key, value):
        text = value[0] if isinstance(value, (list, tuple)) else value
        frames = [frame for frame in id3.getall("COMM") if not (frame.desc or "")]
        if frames:
            frames[0].encoding = Encoding.UTF8
            frames[0].text = [str(text)]
            return
        id3.add(COMM(encoding=Encoding.UTF8, lang="eng", desc="", text=[str(text)]))

    def _delete(id3, _key):
        for key in list(id3.keys()):
            parts = str(key).split(":")
            if parts and parts[0] == "COMM" and (len(parts) < 2 or parts[1] == ""):
                try:
                    del id3[key]
                except KeyError:
                    continue

    try:
        EasyID3.RegisterKey("comment", _get, _set, _delete)
    except Exception:
        logger.info("could not register comment")


_register_easy_keys()
_register_recording_id()
_register_comment()


def stored_text(key, value):
    text = str(value)
    if key in HYPHEN_KEYS:
        text = ascii_hyphen(text)
    return text


def stored_value(key, value):
    if key in _MULTI_MBID:
        ids = mbid_list(value)
        if len(ids) > 1:
            return ids
        if len(ids) == 1:
            return ids[0]
    if key in _MULTI_ARTIST:
        from resonance.fields import split_artists

        names = split_artists(value)
        if len(names) > 1:
            return names
    return stored_text(key, value)


def writable_key(tags, key):
    """Pick the key this tag object can actually store."""
    valid = getattr(type(tags), "Get", None)
    if not isinstance(valid, dict) or key in valid:
        return key
    alias = _TAG_ALIAS.get(key)
    if alias and alias in valid:
        return alias
    return key


def normalize_tag_names(raw):
    out = dict(raw or {})
    for source, target in _TAG_ALIAS.items():
        if str(out.get(target) or "").strip() and not str(out.get(source) or "").strip():
            out[source] = out[target]
    return out


def read_easy(path):
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:
        logger.info("tag read failed for %s: %s", path, exc)
        return {}, None
    if audio is None:
        return {}, None
    raw = {}
    if audio.tags is not None:
        for key in list(audio.keys()):
            value = scalar(audio.get(key))
            if value is not None:
                raw[str(key)] = value
    return normalize_tag_names(raw), audio.info


def technical(info):
    if info is None:
        return {"duration_seconds": 0, "sample_rate": None, "bit_depth": None, "bitrate": None}
    length = float(getattr(info, "length", 0) or 0)
    sample_rate = getattr(info, "sample_rate", None)
    bit_depth = getattr(info, "bits_per_sample", None)
    bitrate = getattr(info, "bitrate", None)
    kbps = int(round(bitrate / 1000)) if bitrate else None
    return {
        "duration_seconds": int(length + 0.5) if length else 0,
        "sample_rate": int(sample_rate) if sample_rate else None,
        "bit_depth": int(bit_depth) if bit_depth else None,
        "bitrate": kbps,
    }


def write_easy(path, file_map):
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:
        raise AppError(f"Cannot open tags for {path}: {exc}", 400) from exc
    if audio is None:
        raise AppError("This audio format cannot be tagged", 400)
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception as exc:
            raise AppError(f"Cannot create tags: {exc}", 400) from exc
    skipped = []
    for key, value in file_map.items():
        target = writable_key(audio.tags, key)
        try:
            if value is None or str(value).strip() == "":
                for name in {key, target}:
                    if name in audio:
                        del audio[name]
            else:
                audio[target] = stored_value(key, value)
        except Exception as exc:
            skipped.append(key)
            logger.info("skipped tag %s on %s: %s", key, path, exc)
    try:
        audio.save()
    except Exception as exc:
        raise AppError(f"Could not save tags: {exc}", 400) from exc
    return skipped


def file_map_from_columns(columns, tags):
    mapping = {}
    reverse = {value: key for key, value in FILE_MAP.items()}
    for field, easy in FILE_MAP.items():
        if field not in columns:
            continue
        value = columns[field]
        mapping[easy] = "" if value is None else str(value)
    for key, value in (tags or {}).items():
        if key in mapping or key in reverse or str(key).startswith("_"):
            continue
        mapping[key] = "" if value is None else str(value)
    return mapping
