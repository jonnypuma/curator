"""Music artwork: banned pictures, pictures of the wrong shape, and acting on several ticked pictures at once.

The music artwork window lists rows of artwork_pool (one per candidate, with its address, size and provider). A ban
is kept by the picture's address in art_bans, the same table the video artwork window uses. A banned picture, and
one whose listed size is the wrong shape for its type, is never suggested and never picked automatically
(artwork.preferred rows are filtered through eligible()).
"""
from __future__ import annotations

import logging
import os
import re

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

# Music artwork type -> the shape rule of curator.video.art_shape. Covers, thumbs, logos and booklets come in every
# shape (a digipak scan is not square), so they are not judged.
SHAPES = {"fanart": "fanart", "extrafanart": "fanart", "banner": "banner", "landscape": "landscape", "discart": "discart"}
# Types that hold many files by themselves: every pick is one more file, numbered by the artwork module.
MANY = {"fanart", "extrafanart", "booklet"}


def _size(row):
    text = str((row or {}).get("resolution") or "").lower()
    if "x" not in text:
        return None
    left, right = text.split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None


def wrong_shape(row):
    """True when the row's listed size does not fit its artwork type (a cover listed among the fanart)."""
    from curator.video import art_shape

    kind = SHAPES.get(str((row or {}).get("asset_type") or ""))
    size = _size(row)
    return bool(kind and size and art_shape.wrong(kind, size))


def banned(row, urls=None):
    from curator.video import art_bans

    found = art_bans.urls() if urls is None else urls
    return bool(found) and str((row or {}).get("source_url") or "") in found


def eligible(rows):
    """The rows that may be suggested or picked automatically: not banned, not the wrong shape."""
    from curator.video import art_bans

    urls = art_bans.urls()
    return [row for row in rows or [] if not banned(row, urls) and not wrong_shape(row)]


def _rows(ids):
    wanted = [str(item) for item in dict.fromkeys(ids or []) if re.fullmatch(r"[0-9a-fA-F-]{36}", str(item or ""))]
    if not wanted:
        return []
    found = {str(row["id"]): dict(row) for row in db.fetchall("SELECT * FROM artwork_pool WHERE id = ANY(%s::uuid[])", (wanted,))}
    return [found[item] for item in wanted if item in found]


def ban(ids):
    """Ban the online pictures of these rows. Uploaded and local ones have no address to ban and are left out."""
    from curator.video import art_bans

    done = 0
    for row in _rows(ids):
        url = str(row.get("source_url") or "")
        if url.startswith(("http://", "https://")):
            art_bans.ban(url, "artist" if row.get("album_id") is None else "album", None, row.get("asset_type") or "")
            done += 1
    return {"banned": done}


def unban(art_id):
    from curator.video import art_bans

    rows = _rows([art_id])
    if not rows:
        raise AppError("Artwork not found", 404)
    return art_bans.unban(str(rows[0].get("source_url") or ""))


def remove_many(ids):
    from resonance import artwork

    removed, failed = 0, []
    for row in _rows(ids):
        try:
            artwork.remove(str(row["id"]))
            removed += 1
        except AppError as exc:
            failed.append({"id": str(row["id"]), "error": str(exc)})
    return {"removed": removed, "failed": failed}


def select_many(ids):
    """Save several ticked pictures. The first one of a type that holds one file (cover, banner, logo…) becomes that
    file; further ones of that type are saved next to it as folder1.jpg, folder2.jpg…, which players ignore. Fanart and
    booklet pages are one more file each, as a single pick is."""
    from resonance import artwork

    seen, saved, failed, last = set(), 0, [], None
    for row in _rows(ids):
        key = (str(row.get("album_id") or ""), str(row.get("artist_id") or ""), row.get("asset_type"))
        try:
            if row.get("asset_type") in MANY or key not in seen:
                last = artwork.select(str(row["id"]))
            else:
                add_numbered(row)
            seen.add(key)
            saved += 1
        except AppError as exc:
            failed.append({"id": str(row["id"]), "error": str(exc)})
    return {"saved": saved, "failed": failed, "artwork": last}


