"""Add a movie or show that has no video file yet.

Radarr or Sonarr is asked first. A wanted row is saved only when that add is accepted,
including when the title is already in Radarr or Sonarr. A rejection, a missing
integration, or a show with no TVDB id leaves Curator unchanged.
"""
from __future__ import annotations

import asyncio
import os

from curator import folders, radarr, sonarr
from curator.scrapers.http import Client
from curator.scrapers.tmdb import Tmdb
from curator.video import config, store
from resonance import db
from resonance.errors import AppError


def service(media):
    """Radarr (movies) or Sonarr (TV) as the add window needs to know it: its name, whether it can be asked at all
    (and if not, why), and whether Settings has it search for what it adds."""
    from curator import automation

    if media == "movies":
        name, source = "Radarr", "radarr"
        url, key, cfg = radarr._settings()
    else:
        name, source = "Sonarr", "sonarr"
        url, key = sonarr._settings()
        cfg = sonarr._config()
    problem = ""
    if not automation.integration_on(source):
        problem = f"{name} is turned off under Settings, Integrations."
    elif not url or not key:
        problem = f"{name} is not set up. Add its address and API key under Settings, Integrations."
    return {"service": name, "ready": not problem, "problem": problem, "search": bool((cfg or {}).get("search", True))}


def options(media):
    cfg = config.current()
    if media == "movies":
        return {
            "sources": [{"id": "tmdb", "label": "TMDB"}],
            "default": "tmdb",
            "roots": folders.configured("movies"),
            **service("movies"),
        }
    sources = [{"id": "tmdb", "label": "TMDB"}]
    if cfg.get("tvdb_key"):
        sources.append({"id": "tvdb", "label": "TheTVDB"})
    default = cfg.get("tv_primary") if cfg.get("tv_primary") == "tvdb" and cfg.get("tvdb_key") else "tmdb"
    return {"sources": sources, "default": default, "roots": folders.configured("tv"), **service("tv")}


def add_movie(tmdb_id, title, year, root, search=None):
    tmdb_id = str(tmdb_id or "").strip()
    title = str(title or "").strip()
    if not tmdb_id or not title:
        raise AppError("Choose a movie from the search results", 400)
    root = _root("movies", root)
    results = radarr.search([tmdb_id], search=search)
    item = results[0] if results else {"ok": False, "error": "Radarr did not answer"}
    if not item.get("ok"):
        raise AppError(item.get("error") or "Radarr did not accept the movie", 502)
    searched = bool(item.get("search"))
    existing = db.fetchone(
        "SELECT id FROM movies WHERE tmdb_id = %s AND NOT wanted LIMIT 1", (tmdb_id,)
    )
    if existing:
        return _answer(existing["id"], False, item.get("action"), _already("Already in the library", searched), searched)
    wanted = db.fetchone("SELECT id FROM movies WHERE wanted AND tmdb_id = %s LIMIT 1", (tmdb_id,))
    if wanted:
        return _answer(wanted["id"], True, item.get("action"), _already("Already waiting for this movie", searched), searched)
    movie_id, _inserted = store.save_movie({
        "path": f"wanted://movie/tmdb/{tmdb_id}",
        "root": root,
        "folder": f"wanted://movie/tmdb/{tmdb_id}",
        "title": title,
        "year": _year(year),
        "tmdb_id": tmdb_id,
        "ids": {"tmdb": tmdb_id},
        "wanted": True,
    })
    return _answer(movie_id, True, item.get("action"), _added("Radarr", "the file arrives", searched), searched)


def add_show(source, source_id, title, year, root, search=None):
    source_id = str(source_id or "").strip()
    title = str(title or "").strip()
    if source not in {"tmdb", "tvdb"} or not source_id or not title:
        raise AppError("Choose a show from the search results", 400)
    root = _root("tv", root)
    tmdb_id = source_id if source == "tmdb" else ""
    tvdb_id = source_id if source == "tvdb" else sonarr.tvdb_for_tmdb(tmdb_id)
    if not tvdb_id and tmdb_id:
        tvdb_id = asyncio.run(_tvdb_from_tmdb(tmdb_id))
    if not tvdb_id:
        raise AppError("This show has no TVDB id, so Sonarr cannot add it.", 400)
    result = sonarr.ensure_series(tvdb_id, search=search)
    searched = bool(result.get("search"))
    existing = db.fetchone(
        "SELECT id FROM tv_shows WHERE tvdb_id = %s AND NOT wanted LIMIT 1", (tvdb_id,)
    )
    if existing:
        return _answer(existing["id"], False, result.get("action"), _already("Already in the library", searched), searched)
    wanted = db.fetchone("SELECT id FROM tv_shows WHERE wanted AND tvdb_id = %s LIMIT 1", (tvdb_id,))
    if wanted:
        return _answer(wanted["id"], True, result.get("action"), _already("Already waiting for this show", searched), searched)
    ids = {"tvdb": tvdb_id}
    if tmdb_id:
        ids["tmdb"] = tmdb_id
    show_id, _inserted = store.save_show({
        "path": f"wanted://show/tvdb/{tvdb_id}",
        "root": root,
        "title": title,
        "year": _year(year),
        "tvdb_id": tvdb_id,
        "tmdb_id": tmdb_id or None,
        "ids": ids,
        "wanted": True,
    })
    return _answer(show_id, True, result.get("action"), _added("Sonarr", "the files arrive", searched), searched)


def _added(service, until, searched):
    """What the toast says after a new title is accepted, including whether a search was started."""
    sent = f"Added to {service} and a search was started" if searched else f"Added to {service} without a search"
    return f"{sent}. Curator will show it as wanted until {until}."


def _already(text, searched):
    return f"{text}. A search was started." if searched else text


def _answer(item_id, wanted, action, message, searched=False):
    return {"id": str(item_id), "wanted": bool(wanted), "action": action or "", "message": message,
            "searched": bool(searched)}


def _year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1870 <= year <= 2100 else None


def _root(kind, root):
    known = folders.configured(kind)
    if not known:
        raise AppError(f"Add a {folders.LABELS[kind]} library folder first", 400)
    if not root:
        if len(known) == 1:
            return known[0]
        raise AppError("Choose a library folder", 400)
    for item in known:
        if os.path.normpath(item) == os.path.normpath(str(root)):
            return item
    raise AppError("That folder is not a library folder", 400)


async def _tvdb_from_tmdb(tmdb_id):
    cfg = config.current()
    if not cfg.get("tmdb_key"):
        return ""
    client = Client()
    try:
        found = await Tmdb(client, cfg["tmdb_key"], cfg["language"], cfg["country"]).tv(tmdb_id)
    finally:
        await client.close()
    return str((found or {}).get("ids", {}).get("tvdb") or "")
