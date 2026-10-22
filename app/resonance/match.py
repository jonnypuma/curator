import logging
import re
from collections import Counter

from psycopg.errors import UniqueViolation
from psycopg.types.json import Json

from resonance import artwork, completeness, db, lyrics, nfo, tags
from resonance.errors import AppError
from resonance.fields import (
    album_title_without_disc,
    ascii_hyphen,
    clean_text,
    join_artists,
    leading_int,
    norm_name,
    opt_uuid,
    opt_uuid_loose,
    release_type,
    genre_label,
    title_with_type,
    title_without_type,
    year_from,
)
from resonance.settings import load as load_settings
from resonance.similarity import (
    LENGTH_TOLERANCE,
    edition_order,
    match_percent,
    release_score,
    text_similarity,
    track_count_similarity,
    track_evidence,
    type_similarity,
)
from resonance.sources import audiodb, deezer, fingerprint, lastfm, musicbrainz, wikipedia

logger = logging.getLogger(__name__)


def _country_code(value):
    text = clean_text(value, 8)
    if not text:
        return None
    text = text.upper()
    if len(text) == 2 and text.isalpha():
        return text
    return None


def _reraise_cancel(exc):
    from resonance.jobs import ScanCancelled

    if isinstance(exc, ScanCancelled):
        raise


def search(album_id, artist_name=None, album_title=None, force_text=False):
    from resonance.jobs import checkpoint
    from resonance.settings import vlog

    checkpoint()
    album, artist, tracks = _context(album_id)
    from resonance.library import guard_editable
    guard_editable(album, album.get("title") or "This album")
    guard_editable(artist, artist.get("name") or "This artist")
    query_artist = artist["name"] if artist_name is None else str(artist_name or "")
    query_title = album["title"] if album_title is None else str(album_title or "")
    if force_text and not query_artist.strip() and not query_title.strip():
        raise AppError("Enter an artist or an album title")
    vlog(logger, "metadata search for %s — %s", query_artist, query_title)
    local_type = _local_release_type(album, tracks)
    remote = deezer.lookup_album(query_artist, query_title)
    deezer_note = deezer.compare([track["title"] for track in tracks], remote)
    checkpoint()
    if force_text:
        groups, acoustid, locked_release, locked_id, disc_ids = _search_by_name(query_artist, query_title, local_type)
    else:
        groups, acoustid, locked_release, locked_id, disc_ids = _identify(album, artist, tracks, local_type)
    fetched = {}
    if locked_release and locked_release.get("id"):
        fetched[str(locked_release["id"])] = locked_release
    grouped = []
    for group in groups:
        if not group or not group.get("id"):
            continue
        releases = _browse_group(group["id"])
        if locked_release and str((locked_release.get("release-group") or {}).get("id") or "") == str(group.get("id")):
            known = {str(item.get("id") or "") for item in releases}
            if str(locked_release.get("id") or "") not in known:
                releases = [locked_release, *releases]
        prepared = [
            _candidate(
                group,
                fetched.get(str(release.get("id") or ""), release),
                tracks,
                acoustid,
                query_artist,
                query_title,
                local_type,
                locked_id,
                disc_ids,
            )
            for release in releases
        ]
        grouped.append(prepared)
    grouped.sort(key=lambda items: max((item["score"] for item in items), default=0), reverse=True)
    if grouped:
        _refine_candidates(
            grouped[0],
            tracks,
            acoustid,
            query_artist,
            query_title,
            local_type,
            locked_id,
            disc_ids,
            fetched,
        )
    candidates = []
    for prepared in grouped:
        prepared.sort(key=edition_order)
        candidates.extend(_keep_editions(prepared))
    _store_fingerprints(acoustid)
    return {
        "candidates": candidates,
        "local_tracks": [_local_track_brief(track) for track in tracks],
        "deezer": deezer_note,
        "acoustid": {
            "skipped": acoustid.get("skipped", False),
            "reason": acoustid.get("reason"),
            "recording_count": len(acoustid.get("recordings") or []),
        },
        "path": album.get("path") or "",
        "query": {"artist": query_artist, "title": query_title},
    }


def release_comparison(album_id, release_id):
    """Local files beside one MusicBrainz release, without writing a proposal."""
    album, artist, tracks = _context(album_id)
    try:
        release = musicbrainz.get_release(str(release_id))
    except Exception as exc:
        _reraise_cancel(exc)
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    if not release:
        raise AppError("Release not found", 404)
    group = release.get("release-group") or {}
    candidate = _candidate(
        group,
        release,
        tracks,
        {"release_groups": []},
        artist["name"],
        album["title"],
        _local_release_type(album, tracks),
        None,
        [],
    )
    return {
        "release_id": str(release.get("id") or ""),
        "title": candidate.get("title") or "",
        "match_percent": candidate.get("match_percent") or 0,
        "local_tracks": [_local_track_brief(track) for track in tracks],
        "tracks": candidate.get("tracks") or [],
    }


def build_proposal(album_id, release_id):
    album, artist, tracks = _context(album_id)
    try:
        release = musicbrainz.get_release(str(release_id))
    except Exception as exc:
        _reraise_cancel(exc)
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    if not release:
        raise AppError("Release not found", 404)
    group = release.get("release-group") or {}
    remote_tracks = _release_tracks(release)
    pairs, local_only, remote_only = _align(tracks, remote_tracks)
    artist_name = _credit(release.get("artist-credit")) or artist["name"]
    artist_mbid = _artist_id(release.get("artist-credit")) or (
        str(artist["musicbrainz_artist_id"]) if artist.get("musicbrainz_artist_id") else None
    )
    genres = _genres(release) or _genres(group)
    year = year_from(release.get("date") or group.get("first-release-date")) or album.get("release_year")
    edition = clean_text(release.get("disambiguation"), 100)
    album_type = _map_type(group)
    raw_title = release.get("title") or group.get("title") or album["title"]
    album_title = ascii_hyphen(title_with_type(raw_title, album_type, load_settings().get("title_suffix_types")))
    facts = _release_facts(release)
    original_album, original_artist = _original_identifiers(group, release)
    facts["musicbrainz_originalalbumid"] = original_album
    facts["musicbrainz_originalartistid"] = original_artist
    instrumental = _is_instrumental(group, release)
    from resonance.settings import metadata_sources

    page = _allmusic_album(raw_title, artist_name, year)
    group_key = group.get("id") or release.get("release-group", {}).get("id")
    review_order = metadata_sources("review")
    desc_order = metadata_sources("descriptors")
    lastfm_album = {}
    if "lastfm" in review_order or "lastfm" in desc_order:
        lastfm_album = lastfm.album_text(artist_name, raw_title) or {}
    biography = _biography(artist_mbid, artist_name, artist, year)
    stored_review = clean_text(album.get("review"), 20000)
    review = stored_review or _review_from(review_order, page, group_key, raw_title, artist_name, lastfm_album)
    desc_style, desc_mood, desc_theme = _album_descriptors(desc_order, page, group_key, lastfm_album)
    proposed = []
    for local, remote in pairs:
        tags_raw = local.get("tags") or {}
        proposed.append(
            {
                "id": local["id"],
                "title": ascii_hyphen(remote.get("title") or local["title"]),
                "artist_name": ascii_hyphen(remote.get("artist") or artist_name or local.get("artist_name")),
                "album_name": album_title,
                "albumartist": ascii_hyphen(artist_name),
                "albumartists": facts.get("albumartists") or "",
                "albumartistsort": facts.get("albumartistsort") or "",
                "artists": remote.get("artists") or facts.get("albumartists") or "",
                "artistsort": remote.get("artistsort") or facts.get("albumartistsort") or "",
                "track_number": remote.get("track_number") or local["track_number"],
                "disc_number": remote.get("disc_number") or local["disc_number"],
                "discsubtitle": remote.get("disc_title") or (local.get("tags") or {}).get("discsubtitle") or "",
                "genre": "; ".join(genres) if genres else local.get("genre"),
                "year": year or local.get("year"),
                "duration_seconds": int(remote.get("duration_seconds") or 0),
                "composer": tags_raw.get("composer") or "",
                "conductor": tags_raw.get("conductor") or "",
                "bpm": tags_raw.get("bpm") or "",
                "initialkey": tags_raw.get("initialkey") or "",
                "replaygain_track_gain": tags_raw.get("replaygain_track_gain") or "",
                "comment": _comment_text(tags_raw.get("comment"), review),
                "musicbrainz_track_id": remote.get("track_id"),
                "musicbrainz_recordingid": remote.get("recording_id"),
                "musicbrainz_release_group_id": str(group.get("id") or ""),
                "musicbrainz_albumid": str(release.get("id") or ""),
                "instrumental": instrumental or bool(remote.get("instrumental")),
                **facts,
                "musicbrainz_artistid": remote.get("artist_ids") or facts.get("musicbrainz_albumartistid") or artist_mbid,
                "isrc": remote.get("isrc") or "",
                "totaltracks": remote.get("disc_tracks") or "",
            }
        )
    return {
        "proposal": {
            "release_id": str(release.get("id") or ""),
            "release_group_id": str(group.get("id") or ""),
            "artist_mbid": artist_mbid,
            "artist_name": artist_name,
            "artist_type": _artist_type(release),
            "album_title": album_title,
            "year": year,
            "edition": edition,
            "type": album_type,
            "genres": genres,
            "biography": biography,
            "review": review,
            "style": "" if clean_text(album.get("style"), 500) else desc_style,
            "mood": "" if clean_text(album.get("mood"), 500) else desc_mood,
            "theme": "" if clean_text(album.get("theme"), 500) else desc_theme,
            "allmusic_rating": album.get("allmusic_rating") or page.get("rating"),
            "allmusic_user_rating": album.get("allmusic_user_rating") or page.get("user_rating"),
            "allmusic_votes": album.get("allmusic_votes") or page.get("votes"),
            "allmusic_url": clean_text(album.get("allmusic_url"), 500) or page.get("url") or "",
            "instrumental": instrumental,
            "country": facts.get("releasecountry") or "",
            **facts,
            "tracks": proposed,
            "unmatched_local": len(local_only),
            "unmatched_remote": len(remote_only),
            "expected": remote_tracks,
        }
    }


