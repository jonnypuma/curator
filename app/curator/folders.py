"""Library folders by media type. A scan only walks the folders of the library it was started from."""
from __future__ import annotations

import os

from resonance.errors import AppError
from resonance.paths import inside

KEYS = {"music": "music_paths", "movies": "movie_paths", "tv": "tv_paths"}
LABELS = {"music": "music", "movies": "movie", "tv": "TV"}


def kind_for_media(media):
    """The folder type a library tab scans. Movie sets come from the movie folders."""
    if media == "sets":
        return "movies"
    if media in KEYS:
        return media
    raise AppError(f"Unknown library {media}", 400)


def configured(kind):
    from resonance.settings import load

    return [path for path in load().get(KEYS[kind]) or [] if isinstance(path, str) and path]


def mounted(kind):
    roots = []
    for path in configured(kind):
        if os.path.isdir(path):
            real = os.path.realpath(path)
            if real not in roots:
                roots.append(real)
    return roots


def excluded_real():
    """Library folders the user turned off for scans."""
    from resonance.settings import load

    found = set()
    for path in load().get("scan_excluded") or []:
        if not isinstance(path, str) or not path.strip():
            continue
        raw = path.strip()
        try:
            found.add(os.path.realpath(raw) if os.path.exists(raw) else os.path.normpath(raw))
        except OSError:
            found.add(os.path.normpath(raw))
    return found


def included(kind):
    """Mounted folders of this type that are still part of a scan."""
    skip = excluded_real()
    return [path for path in mounted(kind) if path not in skip]


def choose(kind, requested):
    """The requested folders, each checked against the folders of that type. Empty means all of them."""
    known = mounted(kind)
    skip = excluded_real()
    included_roots = [path for path in known if path not in skip]
    label = LABELS[kind]
    if not requested:
        if not included_roots:
            if known:
                raise AppError(
                    f"Every {label} folder is excluded from scans. Turn Exclude off under Settings, General.",
                    400,
                )
            raise AppError(f"No {label} folders are mounted. Add a {label} folder in Settings.", 400)
        return included_roots
    chosen = []
    skipped = False
    for item in requested:
        if not isinstance(item, str) or not item.strip():
            continue
        real = os.path.realpath(item.strip())
        if real not in known:
            # mounted() drops a configured folder it cannot read, so tell the user the
            # folder is away rather than claiming it is not a library folder.
            if item.strip() in configured(kind):
                raise AppError(
                    f"{item} cannot be read right now, so it was not scanned. "
                    f"Nothing indexed under it will be removed.",
                    400,
                )
            raise AppError(f"{item} is not a {label} folder", 400)
        if real in skip:
            skipped = True
            continue
        if real not in chosen:
            chosen.append(real)
    if not chosen and skipped:
        raise AppError("That folder is excluded from scans. Turn Exclude off under Settings, General.", 400)
    if not chosen:
        raise AppError(f"Choose a {label} folder to scan", 400)
    return chosen


def set_root():
    """The central movie set folder when one is configured and mounted, else None."""
    from resonance.settings import load

    path = str((load().get("video") or {}).get("set_folder") or "").strip()
    if path and os.path.isdir(path):
        return os.path.realpath(path)
    return None


def owner(path):
    """The video folder type that holds this path ("movies", "tv" or "sets"), or None."""
    real = os.path.realpath(path)
    for kind in ("movies", "tv"):
        for root in mounted(kind):
            if real == root or inside(root, real):
                return kind
    sets = set_root()
    if sets and (real == sets or inside(sets, real)):
        return "sets"
    return None

_volume_cache = {"at": 0.0, "roots": None}


def media_volumes():
    """The mounted media volumes, cached briefly. Artwork requests hit this per image."""
    import time

    now = time.monotonic()
    if _volume_cache["roots"] is not None and now - _volume_cache["at"] < 15:
        return _volume_cache["roots"]
    from resonance.paths import discover_mounts

    roots = []
    for mount in discover_mounts():
        base = str((mount or {}).get("path") or "").rstrip("/")
        if base and base != "/" and base not in roots:
            roots.append(base)
    _volume_cache["roots"] = roots
    _volume_cache["at"] = now
    return roots


def on_media_volume(path):
    """True when the path sits on one of the mounted media volumes.

    A library root can be a symlink or a bind mount of the same share, so a file can be
    reachable by a path that is not under any configured root while still living on a
    mounted volume. owner() answers which library a path belongs to and stays strict;
    this is the confinement check for serving a file by path.
    """
    real = os.path.realpath(path)
    for base in media_volumes():
        if real == base or inside(base, real):
            return True
    return False


def servable(path):
    """True when a file may be served by path: inside a library, or on a media volume."""
    return owner(path) is not None or on_media_volume(path)
