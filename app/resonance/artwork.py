import hashlib
import io
import logging
import os
import re
import threading
import time
import uuid

from PIL import Image

from resonance import completeness, db
from resonance.errors import AppError
from resonance.fields import title_without_type
from resonance.paths import (
    artwork_cache_dir,
    assert_library_writable,
    assert_readable,
    atomic_write,
    additional_artwork_dir,
    additional_media_dir,
    previous_additional_artwork_dir,
    legacy_artwork_cache_dir,
    previous_artwork_cache_dir,
    undo_dir,
)
from resonance import thumbs
from resonance.settings import load as load_settings
from resonance.sources import audiodb, coverart, deezer, fanart, lastfm
from resonance.sources.client import get_bytes, probe_image

logger = logging.getLogger(__name__)

JPEG_TYPES = {
    "front",
    "artistthumb",
    "back",
    "spine",
    "banner",
    "fanart",
    "landscape",
    "tray",
    "obi",
    "liner",
    "sticker",
    "poster",
    "matrix",
    "top",
    "bottom",
}
PNG_TYPES = {"discart", "clearlogo", "clearart"}
ARTIST_TYPES = {"artistthumb", "fanart", "banner", "clearlogo", "clearart", "landscape", "extrafanart"}
FILENAMES = {
    "front": "folder.jpg",
    "artistthumb": "folder.jpg",
    "back": "back.jpg",
    "discart": "discart.png",
    "spine": "spine.jpg",
    "clearlogo": "clearlogo.png",
    "clearart": "clearart.png",
    "banner": "banner.jpg",
    "fanart": "fanart.jpg",
    "landscape": "landscape.jpg",
    "booklet": "booklet.pdf",
    "tray": "tray.jpg",
    "obi": "obi.jpg",
    "liner": "liner.jpg",
    "sticker": "sticker.jpg",
    "poster": "poster.jpg",
    "matrix": "matrix.jpg",
    "top": "top.jpg",
    "bottom": "bottom.jpg",
}
ALBUM_TYPES = (
    "front",
    "back",
    "discart",
    "spine",
    "booklet",
    "tray",
    "obi",
    "liner",
    "sticker",
    "poster",
    "matrix",
    "top",
    "bottom",
)
ALBUM_FILE_NAMES = {
    "front": ("folder.jpg", "folder.jpeg", "cover.jpg", "thumb.jpg"),
    "back": ("back.jpg", "back.jpeg"),
    "discart": ("discart.png", "discart.jpg", "cdart.png", "disc.png"),
    "spine": ("spine.jpg", "spine.png"),
    "booklet": ("booklet.png", "booklet.pdf", "booklet.jpg"),
    "tray": ("tray.jpg", "sleeve.jpg"),
    "obi": ("obi.jpg",),
    "liner": ("liner.jpg",),
    "sticker": ("sticker.jpg",),
    "poster": ("poster.jpg",),
    "matrix": ("matrix.jpg",),
    "top": ("top.jpg",),
    "bottom": ("bottom.jpg",),
}
CAA_TO_KODI = (
    ("front", "front"),
    ("back", "back"),
    ("medium", "discart"),
    ("spine", "spine"),
    ("booklet", "booklet"),
    ("tray", "tray"),
    ("obi", "obi"),
    ("liner", "liner"),
    ("sticker", "sticker"),
    ("poster", "poster"),
    ("matrix/runout", "matrix"),
    ("top", "top"),
    ("bottom", "bottom"),
)


def harvest(album_id, scope="both", respect_enabled=True, query=None, only_types=None):
    album, artist = _subjects(album_id)
    cfg = load_settings()
    warnings = []
    stored_artist = artist["name"] if artist else ""
    stored_title = album["title"] if album else ""
    text, artist_name, album_title = _resolve_query(query, stored_artist, stored_title)
    extra_group = _extra_release_group(text, stored_artist, stored_title, artist_name, album_title, warnings)
    _clear_remote(album["id"] if scope != "artist" else None, artist["id"] if artist and scope != "album" else None)
    candidates = _candidates(
        album,
        artist,
        cfg,
        warnings,
        scope=scope,
        respect_enabled=respect_enabled,
        artist_name=artist_name,
        album_title=album_title,
        extra_group_id=extra_group,
        only_types=only_types,
    )
    if scope == "album":
        candidates = [item for item in candidates if item["asset_type"] in ALBUM_TYPES]
    elif scope == "artist":
        candidates = [item for item in candidates if item["asset_type"] in ARTIST_TYPES and not item.get("album_id")]
    from resonance.settings import vlog

    vlog(logger, "artwork harvest album=%s scope=%s candidates=%s", album_id, scope, len(candidates))
    _persist(candidates, warnings)
    return {
        "album": _annotate(list_for_album(album["id"]), cfg) if scope != "artist" else [],
        "artist": _annotate(list_for_artist(artist["id"]), cfg) if artist and scope != "album" else [],
        "warnings": warnings,
        "query": text,
    }


def artwork_query(artist_name, album_title):
    parts = [str(artist_name or "").strip(), title_without_type(album_title)]
    return " - ".join(part for part in parts if part)


def split_artwork_query(text):
    raw = str(text or "").strip()
    for separator in (" — ", " – ", " - "):
        if separator in raw:
            artist, title = raw.split(separator, 1)
            return artist.strip(), title.strip()
    return "", raw


def _resolve_query(query, stored_artist, stored_title):
    stored = artwork_query(stored_artist, stored_title)
    text = stored if query is None else str(query).strip()
    if not text:
        text = stored
    artist_name, album_title = split_artwork_query(text)
    if not artist_name:
        artist_name = str(stored_artist or "").strip()
    album_title = title_without_type(album_title)
    if not album_title:
        album_title = title_without_type(stored_title)
    return artwork_query(artist_name, album_title), artist_name, album_title


def _extra_release_group(text, stored_artist, stored_title, artist_name, album_title, warnings):
    if text == artwork_query(stored_artist, stored_title):
        return None
    if not artist_name or not album_title:
        return None
    from resonance.sources import musicbrainz

    try:
        groups = musicbrainz.search_release_groups(artist_name, album_title) or []
    except Exception as exc:
        warnings.append(f"MusicBrainz search failed: {exc}")
        return None
    group_id = str(groups[0].get("id") or "") if groups else ""
    return group_id or None


def harvest_artist(artist_id, respect_enabled=True, query=None, only_types=None):
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    cfg = load_settings()
    warnings = []
    stored = str(artist.get("name") or "").strip()
    name = str(query).strip() if query is not None else ""
    if not name:
        name = stored
    looked = dict(artist)
    looked["name"] = name
    if name.casefold() != stored.casefold():
        from resonance.sources import musicbrainz

        looked["musicbrainz_artist_id"] = None
        try:
            hits = musicbrainz.search_artists(name, limit=1) or []
            looked["musicbrainz_artist_id"] = hits[0].get("id") if hits else None
        except Exception as exc:
            warnings.append(f"MusicBrainz search failed: {exc}")
        if not looked["musicbrainz_artist_id"] and not any(item.startswith("MusicBrainz search failed") for item in warnings):
            warnings.append("MusicBrainz has no artist under that search. Name-based sources are still checked.")
    _clear_remote(None, artist["id"])
    candidates = _candidates(
        None, looked, cfg, warnings, scope="artist", respect_enabled=respect_enabled, only_types=only_types
    )
    candidates = [item for item in candidates if item["asset_type"] in ARTIST_TYPES and not item.get("album_id")]
    from resonance.settings import vlog

    vlog(logger, "artist artwork harvest for %s candidates=%s", name, len(candidates))
    _persist(candidates, warnings)
    return {
        "album": [],
        "artist": _annotate(list_for_artist(artist["id"]), cfg),
        "warnings": warnings,
        "query": name,
    }


def _clear_remote(album_id, artist_id):
    if album_id and artist_id:
        db.execute(
            """
            DELETE FROM artwork_pool
            WHERE is_selected = FALSE
              AND source_provider <> 'local'
              AND (album_id = %s OR (artist_id = %s AND album_id IS NULL))
            """,
            (album_id, artist_id),
        )
        return
    if album_id:
        db.execute(
            """
            DELETE FROM artwork_pool
            WHERE is_selected = FALSE
              AND source_provider <> 'local'
              AND album_id = %s
            """,
            (album_id,),
        )
    if artist_id:
        db.execute(
            """
            DELETE FROM artwork_pool
            WHERE is_selected = FALSE
              AND source_provider <> 'local'
              AND artist_id = %s AND album_id IS NULL
            """,
            (artist_id,),
        )


def _persist(candidates, warnings):
    deadline = time.time() + 75
    stored = 0
    for candidate in candidates:
        if time.time() > deadline or stored >= 48:
            warnings.append("Artwork search stopped early so the page stays responsive.")
            break
        if _known(candidate):
            continue
        path, width, height, size = _look_at(candidate["source_url"])
        if size is None:
            continue
        resolution = f"{width}x{height}" if width and height else None
        db.execute(
            """
            INSERT INTO artwork_pool (
                album_id, artist_id, asset_type, source_url, local_path, resolution,
                file_size_bytes, is_selected, source_provider
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s)
            """,
            (
                candidate["album_id"],
                candidate["artist_id"],
                candidate["asset_type"],
                candidate["source_url"],
                path,
                resolution,
                size,
                candidate["source_provider"],
            ),
        )
        stored += 1


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def store_upload(asset_type, data, album_id=None, artist_id=None):
    """Save an image from the user's computer and select it for this artwork type."""
    asset_type = str(asset_type or "").strip().lower()
    if album_id:
        if asset_type not in ALBUM_TYPES:
            raise AppError("Unknown album artwork type", 400)
        if not db.fetchone("SELECT id FROM albums WHERE id = %s", (album_id,)):
            raise AppError("Album not found", 404)
        artist_id = None
    elif artist_id:
        if asset_type not in ARTIST_TYPES:
            raise AppError("Unknown artist artwork type", 400)
        if not db.fetchone("SELECT id FROM artists WHERE id = %s", (artist_id,)):
            raise AppError("Artist not found", 404)
        album_id = None
    else:
        raise AppError("Artwork needs an album or an artist", 400)
    width, height = _accept_upload(asset_type, data)
    folder = additional_media_dir("music")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, uuid.uuid4().hex + _upload_ext(data))
    temp = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        # Written aside and renamed, so a request that arrives meanwhile never reads half an image.
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError as exc:
        raise AppError(f"Could not store the image: {exc}", 500) from exc
    resolution = f"{width}x{height}" if width and height else None
    row = db.fetchone(
        """
        INSERT INTO artwork_pool (
            album_id, artist_id, asset_type, source_url, local_path, resolution,
            file_size_bytes, is_selected, source_provider
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 'local')
        RETURNING id
        """,
        (
            album_id,
            artist_id,
            asset_type,
            f"upload:{uuid.uuid4().hex}",
            path,
            resolution,
            len(data),
        ),
    )
    return select(row["id"])


def _accept_upload(asset_type, data):
    asset_type = str(asset_type or "").strip().lower()
    if asset_type not in ALBUM_TYPES and asset_type not in ARTIST_TYPES:
        raise AppError("Unknown artwork type", 400)
    if not data:
        raise AppError("Choose an image file", 400)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("Artwork files must be 25 MB or smaller", 400)
    width, height = _measure(data)
    if asset_type == "booklet" and (data.startswith(b"%PDF") or width):
        return width, height
    if asset_type == "booklet":
        raise AppError("A booklet must be a PDF or an image", 400)
    if not width:
        raise AppError("That file is not an image", 400)
    return width, height


