"""Online artwork choices for a movie, show, season, episode or set.

The swap button lists TMDB images. Choosing one writes it into the Kodi file name
and records that path on the item.
"""
from __future__ import annotations

import asyncio
import os

from urllib.parse import urlsplit

from curator.scrapers.fanart import Fanart
from curator.scrapers.http import Client, ScrapeError
from curator.video import art_extra, art_fetch, config, naming, sets, store
from resonance.errors import AppError

# How many images of one type to show from each provider.
_PER_SOURCE = 8
_KINDS = {
    "movie": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart"),
    "show": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "characterart", "discart", "squareart"),
    "season": ("poster", "banner", "landscape", "fanart"),
    "episode": ("thumb",),
    "set": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart"),
}
_ART_HOSTS = {"image.tmdb.org", "assets.fanart.tv"}
# Published Fanart.tv frames. TMDB posters are 2:3, which is within 8% of 1000×1426.
_SHAPES = {
    "poster": (1000, 1426), "keyart": (1000, 1426),
    "fanart": (1920, 1080), "extrafanart": (1920, 1080), "extrathumbs": (1920, 1080),
    "clearlogo": (800, 310), "clearart": (1000, 562), "banner": (1000, 185),
    "landscape": (1000, 562), "thumb": (1000, 562),
    "discart": (1000, 1000), "squareart": (1000, 1000), "characterart": (512, 512),
}


def choices(kind, item_id):
    return asyncio.run(_choices(kind, item_id))


def choose(kind, item_id, url, art_kind):
    if str(url or "").startswith(art_extra.URL_PREFIX):
        # An image kept from an earlier upload or replacement.
        return asyncio.run(_choose(kind, item_id, "upload://kept", art_kind or "poster", art_extra.read_url(url)))
    host = urlsplit(str(url or "")).hostname or ""
    if host not in _ART_HOSTS:
        raise AppError("Choose an image from the list")
    return asyncio.run(_choose(kind, item_id, url, art_kind or "poster"))


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def choose_upload(kind, item_id, data, art_kind):
    """Save an image from the user's computer as this artwork kind, the same way a picked candidate is saved."""
    art_kind = str(art_kind or "").strip().lower()
    if art_kind not in _KINDS.get(kind, ()):
        raise AppError("Unknown artwork type for this item", 400)
    if not data:
        raise AppError("Choose an image file", 400)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("Artwork files must be 25 MB or smaller", 400)
    return asyncio.run(_choose(kind, item_id, "upload://local", art_kind, data))


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tbn"}


def remove(kind, item_id, art_kind):
    """Delete the image file stored for this artwork type and forget it. Only image files are removed."""
    art_kind = str(art_kind or "").strip().lower()
    if not art_kind or not all(ch.isalnum() or ch in "_-" for ch in art_kind):
        raise AppError("Unknown artwork type for this item", 400)
    _base, table, existing = _destination(kind, item_id, art_kind)
    current = dict(existing or {})
    path = current.get(art_kind)
    if not isinstance(path, str) or not path:
        raise AppError("There is no artwork of this type to remove", 404)
    removed = False
    if os.path.isfile(path):
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS:
            raise AppError("That file is not an image, so it was left alone", 400)
        try:
            os.remove(path)
            removed = True
        except OSError as exc:
            raise AppError(f"Could not delete the file: {exc.strerror or exc}", 500) from exc
    current.pop(art_kind, None)
    sources = dict(current.get("_sources") or {})
    sources.pop(art_kind, None)
    current["_sources"] = sources
    if table == "movie_sets":
        store.save_set_art(item_id, current, os.path.dirname(path), None)
    else:
        store.set_artwork(table, item_id, current)
    return {"removed": True, "file_deleted": removed, "kind": art_kind, "path": path}


