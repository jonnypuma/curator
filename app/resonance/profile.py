import logging
import re

from resonance import db, library
from resonance.errors import AppError
from resonance.fields import clean_text, genre_label, genre_name, website_url, year_from
from resonance.sources import audiodb, lastfm, musicbrainz

logger = logging.getLogger(__name__)


def save_biography(artist_id, text, fields=None, only_if_longer=False):
    from resonance import nfo
    from resonance.settings import load as load_settings

    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    if artist.get("has_nfo") and not (artist.get("nfo_digest") or ""):
        db.execute(
            "UPDATE artists SET nfo_digest = %s WHERE id = %s AND (nfo_digest IS NULL OR nfo_digest = '')",
            (nfo.artist_digest(artist), artist_id),
        )
    write_nfo = bool(load_settings().get("nfo_on_bio_save", True))
    if write_nfo and isinstance(fields, dict):
        library.store_artist_fields(artist_id, fields)
    stored = str(artist.get("biography") or "").strip()
    if lastfm.is_disambiguation(stored):
        stored = ""
    biography = clean_text(text, 20000)
    if lastfm.is_disambiguation(biography):
        biography = ""
    custom = True
    checked_at = None
    if only_if_longer:
        custom = bool(artist.get("biography_custom"))
        if custom or (stored and (not biography or len(biography) <= len(stored))):
            biography = stored
        else:
            custom = False
        checked_at = None if custom else "stamp"
    if checked_at == "stamp":
        db.execute(
            """
            UPDATE artists
            SET biography = %s, biography_custom = FALSE, biography_checked_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (biography, artist_id),
        )
    else:
        db.execute(
            """
            UPDATE artists
            SET biography = %s, biography_custom = %s, biography_checked_at = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (biography, custom, artist_id),
        )
    written = False
    warning = ""
    if write_nfo:
        try:
            library.write_artist_nfo(artist_id)
            written = True
        except AppError as exc:
            warning = str(exc)
    detail = library.artist_detail(artist_id)
    detail["nfo_written"] = written
    detail["nfo_warning"] = warning
    return detail


def scrape(artist_id, query=None, mbid=None):
    """Return biography and empty-field suggestions. Nothing is stored until the user saves."""
    from resonance.settings import vlog

    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    from resonance.library import guard_editable
    guard_editable(artist, artist.get("name") or "This artist")
    chosen = str(mbid or "").strip()
    text = str(query or "").strip()
    vlog(logger, "artist metadata lookup for %s", text or artist.get("name"))
    if chosen:
        try:
            remote = musicbrainz.get_artist(chosen)
        except Exception as exc:
            raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    elif text:
        remote = _remote_by_name(text)
    else:
        remote = _remote_artist(artist)
    if not remote:
        raise AppError("MusicBrainz has no artist under that name", 404)
    hint = {} if (chosen or text) else artist
    found_id = mbid_hint(remote, hint)
    record = _source(audiodb.artist_by_mbid, found_id) or {}
    info = {}
    lookup_name = remote.get("name") or text or artist["name"]
    try:
        info = lastfm.artist_info(lookup_name, found_id) or {}
    except Exception as exc:
        logger.info("Last.fm artist lookup failed: %s", exc)
    from resonance.settings import metadata_sources

    fields = artist_fields(remote, record, info, found_id)
    sources = []
    if remote:
        sources.append("MusicBrainz")
    if record:
        sources.append("TheAudioDB")
    if info:
        sources.append("Last.fm")
    bio_order = metadata_sources("biography")
    desc_order = metadata_sources("descriptors")
    page = _allmusic_artist(lookup_name, artist, remote) if "allmusic" in bio_order or "allmusic" in desc_order else None
    _home, _discogs, wiki_url = _relation_urls(remote)
    biography, biography_source = _biography_by_priority(
        bio_order,
        page,
        record,
        info,
        lookup_name,
        wiki_url=wiki_url,
        hint=remote.get("disambiguation") or "",
    )
    style, mood = _descriptors_by_priority(desc_order, page, record, info)
    before = len(fields)
    _put(fields, "style", style)
    _put(fields, "mood", mood)
    if page and len(fields) > before:
        sources.append("AllMusic")
    elif page and biography and biography_source == "allmusic":
        sources.append("AllMusic")
    winner = {"allmusic": "AllMusic", "theaudiodb": "TheAudioDB", "lastfm": "Last.fm", "wikipedia": "Wikipedia"}.get(biography_source)
    if winner and winner not in sources:
        sources.append(winner)
    if not biography and not fields:
        raise AppError("No artist metadata found", 404)
    return {
        "biography": biography or "",
        "biography_source": winner or "",
        "fields": fields,
        "sources": sources,
        "artist_name": lookup_name,
    }


