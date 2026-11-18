"""Online artwork choices for a movie, show, season, episode or set.

The swap button lists TMDB images. Choosing one writes it into the Kodi file name
and records that path on the item.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading

from urllib.parse import urlsplit

from curator.scrapers.fanart import Fanart
from curator.scrapers.http import Client, ScrapeError
from curator.video import art_extra, art_fetch, art_shape, config, naming, sets, store, writes
from resonance.errors import AppError

# How many images of one type to show from each provider.
_PER_SOURCE = 8
_KINDS = {
    "movie": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart",
              "extrafanart", "extrathumbs"),
    "show": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "characterart", "discart", "squareart",
             "extrafanart", "extrathumbs"),
    "season": ("poster", "banner", "landscape", "fanart"),
    "episode": ("thumb",),
    "set": ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart",
            "extrafanart"),
}
# Artwork that should carry no title or logo: fanart and character art. Clean ones are listed and suggested first.
CLEAN_KINDS = ("fanart", "characterart")
# Every fanart candidate can also be added to extrafanart/ (a new numbered file; nothing there is replaced).
_EXTRA_FANART = "extrafanart"
# The folders of numbered extra images: type -> (folder, file name prefix, the type whose candidates it offers).
# The same names the scrape writes (art_fetch.extras): extrafanart/fanartN, extrathumbs/thumbN from the landscapes.
EXTRAS = {"extrafanart": ("extrafanart", "fanart", "fanart"), "extrathumbs": ("extrathumbs", "thumb", "landscape")}


def extra_of(art_kind):
    """'extrafanart' for extrafanart3, 'extrathumbs' for extrathumbs2, else None."""
    text = str(art_kind or "")
    return next((name for name in EXTRAS if text.startswith(name)), None)
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


LOCAL_PREFIX = "local://"


def choose(kind, item_id, url, art_kind, players=None):
    """players: the players to update after the download (None: every enabled one, []: none)."""
    if str(url or "").startswith(art_extra.URL_PREFIX):
        # An image kept from an earlier upload or replacement.
        return asyncio.run(_choose(kind, item_id, "upload://kept", art_kind or "poster", art_extra.read_url(url), players))
    if str(url or "").startswith(LOCAL_PREFIX):
        # A numbered file next to the main one (poster2.jpg) becomes the main file. The old main file is kept, to pick
        # again; the numbered copy goes to the recycle bin, so the picture is not there twice.
        from resonance import trash

        real = _alternate_path(kind, item_id, art_kind or "poster", url[len(LOCAL_PREFIX):])
        try:
            with open(real, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise AppError(f"Could not read the file: {exc.strerror or exc}", 500) from exc
        result = asyncio.run(_choose(kind, item_id, "upload://kept", art_kind or "poster", data, players))
        try:
            trash.discard(real, label=f"{store.title_of(_TABLES.get(kind, 'movies'), item_id) or ''} — {art_kind}".strip(" —"),
                          kind="artwork", reason="Artwork replaced by a newer picture")
        except OSError:
            logging.getLogger(__name__).info("the numbered copy could not be removed: %s", real, exc_info=True)
        return result
    host = urlsplit(str(url or "")).hostname or ""
    if host not in _ART_HOSTS:
        raise AppError("Choose an image from the list")
    return asyncio.run(_choose(kind, item_id, url, art_kind or "poster", players=players))


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def choose_upload(kind, item_id, data, art_kind, players=None):
    """Save an image from the user's computer as this artwork kind, the same way a picked candidate is saved."""
    art_kind = str(art_kind or "").strip().lower()
    if art_kind not in _KINDS.get(kind, ()):
        raise AppError("Unknown artwork type for this item", 400)
    if not data:
        raise AppError("Choose an image file", 400)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("Artwork files must be 25 MB or smaller", 400)
    return asyncio.run(_choose(kind, item_id, "upload://local", art_kind, data, players))


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tbn"}


