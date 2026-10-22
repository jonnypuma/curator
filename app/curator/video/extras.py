"""Sort a movie's extra videos into the folder layout Kodi or Plex/Jellyfin expect.

Kodi: the first trailer becomes <movie>-trailer.<ext> next to the movie; every other extra goes into
Extras/. Plex and Jellyfin: one subfolder per type (Trailers, Behind The Scenes, Deleted Scenes, ...).
Only movies in their own folder are touched, because in a shared folder an extra can not be told
apart from another movie.
"""
from __future__ import annotations

import os
import re

from curator.video import delete, naming, store

FOLDERS = {
    "trailer": "Trailers",
    "behindthescenes": "Behind The Scenes",
    "deleted": "Deleted Scenes",
    "featurette": "Featurettes",
    "interview": "Interviews",
    "scene": "Scenes",
    "short": "Shorts",
    "other": "Other",
}
KODI_FOLDER = "Extras"
_SUFFIX_KIND = {"trailer": "trailer", "behindthescenes": "behindthescenes", "deleted": "deleted",
                "deletedscene": "deleted", "featurette": "featurette", "interview": "interview", "scene": "scene",
                "short": "short", "other": "other", "extra": "other"}
_RULES = (
    ("trailer", re.compile(r"(?i)\b(trailer|teaser|tv spot)\b")),
    ("behindthescenes", re.compile(r"(?i)\b(behind the scenes|making of|b-roll|broll|bts)\b")),
    ("deleted", re.compile(r"(?i)\b(deleted|extended scene|blooper|gag reel|outtake)s?\b")),
    ("interview", re.compile(r"(?i)\b(interview|q&a|press|cast talks)\b")),
    ("short", re.compile(r"(?i)\b(short film|one shot|one-shot)\b")),
    ("featurette", re.compile(r"(?i)\b(featurette|inside the|spotlight|vfx breakdown)\b")),
)
_SUFFIX = re.compile(r"[ ._]*-(trailer|behindthescenes|deleted|deletedscene|featurette|interview|scene|short|other|extra)s?$",
                     re.I)
_FOLDER_KIND = {name.lower(): kind for kind, name in FOLDERS.items()}
_FOLDER_KIND.update({"trailer": "trailer", "featurette": "featurette", "deleted scene": "deleted"})
_GENERIC_DIRS = {"extras", "extra", "bonus", "others"}


def classify(stem, folder_kind=None):
    match = _SUFFIX.search(stem)
    if match:
        return _SUFFIX_KIND[match.group(1).lower()]
    if stem.strip().lower() in ("trailer", "trailers"):
        return "trailer"
    for kind, rule in _RULES:
        if rule.search(stem):
            return kind
    return folder_kind or "featurette"


def clean_name(name):
    stem, ext = os.path.splitext(name)
    cleaned = _SUFFIX.sub("", stem).strip(" ._-")
    return (cleaned or stem) + ext


def _videos(folder):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [name for name in names if naming.is_video(name) and not name.startswith(".")
            and os.path.isfile(os.path.join(folder, name))]


