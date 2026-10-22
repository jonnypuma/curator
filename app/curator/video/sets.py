"""The central movie set folder: one sub-folder per set, named the way Kodi looks it up.

Kodi's "Movie set information folder" setting points at the central folder. For a set called
"Alien Collection" Kodi reads <folder>/Alien Collection/poster.jpg, fanart.jpg and the other art types.
"""
from __future__ import annotations

import os
import re

from curator.video import artwork, config

NFO_NAME = "set.nfo"
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def nfo_name(dialect=None):
    """Kodi prefers set.nfo; Emby and Jellyfin prefer collection.nfo."""
    d = str(dialect or "").strip().lower()
    if d in ("emby", "jellyfin"):
        return "collection.nfo"
    return NFO_NAME


def folder_name(name):
    """Kodi's MakeLegalFileName: illegal characters become underscores, trailing dots and spaces go."""
    cleaned = _ILLEGAL.sub("_", str(name or "").strip()).rstrip(". ")
    return cleaned or "_"


def folder_for(root, name):
    return os.path.join(root, folder_name(name))


def local_art(folder):
    """Set art already in the folder, by kind."""
    if not folder or not os.path.isdir(folder):
        return {}
    names = artwork.listing(folder)
    found = {}
    for kind in config.SET_ART:
        for extension in (".jpg", ".png", ".jpeg", ".webp"):
            real = names.get(f"{kind}{extension}")
            if real:
                found[kind] = os.path.join(folder, real)
                break
    return found