def remove(kind, item_id, art_kind, path=None):
    """Move the image file of this artwork type to the recycle bin and forget it. Only image files are removed.

    path: the exact file the card in the artwork window shows. The window lists extra fanart from the disk, so its
    numbering (extrafanart3) can differ from the one the last scan stored; the path is what was clicked. It must be
    inside the item's own folder."""
    from resonance import trash

    art_kind = str(art_kind or "").strip().lower()
    if not art_kind or not all(ch.isalnum() or ch in "_-" for ch in art_kind):
        raise AppError("Unknown artwork type for this item", 400)
    extra = extra_of(art_kind)
    base, table, existing = _destination(kind, item_id, "fanart" if extra else art_kind)
    current = dict(existing or {})
    folder = os.path.dirname(base)
    if path:
        real = os.path.realpath(str(path))
        known = {os.path.realpath(value) for key, value in current.items() if isinstance(value, str) and not str(key).startswith("_")}
        if real not in known and not (real.startswith(os.path.realpath(folder) + os.sep)):
            raise AppError("That file is not this item's artwork", 400)
        target = real
    else:
        target = current.get(art_kind)
    if not isinstance(target, str) or not target:
        raise AppError("There is no artwork of this type to remove", 404)
    removed = False
    if os.path.isfile(target):
        if os.path.splitext(target)[1].lower() not in IMAGE_EXTENSIONS:
            raise AppError("That file is not an image, so it was left alone", 400)
        try:
            trash.discard(target, label=f"{store.title_of(table, item_id) or ''} — {art_kind}".strip(" —"), kind="artwork", reason="Artwork deleted in the artwork window")
            removed = True
        except OSError as exc:
            raise AppError(f"Could not delete the file: {exc.strerror or exc}", 500) from exc
    sources = dict(current.get("_sources") or {})
    if extra:
        # Read extrafanart/ and extrathumbs/ again: the numbering follows the files that are left.
        from curator.video.artwork import apply_local_extras

        current = apply_local_extras(folder, {key: value for key, value in current.items() if not extra_of(key)})
        sources.pop(f"{extra}:{os.path.basename(target)}", None)
    else:
        for key, value in list(current.items()):
            if isinstance(value, str) and os.path.realpath(value) == os.path.realpath(target):
                current.pop(key, None)
                sources.pop(key, None)
    current["_sources"] = sources
    if table == "movie_sets":
        store.save_set_art(item_id, current, folder, None)
    else:
        store.set_artwork(table, item_id, current)
    return {"removed": True, "file_deleted": removed, "kind": art_kind, "path": target}


def undo(kind, item_id, players=None):
    """Put back the picture that was replaced last, of whatever type it was."""
    last = art_extra.last_replaced(kind, item_id)
    if not last:
        raise AppError("There is no replaced artwork to put back", 404)
    result = choose(kind, item_id, last["url"], last["kind"], players)
    return {**result, "restored": last["kind"]}


def remove_many(kind, item_id, items):
    """Move several artwork files of one item to the recycle bin: items are {"art_kind", "path"} as on the cards.
    Each one is checked like a single delete; one that fails is reported and the rest still go."""
    removed, failed = [], []
    for entry in items or []:
        art_kind = str((entry or {}).get("art_kind") or "")
        path = (entry or {}).get("path") or None
        try:
            removed.append(remove(kind, item_id, art_kind, path))
        except AppError as exc:
            failed.append({"art_kind": art_kind, "path": path or "", "error": str(exc)})
    return {"removed": len(removed), "failed": failed, "paths": [item.get("path") for item in removed]}


def choose_many(kind, item_id, picks, players=None):
    """Download several picked candidates, one after another: {"url", "art_kind"} each. Extra fanart and extrathumbs
    each add a new file. For a type that holds one file (poster, fanart…) the first pick becomes that file, the one the
    players use, and every further pick of that type is saved next to it as poster1, poster2… (players ignore those;
    the artwork window lists them, to make one the main file later). The players get one artwork refresh at the end."""
    seen = {}
    ordered = []
    for pick in picks or []:
        art_kind = str((pick or {}).get("art_kind") or "")
        url = str((pick or {}).get("url") or "")
        if not art_kind or not url:
            continue
        if art_kind in EXTRAS or art_kind not in seen:
            ordered.append((art_kind, url, False))
            seen[art_kind] = True
        else:
            ordered.append((art_kind, url, True))
    saved, failed = [], []
    with batched_player_art(players=players):
        for art_kind, url, numbered in ordered:
            try:
                saved.append(add_numbered(kind, item_id, url, art_kind) if numbered else choose(kind, item_id, url, art_kind))
            except AppError as exc:
                failed.append({"art_kind": art_kind, "url": url, "error": str(exc)})
    return {"saved": len(saved), "failed": failed, "paths": [item.get("path") for item in saved if item.get("path")]}


