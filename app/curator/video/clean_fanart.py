"""Replace fanart that has a title or logo on it with a clean one (no language), for movies and shows.

Curator does not record where a scraped fanart came from, so the file on disk is matched against the online
pictures: first by its exact size (no download), then, when that is not enough, by a small fingerprint of the picture
compared with the previews of the candidates of that size. Fanart that matches a picture with text is replaced by the
best clean candidate. Fanart that matches a clean picture stays. Fanart that matches nothing online stays too, unless
`any_unknown` is set. A fanart you picked or uploaded in the artwork window, and a locked item, are never touched. The
replaced file is kept by the artwork window (art_extra), so it can be picked again there.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading

from curator.scrapers.http import Client, ScrapeError
from curator.video import art_fetch, art_pick, art_shape, config, look, store
from curator.video.art_fetch import image_size
from resonance.errors import AppError

logger = logging.getLogger(__name__)
_saved_hook = threading.local()         # on_saved of the running replace(): told the path of each picture written
# Not an artwork type: every artwork file of the item whose shape is wrong for its type (a fanart saved as the poster)
# gets the picture the artwork window marks Suggested, whatever its type.
WRONG_SHAPE = "wrongshape"
# Two pictures at most this far apart (1 - look.similarity) are the same picture.
SAME_PICTURE = round(1.0 - look.SAME, 2)


def replace(kind, item_id, cfg=None, log=None, any_unknown=False, suggested_only=False, art_types=None,
            on_saved=None, fill_missing=True):
    """Returns the folder whose artwork changed, or None. log gets one line per artwork type.

    art_types: the artwork types to look at (default fanart). Fanart follows the modes below; any other type gets the
    picture the artwork window marks Suggested when the current file is not already that picture.
    suggested_only: fanart too gets the suggested picture whenever the current one is not it, whatever its label (TMDB
    lists many backdrops with a title on them as having no language, so "clean" can lie)."""
    write = log or (lambda line: None)
    _saved_hook.callback = on_saved
    try:
        return asyncio.run(_replace(kind, item_id, cfg or config.current(), write, any_unknown, suggested_only,
                                    art_types, fill_missing))
    finally:
        _saved_hook.callback = None


def _uploaded(source):
    return source.startswith("upload://") or source.startswith("kept://") or source.startswith("/api/")


async def _replace(kind, item_id, cfg, write, any_unknown, suggested_only=False, art_types=None, fill_missing=True):
    row = (store.movie_row(item_id) if kind == "movie" else store.show_row(item_id) if kind == "show"
           else store.set_row(item_id) if kind == "set" else None)
    if not row:
        raise AppError("Item not found", 404)
    title = row.get("title") or row.get("name") or str(item_id)
    if row.get("locked"):
        write(f"{title}: locked, left alone")
        return None
    if kind == "set" and not cfg.get("set_folder"):
        # A set's artwork lives in the central set folder; without one there is nowhere to save it.
        write(f"{title}: no central set folder under Settings, Movie Sets, so its artwork has nowhere to go; left alone")
        return None
    allowed = [name for name in (*art_pick.CLEAN_KINDS, "extrafanart") if name in art_pick._KINDS.get(kind, ())]
    allowed.append(WRONG_SHAPE)
    types = [name for name in (art_types or ["fanart"]) if name in allowed]
    if not types:
        return None
    art = row.get("artwork") or {}
    sources = art.get("_sources") or {}
    below = []
    if WRONG_SHAPE in types:
        # Checked on disk first: an item whose artwork all has the right shape needs no online lookup for this.
        # A show also has its seasons' artwork and its episodes' thumbs checked.
        below = await asyncio.to_thread(wrong_below, kind, item_id)
        if not below and not await asyncio.to_thread(_checked, kind, item_id, art):
            write(f"{title}: every artwork file has the right shape")
            types = [name for name in types if name != WRONG_SHAPE]
            if not types:
                return None
    if all(_uploaded(str(sources.get(name) or "")) for name in types):
        write(f"{title}: {', '.join(types)} you uploaded or kept, left alone")
        return None
    if not cfg.get("tmdb_key"):
        raise AppError("Add a TMDB API key under Settings, General, first")
    # The artwork window's own list: the same call, the same trimming, the same Suggested mark.
    shown, images = await art_pick.window_choices(kind, item_id)
    folder = None
    for art_type in types:
        source = str(sources.get(art_type) or "")
        if _uploaded(source):
            write(f"{title}: {art_type} you uploaded or kept, left alone")
            continue
        if art_type == WRONG_SHAPE:
            saved = await _wrong_shapes(kind, item_id, title, art, shown, write, quiet=bool(below))
            for level, row_id, label, row_art in below:
                level_shown, _all = await art_pick.window_choices(level, row_id)
                saved = await _wrong_shapes(level, row_id, f"{title} {label}", row_art, level_shown, write) or saved
        elif art_type == "extrafanart":
            saved = await _extra_fanart(kind, item_id, title, images, write, cfg, fill_missing)
        else:
            saved = await _clean(kind, item_id, title, art, art_type, source, shown, images, write, any_unknown,
                                 suggested_only, fill_missing)
        folder = saved or folder
    return folder


# Two extra fanart files this close are the same picture at another size, crop or zoom, or from another site.
REPEAT = SAME_PICTURE
PREVIEW_LIMIT = 60


async def _extra_fanart(kind, item_id, title, images, write, cfg=None, fill_missing=False):
    """extrafanart/: a picture found more than once keeps its largest copy, and one that matches an online picture
    listed with a language (a title or logo on it) is swapped for a clean picture that is not there yet (or removed
    when there is none). Every file taken out goes to the recycle bin. fill_missing: then clean pictures that are not
    there yet are added, up to Maximum extra fanart (Settings). Returns the item folder when anything changed."""
    from curator.video import artwork as local_art
    from resonance import trash

    base, table, existing = art_pick._destination(kind, item_id, "fanart")
    item_folder = os.path.dirname(base)
    folder = os.path.join(item_folder, "extrafanart")
    paths = local_art._images_in(folder)
    if not paths and not fill_missing:
        write(f"{title}: no extra fanart")
        return None
    limit = max(1, min(20, int((cfg or {}).get("extrafanart_count") or 10)))
    local = []
    for path in paths:
        mark = await asyncio.to_thread(_fingerprint_file, path)
        size = await asyncio.to_thread(image_size, path) or (0, 0)
        local.append({"path": path, "mark": mark, "area": int(size[0]) * int(size[1])})
    label = f"{title} — extra fanart"
    # Repeats: the largest copy of each picture stays.
    kept, repeats = [], []
    for item in sorted(local, key=lambda entry: -entry["area"]):
        if item["mark"] is not None and any(other["mark"] is not None and _distance(item["mark"], other["mark"]) <= REPEAT
                                            for other in kept):
            repeats.append(item)
        else:
            kept.append(item)
    for item in repeats:
        await asyncio.to_thread(trash.discard, item["path"], label, "artwork")
    # Pictures with text, against the online fanart (their previews, fingerprinted once).
    from curator.video import art_bans

    online = art_bans.without_banned([item for item in images if item.get("kind") == "fanart" and item.get("url")
                                      and not art_shape.wrong_item("fanart", item)])[:PREVIEW_LIMIT]
    client = Client()
    swapped, dropped, written = 0, 0, []
    try:
        for item in online:
            item["_mark"] = await _fingerprint_url(client, _preview(item["url"]))
        main = existing.get("fanart") if isinstance(existing.get("fanart"), str) else ""
        main_mark = await asyncio.to_thread(_fingerprint_file, main) if main and os.path.isfile(main) else None
        taken = [entry["mark"] for entry in kept if entry["mark"] is not None] + ([main_mark] if main_mark is not None else [])
        spare = sorted((item for item in online if not item.get("lang") and item.get("_mark") is not None),
                       key=lambda item: (-(int(item.get("width") or 0) * int(item.get("height") or 0)),
                                         -float(item.get("score") or 0)))
        for entry in kept:
            if entry["mark"] is None:
                continue
            # First against the few pictures listed with a language; the clean ones only when one of those matches
            # (a copy with and one without the logo can both be online: the closer one decides).
            texted = [(_distance(entry["mark"], item["_mark"]), item) for item in online
                      if item.get("lang") and item.get("_mark") is not None]
            texted = [pair for pair in texted if pair[0] <= SAME_PICTURE]
            if not texted:
                continue
            closest_text = min(pair[0] for pair in texted)
            if any(_distance(entry["mark"], item["_mark"]) < closest_text for item in online
                   if not item.get("lang") and item.get("_mark") is not None):
                continue
            swap = next((item for item in spare if all(_distance(item["_mark"], mark) > REPEAT for mark in taken)), None)
            await asyncio.to_thread(trash.discard, entry["path"], label, "artwork")
            if swap is None:
                dropped += 1
                continue
            stem = os.path.splitext(entry["path"])[0]
            data = await client.download(swap["url"])
            path = await art_fetch.save_bytes(data, swap["url"], stem, "fanart")
            taken.append(swap["_mark"])
            written.append(path)
            swapped += 1
        added = 0
        if fill_missing:
            have = len(kept) - dropped
            for item in spare:
                if have >= limit:
                    break
                if any(_distance(item["_mark"], mark) <= REPEAT for mark in taken):
                    continue
                slot = art_pick._next_extra_slot(folder)
                await asyncio.to_thread(os.makedirs, folder, exist_ok=True)
                data = await client.download(item["url"])
                path = await art_fetch.save_bytes(data, item["url"], os.path.join(folder, f"fanart{slot}"), "fanart")
                taken.append(item["_mark"])
                written.append(path)
                added += 1
                have += 1
    finally:
        await client.close()
    if not repeats and not swapped and not dropped and not added:
        extra = "" if not fill_missing else f" (no clean picture left to add, or already {limit})"
        write(f"{title}: extra fanart is clean, {len(kept)} picture{'s' if len(kept) != 1 else ''}, no repeats{extra}")
        return None
    current = local_art.apply_local_extras(item_folder, dict(existing or {}))
    if table == "movie_sets":
        store.save_set_art(item_id, current, item_folder, None)
    else:
        store.set_artwork(table, item_id, current)
    callback = getattr(_saved_hook, "callback", None)
    for path in written:
        if callback:
            callback(path)
    parts = []
    if repeats:
        parts.append(f"{len(repeats)} repeat{'s' if len(repeats) != 1 else ''} moved to the recycle bin")
    if swapped:
        parts.append(f"{swapped} with text replaced by a clean picture")
    if dropped:
        parts.append(f"{dropped} with text moved to the recycle bin (no clean picture left to put there)")
    if added:
        parts.append(f"{added} missing clean picture{'s' if added != 1 else ''} added (up to {limit})")
    write(f"{title}: extra fanart, {', '.join(parts)}; {len(kept) - dropped + added} now")
    return item_folder


async def _save(kind, item_id, title, art_type, pick, current, write):
    # The download button's own save.
    saved = await art_pick._choose(kind, item_id, pick["url"], art_type)
    callback = getattr(_saved_hook, "callback", None)
    if callback and saved.get("path"):
        callback(saved["path"])
    size = f"{pick.get('width')}×{pick.get('height')}" if pick.get("width") else "?"
    write(f"{title}: {art_type} replaced with {_name(pick)} ({size}, {pick.get('source') or 'TMDB'}), the card the "
          f"artwork window marks Suggested" + ("" if current else " (it had none)"))
    return os.path.dirname(saved.get("path") or "") or None


async def _clean(kind, item_id, title, art, art_type, source, shown, images, write, any_unknown, suggested_only,
                 fill_missing=True):
    """Fanart or character art: the picture the window marks Suggested, by the chosen mode."""
    fanart = [item for item in images if item.get("kind") == art_type and item.get("url")]
    clean = [item for item in fanart if not item.get("lang")]
    pick = next((row for row in shown["images"] if row.get("kind") == art_type and row.get("suggested")), None)
    if not pick or pick.get("lang"):
        write(f"{title}: the artwork window suggests no clean {art_type}, left as it is")
        return None
    current = art.get(art_type) if isinstance(art.get(art_type), str) else ""
    if not (current and os.path.isfile(current)) and not fill_missing:
        write(f"{title}: no {art_type}, left without (Download missing clean pictures is off)")
        return None
    client = Client()
    try:
        if suggested_only and current and os.path.isfile(current):
            if source == pick["url"] or await _same_picture(client, current, pick):
                write(f"{title}: {art_type} is already the suggested picture ({_name(pick)})")
                return None
        elif current and os.path.isfile(current):
            if source:
                verdict = "clean" if any(item["url"] == source for item in clean) else (
                    "text" if any(item["url"] == source for item in fanart) else None)
            else:
                verdict = None
            if verdict is None:
                verdict = await _match(client, current, fanart)
            if verdict == "clean":
                write(f"{title}: {art_type} counts as clean (listed without a language), left as it is; choose "
                      f"Any picture that is not the suggested one to put {_name(pick)} there")
                return None
            if verdict == "unknown" and not any_unknown:
                write(f"{title}: {art_type} matches no picture online, left as it is")
                return None
    finally:
        await client.close()
    return await _save(kind, item_id, title, art_type, pick, current, write)


def wrong_below(kind, show_id, episode_ids=None):
    """For a show: its seasons and episodes with artwork of the wrong shape on disk, as
    [(level, row id, label, artwork)]. Locked seasons and episodes are left out. episode_ids: only these episodes
    (a scan checks the ones it read); None checks every one."""
    if kind != "show":
        return []
    from resonance import db

    found = []
    for row in db.fetchall("SELECT id::text AS id, season_number, artwork, locked FROM tv_seasons WHERE show_id = %s "
                           "ORDER BY season_number", (show_id,)):
        if not row.get("locked") and _checked("season", row["id"], row.get("artwork") or {}):
            label = "Specials" if row["season_number"] == 0 else f"season {row['season_number']}"
            found.append(("season", row["id"], label, row.get("artwork") or {}))
    if episode_ids is not None and not episode_ids:
        return found
    sql = ("SELECT id::text AS id, season_number, episode_number, artwork, locked FROM tv_episodes WHERE show_id = %s"
           + (" AND id = ANY(%s::uuid[])" if episode_ids is not None else "") + " ORDER BY season_number, episode_number")
    params = (show_id, list(episode_ids)) if episode_ids is not None else (show_id,)
    for row in db.fetchall(sql, params):
        if not row.get("locked") and _checked("episode", row["id"], row.get("artwork") or {}):
            label = f"S{int(row['season_number']):02d}E{int(row['episode_number']):02d}"
            found.append(("episode", row["id"], label, row.get("artwork") or {}))
    return found


def wrong_shapes(kind, art, learned=None):
    """The artwork types of an item whose file has the wrong shape: [(type, path, (width, height))].

    The sizes come from the artwork map ("_sizes", kept by every save). Only a file without a stored size is opened;
    learned, when given, gets its entry so the caller can store it (art_sizes.remember)."""
    from curator.video import art_sizes

    found = []
    for art_type in art_pick._KINDS.get(kind, ()):
        path = (art or {}).get(art_type)
        if art_type in art_pick.EXTRAS or not art_shape.judged(art_type) or not isinstance(path, str) or not path:
            continue
        size = art_sizes.size_of(art, path)
        if size is None:
            if not os.path.isfile(path):
                continue
            size = image_size(path)
            if size and learned is not None:
                stored = art_sizes.entry(path, size)
                if stored:
                    learned[path] = stored
        if size and art_shape.wrong(art_type, size):
            found.append((art_type, path, size))
    return found


def _checked(kind, row_id, art):
    """wrong_shapes for a row, storing the sizes it had to read."""
    from curator.video import art_sizes

    learned = {}
    found = wrong_shapes(kind, art, learned)
    if learned:
        art_sizes.remember(kind, row_id, learned)
    return found


async def _wrong_shapes(kind, item_id, title, art, shown, write, quiet=False):
    """Replace each artwork file of the wrong shape with the suggested picture of its type (always the right shape).
    kind: movie, show, season or episode. quiet: say nothing when all is well (the show, when a season is wrong)."""
    sources = (art or {}).get("_sources") or {}
    found = await asyncio.to_thread(wrong_shapes, kind, art)
    if not found:
        if not quiet:
            write(f"{title}: every artwork file has the right shape")
        return None
    folder = None
    for art_type, path, size in found:
        note = art_shape.describe(art_type, size)
        if _uploaded(str(sources.get(art_type) or "")):
            write(f"{title}: {art_type} has the wrong shape ({note}), but you uploaded or kept it, left alone")
            continue
        pick = next((row for row in shown["images"] if row.get("kind") == art_type and row.get("suggested")), None)
        if not pick:
            write(f"{title}: {art_type} has the wrong shape ({note}); no picture of the right shape was found online, "
                  f"left as it is")
            continue
        write(f"{title}: {art_type} has the wrong shape ({note})")
        folder = await _save(kind, item_id, title, art_type, pick, path, write) or folder
    return folder


def _name(item):
    return str((item or {}).get("url") or "").rsplit("/", 1)[-1]


def suggested(images, clean, kind):
    """The clean fanart the artwork window suggests for this item (the largest clean picture of the right shape), so
    the job takes the picture the user sees marked Suggested there. A higher TMDB vote does not count: a backdrop with
    the title on it is often uploaded without a language and voted up. None when the window suggests none."""
    by_url = {item["url"]: item for item in clean}
    for row in art_pick._trim(list(images), kind):
        if row.get("kind") == "fanart" and row.get("suggested") and not row.get("lang") and row.get("url") in by_url:
            return by_url[row["url"]]
    return None


async def _same_picture(client, path, item):
    """True when the file on disk is this online picture (its fingerprint against the candidate's preview)."""
    mine = await asyncio.to_thread(_fingerprint_file, path)
    theirs = await _fingerprint_url(client, _preview(item["url"]))
    return mine is not None and theirs is not None and _distance(mine, theirs) <= SAME_PICTURE


async def _match(client, path, fanart):
    """"clean", "text" or "unknown": which online fanart the file on disk is."""
    size = await asyncio.to_thread(image_size, path)
    # Only TMDB reports the real size of a picture; Fanart.tv candidates carry the nominal 1920×1080 of their type.
    same = [item for item in fanart
            if size and item.get("source") == "tmdb" and (item.get("width"), item.get("height")) == tuple(size)]
    fanart_tv = [item for item in fanart if item.get("source") != "tmdb"]
    if same and not fanart_tv and all(not item.get("lang") for item in same):
        return "clean"
    if same and all(item.get("lang") for item in same):
        return "text"
    # Mixed, no size match, or Fanart.tv pictures that may be the same size: compare the picture itself with the
    # previews (small downloads), the ones of the right size first.
    mine = await asyncio.to_thread(_fingerprint_file, path)
    if mine is None:
        return "unknown"
    pool = same + fanart_tv + [item for item in fanart if item not in same and item not in fanart_tv]
    best, best_distance = None, None
    for item in pool[:40]:
        theirs = await _fingerprint_url(client, _preview(item["url"]))
        if theirs is None:
            continue
        distance = _distance(mine, theirs)
        if best_distance is None or distance < best_distance:
            best, best_distance = item, distance
        if distance == 0:
            break
    if best is None or best_distance > SAME_PICTURE:
        return "unknown"
    return "text" if best.get("lang") else "clean"


def _preview(url):
    """A small copy of a candidate: TMDB w300, the Fanart.tv preview folder."""
    if "/t/p/original/" in url:
        return url.replace("/t/p/original/", "/t/p/w300/")
    if "assets.fanart.tv/fanart/" in url:
        return url.replace("assets.fanart.tv/fanart/", "assets.fanart.tv/preview/")
    return url


def _fingerprint(data_or_path):
    """A small grey copy of the picture for look.similarity (see curator/video/look.py), or None."""
    return look.prepare(data_or_path)


def _fingerprint_file(path):
    return _fingerprint(path)


async def _fingerprint_url(client, url):
    try:
        data = await client.download(url)
    except ScrapeError:
        return None
    return await asyncio.to_thread(_fingerprint, data)


def _distance(left, right):
    """0.0 for the same picture (resized, re-encoded, cropped or zoomed), up to 2.0 for unrelated ones."""
    return 1.0 - look.similarity(left, right)