def _upload_ext(data):
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"GIF8"):
        return ".gif"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def list_for_album(album_id):
    return db.fetchall(
        """
        SELECT * FROM artwork_pool
        WHERE album_id = %s
        ORDER BY is_selected DESC, asset_type, created_at DESC
        """,
        (album_id,),
    )


def list_for_artist(artist_id):
    if not artist_id:
        return []
    return db.fetchall(
        """
        SELECT * FROM artwork_pool
        WHERE artist_id = %s AND album_id IS NULL
        ORDER BY is_selected DESC, asset_type, created_at DESC
        """,
        (artist_id,),
    )


def _clear_selected_siblings(row, artist):
    """One image stays selected for a type. Extra fanart can keep several."""
    asset = (row or {}).get("asset_type") or ""
    if not asset or asset == "extrafanart":
        return
    art_id = row["id"]
    if row.get("album_id") and asset not in ARTIST_TYPES:
        db.execute(
            """
            UPDATE artwork_pool SET is_selected = FALSE
            WHERE album_id = %s AND asset_type = %s AND id <> %s
            """,
            (row["album_id"], asset, art_id),
        )
    artist_id = row.get("artist_id") or (artist or {}).get("id")
    if artist_id and (asset in ARTIST_TYPES or not row.get("album_id")):
        db.execute(
            """
            UPDATE artwork_pool SET is_selected = FALSE
            WHERE artist_id = %s AND asset_type = %s AND id <> %s
            """,
            (artist_id, asset, art_id),
        )


def select(art_id, refresh_scores=True):
    row = db.fetchone("SELECT * FROM artwork_pool WHERE id = %s", (art_id,))
    if not row:
        raise AppError("Artwork not found", 404)
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (row["album_id"],)) if row["album_id"] else None
    artist = None
    if row["artist_id"]:
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (row["artist_id"],))
    elif album:
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    data, choice_path, downloaded = _load_choice(row)
    if not data:
        raise AppError("Could not download that image", 502)
    cfg = load_settings()
    directory = _destination_dir(row, album, artist, cfg)
    library_path = (album or {}).get("path") or (artist or {}).get("path") or directory
    assert_library_writable(library_path)
    booklet_pages = 0
    subject = _undo_subject(row, album, artist)
    previous_art = _selected_art_id(row) if subject else None
    remembered = False
    already = False
    if row["asset_type"] == "booklet" and row.get("album_id") and (row.get("source_provider") or "") == "caa":
        pages = []
        for page in _booklet_page_rows(row):
            page_data, _page_path, page_downloaded = _load_choice(page)
            downloaded = downloaded or page_downloaded
            if page_data:
                pages.append((page, page_data))
        if not any(str(page["id"]) == str(row["id"]) for page, _page_data in pages):
            raise AppError("Could not download that image", 502)
        written = _write_booklet_set(directory, pages)
        _page, filename, target, payload = next(item for item in written if str(item[0]["id"]) == str(row["id"]))
        booklet_pages = len(written)
        if choice_path and not _same_file(choice_path, target):
            target_record = choice_path
        else:
            target_record = target
    else:
        if row["asset_type"] == "extrafanart":
            filename, payload = _next_fanart_name(directory, data)
            if not filename:
                raise AppError("This folder already has fanart1 through fanart999")
        elif row["asset_type"] == "fanart":
            extension = image_extension(data)
            payload = data if extension == ".png" else _to_jpeg(data)
            filename = fanart_filename(0, extension)
        else:
            filename, payload = _export_bytes(row["asset_type"], data, os.path.basename(row["local_path"] or "image"))
        target = os.path.join(directory, filename)
        already = row["asset_type"] != "extrafanart" and _same_payload(target, payload)
        if already:
            if choice_path and not _same_file(choice_path, target):
                target_record = choice_path
            else:
                target_record = target
        else:
            if subject and os.path.isfile(target):
                remembered = _remember_artwork(subject[0], subject[1], row["asset_type"], target, previous_art, str(row["id"]))
            _keep_other_copies(target, row["id"])
            target = atomic_write(target, payload, binary=True)
            if choice_path and not _same_file(choice_path, target):
                target_record = choice_path
            else:
                target_record = target
    from resonance.settings import vlog

    vlog(logger, "artwork saved %s to %s", row["asset_type"], target)
    if row["asset_type"] in {"fanart", "extrafanart"}:
        _clear_other_fanart_ext(directory, filename)
    width, height = _measure(payload)
    resolution = f"{width}x{height}" if width and height else row["resolution"]
    _clear_selected_siblings(row, artist)
    db.execute(
        """
        UPDATE artwork_pool
        SET is_selected = TRUE, local_path = %s, resolution = %s, file_size_bytes = %s
        WHERE id = %s
        """,
        (target_record, resolution, os.path.getsize(target), row["id"]),
    )
    _drop_cached_original(row, choice_path, target)
    if row["asset_type"] == "discart":
        _mirror_disc_art(directory, payload, album)
    if row["asset_type"] == "front" and album:
        db.execute(
            """
            UPDATE albums
            SET has_artwork = TRUE, artwork_width = %s, artwork_height = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (width, height, album["id"]),
        )
        if not already:
            _embed_album(album["id"])
        if refresh_scores:
            completeness.recompute_album(album["id"])
    if row["asset_type"] == "artistthumb" and artist:
        db.execute(
            """
            UPDATE artists
            SET has_artwork = TRUE, artwork_width = %s, artwork_height = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (width, height, artist["id"]),
        )
    elif row["artist_id"] and row["album_id"] is None and artist:
        db.execute("UPDATE artists SET updated_at = NOW() WHERE id = %s", (artist["id"],))
    updated = dict(db.fetchone("SELECT * FROM artwork_pool WHERE id = %s", (art_id,)))
    if booklet_pages:
        updated["booklet_pages"] = booklet_pages
    updated["undo"] = remembered
    updated["already_on_disk"] = already
    updated["downloaded"] = bool(downloaded) and not already
    return updated


def _drop_cached_original(row, choice_path, target):
    """The chosen image is now saved with the music, so the downloaded original in the cache is not needed.

    It is fetched again if it is ever asked for. The row then points at the saved file.
    """
    if not choice_path or not str((row or {}).get("source_url") or "").startswith(("http://", "https://")):
        return False
    try:
        cache = os.path.realpath(artwork_cache_dir())
        real = os.path.realpath(choice_path)
    except OSError:
        return False
    if not real.startswith(cache + os.sep) or _same_file(choice_path, target):
        return False
    try:
        os.remove(choice_path)
    except OSError:
        return False
    db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (target, row["id"]))
    return True


def remove(art_id):
    """Delete one artwork row and its file on disk."""
    from resonance.paths import assert_library_writable

    row = db.fetchone("SELECT * FROM artwork_pool WHERE id = %s", (art_id,))
    if not row:
        raise AppError("Artwork not found", 404)
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (row["album_id"],)) if row["album_id"] else None
    artist = None
    if row["artist_id"]:
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (row["artist_id"],))
    elif album:
        artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    path = row.get("local_path") or ""
    library_path = (album or {}).get("path") or (artist or {}).get("path") or ""
    if path and _under_library(path):
        assert_library_writable(library_path or os.path.dirname(path))
    selected = bool(row.get("is_selected"))
    asset_type = row.get("asset_type") or ""
    source_url = row.get("source_url") or ""
    db.execute("DELETE FROM artwork_pool WHERE id = %s", (art_id,))
    _drop_exclusive(path)
    home = (album or {}).get("path") or (artist or {}).get("path") or ""
    deployed_name = FILENAMES.get(asset_type)
    if selected and home and deployed_name:
        deployed = os.path.join(home, deployed_name)
        if os.path.isfile(deployed) and not _same_file(deployed, path):
            _drop_exclusive(deployed)
    if source_url.startswith(("http://", "https://")):
        cache = _find_cache(source_url)
        if cache and not _same_file(cache, path):
            _drop_exclusive(cache)
    if selected and asset_type == "discart" and album and album.get("path"):
        _clear_deployed_discarts(album["path"])
    if selected and asset_type == "front" and album:
        if not cover_path(album["id"]):
            db.execute(
                """
                UPDATE albums
                SET has_artwork = FALSE, artwork_width = NULL, artwork_height = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (album["id"],),
            )
            completeness.recompute_album(album["id"])
        else:
            db.execute("UPDATE albums SET updated_at = NOW() WHERE id = %s", (album["id"],))
    elif selected and asset_type == "artistthumb" and artist:
        if not artist_image(artist["id"], "artistthumb"):
            db.execute(
                """
                UPDATE artists
                SET has_artwork = FALSE, artwork_width = NULL, artwork_height = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (artist["id"],),
            )
        else:
            db.execute("UPDATE artists SET updated_at = NOW() WHERE id = %s", (artist["id"],))
    elif artist and row["album_id"] is None:
        db.execute("UPDATE artists SET updated_at = NOW() WHERE id = %s", (artist["id"],))
    elif album:
        db.execute("UPDATE albums SET updated_at = NOW() WHERE id = %s", (album["id"],))
    return {"id": str(art_id), "removed": True}


def _same_file(left, right):
    if not left or not right:
        return False
    try:
        return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))
    except OSError:
        return os.path.normcase(left) == os.path.normcase(right)


def _under_library(path):
    from resonance.paths import inside, music_roots

    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return any(root and inside(root, real) for root in music_roots())