def add_numbered(kind, item_id, url, art_kind):
    """Save an online picture as the next poster1, poster2… next to the item's main file of that type."""
    host = urlsplit(str(url or "")).hostname or ""
    if host not in _ART_HOSTS:
        raise AppError("Choose an image from the list")
    if art_kind in EXTRAS or art_kind not in _KINDS.get(kind, ()):
        raise AppError("Unknown artwork type for this item", 400)
    return asyncio.run(_add_numbered(kind, item_id, url, art_kind))


async def _add_numbered(kind, item_id, url, art_kind):
    base, _table, _existing = _destination(kind, item_id, art_kind)
    number = _next_number(base)
    client = Client()
    try:
        path = await art_fetch.save_choice(client, url, f"{base}{number}", art_kind)
    finally:
        await client.close()
    return {"saved": True, "path": path, "kind": art_kind, "number": number}


def _next_number(base):
    """One past the highest N of base1.jpg, base2.png… in the folder (base is the path without an extension)."""
    import re

    folder, stem = os.path.dirname(base), os.path.basename(base)
    pattern = re.compile(rf"^{re.escape(stem)}(\d+)\.[A-Za-z0-9]+$", re.IGNORECASE)
    highest = 0
    try:
        names = os.listdir(folder) if os.path.isdir(folder) else []
    except OSError:
        names = []
    for name in names:
        match = pattern.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def alternates(kind, item_id):
    """{art type: [paths]} of the numbered files next to each main file of the item (poster1.jpg, poster2.jpg…)."""
    import re

    found = {}
    for art_kind in _KINDS.get(kind, ()):
        if art_kind in EXTRAS:
            continue
        try:
            base, _table, _existing = _destination(kind, item_id, art_kind)
        except AppError:
            continue
        folder, stem = os.path.dirname(base), os.path.basename(base)
        pattern = re.compile(rf"^{re.escape(stem)}(\d+)\.(?:jpe?g|png|webp)$", re.IGNORECASE)
        try:
            names = os.listdir(folder) if os.path.isdir(folder) else []
        except OSError:
            names = []
        paths = sorted(((int(pattern.match(name).group(1)), os.path.join(folder, name)) for name in names if pattern.match(name)))
        if paths:
            found[art_kind] = [path for _number, path in paths]
    return found


_TABLES = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes", "set": "movie_sets"}


def _alternate_path(kind, item_id, art_kind, path):
    """The real path of a numbered file of this item and type; any other path is refused."""
    real = os.path.realpath(str(path or ""))
    if real not in {os.path.realpath(found) for found in alternates(kind, item_id).get(art_kind, [])}:
        raise AppError("That file is not one of this item's pictures", 400)
    return real


def download_missing(kind, item_id):
    """Save the first listed image of each artwork type that is not on disk yet."""
    found = choices(kind, item_id)
    art = dict(found.get("artwork") or {})
    saved = False
    saved_kinds = []
    seen = set()
    listed = list(found.get("images") or [])
    listed.sort(key=lambda item: 0 if item.get("suggested") else 1)       # stable: else the listed order
    for item in listed:
        art_kind = item.get("kind")
        if not art_kind or art.get(art_kind) or art_kind in seen or item.get("banned") or item.get("wrong_shape"):
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


def extras_on(kind, cfg=None):
    """The extra image folders this item type uses. Extrathumbs are legacy: only when ticked in Settings."""
    names = [name for name in EXTRAS if name in _KINDS.get(kind, ())]
    if "extrathumbs" in names:
        settings = (cfg or config.current()).get("movie_art" if kind == "movie" else "tv_art") or {}
        if not settings.get("extrathumbs"):
            names.remove("extrathumbs")
    return names


