"""Finished scan reports saved under config/logs."""
from __future__ import annotations

import os
import re

from resonance.errors import AppError
from resonance.paths import config_dir

_NAME = re.compile(
    r"^(?:"
    r"\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?_(?:(?:movies|tv|music|sets)_scan|scan)(?:-\d+)?"
    r"|"
    r"(?:scan|(?:movies|tv|music|sets)-scan)-\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?"
    r")\.log$"
)
_SCRAPE_NAME = re.compile(
    r"^\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?_(?:movies|tv|sets|episodes|seasons)_scrape\.log$"
)
_STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})")
_MAX = 2_000_000


def is_scrape(name: str) -> bool:
    return bool(_SCRAPE_NAME.fullmatch(name))


def _matches_media(name: str, media: str | None) -> bool:
    target = (media or "").strip().lower()
    if not target or target == "all":
        return True
    return _media(name) == target


def list_logs(media: str | None = None, kind: str = "scan"):
    """kind is "scan" (scan reports) or "scrape" (scrape logs)."""
    folder = os.path.join(config_dir(), "logs")
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        if kind == "scrape":
            if not is_scrape(name):
                continue
        elif not _NAME.fullmatch(name):
            continue
        if media and not _matches_media(name, media):
            continue
        path = os.path.join(folder, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        found.append({
            "name": name,
            "label": _label(name),
            "media": _media(name),
            "when": _when(name),
            "bytes": size,
        })
    found.sort(key=lambda item: (item["when"], item["name"]), reverse=True)
    return found


def latest_log(media: str, kind: str = "scan") -> dict | None:
    logs = list_logs(media=media, kind=kind)
    if not logs:
        return None
    try:
        return read_log(logs[0]["name"])
    except Exception:
        return None


def read_log(name):
    safe = os.path.basename(str(name or ""))
    if not (_NAME.fullmatch(safe) or is_scrape(safe)):
        raise AppError("That scan report is not available", 404)
    path = os.path.join(config_dir(), "logs", safe)
    if not os.path.isfile(path):
        raise AppError("That scan report is not available", 404)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(_MAX)
    except OSError as exc:
        raise AppError("That scan report could not be read", 500) from exc
    return {"name": safe, "label": _label(safe), "media": _media(safe), "when": _when(safe), "text": text}


def _media(name):
    if is_scrape(name):
        return name.split("_")[1]
    if name.startswith("movies-") or "_movies_scan" in name:
        return "movies"
    if name.startswith("tv-") or "_tv_scan" in name:
        return "tv"
    if name.startswith("sets-") or "_sets_scan" in name:
        return "sets"
    return "music"


def _label(name):
    media = _media(name)
    if is_scrape(name):
        noun = {"movies": "Movie", "tv": "TV", "sets": "Movie set", "episodes": "Episode", "seasons": "Season"}[media]
        return f"{noun} scrape"
    if media == "movies":
        return "Movies"
    if media == "tv":
        return "TV"
    if media == "sets":
        return "Movie sets"
    return "Music"


def _when(name):
    match = _STAMP.search(name)
    if not match:
        return ""
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}:{second}"


def write_scrape_log(media, lines, keep=30):
    """Save one finished scrape under config/logs and drop the oldest beyond keep for that media."""
    from datetime import datetime

    folder = os.path.join(config_dir(), "logs")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    name = f"{stamp}_{media}_scrape.log"
    suffix = 2
    while os.path.exists(os.path.join(folder, name)):
        name = f"{stamp}-{suffix}_{media}_scrape.log"
        suffix += 1
    with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    old = sorted(
        (item["name"] for item in list_logs(media=media, kind="scrape")),
        key=lambda item: ((_STAMP.search(item).group(0) if _STAMP.search(item) else ""), item),
    )
    for item in old[:-max(1, int(keep or 30))]:
        try:
            os.remove(os.path.join(folder, item))
        except OSError:
            pass
    return name