def lookup_album_review(album_id, refresh=False):
    """Search the configured sources for an album review and store one that is missing.

    A refresh also compares every enabled source and replaces the stored review when
    a found one is longer, or when the first source has different text that is at
    least as long.
    """
    from resonance.library import album_detail
    from resonance.settings import metadata_sources

    album, artist, _tracks = _context(album_id)
    artist_name = artist["name"] if artist else ""
    title = album.get("title") or ""
    year = album.get("release_year")
    group_key = str(album.get("musicbrainz_release_group_id") or "")
    review_order = metadata_sources("review")
    desc_order = metadata_sources("descriptors")
    page = None
    if "allmusic" in review_order or "allmusic" in desc_order:
        page = _allmusic_album(title, artist_name, year)
    lastfm_album = {}
    if "lastfm" in review_order or "lastfm" in desc_order:
        lastfm_album = lastfm.album_text(artist_name, title) or {}
    stored = clean_text(album.get("review"), 20000)
    status = ""
    review = ""
    if refresh:
        found = _review_candidates(review_order, page, group_key, title, artist_name, lastfm_album)
        review, status = pick_refreshed_review(stored, found)
        wrote = False
        if review:
            db.execute(
                """
                UPDATE albums
                SET review = %s, review_checked_at = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (review, album["id"]),
            )
            wrote = True
            _store_blank_album_text(album, {
                "allmusic_url": (page or {}).get("url") or "",
            })
    else:
        review = "" if stored else _review_from(
            review_order, page, group_key, title, artist_name, lastfm_album
        )
        style, mood, theme = _album_descriptors(desc_order, page, group_key, lastfm_album)
        wrote = _store_blank_album_text(album, {
            "review": review,
            "style": "" if clean_text(album.get("style"), 500) else style,
            "mood": "" if clean_text(album.get("mood"), 500) else mood,
            "theme": "" if clean_text(album.get("theme"), 500) else theme,
            "allmusic_url": "" if clean_text(album.get("allmusic_url"), 500) else (page or {}).get("url") or "",
        })
        if wrote and clean_text(review, 20000):
            status = "saved"
    if wrote and album.get("has_nfo"):
        _rewrite_album_nfo(album_id)
    detail = album_detail(album_id)
    detail["review_found"] = bool(wrote and clean_text(review, 20000))
    detail["review_status"] = status
    detail["review_message"] = _review_message(status, stored, review)
    return detail


_REVIEW_LABELS = {
    "allmusic": "AllMusic",
    "theaudiodb": "TheAudioDB",
    "lastfm": "Last.fm",
    "wikipedia": "Wikipedia",
}


def search_album_reviews(album_id, artist_name=None, title=None):
    """Reviews from the enabled sources for a typed artist and album title. Nothing is stored."""
    from resonance.settings import metadata_sources

    album, artist, _tracks = _context(album_id)
    if artist_name is None:
        name = artist["name"] if artist else ""
    else:
        name = clean_text(artist_name, 255)
    if title is None:
        album_title = title_without_type(album.get("title") or "")
    else:
        album_title = clean_text(title, 500)
    if not name and not album_title:
        raise AppError("Type an artist or an album title")
    year = album.get("release_year")
    group_key = str(album.get("musicbrainz_release_group_id") or "")
    review_order = metadata_sources("review")
    page = _allmusic_album(album_title, name, year) if "allmusic" in review_order else None
    lastfm_album = lastfm.album_text(name, album_title) or {} if "lastfm" in review_order else {}
    found = {
        source: text
        for source, text in _review_candidates(review_order, page, group_key, album_title, name, lastfm_album)
    }
    choices = []
    for source in review_order:
        url = ""
        note = ""
        if source == "allmusic":
            url = clean_text((page or {}).get("url"), 500)
        elif source == "theaudiodb":
            note = "Looked up by MusicBrainz id. The title above does not change this one."
        choices.append({
            "source": source,
            "label": _REVIEW_LABELS.get(source, source),
            "review": found.get(source) or "",
            "url": url,
            "note": note,
        })
    return {"artist": name, "title": album_title, "choices": choices}


def save_chosen_review(album_id, review, source="", url="", allow_blank=False):
    """Store the review the user picked, or the text they typed."""
    from resonance.library import album_detail

    album, _artist, _tracks = _context(album_id)
    text = clean_text(review, 20000) or ""
    if not text and not allow_blank:
        raise AppError("That result has no review to save")
    db.execute(
        """
        UPDATE albums
        SET review = %s, review_checked_at = NULL, updated_at = NOW()
        WHERE id = %s
        """,
        (text, album["id"]),
    )
    page_url = clean_text(url, 500)
    if source == "allmusic" and page_url.startswith("https://www.allmusic.com/"):
        _store_blank_album_text(album, {"allmusic_url": page_url})
    if album.get("has_nfo"):
        _rewrite_album_nfo(album_id)
    detail = album_detail(album_id)
    detail["review_found"] = bool(text)
    detail["review_message"] = "Album review saved." if text else "Album review cleared."
    return detail


def pick_refreshed_review(stored, found):
    """The review to store, and saved, replaced, kept, or missing.

    found is (source, text) in the user's source order. A longer review wins.
    The same length from an earlier source replaces the stored text when it differs.
    A shorter review is left unused.
    """
    stored_text = str(stored or "").strip()
    rows = []
    for source, text in found or []:
        cleaned = str(text or "").strip()
        if cleaned:
            rows.append((source, cleaned))
    if not rows:
        return "", "missing"
    _source, best = max(enumerate(rows), key=lambda item: (len(item[1][1]), -item[0]))[1]
    if not stored_text:
        return best, "saved"
    if best == stored_text:
        return "", "kept"
    if len(best) > len(stored_text):
        return best, "replaced"
    first = rows[0][1]
    if first != stored_text and len(first) >= len(stored_text):
        return first, "replaced"
    return "", "kept"


def _review_message(status, stored, review):
    if status == "saved":
        return "Album review saved."
    if status == "replaced" and len(str(review or "")) > len(str(stored or "").strip()):
        return "A longer review replaced the stored one."
    if status == "replaced":
        return "A newer review replaced the stored one."
    if status == "kept":
        return "The stored review was kept. The sources did not have a longer one."
    if status == "missing":
        return "No album review found."
    return ""


def _store_blank_album_text(album, values):
    sets = []
    params = []
    limits = {"review": 20000, "style": 500, "mood": 500, "theme": 500, "allmusic_url": 500}
    for key, value in values.items():
        text = clean_text(value, limits.get(key, 500))
        if text and not str(album.get(key) or "").strip():
            sets.append(f"{key} = %s")
            params.append(text)
    if not sets:
        return False
    params.append(album["id"])
    db.execute(
        f"UPDATE albums SET {', '.join(sets)}, review_checked_at = NULL, updated_at = NOW() WHERE id = %s",
        tuple(params),
    )
    return True


def _rewrite_album_nfo(album_id):
    from resonance.settings import load as load_settings

    if load_settings().get("nfo_on_bio_save", True) is False:
        return
    try:
        from resonance.library import write_album_nfo

        write_album_nfo(str(album_id))
    except AppError:
        logger.info("album review was stored but album.nfo was not rewritten", exc_info=True)


def remember_release(album_id, proposal):
    """Store the chosen MusicBrainz release on the album without writing tags."""
    from resonance.library import refresh_match_tier

    release_id = opt_uuid(proposal.get("release_id"), "release id")
    group_id = opt_uuid(proposal.get("release_group_id"), "release group id")
    try:
        db.execute(
            """
            UPDATE albums SET
                musicbrainz_release_id = %s,
                musicbrainz_release_group_id = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (release_id, group_id, album_id),
        )
    except UniqueViolation:
        from resonance.db import allow_shared_release_ids

        allow_shared_release_ids()
        db.execute(
            """
            UPDATE albums SET
                musicbrainz_release_id = %s,
                musicbrainz_release_group_id = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (release_id, group_id, album_id),
        )
    refresh_match_tier(album_id)


def release_variants(album_id):
    album, _artist, tracks = _context(album_id)
    group_id = album.get("musicbrainz_release_group_id")
    if not group_id:
        raise AppError("Match this album before swapping the release")
    releases = musicbrainz.browse_releases(str(group_id))
    local_count = len(tracks)
    variants = []
    for release in releases:
        media = release.get("medium-list") or []
        track_count = 0
        formats = []
        for medium in media:
            track_count += len(medium.get("track-list") or [])
            if medium.get("format"):
                formats.append(medium.get("format"))
        if not track_count:
            try:
                track_count = int(release.get("track-count") or 0)
            except (TypeError, ValueError):
                track_count = 0
        catalog = ""
        for item in release.get("label-info-list") or []:
            if item.get("catalog-number"):
                catalog = item.get("catalog-number")
                break
        variants.append(
            {
                "id": release.get("id"),
                "title": release.get("title") or album.get("title"),
                "date": release.get("date") or "",
                "country": release.get("country") or "",
                "barcode": release.get("barcode") or "",
                "catalog": catalog,
                "medium": ", ".join(formats),
                "track_count": track_count,
                "track_delta": track_count - local_count,
            }
        )
    return {"local_tracks": local_count, "releases": variants}


def apply(album_id, body, steps=None, notify=True, on_progress=None):
    from resonance import undo
    from resonance.paths import assert_library_writable
    from resonance.settings import vlog

    if not isinstance(body, dict):
        raise AppError("Expected a JSON object")
    album_row = db.fetchone("SELECT path FROM albums WHERE id = %s", (album_id,))
    if album_row:
        assert_library_writable(album_row["path"])
    enabled = set(steps or ("tags", "nfo", "art", "lyrics", "processed"))
    vlog(logger, "apply match for album %s steps=%s", album_id, ",".join(sorted(enabled)))
    album, artist, tracks = _context(album_id)
    from resonance.library import guard_editable
    guard_editable(album, album.get("title") or "This album")
    guard_editable(artist, artist.get("name") or "This artist")
    by_id = {str(track["id"]): track for track in tracks}
    warnings = []

    def progress(text):
        if on_progress:
            on_progress(text)

    if "tags" in enabled:
        warnings.extend(_write_track_tags(body, by_id, on_progress=progress))
        progress("saving the release")
        _update_release_rows(album, artist, body, warnings, mark_processed="processed" in enabled)
        if body.get("expected"):
            from resonance import gaps

            gaps.store(album["id"], body.get("expected"))
    cfg = load_settings()
    if "nfo" in enabled:
        progress("writing NFO")
        try:
            _write_nfos(album["id"], cfg)
        except Exception as exc:
            warnings.append(f"NFO write failed: {exc}")
    if "art" in enabled:
        progress("saving artwork")
        try:
            warnings.extend(artwork.auto_deploy(album["id"]))
        except Exception as exc:
            warnings.append(f"Artwork download failed: {exc}")
    if "lyrics" in enabled:
        try:
            lyric_result = lyrics.fetch_album(album["id"], on_progress=progress)
            if lyric_result.get("unavailable"):
                warnings.append("LRCLIB is unavailable, so lyrics were not written")
            elif lyric_result["missing"]:
                warnings.append(f"Lyrics missing for {lyric_result['missing']} tracks")
        except Exception as exc:
            warnings.append(f"Lyrics lookup failed: {exc}")
    if "processed" in enabled and "tags" not in enabled:
        from resonance.library import mark

        mark("album", album["id"], "processed")
        mark("artist", artist["id"], "processed")
    completeness.recompute_album(album["id"])
    from resonance.library import album_detail, drop_loaded_match, refresh_match_tier

    drop_loaded_match(album["id"])

    refresh_match_tier(album["id"])
    detail = album_detail(album["id"])
    detail["warnings"] = warnings
    undo.finish()
    if notify:
        album_path = str(album.get("path") or "").replace("\\", "/").rstrip("/")
        folder = str(artist.get("path") or "").strip() or (album_path.rsplit("/", 1)[0] if "/" in album_path else "")
        try:
            from resonance import webhooks

            webhooks.fire("tags", [folder] if folder else [], [artist.get("name") or album.get("title") or ""])
        except Exception:
            logger.info("library update after tag save failed", exc_info=True)
    return detail


def queue_artist_update(album_id):
    """Queue a library update for this album's artist folder.

    Players that can map the folder scan that artist. A player with no matching
    path is left out, so this does not fall back to a full library scan.
    """
    from curator import automation
    from curator.library_queue import enabled_players, full_scan_reason, queue_for, scope_for

    album, artist, _tracks = _context(album_id)
    album_path = str(album.get("path") or "").replace("\\", "/").rstrip("/")
    folder = str(artist.get("path") or "").strip() or (album_path.rsplit("/", 1)[0] if "/" in album_path else "")
    if not folder:
        raise AppError("This album has no folder to send")
    name = artist.get("name") or album.get("title") or "Artist"
    _, cfg = automation.current()
    players = [player for player in enabled_players(cfg) if player != "navidrome"]
    if not players:
        raise AppError("Turn on Kodi, Emby, Jellyfin, or Plex under Settings. Navidrome can only scan its whole music library.", 400)
    chosen = []
    skipped = []
    for player in players:
        full, _paths = scope_for(player, [folder], cfg)
        if full:
            skipped.append(full_scan_reason(player, [folder], cfg) or player)
            continue
        chosen.append(player)
    if not chosen:
        raise AppError(skipped[0] if skipped else "No player has a path for this artist.", 400)
    queued = queue_for(chosen, "music", [folder], False, f"Library update for {name}", cfg, [name])
    if not queued:
        raise AppError("That library update was not queued.", 400)
    message = f"Library update queued for {name}."
    return {"queued": queued, "folder": folder, "message": message}


def _blank_tag_values(current, wanted):
    """Tag values that are present in the proposal and empty on the file."""
    blank = {}
    for key, value in (wanted or {}).items():
        text = str(value or "").strip()
        if text and not str((current or {}).get(key) or "").strip():
            blank[key] = text
    return blank


def fill_stored_release(album_id):
    """Copy blank MusicBrainz fields for the release id already stored on the album.

    Titles, artist names, and disc or track numbers that are already on the file stay
    as they are. An album with no release id is left alone.
    """
    from resonance.paths import assert_library_writable

    album, artist, tracks = _context(album_id)
    if album.get("locked") or artist.get("locked"):
        return 0
    release_id = opt_uuid_loose(album.get("musicbrainz_release_id"))
    if not release_id:
        return 0
    assert_library_writable(album.get("path") or "")
    try:
        release = musicbrainz.get_release(release_id)
    except Exception as exc:
        _reraise_cancel(exc)
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    if not release:
        return 0
    group = release.get("release-group") or {}
    facts = _release_facts(release)
    facts["musicbrainz_albumid"] = str(release.get("id") or "")
    facts["musicbrainz_releasegroupid"] = str(group.get("id") or "")
    genres = _genres(release) or _genres(group)
    if genres:
        facts["genre"] = "; ".join(genres)
    year = year_from(release.get("date") or group.get("first-release-date"))
    pairs, _local_only, _remote_only = _align(tracks, _release_tracks(release))
    paired = {str(local["id"]): remote for local, remote in pairs}
    review = str(album.get("review") or "").strip()
    filled = 0
    for track in tracks:
        remote = paired.get(str(track["id"])) or {}
        wanted = dict(facts)
        if remote.get("artists"):
            wanted["artists"] = remote["artists"]
        if remote.get("artistsort"):
            wanted["artistsort"] = remote["artistsort"]
        if remote.get("artist_ids"):
            wanted["musicbrainz_artistid"] = remote["artist_ids"]
        if remote.get("recording_id"):
            wanted["musicbrainz_recordingid"] = remote["recording_id"]
        if remote.get("track_id"):
            wanted["musicbrainz_trackid"] = remote["track_id"]
        if remote.get("isrc"):
            wanted["isrc"] = remote["isrc"]
        if remote.get("disc_title"):
            wanted["discsubtitle"] = remote["disc_title"]
        if year and not track.get("year"):
            wanted["date"] = str(year)
        if review:
            wanted["comment"] = review
        current, _info = tags.read_easy(track["file_path"])
        blank = _blank_tag_values(current, wanted)
        if not blank:
            continue
        tags.write_easy(track["file_path"], blank)
        raw, _info = tags.read_easy(track["file_path"])
        columns = completeness.columns_from_tags(raw)
        db.execute(
            """
            UPDATE tracks SET
                tags = %s,
                genre = CASE WHEN genre IS NULL OR btrim(genre) = '' THEN %s ELSE genre END,
                year = COALESCE(year, %s),
                musicbrainz_track_id = COALESCE(musicbrainz_track_id, %s),
                musicbrainz_release_group_id = COALESCE(musicbrainz_release_group_id, %s),
                artist_name = CASE WHEN artist_name IS NULL OR btrim(artist_name) = '' THEN %s ELSE artist_name END
            WHERE id = %s
            """,
            (
                Json(columns["tags"]),
                columns["genre"],
                columns["year"],
                columns["musicbrainz_track_id"],
                columns["musicbrainz_release_group_id"],
                columns["artist_name"],
                track["id"],
            ),
        )
        filled += len(blank)
    album_values = {
        "catalog": facts.get("catalognumber"),
        "barcode": facts.get("barcode"),
        "label": facts.get("label"),
        "country": facts.get("releasecountry"),
        "release_status": facts.get("releasestatus"),
    }
    assignments = []
    params = []
    for column, value in album_values.items():
        text = str(value or "").strip()
        if text and not str(album.get(column) or "").strip():
            assignments.append(f"{column} = %s")
            params.append(text)
    group_id = opt_uuid_loose(group.get("id"))
    if group_id and not album.get("musicbrainz_release_group_id"):
        assignments.append("musicbrainz_release_group_id = %s")
        params.append(group_id)
    if year and not album.get("release_year"):
        assignments.append("release_year = %s")
        params.append(year)
    if assignments:
        params.append(album["id"])
        db.execute(
            f"UPDATE albums SET {', '.join(assignments)}, updated_at = NOW() WHERE id = %s",
            tuple(params),
        )
        filled += len(assignments)
    artist_mbid = _artist_id(release.get("artist-credit"))
    if artist_mbid and not artist.get("musicbrainz_artist_id"):
        try:
            if db.artist_mbid_blocked(artist_mbid, artist.get("name"), artist["id"]):
                raise UniqueViolation()
            db.execute(
                "UPDATE artists SET musicbrainz_artist_id = %s, updated_at = NOW() WHERE id = %s",
                (artist_mbid, artist["id"]),
            )
            filled += 1
        except UniqueViolation:
            logger.info("stored artist id %s is already used", artist_mbid)
    if filled:
        completeness.recompute_album(album["id"])
        if album.get("has_nfo"):
            try:
                _write_nfos(album["id"], load_settings())
            except Exception:
                logger.info("nfo refresh after MusicBrainz fill failed for %s", album_id, exc_info=True)
    return filled


def _write_track_tags(body, by_id, on_progress=None):
    warnings = []
    suffix = load_settings().get("title_suffix_types") or {}
    album_type = body.get("type") or ""
    queued = []
    queued_index = []
    for item in body.get("tracks") or []:
        track = by_id.get(str(item.get("id")))
        if track:
            queued.append((item, track))
    total = len(queued)
    for index, (item, track) in enumerate(queued, start=1):
        if on_progress:
            on_progress(f"track {index} of {total}: {track.get('title') or 'untitled'}")
        item = dict(item)
        if item.get("album_name"):
            item["album_name"] = title_with_type(item.get("album_name"), album_type, suffix)
        file_map = _file_map(item)
        try:
            from resonance import undo

            before, _info = tags.read_easy(track["file_path"])
            skipped = tags.write_easy(track["file_path"], file_map)
            undo.snapshot_tags(track["id"], track["file_path"], before)
            try:
                from resonance import pictures

                pictures.embed_track(track["file_path"])
            except Exception:
                logger.info("embed art skipped for %s", track["file_path"], exc_info=True)
        except AppError as exc:
            warnings.append(f"{track['title']}: {exc}")
            continue
        if skipped:
            warnings.append(f"{track['title']} did not store: {', '.join(skipped)}")
        raw, _info = tags.read_easy(track["file_path"])
        columns = completeness.columns_from_tags(raw)
        stored = columns["tags"]
        if item.get("instrumental"):
            stored["_instrumental"] = True
        queued_index.append((track, columns, stored))
    _store_written_indexes(queued_index, warnings)
    return warnings


def _positive_int(value, default):
    number = leading_int(value, default)
    if number is None or number < 1:
        return default
    return number


def _choose_disc_track(wanted, previous, used, taken):
    """Pick a free disc and track slot.

    `taken(disc, number)` is true when a row outside this batch already holds
    that slot. `used` holds slots already given to an earlier row in the batch.
    """
    if wanted not in used and not taken(wanted[0], wanted[1]):
        return wanted, False
    if previous not in used and not taken(previous[0], previous[1]):
        return previous, True
    disc = previous[0] or 1
    number = 1
    while (disc, number) in used or taken(disc, number):
        number += 1
        if number > 100000:
            break
    return (disc, number), False


def _slot_taken(conn, album_id, disc, number, track_id):
    row = conn.execute(
        """
        SELECT id FROM tracks
        WHERE album_id = %s AND disc_number = %s AND track_number = %s AND id <> %s
        """,
        (album_id, disc, number, track_id),
    ).fetchone()
    return row is not None


def _store_written_indexes(written, warnings):
    """Write tag columns for every track in one transaction.

    Disc and track number are unique on an album. Saving one track at a time
    commits that unique check immediately, so a track moving onto a number
    another track still holds is rejected and the index keeps the old number.
    """
    if not written:
        return
    with db.transaction() as conn:
        for index, (track, _columns, _stored) in enumerate(written):
            conn.execute(
                "UPDATE tracks SET track_number = %s WHERE id = %s",
                (-(index + 1), track["id"]),
            )
        used = set()
        for track, columns, stored in written:
            wanted = (
                _positive_int(columns.get("disc_number"), 1),
                _positive_int(columns.get("track_number"), 1),
            )
            previous = (
                _positive_int(track.get("disc_number"), 1),
                _positive_int(track.get("track_number"), 1),
            )
            album_id = track["album_id"]
            track_id = track["id"]

            def taken(disc, number, album_id=album_id, track_id=track_id):
                return _slot_taken(conn, album_id, disc, number, track_id)

            chosen, kept_previous = _choose_disc_track(wanted, previous, used, taken)
            used.add(chosen)
            conn.execute(
                """
                UPDATE tracks SET
                    title = %s,
                    artist_name = %s,
                    album_name = %s,
                    genre = %s,
                    year = %s,
                    track_number = %s,
                    disc_number = %s,
                    musicbrainz_track_id = %s,
                    musicbrainz_release_group_id = %s,
                    tags = %s
                WHERE id = %s
                """,
                (
                    columns["title"],
                    columns["artist_name"],
                    columns["album_name"],
                    columns["genre"],
                    columns["year"],
                    chosen[1],
                    chosen[0],
                    columns["musicbrainz_track_id"],
                    columns["musicbrainz_release_group_id"],
                    Json(stored),
                    track_id,
                ),
            )
            title = track.get("title") or "untitled"
            if chosen != wanted:
                try:
                    tags.write_easy(
                        track["file_path"],
                        {"discnumber": str(chosen[0]), "tracknumber": str(chosen[1])},
                    )
                except Exception:
                    logger.info("could not restore disc and track for %s", title, exc_info=True)
            if kept_previous:
                warnings.append(
                    f"{title}: disc and track number collided; file and index kept the previous number"
                )
            elif chosen != wanted:
                warnings.append(
                    f"{title}: disc and track number collided; file and index stored disc {chosen[0]} track {chosen[1]}"
                )


def _update_release_rows(album, artist, body, warnings, mark_processed=True):
    year = year_from(body.get("year")) if body.get("year") not in (None, "") else album.get("release_year")
    edition = clean_text(body.get("edition"), 100)
    country = _country_code(body.get("releasecountry") or body.get("country"))
    label = clean_text(body.get("label"), 255)
    catalog = clean_text(body.get("catalognumber"), 255)
    barcode = clean_text(body.get("barcode"), 64)
    release_status = clean_text(body.get("releasestatus"), 40)
    album_type = release_type(body.get("type") or album.get("type"))
    title = title_with_type(
        clean_text(body.get("album_title"), 255) or album["title"],
        album_type,
        load_settings().get("title_suffix_types"),
    )
    review = clean_text(body.get("review"), 20000)
    style = clean_text(body.get("style"), 500)
    mood = clean_text(body.get("mood"), 500)
    theme = clean_text(body.get("theme"), 500)
    allmusic_url = clean_text(body.get("allmusic_url"), 500)
    allmusic_rating = _rating_value(body.get("allmusic_rating"))
    allmusic_user_rating = _rating_value(body.get("allmusic_user_rating"))
    allmusic_votes = _vote_count(body.get("allmusic_votes"))
    release_group = opt_uuid(body.get("release_group_id"), "release group id")
    release_id = opt_uuid(body.get("release_id"), "release id")
    try:
        db.execute(
            """
            UPDATE albums SET
                title = %s,
                title_custom = FALSE,
                release_year = %s,
                edition = %s,
                country = %s,
                label = %s,
                catalog = %s,
                barcode = %s,
                release_status = %s,
                type = %s::release_type,
                review = CASE WHEN review IS NULL OR btrim(review) = '' THEN %s ELSE review END,
                style = CASE WHEN style IS NULL OR btrim(style) = '' THEN NULLIF(%s, '') ELSE style END,
                mood = CASE WHEN mood IS NULL OR btrim(mood) = '' THEN NULLIF(%s, '') ELSE mood END,
                theme = CASE WHEN theme IS NULL OR btrim(theme) = '' THEN NULLIF(%s, '') ELSE theme END,
                allmusic_url = CASE WHEN allmusic_url IS NULL OR btrim(allmusic_url) = '' THEN NULLIF(%s, '') ELSE allmusic_url END,
                allmusic_rating = COALESCE(allmusic_rating, %s),
                allmusic_user_rating = COALESCE(allmusic_user_rating, %s),
                allmusic_votes = COALESCE(allmusic_votes, %s),
                musicbrainz_release_group_id = %s,
                musicbrainz_release_id = %s,
                status = CASE WHEN %s THEN 'PROCESSED'::asset_status ELSE status END,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                title, year, edition, country, label, catalog, barcode, release_status,
                album_type, review, style, mood, theme, allmusic_url, allmusic_rating, allmusic_user_rating, allmusic_votes,
                release_group, release_id, mark_processed, album["id"],
            ),
        )
    except UniqueViolation:
        from resonance.db import allow_shared_release_ids

        allow_shared_release_ids()
        db.execute(
            """
            UPDATE albums SET
                title = %s,
                title_custom = FALSE,
                release_year = %s,
                edition = %s,
                country = %s,
                label = %s,
                catalog = %s,
                barcode = %s,
                release_status = %s,
                type = %s::release_type,
                review = CASE WHEN review IS NULL OR btrim(review) = '' THEN %s ELSE review END,
                style = CASE WHEN style IS NULL OR btrim(style) = '' THEN NULLIF(%s, '') ELSE style END,
                mood = CASE WHEN mood IS NULL OR btrim(mood) = '' THEN NULLIF(%s, '') ELSE mood END,
                theme = CASE WHEN theme IS NULL OR btrim(theme) = '' THEN NULLIF(%s, '') ELSE theme END,
                allmusic_url = CASE WHEN allmusic_url IS NULL OR btrim(allmusic_url) = '' THEN NULLIF(%s, '') ELSE allmusic_url END,
                allmusic_rating = COALESCE(allmusic_rating, %s),
                allmusic_user_rating = COALESCE(allmusic_user_rating, %s),
                allmusic_votes = COALESCE(allmusic_votes, %s),
                musicbrainz_release_group_id = %s,
                musicbrainz_release_id = %s,
                status = CASE WHEN %s THEN 'PROCESSED'::asset_status ELSE status END,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                title, year, edition, country, label, catalog, barcode, release_status,
                album_type, review, style, mood, theme, allmusic_url, allmusic_rating, allmusic_user_rating, allmusic_votes,
                release_group, release_id, mark_processed, album["id"],
            ),
        )
    artist_mbid = opt_uuid(body.get("artist_mbid"), "artist id")
    biography = clean_text(body.get("biography"), 20000) or None
    if biography and lastfm.is_disambiguation(biography):
        biography = None
    stored_bio = artist.get("biography") or ""
    if artist.get("biography_custom"):
        biography = None
        replace_biography = False
    elif lastfm.is_disambiguation(stored_bio):
        if not biography:
            biography = clean_text(
                _biography(artist.get("musicbrainz_artist_id"), artist.get("name"), artist),
                20000,
            ) or None
            if biography and lastfm.is_disambiguation(biography):
                biography = None
        replace_biography = True
    elif biography and nfo._folded(biography) == nfo._folded(stored_bio):
        biography = None
        replace_biography = False
    else:
        replace_biography = bool(biography)
    bio_sql = "%s" if replace_biography else "COALESCE(%s, biography)"
    genres = [clean_text(item, 80) for item in (body.get("genres") or []) if clean_text(item, 80)]
    if genres and list(artist.get("genres") or []):
        genres = []
    artist_type = clean_text(body.get("artist_type"), 50) or artist.get("type") or "Group"
    genre_sql = "genres = %s::text[]," if genres else ""
    genre_params = (db.text_array(genres),) if genres else ()
    try:
        db.execute(
            f"""
            UPDATE artists SET
                musicbrainz_artist_id = COALESCE(%s, musicbrainz_artist_id),
                biography = {bio_sql},
                type = %s,
                {genre_sql}
                status = CASE WHEN %s THEN 'PROCESSED'::asset_status ELSE status END,
                updated_at = NOW()
            WHERE id = %s
            """,
            (artist_mbid, biography, artist_type, *genre_params, mark_processed, artist["id"]),
        )
    except UniqueViolation:
        warnings.append("That MusicBrainz artist id is already used by another folder.")
        db.execute(
            f"""
            UPDATE artists SET
                biography = {bio_sql},
                type = %s,
                {genre_sql}
                status = CASE WHEN %s THEN 'PROCESSED'::asset_status ELSE status END,
                updated_at = NOW()
            WHERE id = %s
            """,
            (biography, artist_type, *genre_params, mark_processed, artist["id"]),
        )


def _write_nfos(album_id, cfg):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    artist_payload = dict(artist)
    artist_payload["nfo_name"] = artist["name"]
    nfo.write_artist(artist["path"], cfg["nfo_profile"], artist_payload, cfg["nfo_dialect"], cfg["nfo_backup"])
    album_payload = nfo.album_context(album, artist)
    nfo.write_album(album["path"], cfg["nfo_profile"], album_payload, tracks, cfg["nfo_dialect"], cfg["nfo_backup"])
    db.execute(
        "UPDATE artists SET has_nfo = TRUE, nfo_digest = %s, updated_at = NOW() WHERE id = %s",
        (nfo.artist_digest(artist_payload), artist["id"]),
    )
    db.execute(
        "UPDATE albums SET has_nfo = TRUE, nfo_digest = %s, updated_at = NOW() WHERE id = %s",
        (nfo.album_digest(album_payload, tracks), album["id"]),
    )


def _file_map(item):
    mapping = {
        "title": item.get("title") or "",
        "artist": item.get("artist_name") or "",
        "artists": item.get("artists") or "",
        "artistsort": item.get("artistsort") or "",
        "album": album_title_without_disc(item.get("album_name") or ""),
        "albumartist": item.get("albumartist") or "",
        "albumartists": item.get("albumartists") or "",
        "albumartistsort": item.get("albumartistsort") or "",
        "genre": item.get("genre") or "",
        "date": str(item.get("date") or item.get("year") or ""),
        "originaldate": str(item.get("originaldate") or ""),
        "tracknumber": _paired_number(item.get("track_number"), item.get("totaltracks")),
        "totaltracks": str(item.get("totaltracks") or ""),
        "discnumber": _plain_number(item.get("disc_number")),
        "totaldiscs": _plain_number(item.get("totaldiscs")),
        "isrc": str(item.get("isrc") or ""),
        "composer": item.get("composer") or "",
        "conductor": item.get("conductor") or "",
        "bpm": item.get("bpm") or "",
        "initialkey": item.get("initialkey") or "",
        "replaygain_track_gain": item.get("replaygain_track_gain") or "",
        "comment": item.get("comment") or "",
        "musicbrainz_trackid": item.get("musicbrainz_track_id") or "",
        "musicbrainz_recordingid": item.get("musicbrainz_recordingid") or "",
        "musicbrainz_albumid": item.get("musicbrainz_albumid") or "",
        "musicbrainz_releasegroupid": item.get("musicbrainz_release_group_id") or "",
        "musicbrainz_artistid": item.get("musicbrainz_artistid") or "",
        "musicbrainz_albumartistid": item.get("musicbrainz_albumartistid") or "",
        "catalognumber": item.get("catalognumber") or "",
        "barcode": item.get("barcode") or "",
        "label": item.get("label") or "",
        "releasecountry": item.get("releasecountry") or "",
        "releasestatus": item.get("releasestatus") or "",
        "releasetype": item.get("releasetype") or "",
        "media": item.get("media") or "",
        "asin": item.get("asin") or "",
    }
    subtitle = str(item.get("discsubtitle") or "").strip()
    if subtitle:
        mapping["discsubtitle"] = subtitle
    if "compilation" in str(item.get("releasetype") or "").lower():
        mapping["compilation"] = "1"
    for key in ("musicbrainz_discid", "musicbrainz_originalalbumid", "musicbrainz_originalartistid"):
        text = str(item.get(key) or "").strip()
        if text:
            mapping[key] = text
    return mapping


def _plain_number(value):
    number = leading_int(value, None)
    if not number or number < 1:
        return ""
    return str(number)


def _paired_number(number, total):
    text = str(number or "").strip()
    whole = str(total or "").strip()
    if not text:
        return ""
    if whole:
        return f"{text}/{whole}"
    return text


def _identify(album, artist, tracks, local_type):
    locked_release = None
    locked_id = None
    disc_ids = set()
    group_ids = []
    acoustid = _empty_acoustid("Stored MusicBrainz ids identify this album.")
    release_id = opt_uuid_loose(album.get("musicbrainz_release_id")) or _agreed_uuid(tracks, "musicbrainz_albumid")
    if release_id:
        try:
            locked_release = musicbrainz.get_release(release_id)
        except Exception as exc:
            _reraise_cancel(exc)
            logger.info("stored release lookup failed: %s", exc)
            locked_release = None
        if locked_release:
            locked_id = release_id
            group_id = str((locked_release.get("release-group") or {}).get("id") or "")
            if group_id:
                group_ids = [group_id]
    if not group_ids:
        disc_value = _first_tag(tracks, "musicbrainz_discid")
        if disc_value:
            found = []
            try:
                found = musicbrainz.releases_by_discid(disc_value)
            except Exception as exc:
                _reraise_cancel(exc)
                logger.info("disc id lookup failed: %s", exc)
            for item in found:
                if item.get("id"):
                    disc_ids.add(str(item["id"]))
                group_id = str((item.get("release-group") or {}).get("id") or "")
                if group_id and group_id not in group_ids:
                    group_ids.append(group_id)
            group_ids = group_ids[:3]
            if group_ids:
                acoustid = _empty_acoustid("Disc ID identifies this release.")
    if not group_ids:
        group_id = opt_uuid_loose(album.get("musicbrainz_release_group_id")) or _agreed_uuid(
            tracks, "musicbrainz_releasegroupid"
        )
        if group_id:
            group_ids = [group_id]
            acoustid = _empty_acoustid("Stored MusicBrainz release group identifies this album.")
    if not group_ids:
        from resonance.jobs import checkpoint

        acoustid = fingerprint.fingerprint_tracks(_sample_paths(tracks), limit=None)
        checkpoint()
        recording = _agreed_recording(tracks, acoustid)
        if recording:
            group_ids = _groups_for_recording(recording)
        if not group_ids:
            group_ids = _dominant_groups(acoustid)
    if group_ids:
        groups = []
        for group_id in group_ids:
            if locked_release and str((locked_release.get("release-group") or {}).get("id") or "") == str(group_id):
                groups.append(locked_release.get("release-group"))
                continue
            try:
                loaded = musicbrainz.get_release_group(group_id)
            except Exception as exc:
                _reraise_cancel(exc)
                logger.info("release group lookup failed: %s", exc)
                loaded = {}
            groups.append(loaded or {"id": group_id, "title": album.get("title") or ""})
        return groups, acoustid, locked_release, locked_id, disc_ids
    try:
        found = musicbrainz.search_release_groups(artist["name"], album["title"])
    except Exception as exc:
        _reraise_cancel(exc)
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    found.sort(
        key=lambda group: _group_score(group, artist["name"], album["title"], local_type, acoustid),
        reverse=True,
    )
    return found[:3], acoustid, locked_release, locked_id, disc_ids


def _search_by_name(artist_name, album_title, local_type):
    """MusicBrainz text search. A stored release id is left out so the typed names are used."""
    acoustid = _empty_acoustid("Searching by the artist and album you entered.")
    try:
        found = musicbrainz.search_release_groups(artist_name, album_title, limit=8)
    except Exception as exc:
        _reraise_cancel(exc)
        raise AppError(f"MusicBrainz lookup failed: {exc}", 502) from exc
    found.sort(
        key=lambda group: _group_score(group, artist_name, album_title, local_type, acoustid),
        reverse=True,
    )
    return found[:5], acoustid, None, None, set()


def _groups_for_recording(recording_id):
    try:
        found = musicbrainz.recording_release_groups(recording_id)
    except Exception as exc:
        _reraise_cancel(exc)
        logger.info("recording lookup failed: %s", exc)
        return []
    if not isinstance(found, dict):
        return list(found or [])[:3]
    groups = list(found.get("groups") or [])
    if groups:
        return groups[:3]
    for release_id in found.get("releases") or []:
        try:
            release = musicbrainz.get_release(release_id)
        except Exception as exc:
            _reraise_cancel(exc)
            logger.info("recording release lookup failed: %s", exc)
            continue
        group_id = (release.get("release-group") or {}).get("id")
        if group_id:
            return [group_id]
    return []


def _browse_group(group_id):
    try:
        return musicbrainz.browse_releases(group_id)
    except Exception as exc:
        _reraise_cancel(exc)
        logger.info("release browse failed: %s", exc)
        return []


def _refine_candidates(prepared, tracks, acoustid, artist_name, album_title, local_type, locked_id, disc_ids, fetched):
    from resonance.jobs import checkpoint

    pending = sorted(
        [item for item in prepared if item.get("duration_distance") is None and item.get("release_id")],
        key=lambda item: abs(int(item.get("track_count") or 0) - len(tracks)),
    )[:4]
    for item in pending:
        checkpoint()
        release_id = str(item.get("release_id"))
        release = fetched.get(release_id)
        if release is None or not _has_track_titles(release):
            try:
                release = musicbrainz.get_release(release_id)
            except Exception as exc:
                _reraise_cancel(exc)
                logger.info("release detail failed: %s", exc)
                continue
            fetched[release_id] = release
        group = release.get("release-group") or {"id": item.get("release_group_id"), "title": item.get("title")}
        updated = _candidate(
            group, release, tracks, acoustid, artist_name, album_title, local_type, locked_id, disc_ids
        )
        item.clear()
        item.update(updated)


def _keep_editions(prepared, limit=12):
    if len(prepared) <= limit:
        return prepared
    kept = list(prepared[:limit])
    seen = {id(item) for item in kept}
    for item in prepared:
        if (item.get("locked") or item.get("disc_match")) and id(item) not in seen:
            kept.insert(0, item)
            seen.add(id(item))
    return kept


def _store_fingerprints(acoustid):
    for item in acoustid.get("files") or []:
        if not item.get("path"):
            continue
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


def _sample_paths(tracks, limit=6):
    paths = [track["file_path"] for track in tracks if track.get("file_path")]
    if len(paths) <= limit:
        return paths
    last = len(paths) - 1
    indexes = sorted({round(index * last / (limit - 1)) for index in range(limit)})
    return [paths[index] for index in indexes]


def _empty_acoustid(reason):
    return {
        "skipped": True,
        "reason": reason,
        "release_groups": [],
        "release_group_counts": {},
        "recordings": [],
        "files": [],
    }


def _dominant_groups(acoustid):
    counts = acoustid.get("release_group_counts") or {}
    if counts:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            return [ranked[0][0]]
        return [group_id for group_id, _count in ranked[:3]]
    return list(acoustid.get("release_groups") or [])[:3]


def _acoustid_hit(group, acoustid):
    return str(group.get("id") or "") in set(str(item) for item in (acoustid.get("release_groups") or []))


def _has_track_titles(release):
    for medium in release.get("medium-list") or []:
        for track in medium.get("track-list") or []:
            recording = track.get("recording") or {}
            if recording.get("title") or track.get("title"):
                return True
    return False


def _tag_value(track, key):
    raw = track.get("tags") or {}
    if not isinstance(raw, dict):
        return ""
    return str(raw.get(key) or "").strip()


def _agreed_uuid(tracks, key):
    values = [opt_uuid_loose(_tag_value(track, key)) for track in tracks]
    values = [value for value in values if value]
    if values and len(set(values)) == 1:
        return values[0]
    return None


def _first_tag(tracks, key):
    for track in tracks:
        value = _tag_value(track, key)
        if value:
            return value
    return ""


def _agreed_recording(tracks, acoustid):
    values = []
    for track in tracks:
        found = opt_uuid_loose(_tag_value(track, "musicbrainz_recordingid")) or opt_uuid_loose(
            track.get("acoustid_recording_id")
        )
        if found:
            values.append(found)
    for item in acoustid.get("files") or []:
        found = opt_uuid_loose(item.get("recording_id"))
        if found:
            values.append(found)
    if not values:
        return None
    winner, count = Counter(values).most_common(1)[0]
    if count >= 2 or len(tracks) <= 1:
        return winner
    return None


def _local_release_type(album, tracks):
    tagged = ""
    for track in tracks:
        tagged = _tag_value(track, "releasetype")
        if tagged:
            break
    lowered = tagged.lower()
    if "live" in lowered:
        return "live"
    if "compilation" in lowered:
        return "compilation"
    if "single" in {token.strip() for token in lowered.replace("/", " ").replace(";", " ").split()}:
        return "single"
    tokens = {token.strip() for token in lowered.replace("/", " ").replace(";", " ").split()}
    if "ep" in tokens:
        return "ep"
    if "album" in tokens:
        return "album"
    return album.get("type") or ""


def _original_identifiers(group, release):
    first = str((group or {}).get("first-release-date") or "").strip()
    current_date = str(release.get("date") or "").strip()
    current_artists = _artist_ids(release.get("artist-credit"))
    if first and current_date.startswith(first):
        return str(release.get("id") or ""), current_artists
    group_id = (group or {}).get("id")
    if not group_id:
        return "", ""
    try:
        releases = musicbrainz.browse_releases(str(group_id))
    except Exception as exc:
        _reraise_cancel(exc)
        logger.info("original release lookup failed: %s", exc)
        return "", ""
    matching = [item for item in releases if not first or str(item.get("date") or "").startswith(first)]
    official = [item for item in matching if item.get("status") in (None, "", "Official")]
    pool = official or matching
    if not pool:
        return "", ""
    best = min(pool, key=lambda item: str(item.get("date") or "9999"))
    return str(best.get("id") or ""), _artist_ids(best.get("artist-credit")) or current_artists


def _artist_ids(value):
    if not isinstance(value, list):
        return ""
    found = []
    for item in value:
        if not isinstance(item, dict):
            continue
        mbid = (item.get("artist") or {}).get("id") or item.get("id")
        if mbid and mbid not in found:
            found.append(str(mbid))
    return "; ".join(found)


def _context(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    if not artist:
        raise AppError("Artist not found", 404)
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    return album, artist, tracks


def _group_score(group, artist, title, local_type, acoustid):
    """Album-level Picard score used to choose a release group before editions are ordered."""
    parts = {
        "album": text_similarity(title, group.get("title")),
        "artist": text_similarity(artist, _credit(group.get("artist-credit"))),
        "releasetype": type_similarity(local_type, _map_type(group)),
    }
    return release_score(parts, acoustid=_acoustid_hit(group, acoustid))


def _release_facts(release):
    """Album-level MusicBrainz fields written onto every track when a match is applied."""
    labels = []
    catalogs = []
    for info in release.get("label-info-list") or []:
        name = ((info.get("label") or {}).get("name") or "").strip()
        number = str(info.get("catalog-number") or "").strip()
        if name and name not in labels:
            labels.append(name)
        if number and number not in catalogs:
            catalogs.append(number)
    group = release.get("release-group") or {}
    type_parts = _type_parts(group)
    formats = []
    for medium in release.get("medium-list") or []:
        if medium.get("format") and medium.get("format") not in formats:
            formats.append(medium["format"])
    media = release.get("medium-list") or []
    return {
        "catalognumber": "; ".join(catalogs),
        "barcode": release.get("barcode") or "",
        "label": "; ".join(labels),
        "releasecountry": _country_code(release.get("country")) or "",
        "releasestatus": release.get("status") or "",
        "releasetype": "; ".join(part for part in type_parts if part),
        "media": ", ".join(formats),
        "asin": release.get("asin") or "",
        "date": release.get("date") or "",
        "originaldate": (group.get("first-release-date") or ""),
        "totaldiscs": str(len(media) or ""),
        "musicbrainz_albumartistid": _artist_ids(release.get("artist-credit")),
        "albumartists": join_artists(person["name"] for person in _people(release.get("artist-credit"))),
        "albumartistsort": ascii_hyphen(_sort_credit(release.get("artist-credit"))),
    }


def _local_track_brief(track):
    path = str(track.get("file_path") or "").replace("\\", "/")
    return {
        "disc_number": track.get("disc_number") or 1,
        "track_number": track.get("track_number") or 0,
        "title": track.get("title") or "",
        "duration_seconds": int(track.get("duration_seconds") or 0),
        "file_name": path.rsplit("/", 1)[-1],
    }


def _remote_track_brief(track):
    return {
        "disc_number": track.get("disc_number") or 1,
        "track_number": track.get("track_number") or 0,
        "title": track.get("title") or "",
        "duration_seconds": int(track.get("duration_seconds") or 0),
    }


def _candidate(group, release, tracks, acoustid, artist_name, album_title, local_type, locked_id, disc_ids):
    media = release.get("medium-list") or []
    track_count = 0
    formats = []
    for medium in media:
        track_count += int(medium.get("track-count") or len(medium.get("track-list") or []))
        if medium.get("format"):
            formats.append(medium["format"])
    labels = []
    for info in release.get("label-info-list") or []:
        label = (info.get("label") or {}).get("name")
        if label:
            labels.append(label)
    remote_tracks = _release_tracks(release) if _has_track_titles(release) else []
    title_sim, length_sim, duration_distance = track_evidence(tracks, remote_tracks)
    parts = {
        "title": title_sim,
        "artist": text_similarity(artist_name, _credit(release.get("artist-credit") or group.get("artist-credit"))),
        "album": text_similarity(album_title, release.get("title") or group.get("title")),
        "length": length_sim,
        "totaltracks": track_count_similarity(len(tracks), track_count),
        "releasetype": type_similarity(local_type, _map_type(group)),
    }
    release_id = str(release.get("id") or "")
    locked = bool(locked_id and release_id == str(locked_id))
    disc_match = release_id in {str(item) for item in disc_ids or []}
    score = release_score(parts, acoustid=_acoustid_hit(group, acoustid), identified=locked or disc_match)
    return {
        "release_group_id": group.get("id"),
        "release_id": release.get("id"),
        "title": release.get("title") or group.get("title"),
        "artist": _credit(release.get("artist-credit") or group.get("artist-credit")),
        "year": year_from(release.get("date") or group.get("first-release-date")),
        "country": release.get("country"),
        "status": release.get("status"),
        "edition": release.get("disambiguation") or "",
        "type": _map_type(group),
        "type_label": _type_label(group),
        "track_count": track_count,
        "local_tracks": len(tracks),
        "disc_count": len(media) or 1,
        "format": _format_label(formats),
        "label": ", ".join(labels[:2]),
        "score": round(score, 1),
        "match_percent": match_percent(parts),
        "tracks": [_remote_track_brief(row) for row in remote_tracks],
        "duration_distance": duration_distance,
        "locked": locked,
        "disc_match": disc_match,
        "acoustid_match": _acoustid_hit(group, acoustid),
    }


def _release_tracks(release):
    rows = []
    for medium in release.get("medium-list") or []:
        disc = leading_int(medium.get("position"), 1) or 1
        disc_title = clean_text(medium.get("title"), 255) or ""
        listing = medium.get("track-list") or []
        disc_tracks = len(listing) or int(medium.get("track-count") or 0)
        for track in listing:
            recording = track.get("recording") or {}
            isrcs = recording.get("isrc-list") or []
            rows.append(
                {
                    "disc_number": disc,
                    "disc_title": disc_title,
                    "track_number": leading_int(track.get("number") or track.get("position"), len(rows) + 1),
                    "title": track.get("title") or recording.get("title") or "",
                    "artist": _credit(track.get("artist-credit") or recording.get("artist-credit")),
                    "artists": join_artists(person["name"] for person in _people(track.get("artist-credit") or recording.get("artist-credit"))),
                    "artistsort": ascii_hyphen(_sort_credit(track.get("artist-credit") or recording.get("artist-credit"))),
                    "artist_ids": _artist_ids(track.get("artist-credit") or recording.get("artist-credit")),
                    "track_id": track.get("id"),
                    "recording_id": recording.get("id"),
                    "duration_seconds": _length_seconds(track.get("length") or recording.get("length")),
                    "instrumental": "instrumental" in (recording.get("disambiguation") or "").lower(),
                    "isrc": isrcs[0] if isrcs else "",
                    "disc_tracks": disc_tracks or "",
                }
            )
    return rows


def _compact_title(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _title_index(title, pool):
    """Pick a remote track by its full title, then by a unique shortened title.

    A remix note is part of the full title, so Autumn Sweater and Autumn Sweater
    (μ-Ziq Remix) stay different tracks. The shortened title is used only when one
    remote track still has that name, which keeps a remaster paired to the song.
    """
    compact = _compact_title(title)
    if compact:
        for position, item in enumerate(pool):
            if _compact_title(item.get("title")) == compact:
                return position
    broad = norm_name(title)
    if not broad:
        return None
    hits = [position for position, item in enumerate(pool) if norm_name(item.get("title")) == broad]
    if len(hits) == 1:
        return hits[0]
    return None


def _align(local, remote):
    pool = list(remote)
    pairs = []
    unmatched_local = []
    for track in local:
        index = _title_index(track.get("title"), pool)
        if index is None:
            unmatched_local.append(track)
        else:
            pairs.append((track, pool.pop(index)))
    still_local = []
    for track in unmatched_local:
        best = None
        best_delta = LENGTH_TOLERANCE + 1
        local_length = int(track.get("duration_seconds") or 0)
        if local_length:
            for item in pool:
                remote_length = int(item.get("duration_seconds") or 0)
                if not remote_length:
                    continue
                delta = abs(local_length - remote_length)
                if delta <= LENGTH_TOLERANCE and delta < best_delta:
                    best = item
                    best_delta = delta
        if best is None:
            still_local.append(track)
        else:
            pairs.append((track, best))
            pool.remove(best)
    return pairs, still_local, pool


def _length_seconds(value):
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return 0
    if milliseconds <= 0:
        return 0
    return int(milliseconds / 1000 + 0.5)


def _comment_text(existing, review):
    current = str(existing or "").strip()
    return current or review or ""


def _people(value):
    people = []
    if not isinstance(value, list):
        return people
    for item in value:
        if not isinstance(item, dict):
            continue
        artist = item.get("artist") or {}
        name = artist.get("name") or item.get("name") or ""
        if not str(name).strip():
            continue
        people.append(
            {
                "name": str(name).strip(),
                "sort": str(artist.get("sort-name") or name).strip(),
                "join": item.get("joinphrase") or "",
            }
        )
    return people


def _sort_credit(value):
    parts = []
    for person in _people(value):
        parts.append(person["sort"])
        parts.append(person["join"])
    return "".join(parts).strip()


def _credit(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    parts = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = (item.get("artist") or {}).get("name") or item.get("name") or ""
        parts.append(name)
        parts.append(item.get("joinphrase") or "")
    return "".join(parts).strip()


def _artist_id(value):
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict) and (item.get("artist") or {}).get("id"):
            return item["artist"]["id"]
    return None


def _artist_type(release):
    credit = release.get("artist-credit") or []
    for item in credit:
        if isinstance(item, dict) and (item.get("artist") or {}).get("type"):
            return item["artist"]["type"]
    return "Group"


def _genres(entity):
    names = []
    for key in ("genre-list", "tag-list"):
        for item in entity.get(key) or []:
            name = genre_label(item.get("name"))
            if not name or name.isdigit() or name.lower() in {existing.lower() for existing in names}:
                continue
            names.append(name)
    return names[:8]


def _type_parts(group):
    primary = str(group.get("primary-type") or group.get("type") or "").strip()
    secondary = group.get("secondary-type-list") or group.get("secondary-types") or []
    if isinstance(secondary, str):
        secondary = [secondary]
    parts = []
    if primary:
        parts.append(primary)
    for item in secondary:
        text = str(item or "").strip()
        if text and text.lower() not in {part.lower() for part in parts}:
            parts.append(text)
    return parts


def _type_label(group):
    labels = []
    for part in _type_parts(group):
        labels.append("EP" if part.lower() == "ep" else part)
    return "; ".join(labels)


def _map_type(group):
    secondary = [str(item).lower() for item in group.get("secondary-type-list") or group.get("secondary-types") or []]
    if "live" in secondary:
        return "live"
    if "compilation" in secondary:
        return "compilation"
    primary = group.get("primary-type") or group.get("type") or "album"
    return release_type(str(primary))


def _is_instrumental(group, release):
    secondary = [str(item).lower() for item in group.get("secondary-type-list") or []]
    if "instrumental" in secondary:
        return True
    blob = " ".join(
        [
            release.get("disambiguation") or "",
            group.get("disambiguation") or "",
            release.get("title") or "",
        ]
    ).lower()
    return "instrumental" in blob


def _biography(mbid, name, artist=None, year=None):
    """Same choice as Find metadata, including the longest-biography setting."""
    from resonance.profile import biography_text

    return biography_text(name, mbid, artist)


def _review_from(order, page, group_id, title, artist, lastfm_album=None):
    found = _review_candidates(order, page, group_id, title, artist, lastfm_album, first_only=True)
    return found[0][1] if found else ""


def _review_candidates(order, page, group_id, title, artist, lastfm_album=None, first_only=False):
    found = []
    record = None
    for source in order:
        text = ""
        if source == "allmusic":
            text = clean_text((page or {}).get("review"), 20000)
        elif source == "theaudiodb":
            if record is None:
                record = audiodb.album_by_mbid(group_id) or {}
            text = clean_text(record.get("strDescriptionEN"), 20000)
        elif source == "lastfm":
            text = clean_text((lastfm_album or {}).get("review"), 20000)
        elif source == "wikipedia":
            text = wikipedia.summary(f"{title} {artist} album")
        if text:
            found.append((source, text))
            if first_only:
                return found
    return found


def _album_descriptors(order, page, group_id, lastfm_album=None):
    style = mood = theme = ""
    record = None
    for source in order:
        if source == "allmusic":
            style = style or _joined((page or {}).get("styles"))
            mood = mood or _joined((page or {}).get("moods"))
            theme = theme or _joined((page or {}).get("themes"))
        elif source == "theaudiodb":
            if record is None:
                record = audiodb.album_by_mbid(group_id) or {}
            style = style or clean_text(record.get("strStyle"), 500)
            mood = mood or clean_text(record.get("strMood"), 500)
            theme = theme or clean_text(record.get("strTheme"), 500)
        elif source == "lastfm":
            style = style or _joined((lastfm_album or {}).get("tags"))
    return style, mood, theme


def _allmusic_album(title, artist, year):
    from resonance.sources import allmusic

    if not allmusic.enabled():
        return {}
    try:
        return allmusic.album(artist, title, year) or {}
    except Exception as exc:
        logger.info("allmusic album lookup failed: %s", exc)
        return {}


def _joined(items):
    parts = []
    for item in items or []:
        text = clean_text(item, 80)
        if text and text not in parts:
            parts.append(text)
    return clean_text("; ".join(parts), 500)


def _rating_value(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number > 5:
        return None
    return round(number, 1)


def _vote_count(value):
    if value in (None, ""):
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _format_label(formats):
    if not formats:
        return ""
    counts = {}
    for name in formats:
        counts[name] = counts.get(name, 0) + 1
    parts = []
    for name, count in counts.items():
        parts.append(f"{count}×{name}" if count > 1 else name)
    return " + ".join(parts)