def _next_number(directory, stem):
    pattern = re.compile(rf"^{re.escape(stem)}(\d+)\.[A-Za-z0-9]+$", re.IGNORECASE)
    highest = 0
    try:
        names = os.listdir(directory)
    except OSError:
        names = []
    for name in names:
        match = pattern.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def add_numbered(row):
    """Save this picture next to the type's main file as <name><N>.<ext> (folder1.jpg). Returns the path."""
    from resonance import artwork
    from resonance.paths import assert_library_writable, atomic_write
    from resonance.settings import load as load_settings

    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (row["album_id"],)) if row.get("album_id") else None
    artist_id = row.get("artist_id") or (album or {}).get("artist_id")
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,)) if artist_id else None
    data, _choice_path, _downloaded = artwork._load_choice(row)
    if not data:
        raise AppError("Could not download that image", 502)
    directory = artwork._destination_dir(row, album, artist, load_settings())
    assert_library_writable(directory)
    filename, payload = artwork._export_bytes(row["asset_type"], data, os.path.basename(row.get("local_path") or "image"))
    stem, extension = os.path.splitext(filename)
    target = os.path.join(directory, f"{stem}{_next_number(directory, stem)}{extension}")
    return atomic_write(target, payload, binary=True)


def fix_wrong_shapes(album_ids=None, log=None):
    """A music scan step: a selected fanart, banner, landscape or disc art whose size is the wrong shape for its type
    gets the best picture of the right shape from the candidates already listed for it. album_ids limits it to those
    albums and their artists; None checks the whole library. The sizes come from the database (artwork_pool keeps each
    picture's resolution), so no file is opened to find them. Returns how many were replaced."""
    from resonance import artwork
    from resonance.settings import load as load_settings

    write = log or (lambda line: None)
    types = list(SHAPES)
    if album_ids is None:
        rows = db.fetchall("SELECT * FROM artwork_pool WHERE is_selected AND asset_type = ANY(%s)", (types,))
    else:
        wanted = [str(item) for item in album_ids]
        if not wanted:
            return 0
        rows = db.fetchall(
            """
            SELECT * FROM artwork_pool
            WHERE is_selected AND asset_type = ANY(%s)
              AND (album_id = ANY(%s::uuid[])
                   OR (album_id IS NULL AND artist_id IN (SELECT artist_id FROM albums WHERE id = ANY(%s::uuid[]))))
            """,
            (types, wanted, wanted),
        )
    cfg = load_settings()
    fixed = 0
    for row in rows:
        if not wrong_shape(row) or str(row.get("source_provider") or "") in ("upload", "local"):
            continue
        label = artwork._album_label(row["album_id"]) if row.get("album_id") else (
            (db.fetchone("SELECT name FROM artists WHERE id = %s", (row["artist_id"],)) or {}).get("name") or "")
        if row.get("album_id"):
            others = artwork.list_for_album(row["album_id"])
        else:
            others = artwork.list_for_artist(row["artist_id"])
        best = artwork._unselected(others, row["asset_type"], cfg)
        if not best:
            write(f"Artwork shape: {label}: {row['asset_type']} is {row.get('resolution')}, the wrong shape; "
                  f"no picture of the right shape is listed, left as it is")
            continue
        try:
            artwork.select(str(best[0]["id"]))
            fixed += 1
            write(f"Artwork shape: {label}: {row['asset_type']} was {row.get('resolution')}, the wrong shape; "
                  f"replaced with {best[0].get('resolution') or 'another picture'} from {best[0].get('source_provider') or 'the list'}")
        except AppError as exc:
            write(f"Artwork shape: {label}: {row['asset_type']} could not be replaced: {exc}")
    return fixed