def download_missing(kind, item_id):
    """Save the first listed image of each artwork type that is not on disk yet."""
    found = choices(kind, item_id)
    art = dict(found.get("artwork") or {})
    saved = False
    saved_kinds = []
    seen = set()
    for item in found.get("images") or []:
        art_kind = item.get("kind")
        if not art_kind or art.get(art_kind) or art_kind in seen:
            continue
        seen.add(art_kind)
        try:
            result = choose(kind, item_id, item["url"], art_kind)
        except AppError:
            continue
        if result.get("saved"):
            saved = True
            saved_kinds.append(art_kind)
            art[art_kind] = result.get("path") or True
    return {"saved": saved, "kinds": saved_kinds}


async def _choices(kind, item_id):
    cfg = config.current()
    if not cfg.get("tmdb_key"):
        raise AppError("Add a TMDB API key under Settings, General, before searching artwork")
    client = Client()
    try:
        tmdb = _tmdb(client, cfg)
        images, artwork_map, title = await _images(tmdb, kind, item_id)
        images = _with_keyart(list(images or []), kind)
        images.extend(await _fanart_images(client, cfg, kind, item_id))
    finally:
        await client.close()
    artwork_map = artwork_map or {}
    kept = [item for item in art_extra.listed(kind, item_id) if item["kind"] in (_KINDS.get(kind) or ())]
    return {"title": title, "artwork": artwork_map, "images": _mark_selected(_trim(images, kind), artwork_map) + kept}


async def _choose(kind, item_id, url, art_kind, data=None):
    base, table, existing = _destination(kind, item_id, art_kind)
    # The image on disk is about to be overwritten: keep a copy so it can be chosen again.
    art_extra.keep_file(kind, item_id, art_kind, (existing or {}).get(art_kind))
    if data is not None:
        try:
            path = await art_fetch.save_bytes(data, url, base, art_kind)
        except ScrapeError as exc:
            raise AppError("That file is not an image", 400) from exc
    else:
        client = Client()
        try:
            path = await art_fetch.save_choice(client, url, base, art_kind)
        finally:
            await client.close()
    if url == "upload://local":
        art_extra.keep_bytes(kind, item_id, art_kind, data, "upload")
    current = dict(existing or {})
    sources = dict(current.get("_sources") or {})
    sources[art_kind] = url
    current["_sources"] = sources
    current[art_kind] = path
    if table == "movie_sets":
        store.save_set_art(item_id, current, os.path.dirname(path), None)
    else:
        store.set_artwork(table, item_id, current)
    return {"saved": True, "path": path, "kind": art_kind}


def _with_keyart(images, kind):
    """Textless TMDB posters are the Kodi keyart for a movie or a set."""
    if kind not in {"movie", "set"}:
        return images
    extra = []
    for item in images:
        if item.get("source") == "tmdb" and item.get("kind") == "poster" and not item.get("lang"):
            extra.append({**item, "kind": "keyart"})
    return images + extra


async def _fanart_images(client, cfg, kind, item_id):
    if not cfg.get("fanart_key") or kind == "episode":
        return []
    fanart = Fanart(client, cfg["fanart_key"])
    try:
        if kind == "movie":
            row = store.movie_row(item_id) or {}
            return await fanart.movie({"tmdb": row.get("tmdb_id"), "imdb": row.get("imdb_id")}) or []
        if kind == "set":
            row = store.set_row(item_id) or {}
            return await fanart.collection(row.get("tmdb_collection_id")) or []
        if kind == "show":
            row = store.show_row(item_id) or {}
            art, _seasons = await fanart.tv({"tvdb": row.get("tvdb_id")})
            return art or []
        if kind == "season":
            season = store.season_row(item_id) or {}
            show = store.show_row(season.get("show_id")) or {}
            _art, seasons = await fanart.tv({"tvdb": show.get("tvdb_id")})
            return (seasons or {}).get(season.get("season_number")) or []
    except Exception:
        return []
    return []


def _mark_selected(images, artwork):
    """The file shown on the item is the selected image.

    A saved provider URL is only where that file was downloaded from. Marking
    that URL selected hid the file and highlighted a different picture.
    """
    del artwork
    for item in images:
        item["selected"] = False
    return images