async def _choices(kind, item_id):
    shown, _everything = await window_choices(kind, item_id)
    if "extrathumbs" in _KINDS.get(kind, ()) and "extrathumbs" not in extras_on(kind):
        # Extrathumbs are off: the window neither shows the files nor checks them against the candidates.
        shown["artwork"] = {key: value for key, value in shown["artwork"].items() if extra_of(key) != "extrathumbs"}
    await _mark_extra_in_use(shown)
    shown["alternates"] = alternates(kind, item_id)
    try:
        last = art_extra.last_replaced(kind, item_id)
    except Exception:           # the Undo button is a convenience: it must never stop the window from opening
        logging.getLogger(__name__).debug("could not look up the replaced artwork", exc_info=True)
        last = None
    shown["undo"] = last["kind"] if last else ""
    facts = _file_facts(shown["artwork"])
    facts.update(_file_facts({f"{art_kind}{index}": path for art_kind, paths in shown["alternates"].items()
                              for index, path in enumerate(paths, start=1)}))
    shown["artwork"] = {**shown["artwork"], "_info": facts}
    return shown


def _item_folder(kind, item_id):
    """The folder that holds a movie's or a show's own artwork and its extrafanart/, or "" when unknown."""
    try:
        if kind == "movie":
            return str((store.movie_row(item_id) or {}).get("folder") or "")
        if kind == "show":
            return str((store.show_row(item_id) or {}).get("path") or "")
        if kind == "set":
            return str((store.set_row(item_id) or {}).get("folder") or "")      # its folder in the central set folder
    except Exception:
        return ""
    return ""


def _file_facts(artwork):
    """For every artwork file on disk: width, height, file type and size, for the cards of the artwork window."""
    from curator.video.art_fetch import image_size

    facts = {}
    stored = (artwork or {}).get("_sizes") or {}
    for key, path in (artwork or {}).items():
        if str(key).startswith("_") or not isinstance(path, str):
            continue
        known = stored.get(path)
        if isinstance(known, list) and len(known) >= 4:
            # Kept with the artwork while the file is unchanged: no need to open it.
            facts[path] = {"width": int(known[0]), "height": int(known[1]), "bytes": int(known[3]),
                           "ext": os.path.splitext(path)[1].lstrip(".").upper()}
            continue
        if not os.path.isfile(path):
            continue
        size = image_size(path) or (0, 0)
        facts[path] = {"width": int(size[0] or 0), "height": int(size[1] or 0), "bytes": os.path.getsize(path),
                       "ext": os.path.splitext(path)[1].lstrip(".").upper()}
    return facts


_preview_marks = {}          # candidate preview url -> fingerprint, kept while Curator runs (at most 5000)


async def _mark_extra_in_use(shown):
    """Mark the extra fanart and extrathumbs candidates that are already in their folder: the picture a file was added
    from (its recorded source), or a file that is the same picture (fingerprint)."""
    for extra in EXTRAS:
        await _mark_one_extra(shown, extra)


async def _mark_one_extra(shown, extra):
    from curator.video import clean_fanart

    artwork = shown.get("artwork") or {}
    sources = artwork.get("_sources") or {}
    extras = [path for key, path in artwork.items()
              if isinstance(path, str) and extra_of(key) == extra and os.path.isfile(path)]
    rows = [row for row in shown.get("images") or [] if row.get("kind") == extra and row.get("url")]
    if not extras or not rows:
        return
    recorded = {url for key, url in sources.items() if str(key).startswith(f"{extra}:")}
    marks = [mark for mark in [await asyncio.to_thread(clean_fanart._fingerprint_file, path) for path in extras] if mark is not None]
    client = Client()
    try:
        for row in rows:
            if row["url"] in recorded:
                row["in_use"] = True
                continue
            preview = clean_fanart._preview(row["url"])
            if preview not in _preview_marks:
                if len(_preview_marks) > 5000:
                    _preview_marks.clear()
                _preview_marks[preview] = await clean_fanart._fingerprint_url(client, preview)
            theirs = _preview_marks[preview]
            if theirs is not None and any(clean_fanart._distance(theirs, mark) <= clean_fanart.REPEAT for mark in marks):
                row["in_use"] = True
    finally:
        await client.close()