def _artwork_file_allowed(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    for managed in _managed_dirs():
        if real.startswith(os.path.realpath(managed) + os.sep):
            return True
    return _under_library(real)


def _drop_exclusive(path):
    if not _artwork_file_allowed(path):
        return
    other = db.fetchone("SELECT id FROM artwork_pool WHERE local_path = %s LIMIT 1", (path,))
    if other:
        return
    try:
        os.remove(path)
    except OSError as exc:
        logger.info("could not remove artwork file %s: %s", path, exc)



def _managed_dirs():
    """Folders whose files the app wrote itself. The old cache folder stays listed until it has been emptied."""
    return [
        artwork_cache_dir(),
        additional_artwork_dir(),
        previous_additional_artwork_dir(),
        legacy_artwork_cache_dir(),
        previous_artwork_cache_dir(),
    ]


def additional_stats():
    """How many files the uploaded and replaced artwork folder holds, and how much space they use."""
    folder = additional_artwork_dir()
    files = size = 0
    for base, _dirs, names in os.walk(folder):
        for name in names:
            try:
                size += os.path.getsize(os.path.join(base, name))
                files += 1
            except OSError:
                continue
    rows = db.fetchone(
        "SELECT (SELECT count(*) FROM artwork_pool WHERE local_path LIKE %s) + (SELECT count(*) FROM video_art_extra) AS n",
        (folder.replace("\\", "/").rstrip("/") + "/%",),
    )
    return {
        "path": folder,
        "files": files,
        "bytes": size,
        "options": int((rows or {}).get("n") or 0),
        "mounted": os.path.ismount(os.path.dirname(os.path.dirname(folder))),
    }


def purge_additional():
    """Delete every uploaded and replaced artwork file, and the options in the artwork window that used them.

    An image that is the chosen artwork is never in this folder (choosing copies it next to the music files), but a
    row marked as chosen is left alone with its file in case it is.
    """
    folder = additional_artwork_dir()
    removed = freed = 0
    keep = set()
    db.execute("DELETE FROM video_art_extra", ())
    rows = db.fetchall("SELECT id, local_path, is_selected FROM artwork_pool WHERE local_path IS NOT NULL", ())
    for row in rows:
        path = row["local_path"]
        if not _inside_dir(path, folder):
            continue
        if row.get("is_selected"):
            keep.add(os.path.normcase(os.path.realpath(path)))
            continue
        db.execute("DELETE FROM artwork_pool WHERE id = %s", (row["id"],))
    for base, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(base, name)
            if os.path.normcase(os.path.realpath(path)) in keep:
                continue
            try:
                freed += os.path.getsize(path)
                os.remove(path)
                removed += 1
            except OSError:
                logger.info("could not remove %s", path, exc_info=True)
    return {"removed": removed, "bytes": freed}


CACHE_KEEP_SECONDS = 7 * 24 * 3600
CACHE_MAX_BYTES = 1024 * 1024 * 1024


def sweep_cache():
    """Keep the downloaded artwork cache small. Only the rebuildable cache folder is touched.

    Files no row points to are removed. A file for an option that was never chosen goes after a week without use,
    and the least recently used ones go when the folder is over 1 GB. The file behind a chosen image stays.
    A removed file is downloaded again if the option is opened or chosen. Uploaded files, kept copies and the
    undo files live in the config folder and are never touched here.
    """
    cache_dir = artwork_cache_dir()
    if not os.path.isdir(cache_dir):
        return

    rows = db.fetchall("SELECT local_path, is_selected FROM artwork_pool WHERE local_path IS NOT NULL", ())
    known = {row["local_path"] for row in rows}
    chosen = {row["local_path"] for row in rows if row.get("is_selected")}

    removed = 0
    errors = 0
    candidates = []
    for entry in os.scandir(cache_dir):
        if entry.is_dir():
            continue
        real = os.path.normcase(os.path.realpath(entry.path))
        try:
            info = entry.stat()
        except OSError:
            continue
        if entry.path not in known and real not in known:
            try:
                os.remove(entry.path)
                removed += 1
            except OSError as exc:
                logger.warning("sweep_cache: could not remove %s: %s", entry.path, exc)
                errors += 1
        elif entry.path not in chosen and real not in chosen:
            candidates.append((info.st_mtime, info.st_size, entry.path))

    now = time.time()
    candidates.sort()
    total = sum(size for _m, size, _p in candidates)
    for modified, size, path in candidates:
        if now - modified <= CACHE_KEEP_SECONDS and total <= CACHE_MAX_BYTES:
            break
        try:
            os.remove(path)
            removed += 1
            total -= size
        except OSError as exc:
            logger.warning("sweep_cache: could not remove %s: %s", path, exc)
            errors += 1

    if removed or errors:
        logger.info("sweep_cache: removed %d file(s), %d error(s)", removed, errors)
    try:
        thumbs.trim_all()
    except Exception:
        logger.warning("sweep_cache: could not trim the thumbnails", exc_info=True)


def _labels_for(ids, table):
    if not ids:
        return {}
    if table == "artists":
        rows = db.fetchall(
            "SELECT id, name AS title, '' AS artist_name FROM artists WHERE id = ANY(%s::uuid[])",
            (db.uuid_array(ids),),
        )
    else:
        rows = db.fetchall(
            """
            SELECT album.id, album.title, artist.name AS artist_name
            FROM albums AS album
            LEFT JOIN artists AS artist ON artist.id = album.artist_id
            WHERE album.id = ANY(%s::uuid[])
            """,
            (db.uuid_array(ids),),
        )
    labels = {}
    for row in rows:
        artist_name = row.get("artist_name") or ""
        title = row.get("title") or row.get("name") or "Album"
        labels[str(row["id"])] = f"{artist_name} — {title}" if artist_name else title
    return labels


def _item_status(label, result):
    deployed = list(result.get("deployed") or [])
    warnings = list(result.get("warnings") or [])
    missing = [item for item in (result.get("missing") or []) if item not in deployed]
    saved = ", ".join(deployed)
    if deployed and missing:
        return f"Saved — {label} — {saved}. No artwork for {', '.join(missing)}"
    if deployed and warnings:
        return f"Saved — {label} — {saved}. {warnings[0]}"
    if deployed:
        return f"Saved — {label} — {saved}"
    if warnings:
        return f"Failed — {label} — {warnings[0]}"
    if missing:
        return f"No artwork — {label}"
    return f"Already complete — {label}"


def _queue_log(working, done, queued):
    lines = []
    if working:
        lines.append(working)
    lines.extend(done)
    if queued:
        lines.append(f"{len(queued)} still queued")
        lines.extend(f"Queued — {label}" for label in queued[:80])
    return "\n".join(lines[:200])


def start_missing(album_ids):
    """Queue a missing-artwork download for each album and return the job."""
    from resonance import jobs, library

    ids = []
    seen = set()
    for item in album_ids or []:
        album_id = str(library.require_uuid(item))
        if album_id in seen:
            continue
        seen.add(album_id)
        ids.append(album_id)
    if not ids:
        raise AppError("Select at least one album")
    running = db.fetchone(
        """
        SELECT * FROM work_jobs
        WHERE kind = 'missing-art' AND status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    if running:
        return running, False
    row = jobs.begin_work("missing-art", f"Downloading missing album artwork for {len(ids)} albums", len(ids))

    def run():
        labels = _labels_for(ids, "albums")
        order = [labels.get(album_id, "Album") for album_id in ids]
        done = []
        saved = 0
        try:
            for index, album_id in enumerate(ids, start=1):
                label = order[index - 1]
                queued = order[index:]
                working = f"Working — {label} ({index} of {len(ids)})"
                jobs.touch_work(row["id"], index - 1, working, _queue_log(working, done, queued))
                try:
                    result = deploy_missing(album_id)
                except Exception as exc:
                    logger.exception("missing artwork failed")
                    done.insert(0, f"Failed — {label} — {exc}")
                    jobs.touch_work(row["id"], index, f"Finished {index} of {len(ids)}", _queue_log("", done, queued))
                    continue
                saved += len(result.get("deployed") or [])
                done.insert(0, _item_status(label, result))
                jobs.touch_work(row["id"], index, f"Finished {index} of {len(ids)}", _queue_log("", done, queued))
            jobs.finish_work(
                row["id"],
                "completed",
                f"Saved {saved} missing images across {len(ids)} albums",
                len(ids),
                _queue_log("", done, []),
            )
        except Exception as exc:
            logger.exception("missing artwork queue failed")
            done.insert(0, f"Failed — {exc}")
            jobs.finish_work(row["id"], "failed", str(exc)[:300], log=_queue_log("", done, []))

    threading.Thread(target=run, name="missing-artwork", daemon=True).start()
    return row, True


ARTIST_DOWNLOAD_TYPES = ("artistthumb", "clearlogo", "banner", "landscape")


def deploy_missing_artist(artist_id, only_types=None):
    """Save missing artist thumb, clearlogo, banner, landscape, and fanart up to the settings count."""
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    if not artist.get("path"):
        raise AppError("This artist has no folder to save artwork in")
    assert_library_writable(artist["path"])
    harvest_artist(artist_id, respect_enabled=False, only_types=only_types)
    cfg = load_settings()
    warnings = []
    deployed = []
    missing = []
    present = artist_assets(artist_id)
    rows = list_for_artist(artist_id)
    allowed = set(only_types) if only_types is not None else None
    for asset_type in ARTIST_DOWNLOAD_TYPES:
        if allowed is not None and asset_type not in allowed:
            continue
        if present.get(asset_type):
            continue
        ranked = _unselected(rows, asset_type, cfg)
        if not ranked:
            missing.append(asset_type)
            continue
        try:
            select(ranked[0]["id"], refresh_scores=False)
            deployed.append(asset_type)
            present[asset_type] = True
        except Exception as exc:
            logger.info("artist artwork deploy skipped: %s", exc)
            warnings.append(f"Could not save {asset_type}: {exc}")
    want = fanart_count(cfg)
    have = int(present.get("fanart") or 0)
    save_fanart = allowed is None or "fanart" in allowed
    save_extra = allowed is None or "extrafanart" in allowed
    if save_fanart and have < want and _primary_fanart_missing(artist):
        ranked = _unselected(rows, "fanart", cfg)
        if not ranked:
            missing.append("fanart")
        if ranked:
            try:
                select(ranked[0]["id"], refresh_scores=False)
                deployed.append("fanart")
                have += 1
            except Exception as exc:
                logger.info("artist artwork deploy skipped: %s", exc)
                warnings.append(f"Could not save fanart: {exc}")
    if save_extra:
        for best in _unselected(rows, "extrafanart", cfg):
            if have >= want:
                break
            try:
                select(best["id"], refresh_scores=False)
                deployed.append("fanart")
                have += 1
            except AppError as exc:
                logger.info("artist artwork deploy skipped: %s", exc)
                if "limit" in str(exc).lower():
                    break
                warnings.append(f"Could not save fanart: {exc}")
            except Exception as exc:
                logger.info("artist artwork deploy skipped: %s", exc)
                warnings.append(f"Could not save fanart: {exc}")
    from resonance.settings import vlog

    vlog(
        logger,
        "artist artwork saved for %s: %s (fanart %s/%s)",
        artist.get("name"),
        ", ".join(deployed) or "nothing new",
        have,
        want,
    )
    return {"warnings": warnings, "deployed": deployed, "missing": missing, "fanart": have, "wanted": want}


def start_missing_artist(artist_id):
    """Queue a missing-artwork download for one artist and return the job."""
    from resonance import jobs, library

    artist_id = str(library.require_uuid(artist_id))
    artist = db.fetchone("SELECT name FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    running = db.fetchone(
        """
        SELECT * FROM work_jobs
        WHERE kind = 'missing-artist-art' AND status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    if running:
        return running, False
    name = artist.get("name") or "artist"
    row = jobs.begin_work("missing-artist-art", f"Downloading missing artist artwork for {name}", 1)
    logger.info("artist artwork: looking up thumb, clearlogo, banner, landscape, and fanart for %s", name)

    def run():
        try:
            jobs.touch_work(row["id"], 0, f"Working — {name}", f"Working — {name}")
            result = deploy_missing_artist(artist_id)
            message = _artist_art_message(name, result)
            line = _item_status(name, result)
            logger.info("artist artwork finished for %s: %s", name, message)
            jobs.finish_work(row["id"], "completed", message[:300], 1, line)
        except Exception as exc:
            logger.exception("artist artwork download failed for %s", name)
            jobs.finish_work(row["id"], "failed", str(exc)[:300], log=f"Failed — {name} — {exc}")

    threading.Thread(target=run, name="missing-artist-art", daemon=True).start()
    return row, True


def start_missing_artists(artist_ids):
    """Queue a missing-artwork download for each artist and return the job."""
    from resonance import jobs, library

    ids = []
    seen = set()
    for item in artist_ids or []:
        artist_id = str(library.require_uuid(item))
        if artist_id in seen:
            continue
        seen.add(artist_id)
        ids.append(artist_id)
    if not ids:
        raise AppError("Select at least one artist")
    if len(ids) == 1:
        return start_missing_artist(ids[0])
    running = db.fetchone(
        """
        SELECT * FROM work_jobs
        WHERE kind = 'missing-artist-art' AND status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    if running:
        return running, False
    row = jobs.begin_work("missing-artist-art", f"Downloading missing artist artwork for {len(ids)} artists", len(ids))

    def run():
        labels = _labels_for(ids, "artists")
        order = [labels.get(artist_id, "Artist") for artist_id in ids]
        done = []
        saved = 0
        try:
            for index, artist_id in enumerate(ids, start=1):
                name = order[index - 1]
                queued = order[index:]
                working = f"Working — {name} ({index} of {len(ids)})"
                jobs.touch_work(row["id"], index - 1, working, _queue_log(working, done, queued))
                try:
                    result = deploy_missing_artist(artist_id)
                except Exception as exc:
                    logger.exception("artist artwork download failed for %s", name)
                    done.insert(0, f"Failed — {name} — {exc}")
                    jobs.touch_work(row["id"], index, f"Finished {index} of {len(ids)}", _queue_log("", done, queued))
                    continue
                saved += len(result.get("deployed") or [])
                done.insert(0, _item_status(name, result))
                jobs.touch_work(row["id"], index, f"Finished {index} of {len(ids)}", _queue_log("", done, queued))
            jobs.finish_work(
                row["id"],
                "completed",
                f"Saved {saved} artist images across {len(ids)} artists",
                len(ids),
                _queue_log("", done, []),
            )
        except Exception as exc:
            logger.exception("artist artwork queue failed")
            done.insert(0, f"Failed — {exc}")
            jobs.finish_work(row["id"], "failed", str(exc)[:300], log=_queue_log("", done, []))

    threading.Thread(target=run, name="missing-artist-art", daemon=True).start()
    return row, True


def _unselected(rows, asset_type, cfg):
    group = [row for row in rows if row.get("asset_type") == asset_type and not row.get("is_selected")]
    if not group:
        return []
    best = preferred_artwork(group, cfg)
    rest = [row for row in group if str(row.get("id")) != str(best.get("id"))]
    rest.sort(key=lambda row: _score(row, cfg), reverse=True)
    return [best, *rest]


def _primary_fanart_missing(artist):
    directory = (artist or {}).get("path") or ""
    if not directory or not os.path.isdir(directory):
        return True
    for name in ("fanart.jpg", "fanart.jpeg", "fanart.png"):
        if os.path.isfile(os.path.join(directory, name)):
            return False
    return True


def _artist_art_message(name, result):
    labels = {
        "artistthumb": "artist thumb",
        "clearlogo": "clearlogo",
        "banner": "banner",
        "landscape": "landscape",
    }
    parts = []
    seen = set()
    fanarts = 0
    for asset_type in result.get("deployed") or []:
        if asset_type == "fanart":
            fanarts += 1
            continue
        if asset_type in seen:
            continue
        seen.add(asset_type)
        parts.append(labels.get(asset_type, asset_type))
    if fanarts:
        parts.append(f"{fanarts} fanart" if fanarts == 1 else f"{fanarts} fanarts")
    warnings = result.get("warnings") or []
    if parts:
        message = f"Saved {' and '.join(parts)} for {name}" if len(parts) < 3 else f"Saved {', '.join(parts[:-1])}, and {parts[-1]} for {name}"
    else:
        message = f"No missing artwork found for {name}"
    if warnings:
        message = f"{message}. {warnings[0]}"
    return message


def _album_label(album_id):
    row = db.fetchone(
        """
        SELECT album.title, artist.name AS artist_name
        FROM albums AS album
        LEFT JOIN artists AS artist ON artist.id = album.artist_id
        WHERE album.id = %s
        """,
        (album_id,),
    )
    if not row:
        return "Album"
    artist_name = row.get("artist_name") or ""
    title = row.get("title") or "Album"
    return f"{artist_name} — {title}" if artist_name else title


_SCAN_ARTIST_FILES = {
    "artistthumb": ("folder.jpg", "folder.jpeg", "thumb.jpg", "cover.jpg"),
    "clearlogo": ("clearlogo.png", "logo.png"),
    "banner": ("banner.jpg",),
    "landscape": ("landscape.jpg",),
}
_SCAN_ARTIST_TYPES = ("artistthumb", "clearlogo", "banner", "landscape", "fanart", "extrafanart")


def _has_named_file(directory, names):
    if not directory or not names:
        return False
    return any(os.path.isfile(os.path.join(directory, name)) for name in names)


def _selected_type_map(owner_ids, kind):
    if not owner_ids:
        return {}
    column = "album_id" if kind == "album" else "artist_id"
    album_filter = "" if kind == "album" else "AND album_id IS NULL"
    rows = db.fetchall(
        f"""
        SELECT {column}::text AS owner, asset_type, local_path
        FROM artwork_pool
        WHERE is_selected AND local_path IS NOT NULL
          AND {column} = ANY(%s::uuid[])
          {album_filter}
        """,
        (db.uuid_array(owner_ids),),
    )
    found = {}
    for row in rows:
        path = row.get("local_path")
        if path and os.path.isfile(path):
            found.setdefault(row["owner"], set()).add(row["asset_type"])
    return found


def _artist_missing(artist, present, types, cfg):
    directory = artist.get("path") or ""
    for asset_type in types:
        if asset_type in {"fanart", "extrafanart"}:
            continue
        if asset_type == "artistthumb" and artist.get("has_artwork"):
            continue
        if asset_type in present:
            continue
        if _has_named_file(directory, _SCAN_ARTIST_FILES.get(asset_type, ())):
            continue
        return True
    if ("fanart" in types or "extrafanart" in types) and _fanart_count(artist["id"], directory) < fanart_count(cfg):
        return True
    return False


def _album_missing(album, present, types):
    directory = album.get("path") or ""
    for asset_type in types:
        if asset_type == "front" and album.get("has_artwork"):
            continue
        if asset_type in present:
            continue
        if _has_named_file(directory, ALBUM_FILE_NAMES.get(asset_type, ())):
            continue
        return True
    return False


def scan_targets(roots, limited, album_ids=None):
    """Artists and albums the scan should search, and the types to save.

    Limited mode is the cover search: artists and albums with no folder image.
    Otherwise a folder is included when any artwork type turned on in Settings is missing.
    Type lists are None in limited mode so the existing cover download stays as it is.
    album_ids limits the search to those albums and their artists.
    """
    from resonance.paths import like_prefix

    cfg = load_settings()
    artist_clause = " OR ".join(["path LIKE %s ESCAPE '\\'"] * len(roots))
    album_clause = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    artist_scope = ""
    album_scope = ""
    scope_params = []
    if album_ids is not None:
        if not album_ids:
            return [], [], None, None
        artist_scope = " AND id IN (SELECT artist_id FROM albums WHERE id = ANY(%s::uuid[]))"
        album_scope = " AND al.id = ANY(%s::uuid[])"
        scope_params = [db.uuid_array(album_ids)]
    if limited:
        artists = db.fetchall(
            f"""
            SELECT id, name FROM artists
            WHERE has_artwork = FALSE AND ({artist_clause})
              AND status IS DISTINCT FROM 'IGNORED'
              AND NOT COALESCE(locked, FALSE)
              {artist_scope}
            ORDER BY lower(name)
            """,
            params + scope_params,
        )
        albums = db.fetchall(
            f"""
            SELECT al.id, al.title, ar.name AS artist_name
            FROM albums al
            JOIN artists ar ON ar.id = al.artist_id
            WHERE al.has_artwork = FALSE AND ({album_clause})
              AND al.status IS DISTINCT FROM 'IGNORED'
              AND NOT COALESCE(al.locked, FALSE)
              AND ar.status IS DISTINCT FROM 'IGNORED'
              AND NOT COALESCE(ar.locked, FALSE)
              {album_scope}
            ORDER BY lower(ar.name), lower(al.title)
            """,
            params + scope_params,
        )
        return artists, albums, None, None
    artist_types = [asset_type for asset_type in _SCAN_ARTIST_TYPES if _enabled(asset_type, cfg)]
    album_types = [asset_type for asset_type in ALBUM_TYPES if _enabled(asset_type, cfg)]
    artists = db.fetchall(
        f"""
        SELECT id, name, path, has_artwork FROM artists
        WHERE ({artist_clause})
          AND status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(locked, FALSE)
          {artist_scope}
        ORDER BY lower(name)
        """,
        params + scope_params,
    )
    albums = db.fetchall(
        f"""
        SELECT al.id, al.title, al.path, al.has_artwork, ar.name AS artist_name
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE ({album_clause})
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND ar.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(ar.locked, FALSE)
          {album_scope}
        ORDER BY lower(ar.name), lower(al.title)
        """,
        params + scope_params,
    )
    artist_have = _selected_type_map([row["id"] for row in artists], "artist")
    album_have = _selected_type_map([row["id"] for row in albums], "album")
    artists = [
        row
        for row in artists
        if _artist_missing(row, artist_have.get(str(row["id"]), set()), artist_types, cfg)
    ]
    albums = [
        row
        for row in albums
        if _album_missing(row, album_have.get(str(row["id"]), set()), album_types)
    ]
    return artists, albums, artist_types, album_types


def deploy_missing(album_id, scope="album", only_types=None):
    """Save missing album images: front, back, disc, spine, booklet, and the other enabled album types."""
    from resonance.settings import vlog

    album, _artist = _subjects(album_id)
    vlog(logger, "album artwork: filling missing images for %s", album.get("title") or album_id)
    harvest(album_id, scope="album", respect_enabled=True, only_types=only_types)
    cfg = load_settings()
    warnings = []
    deployed = []
    present_album = album_assets(album["id"])
    allowed = set(only_types) if only_types is not None else None
    needed = [
        asset_type
        for asset_type in ALBUM_TYPES
        if (allowed is None or asset_type in allowed)
        and _enabled(asset_type, cfg)
        and not _asset_present(album["id"], None, asset_type, present_album, None)
    ]
    rows = list_for_album(album["id"])
    groups = {}
    for row in rows:
        key = (str(row["album_id"] or ""), row["asset_type"])
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        asset_type = group[0]["asset_type"]
        if asset_type not in ALBUM_TYPES or not _enabled(asset_type, cfg):
            continue
        if allowed is not None and asset_type not in allowed:
            continue
        if _asset_present(album["id"], None, asset_type, present_album, None):
            continue
        if any(row["is_selected"] for row in group):
            continue
        best = preferred_artwork(group, cfg)
        try:
            select(best["id"], refresh_scores=False)
            deployed.append(asset_type)
            if asset_type in present_album:
                present_album[asset_type] = True
        except Exception as exc:
            logger.info("artwork deploy skipped: %s", exc)
            warnings.append(f"Could not save {asset_type}: {exc}")
    missing = [asset_type for asset_type in needed if asset_type not in deployed]
    if _enabled("discart", cfg):
        try:
            ensure_disc_arts(album)
        except Exception as exc:
            logger.info("disc art download skipped: %s", exc)
            warnings.append(f"Could not save disc art: {exc}")
    completeness.recompute_album(album_id)
    vlog(logger, "album artwork finished for %s: %s", album.get("title") or album_id, ", ".join(deployed) or "nothing new")
    return {"warnings": warnings, "deployed": deployed, "missing": missing}


def auto_deploy(album_id):
    album, _artist = _subjects(album_id)
    harvest(album_id, scope="album")
    cfg = load_settings()
    warnings = []
    rows = list_for_album(album["id"])
    groups = {}
    for row in rows:
        key = (str(row["album_id"] or ""), row["asset_type"])
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        asset_type = group[0]["asset_type"]
        if asset_type not in ALBUM_TYPES or not _enabled(asset_type, cfg):
            continue
        if any(row["is_selected"] for row in group):
            continue
        best = preferred_artwork(group, cfg)
        try:
            select(best["id"], refresh_scores=False)
        except Exception as exc:
            logger.info("artwork deploy skipped: %s", exc)
            warnings.append(f"Could not save {asset_type}: {exc}")
    if _enabled("discart", cfg):
        try:
            ensure_disc_arts(album)
        except Exception as exc:
            logger.info("disc art download skipped: %s", exc)
            warnings.append(f"Could not save disc art: {exc}")
    completeness.recompute_album(album_id)
    return warnings


def cover_path(album_id):
    return album_image(album_id, "front")


def album_image(album_id, asset_type):
    names = ALBUM_FILE_NAMES.get(asset_type)
    if not names:
        raise AppError("Unknown artwork type", 404)
    row = db.fetchone(
        """
        SELECT local_path FROM artwork_pool
        WHERE album_id = %s AND asset_type = %s AND is_selected = TRUE
          AND local_path IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (album_id, asset_type),
    )
    album = db.fetchone("SELECT path FROM albums WHERE id = %s", (album_id,))
    directory = (album or {}).get("path") or ""
    local = (row or {}).get("local_path") or ""
    if local and _inside_dir(local, directory):
        found = _readable_file(local)
        if found:
            return found
    if directory and names:
        found = _readable_file(os.path.join(directory, names[0]))
        if found:
            return found
    if local:
        found = _readable_file(local)
        if found:
            return found
    if not directory:
        return None
    for name in names[1:]:
        found = _readable_file(os.path.join(directory, name))
        if found:
            return found
    if asset_type == "booklet":
        pages = _booklet_on_disk(album["path"])
        if pages:
            try:
                return assert_readable(pages[0])
            except AppError:
                return None
    return None


def preview_path(art_id):
    row = db.fetchone("SELECT * FROM artwork_pool WHERE id = %s", (art_id,))
    if not row:
        raise AppError("Artwork not found", 404)
    # A file already in the library is the image on the info pane. Serving the
    # original download instead, and pointing local_path at that cache, is what
    # made the modal highlight a different thumb than the one on screen.
    local = _readable_file(row.get("local_path") or "")
    if local and _under_library(local):
        return local
    source = str(row.get("source_url") or "")
    if source.startswith(("http://", "https://")):
        path, width, height, size = _cache_remote(source)
        if path:
            if not local:
                resolution = f"{width}x{height}" if width and height else row.get("resolution")
                db.execute(
                    "UPDATE artwork_pool SET local_path = %s, resolution = %s, file_size_bytes = %s WHERE id = %s",
                    (path, resolution, size, art_id),
                )
            return assert_readable(path)
    if local:
        return local
    path, width, height, size = _cache_remote(row["source_url"])
    if not path:
        raise AppError("Could not load artwork", 502)
    resolution = f"{width}x{height}" if width and height else None
    db.execute(
        "UPDATE artwork_pool SET local_path = %s, resolution = %s, file_size_bytes = %s WHERE id = %s",
        (path, resolution, size, art_id),
    )
    return assert_readable(path)


def _subjects(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    return album, artist


def _candidates(
    album,
    artist,
    cfg,
    warnings,
    scope="both",
    respect_enabled=True,
    artist_name=None,
    album_title=None,
    extra_group_id=None,
    only_types=None,
):
    found = []
    want_album = scope in {"both", "album"} and album is not None
    want_artist = scope in {"both", "artist"} and artist is not None
    allowed = set(only_types) if only_types is not None else None

    def add(asset_type, url, provider, album_id=None, artist_id=None, enabled=None):
        if allowed is not None and asset_type not in allowed:
            return
        if asset_type in ARTIST_TYPES and not want_artist:
            return
        if asset_type not in ARTIST_TYPES and not want_album:
            return
        if enabled is False:
            return
        if respect_enabled and enabled is None and not _enabled(asset_type, cfg):
            return
        if not url or not _provider_enabled(provider, cfg):
            return
        found.append(
            {
                "asset_type": asset_type,
                "source_url": url,
                "source_provider": provider,
                "album_id": album_id,
                "artist_id": artist_id,
            }
        )

    release_id = album.get("musicbrainz_release_id") if album else None
    group_id = album.get("musicbrainz_release_group_id") if album else None
    artist_mbid = artist.get("musicbrainz_artist_id") if artist else None
    searched_artist = artist["name"] if artist and artist_name is None else (artist_name or "")
    searched_title = album["title"] if album and album_title is None else (album_title or "")
    if want_album and _provider_enabled("caa", cfg):
        if not release_id and not group_id and not extra_group_id:
            warnings.append("Match a MusicBrainz release to unlock Cover Art Archive.")
        else:
            images = coverart.images_for_release(release_id) + coverart.images_for_group(group_id)
            if extra_group_id and str(extra_group_id) != str(group_id or ""):
                images += coverart.images_for_group(extra_group_id)
            for image in images:
                asset = _caa_type(image)
                if asset:
                    add(asset, image["url"], "caa", album_id=album["id"])
    if (want_album or want_artist) and _provider_enabled("fanart.tv", cfg):
        if artist_mbid and fanart.configured():
            payload = fanart.music(artist_mbid) or {}
            if want_artist:
                for item in _liked(payload.get("artistthumb"))[:4]:
                    add("artistthumb", item.get("url"), "fanart.tv", artist_id=artist["id"])
                backgrounds = _liked(payload.get("artistbackground") or payload.get("musicbackground"))
                _queue_backgrounds(
                    add,
                    [item.get("url") for item in backgrounds],
                    "fanart.tv",
                    artist["id"],
                    cfg,
                    respect_enabled=respect_enabled,
                )
                for item in _liked(payload.get("hdmusiclogo") or payload.get("musiclogo"))[:3]:
                    add("clearlogo", item.get("url"), "fanart.tv", artist_id=artist["id"])
                for item in _liked(payload.get("musicbanner"))[:2]:
                    add("banner", item.get("url"), "fanart.tv", artist_id=artist["id"])
            if want_album:
                groups = [str(group_id or "")]
                if extra_group_id and str(extra_group_id) not in groups:
                    groups.append(str(extra_group_id))
                for group in groups:
                    bucket = (payload.get("albums") or {}).get(group) or {}
                    for item in _liked(bucket.get("albumcover"))[:6]:
                        add("front", item.get("url"), "fanart.tv", album_id=album["id"])
                    for item in _liked(bucket.get("cdart"))[:4]:
                        add("discart", item.get("url"), "fanart.tv", album_id=album["id"])
        elif not fanart.configured():
            warnings.append("Fanart.tv key is not set.")
    if _provider_enabled("deezer", cfg):
        if want_album:
            remote = deezer.lookup_album(searched_artist, searched_title)
            if remote and remote.get("cover_url"):
                add("front", remote["cover_url"], "deezer", album_id=album["id"])
        if want_artist:
            picture = deezer.artist_image(searched_artist or (artist["name"] if artist else ""))
            if picture:
                add("artistthumb", picture, "deezer", artist_id=artist["id"])
    if _provider_enabled("lastfm", cfg):
        if lastfm.configured():
            if want_album:
                album_art = lastfm.album_image(searched_artist, searched_title)
                if album_art:
                    add("front", album_art["url"], "lastfm", album_id=album["id"])
            if want_artist:
                artist_art = lastfm.artist_image(searched_artist or (artist["name"] if artist else ""))
                if artist_art:
                    add("artistthumb", artist_art["url"], "lastfm", artist_id=artist["id"])
        elif want_album or want_artist:
            warnings.append("Last.fm key is not set.")
    if _provider_enabled("theaudiodb", cfg):
        if want_album and (group_id or extra_group_id):
            seen_groups = []
            for group in (group_id, extra_group_id):
                if not group or str(group) in seen_groups:
                    continue
                seen_groups.append(str(group))
                audio_album = audiodb.album_by_mbid(group)
                if not audio_album:
                    continue
                add("front", audio_album.get("strAlbumThumb"), "theaudiodb", album_id=album["id"])
                add("back", audio_album.get("strAlbumBack"), "theaudiodb", album_id=album["id"])
                add("discart", audio_album.get("strAlbumCDart"), "theaudiodb", album_id=album["id"])
                add("spine", audio_album.get("strAlbumSpine"), "theaudiodb", album_id=album["id"])
        if want_artist:
            audio_artist = audiodb.artist_by_mbid(artist_mbid)
            if audio_artist:
                add("artistthumb", audio_artist.get("strArtistThumb"), "theaudiodb", artist_id=artist["id"])
                _queue_backgrounds(
                    add,
                    [
                        audio_artist.get("strArtistFanart"),
                        audio_artist.get("strArtistFanart2"),
                        audio_artist.get("strArtistFanart3"),
                    ],
                    "theaudiodb",
                    artist["id"],
                    cfg,
                    respect_enabled=respect_enabled,
                )
                add("banner", audio_artist.get("strArtistBanner"), "theaudiodb", artist_id=artist["id"])
                add("clearlogo", audio_artist.get("strArtistLogo"), "theaudiodb", artist_id=artist["id"])
                add("clearart", audio_artist.get("strArtistClearart"), "theaudiodb", artist_id=artist["id"])
                add("landscape", audio_artist.get("strArtistWideThumb"), "theaudiodb", artist_id=artist["id"])
    return found


def _caa_type(image):
    types = [str(item).strip().lower() for item in (image.get("types") or [])]
    if image.get("front"):
        return "front"
    if image.get("back") and "spine" not in types and "medium" not in types:
        return "back"
    for source, target in CAA_TO_KODI:
        if source in types:
            return target
    return None


def _liked(items):
    rows = [item for item in (items or []) if item.get("url")]
    rows.sort(key=lambda item: int(item.get("likes") or 0), reverse=True)
    return rows


def _enabled(asset_type, cfg):
    return bool((cfg.get("assets") or {}).get(asset_type))


def _provider_enabled(provider, cfg):
    enabled = cfg.get("sources_enabled")
    if not isinstance(enabled, dict) or provider not in enabled:
        return True
    return bool(enabled[provider])


def _known(candidate):
    return db.fetchone(
        """
        SELECT id FROM artwork_pool
        WHERE source_url = %s AND asset_type = %s
          AND album_id IS NOT DISTINCT FROM %s
          AND artist_id IS NOT DISTINCT FROM %s
        """,
        (candidate["source_url"], candidate["asset_type"], candidate["album_id"], candidate["artist_id"]),
    )


def _look_at(url):
    """Size and resolution of a candidate without downloading all of it.

    Only the first bytes are fetched, which hold the image size, and the server says how large the file is. The
    whole file is downloaded later, when a card's picture is shown or the image is compared or chosen. A file
    already in the cache is checked against the size the server reports now, so an image the provider replaced at
    the same address is fetched again. Returns (cached path or None, width, height, size), and size None when
    the image cannot be reached.
    """
    if not url or not str(url).startswith(("http://", "https://")):
        return None, None, None, None
    data, total = probe_image(url)
    cached = _find_cache(url)
    if cached:
        try:
            on_disk = os.path.getsize(cached)
        except OSError:
            on_disk = None
        if total and on_disk is not None and total != on_disk:
            logger.info("artwork changed at %s, fetching it again", url)
            try:
                os.remove(cached)
            except OSError:
                pass
            cached = None
    if cached:
        return _cache_remote(url)
    if data:
        width, height = _measure(data)
        if width and height:
            return None, width, height, total or 0
    # The size could not be read from the start of the file: download it whole, as before.
    return _cache_remote(url)


def _cache_remote(url):
    if not url or not str(url).startswith(("http://", "https://")):
        return None, None, None, None
    existing = _find_cache(url)
    if existing:
        try:
            os.utime(existing, None)
        except OSError:
            pass
        try:
            data = open(existing, "rb").read()
        except OSError:
            data = b""
        width, height = _measure(data)
        if data and (width is not None or existing.lower().endswith(".pdf")):
            return existing, width, height, len(data)
        # An empty or cut-off file left by an interrupted download: fetch it again.
        try:
            os.remove(existing)
        except OSError:
            pass
    try:
        data, _content_type = get_bytes(url)
    except Exception as exc:
        logger.info("artwork download failed: %s", exc)
        return None, None, None, None
    if not data:
        return None, None, None, None
    width, height = _measure(data)
    if data.startswith(b"%PDF"):
        ext = ".pdf"
    elif data.startswith(b"\x89PNG"):
        ext = ".png"
    elif data.startswith(b"GIF8"):
        ext = ".gif"
    elif data[0:4] == b"RIFF" and b"WEBP" in data[8:16]:
        ext = ".webp"
    else:
        ext = ".jpg"
        if width is None:
            return None, None, None, None
    os.makedirs(artwork_cache_dir(), exist_ok=True)
    path = os.path.join(artwork_cache_dir(), _digest(url) + ext)
    try:
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        logger.info("cache write failed: %s", exc)
        return None, None, None, None
    return path, width, height, len(data)


def _find_cache(url):
    folder = artwork_cache_dir()
    prefix = _digest(url)
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"):
        path = os.path.join(folder, prefix + ext)
        if os.path.isfile(path):
            return path
    return None


def _digest(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _measure(data):
    if not data or data.startswith(b"%PDF"):
        return None, None
    try:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return None, None


def _same_payload(path, payload):
    """True when the file in the music folder is already this image."""
    if not path or payload is None or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) != len(payload):
            return False
        with open(path, "rb") as handle:
            return handle.read() == payload
    except OSError:
        return False


def _readable_file(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return assert_readable(path)
    except AppError:
        return None


def _inside_dir(path, directory):
    if not path or not directory:
        return False
    try:
        root = os.path.normcase(os.path.realpath(directory))
        real = os.path.normcase(os.path.realpath(path))
    except OSError:
        return False
    return real == root or real.startswith(root + os.sep)


def _row_on_disk(row):
    """A local or cached file already holds this image, so choosing it is not a download."""
    local = str((row or {}).get("local_path") or "")
    if local and os.path.isfile(local):
        return True
    source = str((row or {}).get("source_url") or "")
    if source.startswith(("http://", "https://")):
        found = _find_cache(source)
        return bool(found and os.path.isfile(found))
    return False


def _local_choice(row):
    """Bytes already stored for this row. A library file is used only when it still is this image."""
    cached = _cached_original(row)
    if not cached:
        source = str((row or {}).get("source_url") or "")
        if source.startswith(("http://", "https://")):
            cached = _find_cache(source) or ""
    if cached and os.path.isfile(cached):
        try:
            assert_readable(cached)
            with open(cached, "rb") as handle:
                return handle.read(), cached
        except (AppError, OSError):
            cached = ""
    source = str((row or {}).get("source_url") or "")
    if source.startswith(("http://", "https://")):
        return None, None
    local = str((row or {}).get("local_path") or "")
    if local and os.path.isfile(local):
        try:
            assert_readable(local)
        except AppError:
            return None, None
        with open(local, "rb") as handle:
            return handle.read(), local
    return None, None


def _load_choice(row):
    data, path = _local_choice(row)
    if data:
        return data, path, False
    data, path = _choice_bytes(row)
    return data, path, bool(data)


def _choice_bytes(row):
    """The image this row actually is, not the album file a later choice overwrote."""
    cached = _cached_original(row)
    if cached:
        with open(cached, "rb") as handle:
            return handle.read(), cached
    source = str((row or {}).get("source_url") or "")
    if source.startswith(("http://", "https://")):
        path, _width, _height, _size = _cache_remote(source)
        if path and os.path.isfile(path):
            with open(path, "rb") as handle:
                return handle.read(), path
    local = str((row or {}).get("local_path") or "")
    if local and os.path.isfile(local):
        try:
            assert_readable(local)
        except AppError:
            return None, None
        with open(local, "rb") as handle:
            return handle.read(), local
    return None, None


def _read_row_bytes(row):
    data, _path = _choice_bytes(row)
    return data


def _cached_original(row):
    """A cache file for this row. An album folder file can be a later choice, so it is not used."""
    local = str((row or {}).get("local_path") or "")
    if not local or not os.path.isfile(local):
        return ""
    try:
        path = os.path.normcase(os.path.realpath(local))
        managed = [os.path.normcase(os.path.realpath(item)) for item in _managed_dirs()]
    except OSError:
        return ""
    if any(path == item or path.startswith(item + os.sep) for item in managed):
        return local
    return ""


def _same_artwork_path(left, right):
    first = os.path.normcase(os.path.normpath(left or ""))
    second = os.path.normcase(os.path.normpath(right or ""))
    if not first or not second:
        return False
    if first == second:
        return True
    try:
        return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))
    except OSError:
        return False


def _keep_other_copies(target, keep_id):
    """Give every other row its own file before this path is replaced."""
    if not target or not os.path.isfile(target):
        return
    needle = os.path.normpath(target)
    rows = db.fetchall(
        """
        SELECT id, local_path, source_url, source_provider
        FROM artwork_pool
        WHERE id <> %s
          AND local_path IS NOT NULL
          AND lower(replace(local_path, '\\', '/')) = lower(replace(%s, '\\', '/'))
        """,
        (keep_id, needle),
    )
    for other in rows:
        path = other.get("local_path") or ""
        if not path or not os.path.isfile(path) or not _same_artwork_path(path, target):
            continue
        source = str(other.get("source_url") or "")
        if source.startswith(("http://", "https://")):
            cached, _width, _height, _size = _cache_remote(source)
            if cached and not _same_file(cached, target):
                db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (cached, other["id"]))
            continue
        preserved = _preserve_copy(target)
        if not preserved:
            continue
        db.execute(
            "UPDATE artwork_pool SET local_path = %s, source_url = %s WHERE id = %s",
            (preserved, preserved, other["id"]),
        )


def _preserve_copy(path):
    folder = additional_media_dir("music")
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(path)[1].lower() or ".img"
    dest = os.path.join(folder, uuid.uuid4().hex + ext)
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        with open(dest, "wb") as handle:
            handle.write(data)
    except OSError:
        logger.info("could not keep a copy of %s", path, exc_info=True)
        return None
    return dest


def _undo_subject(row, album, artist):
    asset = (row or {}).get("asset_type") or ""
    if album and row.get("album_id") and asset not in ARTIST_TYPES:
        return "album", str(album["id"])
    if artist and artist.get("id"):
        return "artist", str(artist["id"])
    return None


def _selected_art_id(row):
    asset = (row or {}).get("asset_type") or ""
    if row.get("album_id") and asset not in ARTIST_TYPES:
        found = db.fetchone(
            """
            SELECT id FROM artwork_pool
            WHERE album_id = %s AND asset_type = %s AND is_selected IS TRUE
            LIMIT 1
            """,
            (row["album_id"], asset),
        )
    elif row.get("artist_id"):
        found = db.fetchone(
            """
            SELECT id FROM artwork_pool
            WHERE artist_id = %s AND album_id IS NULL AND asset_type = %s AND is_selected IS TRUE
            LIMIT 1
            """,
            (row["artist_id"], asset),
        )
    else:
        found = None
    return str(found["id"]) if found else None


def _remember_artwork(kind, subject_id, asset_type, target, previous_art_id, next_art_id):
    """Keep the file that is about to be replaced, so the last artwork choice can be undone."""
    if not kind or not subject_id or not target or not os.path.isfile(target):
        return False
    existing = db.fetchone(
        "SELECT cache_path FROM artwork_undo WHERE subject_kind = %s AND subject_id = %s",
        (kind, subject_id),
    )
    folder = undo_dir()
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(target)[1].lower() or ".img"
    dest = os.path.join(folder, f"{kind}-{subject_id}{ext}")
    old_cache = (existing or {}).get("cache_path") or ""
    if old_cache and os.path.normcase(old_cache) != os.path.normcase(dest):
        try:
            os.remove(old_cache)
        except OSError:
            pass
    try:
        with open(target, "rb") as handle:
            data = handle.read()
        with open(dest, "wb") as handle:
            handle.write(data)
    except OSError:
        logger.info("could not keep the previous %s", target, exc_info=True)
        return False
    db.execute(
        """
        INSERT INTO artwork_undo (
            subject_kind, subject_id, asset_type, target_path, cache_path, previous_art_id, next_art_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (subject_kind, subject_id) DO UPDATE
        SET asset_type = EXCLUDED.asset_type,
            target_path = EXCLUDED.target_path,
            cache_path = EXCLUDED.cache_path,
            previous_art_id = EXCLUDED.previous_art_id,
            next_art_id = EXCLUDED.next_art_id,
            created_at = NOW()
        """,
        (kind, subject_id, asset_type, target, dest, previous_art_id, next_art_id),
    )
    return True


def undo_status(kind, subject_id):
    row = db.fetchone(
        "SELECT asset_type FROM artwork_undo WHERE subject_kind = %s AND subject_id = %s",
        (kind, subject_id),
    )
    if not row:
        return None
    return {"asset_type": row["asset_type"]}


def restore_artwork(kind, subject_id):
    """Put the previous artwork file back. A second undo swaps the two files again."""
    row = db.fetchone(
        "SELECT * FROM artwork_undo WHERE subject_kind = %s AND subject_id = %s",
        (kind, subject_id),
    )
    if not row:
        raise AppError("There is no artwork change to undo", 404)
    cache = row.get("cache_path") or ""
    target = row.get("target_path") or ""
    if not cache or not os.path.isfile(cache):
        raise AppError("The previous artwork file is missing", 404)
    if not target:
        raise AppError("The artwork file to restore is missing", 404)
    assert_library_writable(os.path.dirname(target) or target)
    with open(cache, "rb") as handle:
        previous = handle.read()
    current = b""
    if os.path.isfile(target):
        with open(target, "rb") as handle:
            current = handle.read()
    atomic_write(target, previous, binary=True)
    if current:
        with open(cache, "wb") as handle:
            handle.write(current)
    db.execute(
        """
        UPDATE artwork_undo
        SET previous_art_id = %s, next_art_id = %s, created_at = NOW()
        WHERE subject_kind = %s AND subject_id = %s
        """,
        (row.get("next_art_id"), row.get("previous_art_id"), kind, subject_id),
    )
    asset = row.get("asset_type") or ""
    _apply_restored_selection(row.get("previous_art_id"), asset, kind, subject_id, previous)
    return {"asset_type": asset, "undo": True}


def _apply_restored_selection(art_id, asset_type, kind, subject_id, data):
    if kind == "album":
        db.execute(
            "UPDATE artwork_pool SET is_selected = FALSE WHERE album_id = %s AND asset_type = %s",
            (subject_id, asset_type),
        )
    else:
        db.execute(
            """
            UPDATE artwork_pool
            SET is_selected = FALSE
            WHERE artist_id = %s AND album_id IS NULL AND asset_type = %s
            """,
            (subject_id, asset_type),
        )
    if art_id and db.fetchone("SELECT id FROM artwork_pool WHERE id = %s", (art_id,)):
        db.execute("UPDATE artwork_pool SET is_selected = TRUE WHERE id = %s", (art_id,))
    width, height = _measure(data)
    if kind == "album" and asset_type == "front":
        db.execute(
            """
            UPDATE albums
            SET has_artwork = TRUE, artwork_width = %s, artwork_height = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (width, height, subject_id),
        )
        completeness.recompute_album(subject_id)
    elif kind == "artist" and asset_type == "artistthumb":
        db.execute(
            """
            UPDATE artists
            SET has_artwork = TRUE, artwork_width = %s, artwork_height = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (width, height, subject_id),
        )


def _destination_dir(row, album, artist, cfg):
    if row["asset_type"] in ARTIST_TYPES or not row["album_id"]:
        if not artist:
            raise AppError("Artist folder is missing for this artwork", 404)
        return artist["path"]
    return album["path"]


def fanart_count(cfg=None):
    cfg = cfg if cfg is not None else load_settings()
    try:
        count = int(cfg.get("fanart_count", 5))
    except (TypeError, ValueError):
        count = 5
    return max(1, min(count, 20))


def image_extension(data):
    if data.startswith(b"\x89PNG"):
        return ".png"
    return ".jpg"


def fanart_filename(index, extension=".jpg"):
    ext = extension if str(extension).startswith(".") else f".{extension}"
    ext = ".jpg" if ext.lower() == ".jpeg" else ext.lower()
    if ext not in {".jpg", ".png"}:
        ext = ".jpg"
    index = int(index)
    if index <= 0:
        return f"fanart{ext}"
    return f"fanart{index}{ext}"


def fanart_index(name):
    match = re.match(r"^fanart(\d*)\.(?:jpg|jpeg|png)$", os.path.basename(name), re.IGNORECASE)
    if not match:
        return None
    digits = match.group(1)
    return 0 if digits == "" else int(digits)


def _queue_backgrounds(add, urls, provider, artist_id, cfg, respect_enabled=True):
    urls = [url for url in urls if url][: fanart_count(cfg)]
    if not urls:
        return
    fanart_on = (not respect_enabled) or _enabled("fanart", cfg)
    extra_on = (not respect_enabled) or _enabled("extrafanart", cfg)
    if fanart_on:
        add("fanart", urls[0], provider, artist_id=artist_id)
        extras = urls[1:]
    elif extra_on:
        extras = urls[: max(0, fanart_count(cfg) - 1)]
    else:
        return
    for url in extras:
        add("extrafanart", url, provider, artist_id=artist_id, enabled=True)


def _next_fanart_name(directory, data, limit=None):
    extension = image_extension(data)
    payload = data if extension == ".png" else _to_jpeg(data)
    used = set()
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            index = fanart_index(name)
            if index is not None:
                used.add(index)
    # A number keeps the automatic download count. No number means a choice from the artwork tab.
    ceiling = 999 if limit is None else max(0, int(limit) - 1)
    for number in range(1, ceiling + 1):
        if number not in used:
            return fanart_filename(number, extension), payload
    return None, None


def _clear_other_fanart_ext(directory, filename):
    index = fanart_index(filename)
    if index is None or not os.path.isdir(directory):
        return
    for name in os.listdir(directory):
        if name == filename or fanart_index(name) != index:
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            logger.info("could not replace fanart file %s", name)


def album_assets(album_id):
    album = db.fetchone("SELECT path, has_artwork FROM albums WHERE id = %s", (album_id,))
    if not album:
        return {}
    directory = album.get("path") or ""
    present = {}
    for asset_type in ALBUM_TYPES:
        present[asset_type] = _album_type_present(album_id, directory, asset_type, album)
    return present


def _album_type_present(album_id, directory, asset_type, album=None):
    row = db.fetchone(
        """
        SELECT local_path FROM artwork_pool
        WHERE album_id = %s AND asset_type = %s AND is_selected = TRUE
          AND local_path IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (album_id, asset_type),
    )
    if row and row["local_path"] and os.path.isfile(row["local_path"]):
        return True
    if asset_type == "front" and album and album.get("has_artwork"):
        return True
    if not directory:
        return False
    for name in ALBUM_FILE_NAMES.get(asset_type, ()):
        if os.path.isfile(os.path.join(directory, name)):
            return True
    if asset_type == "booklet" and _booklet_on_disk(directory):
        return True
    return False


def _asset_present(album_id, artist_id, asset_type, album_present=None, artist_present=None):
    if asset_type in ARTIST_TYPES:
        if not artist_id:
            return True
        present = artist_present or artist_assets(artist_id)
        if asset_type == "fanart":
            return int(present.get("fanart") or 0) > 0
        return bool(present.get(asset_type))
    present = album_present or album_assets(album_id)
    return bool(present.get(asset_type))


def artist_assets(artist_id):
    """Which artist sidecar files are already in the artist folder or selected."""
    artist = db.fetchone("SELECT path, has_nfo FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        return {}
    directory = artist.get("path") or ""
    return {
        "artistthumb": artist_image(artist_id, "artistthumb") is not None,
        "clearlogo": artist_image(artist_id, "clearlogo") is not None,
        "banner": artist_image(artist_id, "banner") is not None,
        "landscape": artist_image(artist_id, "landscape") is not None,
        "fanart": _fanart_count(artist_id, directory),
        "has_nfo": bool(artist.get("has_nfo")) or _artist_nfo_present(directory),
    }


def _artist_nfo_present(directory):
    if not directory:
        return False
    return any(os.path.isfile(os.path.join(directory, name)) for name in ("artist.nfo", "folder.nfo"))


def _fanart_paths(artist_id, directory):
    found = {}

    def add(path):
        if path and os.path.isfile(path):
            found[os.path.normcase(os.path.abspath(path))] = path

    if directory and os.path.isdir(directory):
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        for name in names:
            if fanart_index(name) is not None:
                add(os.path.join(directory, name))
        extra = os.path.join(directory, "extrafanart")
        if os.path.isdir(extra):
            try:
                extra_names = os.listdir(extra)
            except OSError:
                extra_names = []
            for name in extra_names:
                if name.lower().endswith((".jpg", ".jpeg", ".png")):
                    add(os.path.join(extra, name))
    rows = db.fetchall(
        """
        SELECT local_path FROM artwork_pool
        WHERE artist_id = %s AND album_id IS NULL
          AND asset_type IN ('fanart', 'extrafanart')
          AND is_selected = TRUE AND local_path IS NOT NULL
        """,
        (artist_id,),
    )
    for row in rows:
        add(row["local_path"])

    def sort_key(path):
        parent = os.path.basename(os.path.dirname(path)).lower()
        index = fanart_index(os.path.basename(path))
        return (1 if parent == "extrafanart" else 0, 10000 if index is None else index, os.path.basename(path).lower())

    return [found[key] for key in sorted(found, key=lambda key: sort_key(found[key]))]


def fanart_file(artist_id, index):
    """One fanart image in display order. Index 0 is fanart.jpg."""
    artist = db.fetchone("SELECT path FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        return None
    paths = _fanart_paths(artist_id, artist.get("path") or "")
    number = int(index)
    if number < 0 or number >= len(paths):
        return None
    try:
        return assert_readable(paths[number])
    except AppError:
        return None


def _fanart_count(artist_id, directory):
    return len(_fanart_paths(artist_id, directory))


def artist_image(artist_id, asset_type):
    if asset_type not in {"artistthumb", "fanart", "clearlogo", "clearart", "banner", "landscape"}:
        raise AppError("Unknown artwork type", 404)
    row = db.fetchone(
        """
        SELECT local_path FROM artwork_pool
        WHERE artist_id = %s AND album_id IS NULL AND asset_type = %s AND is_selected = TRUE
          AND local_path IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (artist_id, asset_type),
    )
    artist = db.fetchone("SELECT path FROM artists WHERE id = %s", (artist_id,))
    directory = (artist or {}).get("path") or ""
    names = {
        "artistthumb": ("folder.jpg", "thumb.jpg", "cover.jpg"),
        "fanart": ("fanart.jpg", "fanart.jpeg", "fanart.png"),
        "clearlogo": ("clearlogo.png", "logo.png"),
        "clearart": ("clearart.png",),
        "banner": ("banner.jpg",),
        "landscape": ("landscape.jpg",),
    }[asset_type]
    local = (row or {}).get("local_path") or ""
    if local and _inside_dir(local, directory):
        found = _readable_file(local)
        if found:
            return found
    if directory and names:
        found = _readable_file(os.path.join(directory, names[0]))
        if found:
            return found
    if local:
        found = _readable_file(local)
        if found:
            return found
    if not directory:
        return None
    for name in names[1:]:
        found = _readable_file(os.path.join(directory, name))
        if found:
            return found
    if asset_type == "fanart" and artist.get("path"):
        return _first_fanart(artist["path"])
    return None


def _first_fanart(directory):
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        names = []
    for name in names:
        if fanart_index(name) is not None:
            found.append(os.path.join(directory, name))
    extra = os.path.join(directory, "extrafanart")
    if os.path.isdir(extra):
        try:
            extra_names = os.listdir(extra)
        except OSError:
            extra_names = []
        for name in extra_names:
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                found.append(os.path.join(extra, name))
    found.sort()
    for path in found:
        if os.path.isfile(path):
            try:
                return assert_readable(path)
            except AppError:
                return None
    return None


def booklet_filename(index):
    """First Cover Art Archive booklet page is booklet.png, then booklet1.png, booklet2.png."""
    number = int(index or 0)
    if number <= 0:
        return "booklet.png"
    return f"booklet{number}.png"


def booklet_index(name):
    match = re.match(r"^booklet(\d*)\.(?:png|jpe?g|pdf)$", str(name or ""), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1) or "0")