def _trim(images, kind):
    """Keep each artwork type, with a cap per provider so later types are not dropped."""
    order = _KINDS.get(kind) or ("poster", "fanart", "clearlogo")
    buckets = {name: [] for name in order}
    seen = {name: set() for name in order}
    counts = {}
    for item in images or []:
        name = item.get("kind") or ""
        url = item.get("url") or ""
        if name not in buckets or not url or url in seen[name]:
            continue
        source = item.get("source") or "tmdb"
        key = (name, source)
        if counts.get(key, 0) >= _PER_SOURCE:
            continue
        seen[name].add(url)
        counts[key] = counts.get(key, 0) + 1
        buckets[name].append({
            "kind": name,
            "url": url,
            "preview": url.replace("/original/", "/w342/") if "/original/" in url else url,
            "width": item.get("width") or 0,
            "height": item.get("height") or 0,
            "score": item.get("score") or 0,
            "lang": item.get("lang") or "",
            "source": "Fanart.tv" if source == "fanart" else "TMDB",
        })
    minimums = config.current().get("min_width") or {}
    trimmed = []
    for name in order:
        rows = buckets[name]
        _mark_suggestion(rows, name, int(minimums.get(name) or 0))
        trimmed.extend(rows)
    return trimmed


def _shape_fit(item, kind):
    """1 when the image is within 8% of this type's frame. 0 when the size is unknown or far off."""
    width, height = int(item.get("width") or 0), int(item.get("height") or 0)
    frame = _SHAPES.get(kind)
    if not width or not height or not frame:
        return 0
    target = frame[0] / frame[1]
    return 1 if abs((width / height) - target) / target <= 0.08 else 0


def _mark_suggestion(rows, kind, minimum):
    """The largest image that matches this type's shape. A wide-enough image wins a tie."""
    if not rows:
        return
    def rank(item):
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        wide = 1 if not minimum or width >= minimum else 0
        return (_shape_fit(item, kind), wide, width * height, float(item.get("score") or 0))

    winner = max(rows, key=rank)
    winner["suggested"] = True
    width, height = int(winner.get("width") or 0), int(winner.get("height") or 0)
    size = f"{width}×{height}" if width and height else "unknown size"
    if _shape_fit(winner, kind):
        reason = f"Largest {size} at this shape"
    else:
        reason = f"Largest {size}"
    if minimum and width >= minimum:
        reason += f", at least {minimum} px wide"
    winner["suggestion_reason"] = reason


async def _images(tmdb, kind, item_id):
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        tmdb_id = row.get("tmdb_id")
        if not tmdb_id:
            raise AppError("Scrape this movie so it has a TMDB id")
        data = await tmdb.movie(tmdb_id)
        return (data or {}).get("art") or [], row.get("artwork") or {}, row.get("title") or ""
    if kind == "show":
        row = store.show_row(item_id)
        if not row:
            raise AppError("Show not found", 404)
        if not row.get("tmdb_id"):
            raise AppError("Scrape this show so it has a TMDB id")
        data = await tmdb.tv(row["tmdb_id"])
        return (data or {}).get("art") or [], row.get("artwork") or {}, row.get("title") or ""
    if kind == "season":
        season = store.season_row(item_id)
        if not season:
            raise AppError("Season not found", 404)
        show = store.show_row(season["show_id"])
        if not show.get("tmdb_id"):
            raise AppError("Scrape this show so it has a TMDB id")
        data = await tmdb.season(show["tmdb_id"], season["season_number"])
        label = "Specials" if season["season_number"] == 0 else f"Season {season['season_number']}"
        artwork = dict(season.get("artwork") or {})
        show_art = show.get("artwork") or {}
        for key in ("poster", "fanart"):
            if not artwork.get(key) and show_art.get(key):
                artwork[key] = show_art[key]
        return (data or {}).get("art") or [], artwork, f"{show.get('title') or ''} {label}"
    if kind == "episode":
        episode = store.episode_detail(item_id)
        if not episode:
            raise AppError("Episode not found", 404)
        show = store.show_row(episode["show_id"])
        if not show.get("tmdb_id"):
            raise AppError("Scrape this show so it has a TMDB id")
        images = await tmdb.episode_stills(show["tmdb_id"], episode["season_number"], episode["episode_number"])
        return images, episode.get("artwork") or {}, episode.get("title") or "Episode"
    if kind == "set":
        row = store.set_row(item_id)
        if not row:
            raise AppError("Set not found", 404)
        if not row.get("tmdb_collection_id"):
            raise AppError("Scrape this set so it has a TMDB collection id")
        data = await tmdb.collection(row["tmdb_collection_id"], images=True)
        return (data or {}).get("art") or [], row.get("artwork") or {}, row.get("name") or ""
    raise AppError("Artwork can be chosen for a movie, show, season, episode or set")