async def window_choices(kind, item_id):
    """What the artwork window shows ({"title", "artwork", "images"} with Suggested and In use marked), and every
    online candidate before the window trims it. Clean fanart calls this too, so it takes the very card the window
    marks Suggested."""
    cfg = config.current()
    if not cfg.get("tmdb_key"):
        raise AppError("Add a TMDB API key under Settings, General, before searching artwork")
    client = Client()
    try:
        tmdb = _tmdb(client, cfg)
        images, artwork_map, title = await _images(tmdb, kind, item_id)
        images = _with_keyart(list(images or []), kind)
        images.extend(await _fanart_images(client, cfg, kind, item_id))
        images = _with_extra_fanart(images, kind, extras_on(kind, cfg))
    finally:
        await client.close()
    artwork_map = artwork_map or {}
    folder = _item_folder(kind, item_id)
    if folder and os.path.isdir(folder):
        # extrafanart/ as it is on disk now, not as the last scan recorded it.
        from curator.video.artwork import apply_local_extras

        artwork_map = apply_local_extras(folder, artwork_map)
    kept = [item for item in art_extra.listed(kind, item_id) if item["kind"] in (_KINDS.get(kind) or ())]
    shown = {"title": title, "artwork": artwork_map, "images": _mark_selected(_trim(images, kind), artwork_map) + kept}
    return shown, images


async def _choose(kind, item_id, url, art_kind, data=None, players=None):
    if art_kind in EXTRAS:
        return await _add_extra_fanart(kind, item_id, url, data, art_kind)
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
    queue_player_art(kind, item_id, {art_kind: path}, players)
    return {"saved": True, "path": path, "kind": art_kind}


# Kodi keeps a cached copy of every picture it has shown: a new fanart.jpg under the same name stays hidden behind it.
# Kodi art types that Curator writes under the same name (extra fanart is not one: Kodi has no entry for it).
PLAYER_ART = {"poster", "fanart", "banner", "clearlogo", "clearart", "landscape", "discart", "keyart", "characterart",
              "squareart"}


_art_batch = threading.local()
ART_BATCH = 100


@contextlib.contextmanager
def batched_player_art(players=None):
    """Inside this block queue_player_art collects the refreshes and hands them over ART_BATCH at a time (a job over
    the whole library must not rewrite the waiting queue job once per item). players: the players that were ticked
    (None: every enabled one); an empty list drops them all."""
    _art_batch.items = {"movies": [], "tv": []}
    _art_batch.players = None if players is None else list(players)
    try:
        yield
    finally:
        pending, _art_batch.items = _art_batch.items, None
        _flush_player_art(pending, _art_batch.players)
        _art_batch.players = None


def _flush_player_art(pending, players=None):
    from curator import library_queue

    if players is not None and not players:
        for items in (pending or {}).values():
            items.clear()
        return
    for media, items in (pending or {}).items():
        if not items:
            continue
        try:
            library_queue.queue_refresh(media, list(items), players=players)
        except Exception:
            logging.getLogger(__name__).exception("could not queue the artwork refresh for the players")
        items.clear()


def player_art_item(kind, item_id, art):
    """(media, refresh item) for an artwork-only refresh of one movie or show, or None."""
    art = {key: value for key, value in (art or {}).items() if key in PLAYER_ART and value}
    if art and kind == "set":
        row = store.set_row(item_id) or {}
        if not row.get("name"):
            return None
        return "movies", {"kind": "set", "title": row["name"], "label": row["name"],
                          "folder": row.get("folder") or os.path.dirname(next(iter(art.values()))), "art": art}
    if not art or kind not in ("movie", "show"):
        return None
    if kind == "movie":
        row = store.movie_row(item_id) or {}
        paths = store.movie_file_paths({**row, "file_path": row.get("file_path") or (row.get("file") or {}).get("path")})
        if not paths:
            return None
        return "movies", {"kind": "movie", "path": paths[0], "folder": row.get("folder") or os.path.dirname(paths[0]),
                          "label": row.get("title") or "", "art": art}
    row = store.show_row(item_id) or {}
    if not row.get("path"):
        return None
    return "tv", {"kind": "show", "folder": row["path"], "label": row.get("title") or "", "art": art}