def _booklet_page_rows(row):
    pages = db.fetchall(
        """
        SELECT * FROM artwork_pool
        WHERE album_id = %s AND asset_type = 'booklet' AND source_provider = 'caa'
        ORDER BY created_at, id
        """,
        (row["album_id"],),
    )
    if any(str(page["id"]) == str(row["id"]) for page in pages):
        return pages
    return [row, *pages]


def _booklet_on_disk(directory):
    if not directory or not os.path.isdir(directory):
        return []
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    for name in names:
        index = booklet_index(name)
        if index is None:
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            found.append((index, name.lower(), path))
    found.sort()
    return [path for _index, _name, path in found]


def _write_booklet_set(directory, pages):
    """Write every booklet page. Images are numbered; a PDF stays booklet.pdf."""
    written = []
    image_index = 0
    for page, data in pages:
        if data.startswith(b"%PDF"):
            filename = "booklet.pdf"
            payload = data
        else:
            filename = booklet_filename(image_index)
            payload = _to_png(data)
            image_index += 1
        path = os.path.join(directory, filename)
        page_id = page.get("id") if isinstance(page, dict) else None
        if page_id:
            _keep_other_copies(path, page_id)
        target = atomic_write(path, payload, binary=True)
        written.append((page, filename, target, payload))
    _clear_booklet_files(directory, {filename for _page, filename, _target, _payload in written})
    return written


