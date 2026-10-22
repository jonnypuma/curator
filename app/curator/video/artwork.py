"""Find local artwork beside movies, shows, seasons and episodes. Names follow Kodi."""
from __future__ import annotations

import os
import re

from curator.video.naming import IMAGE_EXTS, episode_mark

MOVIE_TYPES = {
    "poster": ("poster", "folder", "cover", "movie"),
    "fanart": ("fanart", "backdrop", "background"),
    "banner": ("banner",),
    "clearlogo": ("clearlogo", "logo"),
    "clearart": ("clearart",),
    "discart": ("discart", "disc"),
    "landscape": ("landscape", "thumb"),
    "keyart": ("keyart",),
    "squareart": ("squareart", "square"),
}
SHOW_TYPES = {
    "poster": ("poster", "folder", "cover"),
    "fanart": ("fanart", "backdrop", "background"),
    "banner": ("banner",),
    "clearlogo": ("clearlogo", "logo"),
    "clearart": ("clearart",),
    "landscape": ("landscape", "thumb"),
    "characterart": ("characterart",),
    "discart": ("discart", "disc"),
    "keyart": ("keyart",),
    "squareart": ("squareart", "square"),
}
SEASON_TYPES = ("poster", "banner", "fanart", "landscape")


def listing(folder, cache=None):
    """Lower-case file name to real file name for one folder."""
    if cache is not None and folder in cache:
        return cache[folder]
    names = {}
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file():
                    names[entry.name.lower()] = entry.name
    except OSError:
        pass
    if cache is not None:
        cache[folder] = names
    return names


def _find(folder, names, stems):
    for stem in stems:
        for extension in (".jpg", ".png", ".jpeg", ".webp", ".tbn"):
            real = names.get(f"{stem}{extension}".lower())
            if real:
                return os.path.join(folder, real)
    return None


def movie(folder, video_stem=None, own_folder=True, cache=None):
    names = listing(folder, cache)
    found = {}
    for kind, stems in MOVIE_TYPES.items():
        tried = [f"{video_stem}-{kind}"] if video_stem else []
        if kind == "discart" and video_stem:
            tried.append(f"{video_stem}-discart1")
        if kind == "poster" and video_stem:
            tried.append(video_stem)
        if own_folder:
            tried.extend(stems)
        path = _find(folder, names, tried)
        if path:
            found[kind] = path
    found.update(extra_images(folder))
    return found


def show(folder, cache=None):
    names = listing(folder, cache)
    found = {}
    for kind, stems in SHOW_TYPES.items():
        path = _find(folder, names, stems)
        if path:
            found[kind] = path
    found.update(extra_images(folder))
    return found


def season(show_folder, number, season_folder=None, cache=None):
    names = listing(show_folder, cache)
    label = "specials" if number == 0 else f"{number:02d}"
    found = {}
    for kind in SEASON_TYPES:
        path = _find(show_folder, names, [f"season{label}-{kind}", f"season{number}-{kind}"])
        if not path and season_folder:
            inner = listing(season_folder, cache)
            path = _find(season_folder, inner, [kind] + (["folder"] if kind == "poster" else []))
        if path:
            found[kind] = path
    return found


def episode(folder, video_stem, cache=None, season=None, episode=None, multi=False):
    """Episode thumb. A multi-episode file looks for <stem>-SxxEyy-thumb first, then the shared thumb."""
    names = listing(folder, cache)
    candidates = []
    if multi and season is not None and episode is not None:
        candidates.append(f"{video_stem}-{episode_mark(season, episode)}-thumb")
    candidates.extend((f"{video_stem}-thumb", video_stem))
    path = _find(folder, names, candidates)
    return {"thumb": path} if path else {}


def retarget_sidecars(folder, old_stems, new_stem, protected=()):
    """Rename artwork and .nfo files that carry an old video name onto the new video name.

    poster.jpg and other names that do not include the video name stay where they are.
    A file that already uses the new name is left in place. Returns the moves as (old, new) pairs.
    """
    from curator.video import delete

    new_stem = str(new_stem or "").strip()
    stems = []
    for stem in old_stems or []:
        text = str(stem or "").strip()
        if text and text != new_stem and text not in stems:
            stems.append(text)
    if not folder or not new_stem or not stems:
        return []
    moved = []
    for path in delete.sidecars(folder, stems, protected):
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS and ext != ".nfo":
            continue
        name = os.path.basename(path)
        lowered = name.lower()
        matched = ""
        for stem in sorted(stems, key=len, reverse=True):
            if lowered.startswith(stem.lower()) and len(lowered) > len(stem) and lowered[len(stem)] in ".-":
                matched = stem
                break
        if not matched:
            continue
        target = os.path.join(folder, new_stem + name[len(matched):])
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(target)):
            continue
        if os.path.exists(target):
            continue
        os.rename(path, target)
        moved.append((path, target))
    return moved


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


_EXTRA_KEY = re.compile(r"^(?:extrafanart\d*|extrathumbs\d*|actor .+)$")


def _images_in(folder):
    found = []
    if not folder or not os.path.isdir(folder):
        return found
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file() and is_image(entry.name):
                    found.append(entry.path)
    except OSError:
        return found
    found.sort(key=_image_order)
    return found


def _image_order(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    match = re.search(r"(\d+)$", stem)
    return (int(match.group(1)) if match else 0, stem)


def extra_images(folder):
    """Images already saved in extrafanart/ and extrathumbs/. Actor portraits stay in the cast list."""
    found = {}
    if not folder:
        return found
    from curator.video import actor_art

    actor_art.collapse_files(folder)
    for dirname, kind in (("extrafanart", "extrafanart"), ("extrathumbs", "extrathumbs")):
        paths = _images_in(os.path.join(folder, dirname))
        if len(paths) == 1:
            found[kind] = paths[0]
        else:
            for index, path in enumerate(paths, start=1):
                found[f"{kind}{index}"] = path
    return found


def apply_local_extras(folder, art):
    """Replace stored extra-fanart keys with the images in those folders now."""
    kept = {key: value for key, value in (art or {}).items() if not _EXTRA_KEY.match(str(key))}
    kept.update(extra_images(folder))
    return kept


def bind_actor_thumbs(folder, actors):
    """Point each actor at a portrait in .actors when the .nfo only stored the file name."""
    if not folder or not isinstance(actors, list):
        return actors or []
    directory = os.path.join(folder, ".actors")
    names = listing(directory)
    if not names:
        return actors
    bound = []
    for actor in actors:
        if not isinstance(actor, dict):
            bound.append(actor)
            continue
        item = dict(actor)
        thumb = str(item.get("thumb") or "").strip()
        if thumb.lower().startswith(("http://", "https://")) or (thumb and os.path.isfile(thumb)):
            bound.append(item)
            continue
        stems = []
        if thumb:
            stems.append(os.path.splitext(os.path.basename(thumb))[0])
        if item.get("name"):
            stems.append(str(item["name"]))
        stems = [stem for stem in stems if stem]
        stems.extend(stem.replace(" ", "_") for stem in stems if " " in stem)
        stems.extend(stem.replace("_", " ") for stem in list(stems) if "_" in stem)
        path = _find(directory, names, stems)
        if not path and thumb:
            real = names.get(os.path.basename(thumb).lower())
            if real:
                path = os.path.join(directory, real)
        if path:
            item["thumb"] = path
        bound.append(item)
    return bound