def queue_player_art(kind, item_id, art, players=None):
    """Queue an artwork-only refresh of one movie or show on the players (library queue): Kodi forgets its cached copy
    of these pictures and points the item at the files; Plex, Emby and Jellyfin refresh the item. Never raises."""
    try:
        found = player_art_item(kind, item_id, art)
        if not found:
            return False
        media, item = found
        batch = getattr(_art_batch, "items", None)
        if batch is not None:
            chosen = getattr(_art_batch, "players", None)
            if chosen is not None and not chosen:
                return False
            batch[media].append(item)
            if len(batch[media]) >= ART_BATCH:
                _flush_player_art({media: batch[media]}, chosen)
            return True
        if players is not None and not players:
            return False
        from curator import library_queue

        queued, _skipped = library_queue.queue_refresh(media, [item], players=players)
        return bool(queued)
    except Exception:
        logging.getLogger(__name__).exception("could not queue the artwork refresh for the players")
        return False


async def _add_extra_fanart(kind, item_id, url, data=None, extra=_EXTRA_FANART):
    """Save a picked or uploaded image as the next extrafanart/fanartN (or extrathumbs/thumbN) of the item. Files
    already there stay."""
    if extra not in EXTRAS or extra not in _KINDS.get(kind, ()):
        raise AppError("This item has no extra fanart" if extra == _EXTRA_FANART else "This item has no extrathumbs", 400)
    dirname, prefix, _source = EXTRAS[extra]
    base, table, existing = _destination(kind, item_id, "fanart")
    folder = os.path.join(os.path.dirname(base), dirname)
    slot = _next_extra_slot(folder, prefix)
    target = os.path.join(folder, f"{prefix}{slot}")
    writes.ensure_dir(folder)
    if data is not None:
        try:
            path = await art_fetch.save_bytes(data, url, target, "fanart")
        except ScrapeError as exc:
            raise AppError("That file is not an image", 400) from exc
    else:
        client = Client()
        try:
            path = await art_fetch.save_choice(client, url, target, "fanart")
        finally:
            await client.close()
    from curator.video.artwork import apply_local_extras

    current = apply_local_extras(os.path.dirname(base), dict(existing or {}))
    if url and not str(url).startswith("upload://"):
        # Which online picture this extra fanart came from: the window marks it In use.
        current["_sources"] = {**(current.get("_sources") or {}), f"{extra}:{os.path.basename(path)}": url}
    if table == "movie_sets":
        store.save_set_art(item_id, current, os.path.dirname(base), None)
    else:
        store.set_artwork(table, item_id, current)
    return {"saved": True, "path": path, "kind": extra, "slot": slot}


def _next_extra_slot(folder, prefix="fanart"):
    """One past the highest fanartN (thumbN) in the folder, so a new extra image never overwrites one."""
    import re

    highest = 0
    try:
        names = os.listdir(folder) if os.path.isdir(folder) else []
    except OSError:
        names = []
    for name in names:
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)\.[A-Za-z0-9]+", name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _with_extra_fanart(images, kind, wanted=None):
    """The fanart candidates once more as extra fanart, and the landscapes as extrathumbs, for the items that have
    those folders. wanted: the extra folders in use (extras_on); None means every one the type has."""
    added = []
    for extra, (_folder, _prefix, source) in EXTRAS.items():
        if extra in _KINDS.get(kind, ()) and (wanted is None or extra in wanted):
            added += [{**item, "kind": extra} for item in images if item.get("kind") == source]
    return images + added


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
    sources = (artwork or {}).get("_sources") or {}
    for item in images:
        item["selected"] = False
        # The online picture the current file was downloaded from (a pick, an upload is not one): marked In use, so
        # what Clean fanart or a pick put there can be told apart from the suggestion.
        item["in_use"] = bool(item.get("url")) and sources.get(item.get("kind")) == item.get("url")
    return images