def _clear_booklet_files(directory, keep):
    if not directory or not os.path.isdir(directory):
        return
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if booklet_index(name) is None or name in keep:
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            logger.info("could not replace booklet file %s", name)


def _export_bytes(asset_type, data, fallback_name):
    if asset_type == "booklet" and data.startswith(b"%PDF"):
        return "booklet.pdf", data
    if asset_type == "booklet":
        return "booklet.png", _to_png(data)
    if asset_type == "extrafanart":
        ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in fallback_name) or "image"
        if not safe.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            safe += ext
        if ext == ".jpg" and not data.startswith(b"\xff\xd8"):
            return os.path.splitext(safe)[0] + ".jpg", _to_jpeg(data)
        return safe, data
    if asset_type in PNG_TYPES:
        return FILENAMES[asset_type], _to_png(data)
    return FILENAMES.get(asset_type, "folder.jpg"), _to_jpeg(data)


def _embed_album(album_id):
    from resonance import pictures

    paths = [row["file_path"] for row in db.fetchall("SELECT file_path FROM tracks WHERE album_id = %s", (album_id,))]
    try:
        pictures.embed_tracks(paths)
    except Exception:
        logger.info("embed art skipped for album %s", album_id, exc_info=True)


MAX_DISCS = 30
_DISC_COMMENT = re.compile(r"(?:discs?|cds?|mediums?)\s*#?\s*(\d+)", re.IGNORECASE)
_DISC_DIR = re.compile(r"^(?:cd|disc)\s*0*(\d+)$", re.IGNORECASE)
_LEGACY_DISC = re.compile(r"^(?:cd|disc)\d+\.(?:png|jpe?g)$", re.IGNORECASE)
_NUMBERED_DISCART = re.compile(r"^(?:discart|cdart)\d+\.(?:png|jpe?g)$", re.IGNORECASE)