def search_choices(artist_id, query):
    """MusicBrainz artists matching a typed name. Nothing is stored."""
    artist = db.fetchone("SELECT id, name FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    name = str(query or "").strip() or str(artist.get("name") or "").strip()
    return search_by_name(name)


def search_by_name(query):
    """MusicBrainz artists matching a typed name. Nothing is stored."""
    name = str(query or "").strip()
    if not name:
        raise AppError("Type an artist name to search")
    try:
        hits = musicbrainz.search_artists(name, limit=8) or []
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    choices = []
    for hit in hits:
        if not hit.get("id"):
            continue
        area = hit.get("area") or {}
        begin = ((hit.get("life-span") or {}).get("begin") or "")[:4]
        choices.append(
            {
                "id": hit.get("id"),
                "name": hit.get("name") or "",
                "disambiguation": hit.get("disambiguation") or "",
                "type": hit.get("type") or "",
                "country": hit.get("country") or area.get("name") or "",
                "begin": begin,
            }
        )
    return {"query": name, "choices": choices}


def mbid_hint(remote, artist):
    return (remote or {}).get("id") or (artist or {}).get("musicbrainz_artist_id")


def _biography_text(source, page, record, info, name, wiki_url, hint):
    if source == "allmusic":
        return clean_text((page or {}).get("biography"), 20000)
    if source == "theaudiodb":
        return _plain((record or {}).get("strBiographyEN"))
    if source == "lastfm":
        bio = (info or {}).get("bio") or {}
        return lastfm.plain_bio(bio.get("content") or bio.get("summary") or "")
    if source == "wikipedia":
        from resonance.sources import wikipedia

        return clean_text(wikipedia.for_artist(name, wiki_url, hint), 20000)
    return ""


def _pick_biography(found, order, longest):
    """Choose one biography. longest keeps the longest text from the enabled sources."""
    usable = []
    for source, text in found:
        if text and not lastfm.is_disambiguation(text):
            usable.append((source, text))
    if not usable:
        return "", ""
    if not longest:
        source, text = usable[0]
        return text, source
    usable.sort(key=lambda item: (-len(item[1]), order.index(item[0]) if item[0] in order else 99))
    source, text = usable[0]
    return text, source


def biography_text(name, mbid, artist=None):
    """The biography Find metadata would keep for this artist."""
    from resonance.settings import metadata_sources

    order = metadata_sources("biography")
    page = _allmusic_artist(name, artist, {}) if "allmusic" in order else None
    record = _source(audiodb.artist_by_mbid, mbid) if "theaudiodb" in order and mbid else {}
    info = {}
    if "lastfm" in order:
        try:
            info = lastfm.artist_info(name, mbid) or {}
        except Exception as exc:
            logger.info("Last.fm artist lookup failed: %s", exc)
    text, _winner = _biography_by_priority(
        order,
        page,
        record or {},
        info,
        name,
        wiki_url=(artist or {}).get("wikipedia_url") or "",
        hint=(artist or {}).get("disambiguation") or "",
    )
    return text or ""


def _biography_by_priority(order, page, record, info, name, wiki_url="", hint=""):
    from resonance.settings import load as load_settings

    longest = load_settings().get("biography_longest", True) is not False
    found = []
    for source in order:
        text = _biography_text(source, page, record, info, name, wiki_url, hint)
        if not text or lastfm.is_disambiguation(text):
            continue
        if not longest:
            return text, source
        found.append((source, text))
    return _pick_biography(found, order, True)


def _descriptors_by_priority(order, page, record, info=None):
    style = mood = ""
    record = record or {}
    for source in order:
        if style and mood:
            break
        if source == "allmusic":
            style = style or "; ".join((page or {}).get("styles") or [])
            mood = mood or "; ".join((page or {}).get("moods") or [])
        elif source == "theaudiodb":
            style = style or str(record.get("strStyle") or "")
            mood = mood or str(record.get("strMood") or "")
        elif source == "lastfm":
            style = style or "; ".join(lastfm.tag_names((info or {}).get("tags")))
    return style, mood


_JUNK_TAGS = {
    "seen live",
    "favorites",
    "favourites",
    "favorite",
    "favourite",
    "my favorite",
    "my favourite",
    "under 2000 listeners",
    "albums i own",
}


def artist_fields(remote, record, info, mbid):
    """Non-empty artist.nfo values found online. The editor fills only blank fields."""
    remote = remote or {}
    record = record or {}
    info = info or {}
    fields = {}
    life = remote.get("life-span") or {}
    kind = str(remote.get("type") or "").strip()
    begin_year = year_from(life.get("begin")) or year_from(record.get("intFormedYear"))
    died_year = year_from(record.get("intDiedYear"))
    disbanded_year = year_from(record.get("strDisbanded"))
    end_year = year_from(life.get("end"))
    if kind.lower() == "person":
        died_year = died_year or end_year
        disbanded_year = None
    elif kind.lower() in {"group", "orchestra", "choir"}:
        disbanded_year = disbanded_year or end_year
        died_year = None
    else:
        disbanded_year = disbanded_year or end_year
    home, discogs, wiki = _relation_urls(remote)
    _put(fields, "type", kind)
    _put(fields, "sortname", remote.get("sort-name"))
    _put(fields, "gender", remote.get("gender") or record.get("strGender"))
    _put(fields, "disambiguation", remote.get("disambiguation"))
    _put(fields, "formed", begin_year)
    _put(fields, "origin", _origin(remote, record))
    if begin_year and (died_year or disbanded_year):
        _put(fields, "years_active", f"{begin_year}-{died_year or disbanded_year}")
    elif begin_year:
        _put(fields, "years_active", f"{begin_year}-present")
    _put(fields, "died", died_year)
    _put(fields, "disbanded", disbanded_year)
    _put(fields, "website", home or _http(record.get("strWebsite")))
    _put(fields, "discogs_url", discogs)
    _put(fields, "wikipedia_url", wiki)
    if mbid:
        _put(fields, "musicbrainz_artist_id", mbid)
    genres = _genre_names(remote, record, info)
    if genres:
        fields["genres"] = genres
    return fields


def _allmusic_artist(name, artist, remote):
    from resonance.sources import allmusic

    if not allmusic.enabled():
        return None
    try:
        return allmusic.artist(name, active=_active_years(artist, remote))
    except Exception as exc:
        logger.info("allmusic artist lookup failed: %s", exc)
        return None


def _active_years(artist, remote):
    """Years this artist was working, including release years already in the library."""
    artist = artist or {}
    remote = remote or {}
    start = year_from((remote.get("life-span") or {}).get("begin")) or year_from(artist.get("formed"))
    end = year_from((remote.get("life-span") or {}).get("end"))
    end = end or year_from(artist.get("died")) or year_from(artist.get("disbanded"))
    active_text = str(artist.get("years_active") or "")
    numbers = [int(item) for item in re.findall(r"(?:19|20)\d{2}", active_text)]
    if numbers:
        start = min(numbers) if start is None else min(start, min(numbers))
        if "present" not in active_text.lower() and len(numbers) > 1:
            end = max(numbers) if end is None else max(end, max(numbers))
    if artist.get("id"):
        rows = db.fetchall(
            "SELECT release_year FROM albums WHERE artist_id = %s AND release_year IS NOT NULL",
            (artist["id"],),
        )
        years = [row["release_year"] for row in rows if row.get("release_year")]
        if years:
            start = min(years) if start is None else min(start, min(years))
            end = max(years) if end is None else max(end, max(years))
    if start is None:
        return None
    if end is None:
        end = 2099
    return (start, end)


def _put(fields, key, value):
    text = clean_text(value, 500)
    if not text or text.lower() in {"null", "none"}:
        return
    fields[key] = text


def _origin(remote, record):
    for area in (remote.get("begin-area"), remote.get("area")):
        name = (area or {}).get("name")
        if name:
            return name
    return remote.get("country") or record.get("strCountry")


def _http(url):
    return website_url(url)


def _relation_urls(remote):
    home = discogs = wiki = ""
    for rel in remote.get("url-relation-list") or []:
        url = _http(rel.get("target") or "")
        kind = str(rel.get("type") or "").lower()
        if not url:
            continue
        if kind in {"official homepage", "official site"} and not home:
            home = url
        elif ("discogs" in kind or "discogs.com" in url) and not discogs:
            discogs = url
        elif ("wikipedia" in kind or "wikipedia.org" in url) and not wiki:
            wiki = url
    return home, discogs, wiki


def _genre_names(remote, record, info):
    names = []

    def add(value):
        label = genre_label(genre_name(value))
        if not label or label.lower() in _JUNK_TAGS:
            return
        if label.lower() in {existing.lower() for existing in names}:
            return
        names.append(label)

    for item in (remote.get("genre-list") or []) + (remote.get("tag-list") or []):
        if isinstance(item, dict):
            add(item.get("name"))
    for part in _split_names(record.get("strGenre")):
        add(part)
    tags = (info.get("tags") or {}).get("tag") or []
    if isinstance(tags, dict):
        tags = [tags]
    for tag in tags:
        if isinstance(tag, dict):
            add(tag.get("name"))
    return names[:8]


def _split_names(value):
    return [part.strip() for part in re.split(r"[,;/|]", str(value or "")) if part.strip()]


def _source(func, arg):
    if not arg:
        return None
    try:
        return func(arg)
    except Exception as exc:
        logger.info("biography source failed: %s", exc)
        return None


def _plain(value):
    text = lastfm.formatted_bio(value)
    if not text or text.lower() in {"null", "none"} or lastfm.is_disambiguation(text) or len(text) < 80:
        return None
    return text[:8000]


def _remote_by_name(name):
    try:
        hits = musicbrainz.search_artists(name, limit=1)
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    if not hits:
        return None
    found = hits[0].get("id")
    if not found:
        return hits[0]
    try:
        return musicbrainz.get_artist(found)
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc


def _remote_artist(artist):
    mbid = artist.get("musicbrainz_artist_id")
    if mbid:
        try:
            return musicbrainz.get_artist(str(mbid))
        except Exception as exc:
            raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    try:
        hits = musicbrainz.search_artists(artist["name"])
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    if not hits:
        return None
    found = hits[0].get("id")
    if not found:
        return hits[0]
    try:
        return musicbrainz.get_artist(found)
    except Exception as exc:
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
