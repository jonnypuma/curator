"""Banned artwork: online pictures the user never wants. A banned picture is never marked Suggested in the artwork
window, never picked by Clean artwork, and never downloaded by a scrape (merge.rank_art leaves it out).

A ban is kept by the picture's address, so it covers every type that lists that picture (a fanart is also an extra
fanart candidate). The same shot on another site has another address and needs its own ban.
"""
from __future__ import annotations

import logging
import threading
import time

from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_cache = {"urls": None, "at": 0.0}
CACHE_SECONDS = 300


def urls():
    """Every banned address. Read once and kept for a few minutes; a ban or unban here clears it. Never raises."""
    with _lock:
        if _cache["urls"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["urls"]
    try:
        found = frozenset(str(row["url"]) for row in db.fetchall("SELECT url FROM art_bans"))
    except Exception:
        logger.debug("banned artwork could not be read", exc_info=True)
        return frozenset()
    with _lock:
        _cache.update({"urls": found, "at": time.monotonic()})
    return found


def _forget():
    with _lock:
        _cache.update({"urls": None, "at": 0.0})


def ban(url, item_kind="", item_id=None, art_kind=""):
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        raise AppError("Only an online picture can be banned", 400)
    db.execute(
        """
        INSERT INTO art_bans (url, item_kind, item_id, art_kind) VALUES (%s, %s, %s::uuid, %s)
        ON CONFLICT (url) DO NOTHING
        """,
        (text[:1000], str(item_kind or "")[:10], item_id or None, str(art_kind or "")[:20]),
    )
    _forget()
    return {"banned": True, "url": text}


def unban(url):
    db.execute("DELETE FROM art_bans WHERE url = %s", (str(url or "").strip(),))
    _forget()
    return {"banned": False, "url": url}


def ban_many(picks, item_kind="", item_id=None):
    done = 0
    for pick in picks or []:
        url = str((pick or {}).get("url") or "")
        if url.startswith(("http://", "https://")):
            ban(url, item_kind, item_id, (pick or {}).get("art_kind") or "")
            done += 1
    return {"banned": done}


def without_banned(candidates):
    """The candidates that are not banned (a list of dicts with "url")."""
    banned = urls()
    if not banned:
        return list(candidates or [])
    return [item for item in candidates or [] if str((item or {}).get("url") or "") not in banned]