def disc_index(comment):
    """Disc number from a Cover Art Archive comment, when the comment is a disc label."""
    text = str(comment or "").strip()
    match = _DISC_COMMENT.search(text)
    if match:
        number = int(match.group(1))
        return number if 1 <= number <= MAX_DISCS else None
    if re.fullmatch(r"\d+", text):
        number = int(text)
        return number if 1 <= number <= MAX_DISCS else None
    return None


def assign_medium_discs(images):
    """Map Cover Art Archive medium images onto disc numbers, in archive order."""
    assigned = {}
    pending = []
    seen = set()
    for image in images or []:
        url = (image or {}).get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        number = disc_index((image or {}).get("comment"))
        if number and number not in assigned:
            assigned[number] = url
        else:
            pending.append(url)
    for url in pending:
        number = 1
        while number in assigned and number <= MAX_DISCS:
            number += 1
        if number > MAX_DISCS:
            break
        assigned[number] = url
    return [{"disc": number, "url": url} for number, url in sorted(assigned.items())]


def disc_directories(album_path):
    """CD1, CD 2, and Disc 3 folders under the album, keyed by disc number."""
    found = {}
    try:
        names = os.listdir(album_path)
    except OSError:
        return found
    for name in names:
        match = _DISC_DIR.fullmatch(name)
        path = os.path.join(album_path, name)
        if not match or not os.path.isdir(path):
            continue
        number = int(match.group(1))
        if 1 <= number <= MAX_DISCS:
            found[number] = path
    return found