def plan_movie(movie_id, layout):
    row = store.movie_row(movie_id)
    if not row:
        return None
    title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
    plan = {"kind": "movie", "id": str(movie_id), "title": title, "moves": [], "db_only": [], "error": None,
            "folders": [row["folder"]]}
    folder = row["folder"]
    if row["path"] != folder:
        plan["error"] = "Shares its folder with other movies; extras are only sorted inside a movie's own folder"
        return plan
    try:
        delete._guard(folder, row["root"], "movies")
    except Exception as exc:
        plan["error"] = str(exc)
        return plan
    parts = {os.path.normcase(path) for path in row.get("parts") or []}
    main = sorted(row.get("parts") or [])
    main_stem = os.path.splitext(os.path.basename(main[0]))[0] if main else os.path.basename(folder)
    found = []
    for name in _videos(folder):
        path = os.path.join(folder, name)
        if os.path.normcase(path) in parts or naming._SAMPLE.search(os.path.splitext(name)[0]):
            continue
        if naming.is_extra_file(name):
            found.append((path, classify(os.path.splitext(name)[0])))
    for entry in sorted(os.listdir(folder)):
        sub = os.path.join(folder, entry)
        if not os.path.isdir(sub) or not naming.is_extra_dir(entry) or entry.lower() in ("sample", "samples"):
            continue
        folder_kind = _FOLDER_KIND.get(entry.lower())
        for name in _videos(sub):
            stem = os.path.splitext(name)[0]
            kind = classify(stem, None if entry.lower() in _GENERIC_DIRS else folder_kind)
            found.append((os.path.join(sub, name), kind))
    kodi_trailer = f"{main_stem.lower()}-trailer"
    has_trailer = any(os.path.splitext(name)[0].lower() == kodi_trailer for name in _videos(folder))
    for path, kind in found:
        name = os.path.basename(path)
        if layout == "kodi":
            if os.path.dirname(path) == folder and os.path.splitext(name)[0].lower() == kodi_trailer:
                continue
            if kind == "trailer" and not has_trailer:
                target = os.path.join(folder, f"{main_stem}-trailer{os.path.splitext(name)[1].lower()}")
                has_trailer = True
            else:
                target = os.path.join(folder, KODI_FOLDER, clean_name(name))
        else:
            target = os.path.join(folder, FOLDERS[kind], clean_name(name))
        if os.path.normcase(target) != os.path.normcase(path):
            plan["moves"].append({"from": path, "to": target, "dir": False})
    return plan


def plan_show(show_id, layout):
    """Sort extra videos in a show folder. Episode files stay where they are."""
    show = store.show_row(show_id)
    if not show:
        return None
    title = f"{show['title']} ({show['year']})" if show.get("year") else show["title"]
    folder = show["path"]
    plan = {"kind": "show", "id": str(show_id), "title": title, "moves": [], "db_only": [], "error": None,
            "folders": [folder]}
    try:
        delete._guard(folder, show["root"], "tv")
    except Exception as exc:
        plan["error"] = str(exc)
        return plan
    episodes = db_episode_paths(show_id)
    found = []
    for name in _videos(folder):
        path = os.path.join(folder, name)
        if os.path.normcase(path) in episodes or naming._SAMPLE.search(os.path.splitext(name)[0]):
            continue
        if naming.is_extra_file(name) or os.path.splitext(name)[0].lower() in ("tvshow-trailer", "season-trailer"):
            found.append((path, classify(os.path.splitext(name)[0])))
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        entries = []
    for entry in entries:
        sub = os.path.join(folder, entry)
        if not os.path.isdir(sub) or not naming.is_extra_dir(entry) or entry.lower() in ("sample", "samples"):
            continue
        folder_kind = _FOLDER_KIND.get(entry.lower())
        for name in _videos(sub):
            stem = os.path.splitext(name)[0]
            kind = classify(stem, None if entry.lower() in _GENERIC_DIRS else folder_kind)
            found.append((os.path.join(sub, name), kind))
    has_trailer = any(os.path.splitext(name)[0].lower() == "tvshow-trailer" for name in _videos(folder))
    for path, kind in found:
        name = os.path.basename(path)
        if layout == "kodi":
            if os.path.dirname(path) == folder and os.path.splitext(name)[0].lower() == "tvshow-trailer":
                continue
            if kind == "trailer" and not has_trailer:
                target = os.path.join(folder, f"tvshow-trailer{os.path.splitext(name)[1].lower()}")
                has_trailer = True
            else:
                target = os.path.join(folder, KODI_FOLDER, clean_name(name))
        else:
            target = os.path.join(folder, FOLDERS[kind], clean_name(name))
        if os.path.normcase(target) != os.path.normcase(path):
            plan["moves"].append({"from": path, "to": target, "dir": False})
    return plan


def db_episode_paths(show_id):
    from resonance import db

    rows = db.fetchall("SELECT path FROM tv_episodes WHERE show_id = %s", (show_id,))
    return {os.path.normcase(row["path"]) for row in rows if row.get("path")}
