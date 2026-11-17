"""Tell the players when an album's or an artist's artwork changed.

Kodi keeps a cached copy of every picture it has shown, so a new folder.jpg under the same name stays hidden behind
the old one. A change queues an artwork-only refresh in the library queue: Kodi forgets its cached copy and points the
album or artist at the file. The other players read music artwork on their own scans, so nothing is queued for them.
"""
from __future__ import annotations

import logging

from resonance import db

logger = logging.getLogger(__name__)

# Curator's music artwork type -> the name Kodi gives that picture on an album or an artist.
ALBUM_ART = {"front": "thumb", "discart": "discart", "back": "back", "spine": "spine"}
ARTIST_ART = {"artistthumb": "thumb", "fanart": "fanart", "clearlogo": "clearlogo", "clearart": "clearart",
              "banner": "banner", "landscape": "landscape"}


def item_for(row):
    """The library-queue refresh item for one artwork_pool row whose picture was just saved, or None."""
    from resonance import artwork

    asset = str((row or {}).get("asset_type") or "")
    if row.get("album_id") and asset in ALBUM_ART:
        album = db.fetchone(
            "SELECT al.title, al.path, ar.name AS artist FROM albums al JOIN artists ar ON ar.id = al.artist_id WHERE al.id = %s",
            (row["album_id"],))
        path = artwork.album_image(row["album_id"], asset)
        if not album or not path:
            return None
        return {"kind": "album", "title": album["title"], "artist": album["artist"], "folder": album["path"],
                "label": f"{album['artist']} — {album['title']}", "art": {ALBUM_ART[asset]: str(path)}}
    if row.get("artist_id") and asset in ARTIST_ART:
        artist = db.fetchone("SELECT name, path FROM artists WHERE id = %s", (row["artist_id"],))
        path = artwork.artist_image(row["artist_id"], asset)
        if not artist or not path:
            return None
        return {"kind": "artist", "title": artist["name"], "folder": artist["path"], "label": artist["name"],
                "art": {ARTIST_ART[asset]: str(path)}}
    return None


def changed(rows):
    """Queue the artwork refresh for these saved rows. Never raises; returns how many items were queued."""
    try:
        from curator import library_queue

        items = [item for item in (item_for(row) for row in rows or [] if row) if item]
        if not items:
            return 0
        library_queue.queue_refresh("music", items)
        return len(items)
    except Exception:
        logger.exception("could not queue the music artwork refresh for the players")
        return 0