def _trim(images, kind):
    """Keep each artwork type, with a cap per provider so later types are not dropped."""
    order = _KINDS.get(kind) or ("poster", "fanart", "clearlogo")
    buckets = {name: [] for name in order}
    seen = {name: set() for name in order}
    counts = {}
    images = list(images or [])
    if config.current().get("fanart_textless", True):
        # Clean fanart (no language: no title on it) first, so the cap per source keeps it and the window shows it first.
        images.sort(key=lambda item: 0 if item.get("kind") not in CLEAN_KINDS or not item.get("lang") else 1)
    from curator.video import art_bans

    banned = art_bans.urls()
    # Banned pictures come last and do not count against the cap: they are shown (to be unbanned), never suggested.
    images.sort(key=lambda item: 1 if str(item.get("url") or "") in banned else 0)
    for item in images:
        name = item.get("kind") or ""
        url = item.get("url") or ""
        if name not in buckets or not url or url in seen[name]:
            continue
        source = item.get("source") or "tmdb"
        key = (name, source)
        is_banned = url in banned
        if not is_banned and counts.get(key, 0) >= _PER_SOURCE:
            continue
        seen[name].add(url)
        if not is_banned:
            counts[key] = counts.get(key, 0) + 1
        buckets[name].append({
            "banned": is_banned,
            "kind": name,
            "url": url,
            "preview": url.replace("/original/", "/w342/") if "/original/" in url else url,
            "width": item.get("width") or 0,
            "height": item.get("height") or 0,
            "score": item.get("score") or 0,
            "lang": item.get("lang") or "",
            "source": "Fanart.tv" if source == "fanart" else "TMDB",
            # A picture listed at another type's shape (a fanart among the posters): shown, never suggested.
            "wrong_shape": art_shape.wrong_item(name, item),
        })
    minimums = config.current().get("min_width") or {}
    trimmed = []
    for name in order:
        rows = buckets[name]
        if name not in EXTRAS:                 # extra images repeat the fanart or landscape list; no suggestion
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
    """The largest image that matches this type's shape. A wide-enough image wins a tie. A banned one never, nor one
    of the wrong shape (a fanart listed among the posters)."""
    rows = [row for row in rows if not row.get("banned") and not row.get("wrong_shape")]
    if not rows:
        return
    # Settings, Movies: clean fanart (no title on it) is suggested before a larger one with text.
    clean_first = kind in CLEAN_KINDS and config.current().get("fanart_textless", True)

    def rank(item):
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        wide = 1 if not minimum or width >= minimum else 0
        clean = 1 if clean_first and not item.get("lang") else 0
        return (clean, _shape_fit(item, kind), wide, width * height, float(item.get("score") or 0))

    winner = max(rows, key=rank)
    winner["suggested"] = True
    width, height = int(winner.get("width") or 0), int(winner.get("height") or 0)
    size = f"{width}×{height}" if width and height else "unknown size"
    if _shape_fit(winner, kind):
        reason = f"Largest {size} at this shape"
    else:
        reason = f"Largest {size}"
    if clean_first and not winner.get("lang"):
        reason = reason.replace("Largest", "Largest clean (no text)", 1)
    if minimum and width >= minimum:
        reason += f", at least {minimum} px wide"
    winner["suggestion_reason"] = reason


async def _images(tmdb, kind, item_id):
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        tmdb_id = row.get("tmdb_id")
        if not tmdb_id:       # nothing to offer from TMDB, but the item can still take an uploaded image
            return [], row.get("artwork") or {}, row.get("title") or ""
        data = await tmdb.movie(tmdb_id)
        return (data or {}).get("art") or [], row.get("artwork") or {}, row.get("title") or ""
    if kind == "show":
        row = store.show_row(item_id)
        if not row:
            raise AppError("Show not found", 404)
        if not row.get("tmdb_id"):
            return [], row.get("artwork") or {}, row.get("title") or ""
        data = await tmdb.tv(row["tmdb_id"])
        return (data or {}).get("art") or [], row.get("artwork") or {}, row.get("title") or ""
    if kind == "season":
        season = store.season_row(item_id)
        if not season:
            raise AppError("Season not found", 404)
        show = store.show_row(season["show_id"])
        data = await tmdb.season(show["tmdb_id"], season["season_number"]) if show.get("tmdb_id") else None
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
        images = []
        if show.get("tmdb_id"):
            images = await tmdb.episode_stills(show["tmdb_id"], episode["season_number"], episode["episode_number"])
        return images, episode.get("artwork") or {}, episode.get("title") or "Episode"
    if kind == "set":
        row = store.set_row(item_id)
        if not row:
            raise AppError("Set not found", 404)
        if not row.get("tmdb_collection_id"):
            return [], row.get("artwork") or {}, row.get("name") or ""
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