def disc_art_plan(album_path, images, fallback, disc_count):
    """Kodi discart paths. Numbered files are written for a multi-disc release."""
    numbered = {number: payload for number, payload in (images or {}).items() if payload and 1 <= int(number) <= MAX_DISCS}
    count = max(int(disc_count or 1), max(numbered) if numbered else 1)
    root = fallback or numbered.get(1) or (numbered[min(numbered)] if numbered else None)
    if not root:
        return []
    if count > 1 and 1 not in numbered:
        numbered[1] = root
    files = [(os.path.join(album_path, "discart.png"), root)]
    if count > 1 or len(numbered) > 1:
        for number, payload in sorted(numbered.items()):
            files.append((os.path.join(album_path, f"discart{int(number)}.png"), payload))
    for number, folder in sorted(disc_directories(album_path).items()):
        payload = numbered.get(number)
        if payload is None and number == 1:
            payload = root
        if payload:
            files.append((os.path.join(folder, "discart.png"), payload))
    return files


def album_disc_count(album):
    total = 1
    try:
        total = max(1, int((album or {}).get("total_discs") or 1))
    except (TypeError, ValueError):
        total = 1
    album_id = (album or {}).get("id")
    if not album_id:
        return total
    row = db.fetchone(
        "SELECT COALESCE(MAX(disc_number), 1) AS discs FROM tracks WHERE album_id = %s",
        (album_id,),
    )
    try:
        total = max(total, int((row or {}).get("discs") or 1))
    except (TypeError, ValueError):
        pass
    return min(total, MAX_DISCS)