def _refuse_wanted(path):
    if str(path or "").startswith("wanted://"):
        raise AppError("This title has no video file yet, so artwork stays empty until a scan finds it.", 400)


def _destination(kind, item_id, art_kind):
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        _refuse_wanted(row.get("path"))
        own = row["path"] == row["folder"]
        parts = row.get("parts") or []
        stem = naming.movie_art_stem(parts)
        if len(parts) > 1 and stem:
            name = f"{stem}-{art_kind}"
        else:
            name = art_kind if own or not stem else f"{stem}-{art_kind}"
        return os.path.join(row["folder"], name), "movies", row.get("artwork") or {}
    if kind == "show":
        row = store.show_row(item_id)
        if not row:
            raise AppError("Show not found", 404)
        _refuse_wanted(row.get("path"))
        return os.path.join(row["path"], art_kind), "tv_shows", row.get("artwork") or {}
    if kind == "season":
        season = store.season_row(item_id)
        if not season:
            raise AppError("Season not found", 404)
        show = store.show_row(season["show_id"])
        label = "specials" if season["season_number"] == 0 else f"{season['season_number']:02d}"
        folder = season.get("path") or show["path"]
        return os.path.join(folder, f"season{label}-{art_kind}"), "tv_seasons", season.get("artwork") or {}
    if kind == "episode":
        episode = store.episode_detail(item_id)
        if not episode:
            raise AppError("Episode not found", 404)
        if episode.get("missing") or str(episode.get("path") or "").startswith("missing://"):
            show = store.show_row(episode["show_id"])
            season = store.season_row(episode["season_id"])
            folder = season.get("path") if season and season.get("path") and os.path.isdir(str(season.get("path"))) else ""
            if not folder and show and show.get("path") and os.path.isdir(str(show.get("path"))):
                folder = show["path"]
            if not folder:
                raise AppError("This episode has no season folder for a thumbnail yet", 400)
            mark = naming.episode_mark(episode.get("season_number"), episode.get("episode_number"))
            return os.path.join(folder, f"{mark}-thumb"), "tv_episodes", episode.get("artwork") or {}
        stem = os.path.splitext(os.path.basename(episode["path"]))[0]
        multi = store.episode_file_count(episode["path"]) > 1
        if multi:
            mark = naming.episode_mark(episode.get("season_number"), episode.get("episode_number"))
            stem = f"{stem}-{mark}"
        return os.path.join(os.path.dirname(episode["path"]), f"{stem}-thumb"), "tv_episodes", episode.get("artwork") or {}
    if kind == "set":
        row = store.set_row(item_id)
        cfg = config.current()
        root = cfg.get("set_folder") or ""
        if not root:
            raise AppError("Choose a central set folder under Settings, Movie Sets")
        folder = sets.folder_for(root, row.get("name") or "set")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, art_kind), "movie_sets", row.get("artwork") or {}
    raise AppError("Unknown item type")


def _tmdb(client, cfg):
    from curator.scrapers.tmdb import Tmdb

    return Tmdb(client, cfg["tmdb_key"], cfg.get("language") or "en-US", cfg.get("country") or "US")