def ensure_disc_arts(album):
    """Download every disc image and write discart.png plus discart1.png, discart2.png, and each CD folder."""
    directory = (album or {}).get("path") or ""
    if not directory or not os.path.isdir(directory):
        return []
    images = _fetch_disc_images(album)
    fallback = _read_bytes(os.path.join(directory, "discart.png"))
    if not fallback and images:
        fallback = images.get(1) or images[min(images)]
    if not fallback and not images:
        return []
    return _write_disc_plan(disc_art_plan(directory, images, fallback, album_disc_count(album)))


def _mirror_disc_art(directory, payload, album):
    images = {}
    if album:
        try:
            images = _fetch_disc_images(album)
        except Exception:
            logger.info("disc art lookup failed", exc_info=True)
    try:
        fallback = _to_png(payload)
    except Exception:
        fallback = payload
    if album and 1 not in images and fallback:
        images[1] = fallback
    count = album_disc_count(album) if album else 1
    _write_disc_plan(disc_art_plan(directory, images, fallback, count))
    _remove_legacy_disc_mirrors(directory)


def _fetch_disc_images(album):
    mediums = []
    release_id = album.get("musicbrainz_release_id")
    group_id = album.get("musicbrainz_release_group_id")
    try:
        if release_id:
            mediums.extend(coverart.images_for_release(release_id) or [])
        if group_id:
            mediums.extend(coverart.images_for_group(group_id) or [])
    except Exception:
        logger.info("cover art disc lookup failed", exc_info=True)
        mediums = []
    mediums = [image for image in mediums if "medium" in (image.get("types") or [])]
    assigned = assign_medium_discs(mediums)
    if not assigned and album.get("id"):
        assigned = _pool_disc_urls(album)
    images = {}
    for item in assigned:
        png = _png_from_url(item["url"])
        if png:
            images[item["disc"]] = png
    return images


def _pool_disc_urls(album):
    count = album_disc_count(album)
    if count <= 1:
        return []
    rows = db.fetchall(
        """
        SELECT source_url FROM artwork_pool
        WHERE album_id = %s AND asset_type = 'discart' AND source_url LIKE 'http%%'
        ORDER BY is_selected DESC, created_at
        """,
        (album["id"],),
    )
    images = [{"url": row["source_url"], "comment": ""} for row in rows if row.get("source_url")]
    return [item for item in assign_medium_discs(images) if item["disc"] <= count]


def _png_from_url(url):
    body, _kind = get_bytes(url)
    if not body:
        return None
    try:
        return _to_png(body)
    except Exception:
        logger.info("disc image was not a picture: %s", url)
        return None


def _read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _write_disc_plan(files):
    written = []
    for path, payload in files:
        try:
            png = payload if payload.startswith(b"\x89PNG") else _to_png(payload)
        except Exception:
            logger.info("disc art skipped, not an image: %s", path)
            continue
        if _same_payload(path, png):
            written.append(path)
            continue
        atomic_write(path, png, binary=True)
        written.append(path)
    if files:
        _remove_legacy_disc_mirrors(os.path.dirname(files[0][0]))
    return written


def _remove_legacy_disc_mirrors(directory):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if _LEGACY_DISC.match(name):
            _drop_exclusive(os.path.join(directory, name))


def _clear_deployed_discarts(directory):
    if not directory or not os.path.isdir(directory):
        return
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        path = os.path.join(directory, name)
        if name.lower() in {"discart.png", "discart.jpg", "cdart.png", "disc.png"} or _NUMBERED_DISCART.match(name) or _LEGACY_DISC.match(name):
            _drop_exclusive(path)
        elif os.path.isdir(path) and _DISC_DIR.fullmatch(name):
            _drop_exclusive(os.path.join(path, "discart.png"))


def _to_jpeg(data):
    with Image.open(io.BytesIO(data)) as image:
        converted = image.convert("RGB")
        output = io.BytesIO()
        converted.save(output, format="JPEG", quality=92)
        return output.getvalue()


def _to_png(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _score(row, cfg):
    priority = cfg["source_priority"]
    provider = row.get("source_provider") or ""
    try:
        rank = priority.index(provider)
    except ValueError:
        rank = len(priority) + 1
    width, height = _resolution(row.get("resolution"))
    edge = max(width, height) if width and height else 0
    cap = int(cfg.get("min_resolution") or 0)
    size = int(row.get("file_size_bytes") or 0)
    if edge <= 0:
        return (0, 0, -rank, size)
    if cap <= 0 or edge <= cap:
        return (2, edge, -rank, size)
    return (1, -edge, -rank, size)


def _resolution(value):
    if not value or "x" not in str(value):
        return 0, 0
    left, right = str(value).lower().split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return 0, 0


def preferred_artwork(group, cfg):
    """Largest image that fits the maximum edge. A thumbnail under 500 px loses to a real cover."""
    rows = list(group or [])
    cap = int((cfg or {}).get("min_resolution") or 0)
    floor = 500 if cap >= 1000 else (cap // 2 if cap else 0)
    if floor:
        sized = [row for row in rows if _edge(row) >= floor]
        if sized:
            rows = sized
    return max(rows, key=lambda row: _score(row, cfg))


def _edge(row):
    width, height = _resolution((row or {}).get("resolution"))
    if not width or not height:
        return 0
    return max(width, height)


def suggestion_reason(row, group, cfg):
    """Why this image is the suggestion for its artwork type."""
    cap = int((cfg or {}).get("min_resolution") or 0)
    floor = 500 if cap >= 1000 else (cap // 2 if cap else 0)
    edge = _edge(row)
    smaller = 0
    if floor:
        smaller = sum(1 for item in (group or []) if 0 < _edge(item) < floor)
    if cap <= 0:
        reason = "Largest image"
    elif edge and edge <= cap:
        reason = f"Largest image at or under {cap} px"
    elif edge:
        reason = f"Closest image to the {cap} px maximum"
    else:
        reason = "No size was recorded"
    if smaller:
        reason += f". Images under {floor} px were skipped"
    return reason


def _annotate(rows, cfg):
    groups = {}
    for row in rows:
        key = (str(row["album_id"] or ""), str(row["artist_id"] or ""), row["asset_type"])
        groups.setdefault(key, []).append(row)
    reasons = {}
    for group in groups.values():
        winner = preferred_artwork(group, cfg)
        reasons[str(winner["id"])] = suggestion_reason(winner, group, cfg)
    annotated = []
    for row in rows:
        item = dict(row)
        item["suggested"] = str(row["id"]) in reasons
        item["suggestion_reason"] = reasons.get(str(row["id"]), "")
        item["on_disk"] = _row_on_disk(row)
        annotated.append(item)
    _prefer_displayed(annotated)
    return annotated


def _displayed_file(row):
    """The file the info pane shows for this artwork type."""
    asset = str((row or {}).get("asset_type") or "")
    if not asset or asset == "extrafanart":
        return None
    try:
        if row.get("album_id"):
            return album_image(row["album_id"], asset)
        if row.get("artist_id"):
            return artist_image(row["artist_id"], asset)
    except AppError:
        return None
    return None


def _prefer_displayed(rows):
    """Select the pool row whose file is the one on the info pane.

    A renamed artist folder leaves the old folder.jpg marked selected. The pane
    reads the file in the current folder, so the modal has to follow that file.
    """
    shown = {}
    for row in rows:
        asset = str(row.get("asset_type") or "")
        if asset == "extrafanart":
            continue
        key = (str(row.get("album_id") or ""), str(row.get("artist_id") or ""), asset)
        if key not in shown:
            shown[key] = _displayed_file(row)
        path = shown[key]
        local = row.get("local_path") or ""
        row["is_selected"] = bool(path and local and _same_file(path, local))
    return rows
