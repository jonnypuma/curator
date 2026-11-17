import re
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from curator.scrapers.http import Client, ScrapeError
from curator.scrapers.omdb import Omdb
from curator.scrapers.tmdb import Tmdb
from curator.scrapers.trakt import TraktRatings
from curator.scrapers.tvdb import Tvdb
from curator import trakt as trakt_auth
from curator.video import activity, art_extra, art_pick, config, copies, delete, exports, files, scanner, scrape, store
from resonance import backup
from resonance.errors import AppError

router = APIRouter()

TEXT = {"title", "name", "original_title", "sort_title", "tagline", "outline", "plot", "overview", "mpaa", "premiered", "aired",
        "show_status", "trailer", "edition", "original_language", "episode_order", "scrape_language"}
NUMBERS = {"year", "runtime_minutes", "top250", "votes", "display_season", "display_episode", "season_number", "episode_number"}
DECIMALS = {"rating", "user_rating"}
SECONDS = {"resume_position", "resume_total"}
LISTS = {"genres", "countries", "studios", "tags", "directors", "writers", "producers", "languages"}
EDITABLE = {
    "movie": TEXT - {"name", "overview", "aired", "show_status", "episode_order"} | NUMBERS | DECIMALS | LISTS
            | {"source_format", "is_hybrid", "release_group", "set_name", "set_overview", "set", "ids"},
    "show": (TEXT - {"name", "overview", "aired", "edition"}) | {"year", "runtime_minutes", "votes", "top250", "original_language", "trailer"} | DECIMALS
            | {"genres", "countries", "studios", "tags", "directors", "ids"},
    "episode": {"ids", "season_number", "episode_number", "title", "plot", "aired", "runtime_minutes", "mpaa", "votes", "rating", "user_rating", "directors", "writers",
                "scrape_language",
                "display_season", "display_episode", "resume_position", "resume_total",
                "source_format", "is_hybrid", "edition", "release_group"},
    "season": {"title", "season_name", "plot", "premiered", "year", "trailer", "season_number"},
    "set": {"name", "overview"},
}


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise AppError("Unknown item", 404) from exc


# A batch can be as large as a whole library. Past this the request is refused, never silently cut short.
MAX_BATCH_IDS = 500000


def _ids(values):
    if len(values) > MAX_BATCH_IDS:
        raise AppError(f"Too many items in one request (limit {MAX_BATCH_IDS}).", 400)
    return [_uuid(item) for item in values]


def _primary_choice(value):
    if isinstance(value, dict):
        chosen = {}
        for level, source in value.items():
            name = str(source or "").strip().lower()
            if not name:
                continue
            if name not in scrape.PRIMARY_SOURCES:
                raise AppError(f"Unknown primary source {source}", 400)
            chosen[str(level)] = name
        return chosen or None
    name = str(value or "").strip().lower()
    if name and name not in scrape.PRIMARY_SOURCES:
        raise AppError(f"Unknown primary source {value}", 400)
    return name or None


def _media(value):
    media = "movies" if value in {"movies", "sets", "movie"} else "tv" if value in {"tv", "show", "shows"} else None
    if not media:
        raise AppError(f"Unknown library {value}", 400)
    return media


class ScrapeBody(BaseModel):
    media: str
    scope: str = "missing"
    ids: list[str] = []
    policy: str | None = None
    meta_policy: str | None = None
    art_policy: str | None = None
    rewrite_nfo: bool | None = None
    art_only: bool = False
    groups: list[str] | None = None
    fields: list[str] | None = None
    art: list[str] | None = None
    art_primary: dict[str, str] | None = None
    primary: str | dict[str, str] | None = None
    art_levels: list[str] | None = None


@router.post("/scrape")
def start_scrape(body: ScrapeBody):
    if body.media == "episodes":
        media = "episodes"
    elif body.media == "seasons":
        media = "seasons"
    elif body.media == "sets":
        media = "sets"
    else:
        media = _media(body.media)
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    if body.scope == "selected" and not body.ids:
        raise AppError("Pick at least one item to scrape", 400)
    if body.policy and body.policy not in config.POLICIES:
        raise AppError(f"Unknown overwrite policy {body.policy}", 400)
    for name, value in (("metadata", body.meta_policy), ("artwork", body.art_policy)):
        if value and value not in config.POLICIES:
            raise AppError(f"Unknown {name} overwrite policy {value}", 400)
    groups = None
    if body.groups is not None:
        groups = []
        for name in body.groups:
            if name not in scrape.SCRAPE_GROUPS:
                raise AppError(f"Unknown scrape choice {name}", 400)
            if name not in groups:
                groups.append(name)
        if not groups:
            raise AppError("Pick at least one thing to update", 400)
    primary = _primary_choice(body.primary)
    art_primary = {}
    for level, source in (body.art_primary or {}).items():
        name = str(source or "").strip().lower()
        if name and name not in {"fanart", "tmdb", "tvdb"}:
            raise AppError(f"Unknown artwork source {source}", 400)
        if name:
            art_primary[str(level)] = name
    from resonance import scan_queue

    label = "Episode scrape" if media == "episodes" else "Season scrape" if media == "seasons" else "Set scrape" if media == "sets" else ("Artwork" if body.art_only else "Scrape")
    outcome = scan_queue.submit({
        "kind": "scrape",
        "media": media,
        "scope": body.scope,
        "ids": _ids(body.ids),
        "policy": body.policy,
        "meta_policy": body.meta_policy,
        "art_policy": body.art_policy,
        "rewrite_nfo": body.rewrite_nfo,
        "art_only": body.art_only,
        "art_levels": sorted(scrape.normalize_art_levels(body.art_levels) or []) if body.art_levels is not None else None,
        "groups": groups,
        "fields": body.fields,
        "art": body.art,
        "art_primary": art_primary or None,
        "primary": primary or None,
        "label": label,
    })
    place = scan_queue.depth()
    if outcome == "started":
        return {"started": True, "queued": False, "place": place, "scrape": scrape.status(include_log=False),
                "scan_queue": scan_queue.snapshot()}
    return {
        "started": False,
        "queued": True,
        "duplicate": outcome == "duplicate",
        "place": place,
        "scrape": scrape.status(include_log=False),
        "scan_queue": scan_queue.snapshot(),
    }


@router.get("/scrape/status")
def scrape_status():
    return scrape.status()


@router.post("/scrape/cancel")
def cancel_scrape():
    if not scrape.cancel():
        raise AppError("No scrape is running", 409)
    return scrape.status(include_log=False)


@router.get("/match/search")
async def match_search(media: str, query: str, year: int | None = None, source: str = "tmdb"):
    is_set = media in {"set", "sets"}
    if not is_set:
        media = _media(media)
    query = query.strip()
    if not query:
        raise AppError("Type a title to search for", 400)
    cfg = await run_in_threadpool(config.current)
    client = Client()
    movie = media == "movies"
    try:
        if is_set:
            if source != "tmdb":
                raise AppError("Movie sets are matched against TMDB collections", 400)
            scraper = Tmdb(client, cfg["tmdb_key"], cfg["language"], cfg["country"])
            hits = await scraper.search_collection(query)
        elif source == "tvdb":
            scraper = Tvdb(client, cfg["tvdb_key"], cfg["language"])
            hits = await (scraper.search_movie(query, year) if movie else scraper.search_tv(query, year))
        elif source == "omdb":
            hits = await Omdb(client, cfg["omdb_key"]).search(query, year, "movie" if movie else "series")
        elif source == "trakt":
            hits = await TraktRatings(client, trakt_auth.client_id()).search(query, year, "movie" if movie else "show")
        elif source == "tmdb":
            scraper = Tmdb(client, cfg["tmdb_key"], cfg["language"], cfg["country"])
            hits = await (scraper.search_movie(query, year) if movie else scraper.search_tv(query, year))
        else:
            raise AppError(f"{source} cannot search {media}", 400)
    except ScrapeError as exc:
        raise AppError(str(exc), 502) from exc
    finally:
        await client.close()
    return {"results": hits[:30]}


class MatchBody(BaseModel):
    kind: str
    id: str
    source: str
    source_id: str
    ids: dict[str, str] | None = None


def _match_id_ok(source, source_id):
    if source == "omdb":
        return bool(re.fullmatch(r"tt\d{5,}", source_id, re.I))
    return source in {"tmdb", "tvdb", "trakt"} and source_id.isdigit()


@router.post("/match")
def apply_match(body: MatchBody):
    if body.kind not in {"movie", "show", "set"}:
        raise AppError("Fix Match works on movies, shows and sets", 400)
    source_id = body.source_id.strip()
    if not _match_id_ok(body.source, source_id):
        raise AppError("That id does not look right", 400)
    item_id = _uuid(body.id)
    media = "movies" if body.kind == "movie" else "sets" if body.kind == "set" else "tv"
    if scanner.running() or files.running():
        # A scan or file job is running: the match waits in the queue with the scrape, and is applied when its turn comes.
        from resonance import scan_queue

        outcome = scan_queue.submit({
            "kind": "scrape", "media": media, "scope": "selected", "ids": [item_id], "policy": "overwrite",
            "label": "Fix match",
            "match": {"kind": body.kind, "id": item_id, "source": body.source, "source_id": source_id, "ids": body.ids},
        })
        return {"started": outcome == "started", "queued": max(1, scan_queue.depth()), "deferred": True,
                "scrape": scrape.status(include_log=False), "peers": {}}
    try:
        peers = store.set_match(body.kind, item_id, body.source, source_id, body.ids)
    except ValueError as exc:
        raise AppError(f"{body.source} cannot match a {body.kind}", 400) from exc
    if peers is None:
        raise AppError("That item is locked or gone. Unlock it first.", 409)
    from resonance import scan_queue

    # The shared queue, so a waiting Fix Match shows in the Jobs window like any other scrape.
    outcome = scan_queue.submit({
        "kind": "scrape", "media": media, "scope": "selected", "ids": [item_id], "policy": "overwrite",
        "label": "Fix match",
    })
    if outcome == "started":
        return {"started": True, "scrape": scrape.status(include_log=False), "peers": peers}
    return {"started": False, "queued": max(1, scan_queue.depth()), "scrape": scrape.status(include_log=False), "peers": peers}


class UndoMatchBody(BaseModel):
    kind: str
    id: str


@router.post("/match/undo")
def undo_match(body: UndoMatchBody):
    """Put a movie or show back the way it was before its last Fix Match (kept 7 days)."""
    from curator.video import match_undo

    if body.kind not in {"movie", "show"}:
        raise AppError("Undo Fix Match works on movies and shows", 400)
    return match_undo.undo(body.kind, _uuid(body.id))


@router.get("/match/pending")
def pending_matches(media: str = ""):
    """Movies and shows waiting for Apply match, with the folder each one came from."""
    items = store.pending_match_items()
    if media in {"movies", "tv"}:
        kind = "movie" if media == "movies" else "show"
        items = [item for item in items if item["kind"] == kind]
    return {"items": items}


class ApplyBody(BaseModel):
    ids: list[str] | None = None


@router.post("/match/apply")
def apply_pending_matches(body: ApplyBody | None = None):
    from resonance import scan_queue

    ids = [_uuid(item) for item in body.ids] if body and body.ids is not None else None
    if scan_queue.busy() or scrape.running():
        # Something else holds the library: this waits its turn in the Jobs window.
        outcome = scan_queue.submit({"kind": "action", "action": "apply_matches", "args": [ids], "label": "Apply match"})
        if outcome == "duplicate":
            raise AppError("Apply match is already queued", 409)
        return {"started": outcome == "started", "queued": max(1, scan_queue.depth()),
                "scrape": scrape.status(include_log=False)}
    if not scrape.apply_pending(ids):
        raise AppError("No unmatched movies or shows are waiting", 409)
    return {"started": True, "scrape": scrape.status(include_log=False)}


_PREF_META = ("tmdb", "tvdb", "omdb", "trakt")
_PREF_ART = ("fanart", "tmdb", "tvdb")
_PREF_KINDS = {"movie", "show", "season", "episode"}


def _pref_lists(kind):
    cfg = config.current()
    meta_chain = cfg["movie_sources"] if kind == "movie" else cfg["tv_sources"]
    art_chain = cfg["art_sources"] if kind == "movie" else (cfg.get("tv_art_sources") or cfg.get("art_sources") or [])
    sources = [name for name in meta_chain if name in _PREF_META]
    arts = [name for name in art_chain if name in _PREF_ART]
    if kind == "movie":
        if "tvdb" not in sources:
            sources.append("tvdb")
        if "tvdb" not in arts:
            arts.append("tvdb")
    return sources, arts


def _pref_kind(kind):
    if kind not in _PREF_KINDS:
        raise AppError("Custom scrapers work on a movie, show, season, or episode", 400)
    return kind


@router.get("/scrape/prefs")
def scrape_prefs(kind: str, id: str):
    kind = _pref_kind(kind)
    row = store.scrape_prefs(kind, _uuid(id))
    if not row:
        raise AppError("That item is not in the library", 404)
    sources, arts = _pref_lists(kind)
    payload = {
        "kind": kind,
        "source": row.get("preferred_source") or "",
        "art": row.get("preferred_art") or "",
        "sources": sources,
        "art_sources": arts,
    }
    if kind == "show":
        payload["episode_order"] = row.get("episode_order") or ""
        payload["orders"] = list(config.ORDERS)
    return payload


class PrefsBody(BaseModel):
    kind: str
    id: str
    source: str = ""
    art: str = ""
    episode_order: str | None = None


@router.put("/scrape/prefs")
def save_scrape_prefs(body: PrefsBody):
    kind = _pref_kind(body.kind)
    sources, arts = _pref_lists(kind)
    source = str(body.source or "").strip().lower()
    art = str(body.art or "").strip().lower()
    if source and source not in sources:
        raise AppError("That metadata provider is not enabled", 400)
    if art and art not in arts:
        raise AppError("That artwork provider is not enabled", 400)
    order = None
    if kind == "show":
        order = str(body.episode_order or "").strip().lower()
        if order and order not in config.ORDERS:
            raise AppError("Episode order is aired, dvd or absolute", 400)
        order = order or None
    if not store.save_scrape_prefs(kind, _uuid(body.id), source or None, art or None, order):
        raise AppError("That item is not in the library", 404)
    return {"saved": True}


class ItemsBody(BaseModel):
    kind: str
    ids: list[str]
    keep_copy: bool = False  # from the duplicate windows: an episode with a second file keeps that file


class LockBody(ItemsBody):
    locked: bool


@router.post("/lock")
def lock_items(body: LockBody):
    if body.kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Unknown item type", 400)
    store.set_lock(body.kind, _ids(body.ids), body.locked)
    return {"ok": True, "locked": body.locked}


BUSY_ITEM = "A running job is using this item. Wait until it moves on."


def _without_busy(kind, ids):
    """Leave out items a scan, scrape, or file job is writing right now."""
    free, held = activity.partition(kind, ids)
    if held and not free:
        raise AppError(BUSY_ITEM, 409)
    return free, held


def _split_extra_files(kind, values):
    """A second file of an episode is named file:<path>. Returns those names and the ordinary ids."""
    values = list(values or [])
    if kind != "episode":
        return [], values
    files = [item for item in values if str(item).startswith("file:")]
    return files, [item for item in values if not str(item).startswith("file:")]


def _note_removed(kind, removed, labels):
    """History lines for items removed from the library (the files stay). A big selection is one line."""
    from resonance import history

    if len(removed) > 50 or not labels:
        if removed:
            history.record("removed", f"{len(removed)} {kind} item{'s' if len(removed) != 1 else ''}", kind, "",
                           "Removed from the library. The files stay on disk.")
        return
    for item_id in removed:
        history.record("removed", labels.get(str(item_id)) or str(item_id), kind, "",
                       "Removed from the library. The files stay on disk.")


@router.post("/remove")
def remove_items(body: ItemsBody):
    if body.kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Unknown item type", 400)
    files, wanted = _split_extra_files(body.kind, body.ids)
    free, held = _without_busy(body.kind, _ids(wanted)) if wanted else ([], [])
    backup.snapshot_before("removing items", len(free) + len(files))
    promoted = {"ids": [], "peers": []}
    if body.kind == "episode" and body.keep_copy and free:
        # A two-part file is two episodes; the copy goes for both. An episode with a second file keeps that file.
        free = copies.with_sharing_episodes(free)
        keep = copies.with_extra_files(free)
        if keep:
            promoted = copies.drop_primary_file(keep, False)
            free = [item for item in free if str(item) not in keep]
    labels = {str(item): delete.label(body.kind, item) for item in free} if len(free) <= 50 else {}
    removed, peers = store.remove(body.kind, free) if free else ([], [])
    _note_removed(body.kind, removed, labels)
    peers = list(peers) + promoted["peers"]
    if files:
        extra = copies.drop_extra_files(files, False)
        removed = list(removed) + extra["ids"]
        peers = list(peers) + extra["peers"]
    return {"removed": len(removed) + len(promoted["ids"]), "ids": list(removed), "promoted": promoted["ids"], "busy": len(held), "peers": peers}


@router.post("/delete")
def delete_items(body: ItemsBody):
    if body.kind not in delete.KINDS:
        raise AppError("Unknown item type", 400)
    files, wanted = _split_extra_files(body.kind, body.ids)
    ids = _ids(wanted)
    if not ids and not files:
        raise AppError("Pick at least one item to delete", 400)
    free, held = _without_busy(body.kind, ids) if ids else ([], [])
    backup.snapshot_before("deleting items", len(free) + len(files))
    promoted = {"ids": [], "names": [], "errors": [], "peers": []}
    if body.kind == "episode" and body.keep_copy and free:
        # A two-part file is two episodes; the copy goes for both. An episode with a second file keeps that file.
        free = copies.with_sharing_episodes(free)
        keep = copies.with_extra_files(free)
        if keep:
            promoted = copies.drop_primary_file(keep, True)
            free = [item for item in free if str(item) not in keep]
    result = delete.delete_items(body.kind, free) if free else {"deleted": [], "errors": [], "ids": []}
    result["deleted"] = list(result["deleted"]) + promoted["names"]
    result["errors"] = list(result["errors"]) + promoted["errors"]
    result["peers"] = list(result.get("peers") or []) + promoted["peers"]
    result["promoted"] = promoted["ids"]
    if files:
        extra = copies.drop_extra_files(files, True)
        result["deleted"] = list(result["deleted"]) + extra["names"]
        result["errors"] = list(result["errors"]) + extra["errors"]
        result["ids"] = list(result.get("ids") or []) + extra["ids"]
        result["peers"] = list(result.get("peers") or []) + extra["peers"]
    for item_id in held:
        result["errors"].append(f"{delete.label(body.kind, item_id)}: {BUSY_ITEM}")
    if result["deleted"]:
        from curator import library_queue

        library_queue.request_clean("Clean after deleting files")
    return result


@router.post("/nfo")
def write_nfo(body: ItemsBody):
    cfg = config.current()
    ids = _ids(body.ids)
    written = 0
    report = {"shared": []}
    try:
        if body.kind == "movie":
            for item_id in ids:
                written += 1 if exports.write_movie(item_id, cfg) else 0
        elif body.kind == "show":
            for item_id in ids:
                written += len(exports.write_show(item_id, cfg, report=report))
        elif body.kind == "season":
            for item_id in ids:
                written += 1 if exports.write_season(item_id, cfg) else 0
        elif body.kind == "set":
            for item_id in ids:
                written += 1 if exports.write_set(item_id, cfg) else 0
        elif body.kind == "episode":
            shows = {}
            for item_id in ids:
                detail = store.episode_detail(item_id)
                if detail:
                    shows.setdefault(str(detail["show_id"]), []).append(item_id)
            for show_id, episode_ids in shows.items():
                written += len(exports.write_show(show_id, cfg, episode_ids=episode_ids, report=report))
        else:
            raise AppError("Unknown item type", 400)
    except OSError as exc:
        raise AppError(f"Could not write the .nfo: {exc}", 500) from exc
    return {"written": written, "shared": report["shared"]}


class ArtBody(BaseModel):
    kind: str
    id: str


@router.post("/artwork/fetch")
def fetch_artwork(body: ArtBody):
    if body.kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork download works on a movie, show, season, episode or set", 400)
    if body.kind in {"season", "episode", "set"}:
        art_pick_result = art_pick.download_missing(body.kind, _uuid(body.id))
        return {"started": False, "saved": bool(art_pick_result.get("saved")), "scrape": scrape.status(include_log=False)}
    from resonance import scan_queue

    media = "movies" if body.kind == "movie" else "tv"
    outcome = scan_queue.submit({
        "kind": "scrape", "media": media, "scope": "selected", "ids": [_uuid(body.id)], "policy": "missing",
        "label": "Artwork", "art_only": True,
    })
    if outcome == "started":
        return {"started": True, "scrape": scrape.status(include_log=False)}
    return {"started": False, "queued": max(1, scan_queue.depth()), "scrape": scrape.status(include_log=False)}


class ChoiceBody(BaseModel):
    url: str
    art_kind: str = "poster"
    players: list[str] | None = None     # the players to update after the download (None: every enabled one)


@router.get("/artwork/choices/{kind}/{item_id}")
def artwork_choices(kind: str, item_id: str):
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork choices work on a movie, show, season, episode or set", 400)
    try:
        return art_pick.choices(kind, _uuid(item_id))
    except Exception as exc:
        raise AppError(str(exc), 400) from exc


@router.post("/artwork/upload/{kind}/{item_id}")
async def upload_artwork(kind: str, item_id: str, file: UploadFile = File(...), art_kind: str = Form("poster"),
                         players: str | None = Form(None)):
    """Use an image from the user's computer as this item's artwork."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    if file is None or not file.filename:
        raise AppError("Choose an image file", 400)
    data = await file.read(art_pick.MAX_UPLOAD_BYTES + 1)
    item = _uuid(item_id)
    chosen = None if players is None else [name.strip().lower() for name in players.split(",") if name.strip()]
    return await run_in_threadpool(art_pick.choose_upload, kind, item, data, art_kind, chosen)


@router.get("/artwork/extra/{extra_id}")
def kept_artwork(extra_id: str):
    """An uploaded or replaced image kept in the data folder."""
    return FileResponse(art_extra.path_for(extra_id), headers={"Cache-Control": "private, no-cache"})


@router.delete("/artwork/{kind}/{item_id}/{art_kind}")
def remove_artwork(kind: str, item_id: str, art_kind: str, path: str | None = None):
    """Move one artwork image of a movie, show, season, episode or set to the recycle bin. path: the exact file."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    return art_pick.remove(kind, _uuid(item_id), art_kind, path)


class ManyChoicesBody(BaseModel):
    picks: list[dict] = []               # {"url", "art_kind"} each
    players: list[str] | None = None


class ManyRemoveBody(BaseModel):
    items: list[dict] = []               # {"art_kind", "path"} each, as on the cards


@router.post("/artwork/choices/{kind}/{item_id}/many")
def choose_many_artwork(kind: str, item_id: str, body: ManyChoicesBody):
    """Download several ticked candidates of one item, one after another."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork choices work on a movie, show, season, episode or set", 400)
    if not body.picks:
        raise AppError("Tick at least one image", 400)
    if len(body.picks) > 60:
        raise AppError("Tick at most 60 images at a time", 400)
    return art_pick.choose_many(kind, _uuid(item_id), body.picks, body.players)


class BanBody(BaseModel):
    url: str = ""
    art_kind: str = ""
    picks: list[dict] = []               # several at once: {"url", "art_kind"} each


@router.post("/artwork/ban/{kind}/{item_id}")
def ban_artwork(kind: str, item_id: str, body: BanBody):
    """Ban online pictures: never suggested, never picked by Clean artwork or a scrape."""
    from curator.video import art_bans

    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    picks = body.picks or ([{"url": body.url, "art_kind": body.art_kind}] if body.url else [])
    if not picks:
        raise AppError("Choose a picture to ban", 400)
    return art_bans.ban_many(picks[:60], kind, _uuid(item_id))


class UndoBody(BaseModel):
    players: list[str] | None = None


@router.post("/artwork/undo/{kind}/{item_id}")
def undo_artwork(kind: str, item_id: str, body: UndoBody):
    """Put back the artwork that was replaced last on this item."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    return art_pick.undo(kind, _uuid(item_id), body.players)


@router.post("/artwork/unban")
def unban_artwork(body: BanBody):
    from curator.video import art_bans

    if not body.url:
        raise AppError("Choose a picture to unban", 400)
    return art_bans.unban(body.url)


@router.post("/artwork/{kind}/{item_id}/remove-many")
def remove_many_artwork(kind: str, item_id: str, body: ManyRemoveBody):
    """Move several ticked artwork files of one item to the recycle bin."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    if not body.items:
        raise AppError("Tick at least one image", 400)
    return art_pick.remove_many(kind, _uuid(item_id), body.items)


@router.post("/artwork/choices/{kind}/{item_id}")
def choose_artwork(kind: str, item_id: str, body: ChoiceBody):
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork choices work on a movie, show, season, episode or set", 400)
    try:
        return art_pick.choose(kind, _uuid(item_id), body.url, body.art_kind, body.players)
    except Exception as exc:
        raise AppError(str(exc), 400) from exc



def _parse_ids(value):
    """Accept {"tmdb": "1"} or "tmdb=1, tvdb=2" and return a dict of known provider ids."""
    if isinstance(value, dict):
        pairs = list(value.items())
    else:
        pairs = []
        for part in re.split(r"[,;\n]", str(value or "")):
            if not part.strip():
                continue
            if "=" not in part:
                raise AppError(f"Write provider ids as tmdb=1022, tvdb=2405 ({part.strip()} has no =)", 400)
            key, _, val = part.partition("=")
            pairs.append((key, val))
    ids = {}
    for key, val in pairs:
        key = str(key).strip().lower()
        val = str(val if val is not None else "").strip()
        if not key:
            continue
        if key not in store.EDITABLE_ID_KEYS:
            raise AppError(f"Unknown provider {key}. Use: {', '.join(store.EDITABLE_ID_KEYS)}", 400)
        if val:
            if len(val) > 80 or re.search(r"\s", val):
                raise AppError(f"{key} id looks wrong", 400)
            ids[key] = val
    return ids


def _coerce(field, value):
    if field == "ids":
        return _parse_ids(value)
    if value is None or value == "":
        return [] if field in LISTS else None
    if field in LISTS:
        items = value if isinstance(value, list) else str(value).split(",")
        return [str(item).strip() for item in items if str(item).strip()][:100]
    if field in NUMBERS:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise AppError(f"{field.replace('_', ' ')} must be a whole number", 400) from exc
    if field == "is_hybrid" or field == "watched":
        return str(value).lower() in {"1", "true", "yes", "on"}
    if field == "release_group":
        text = str(value).strip()
        if len(text) > 40:
            raise AppError("Release group is at most 40 characters", 400)
        if re.search(r"[\\/]", text):
            raise AppError("Release group cannot contain a slash", 400)
        return text or None
    if field == "scrape_language":
        text = str(value).strip()
        if text and not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", text):
            raise AppError("Scrape language looks like en-US", 400)
        return text or None
    if field in SECONDS:
        try:
            number = round(float(value), 3)
        except (TypeError, ValueError) as exc:
            raise AppError(f"{field.replace('_', ' ')} must be a number of seconds", 400) from exc
        if number < 0:
            raise AppError(f"{field.replace('_', ' ')} cannot be negative", 400)
        return number
    if field in DECIMALS:
        try:
            number = round(float(value), 1)
        except (TypeError, ValueError) as exc:
            raise AppError(f"{field} must be a number", 400) from exc
        if not 0 <= number <= 10:
            raise AppError("Ratings go from 0 to 10", 400)
        return number
    return str(value).strip()[:20000]


class EditBody(BaseModel):
    fields: dict[str, Any]
    renumber_episodes: bool = True
    merge_seasons: bool = False


class RatingsOneBody(BaseModel):
    sources: list[str] | None = None


@router.get("/ratings/sources")
def rating_sources(kind: str = "movie"):
    """The sources a ratings update can use, and which of them are set up."""
    if kind not in {"movie", "show", "episode"}:
        raise AppError("Ratings can be updated for movies, shows or episodes", 400)
    return {"sources": scrape.rating_source_options(kind)}


@router.post("/ratings/{kind}/{item_id}")
def update_ratings(kind: str, item_id: str, body: RatingsOneBody | None = None):
    if kind not in {"movie", "show", "episode"}:
        raise AppError("Ratings can be updated for a movie, a show or an episode", 400)
    try:
        return scrape.refresh_ratings(kind, _uuid(item_id), body.sources if body else None)
    except ScrapeError as exc:
        raise AppError(str(exc), 400) from exc


class RatingsBody(BaseModel):
    kind: str
    ids: list[str]
    sources: list[str] | None = None
    rating_filter: dict | None = None


@router.post("/ratings")
def update_ratings_batch(body: RatingsBody):
    """Update the ratings of the picked movies, shows or episodes as one job. The local IMDb copy goes first."""
    media = {"movie": "movies", "show": "tv", "episode": "episodes"}.get(body.kind)
    if not media:
        raise AppError("Ratings can be updated for movies, shows or episodes", 400)
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item to update", 400)
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    from resonance import scan_queue

    try:
        picked = scrape.normalize_rating_sources(body.sources)
        narrowed = scrape.normalize_rating_filter(body.rating_filter)
    except ScrapeError as exc:
        raise AppError(str(exc), 400) from exc
    outcome = scan_queue.submit({
        "kind": "scrape",
        "media": media,
        "scope": "selected",
        "ids": ids,
        "ratings_only": True,
        "rating_sources": sorted(picked) if picked is not None else None,
        "rating_filter": narrowed,
        "label": "Ratings update",
    })
    place = scan_queue.depth()
    return {
        "started": outcome == "started",
        "queued": outcome != "started",
        "duplicate": outcome == "duplicate",
        "count": len(ids),
        "place": place,
        "scrape": scrape.status(include_log=False),
        "scan_queue": scan_queue.snapshot(),
    }


def _ask_sonarr(show_id):
    """Ask Sonarr to rescan a show after a merge, so it picks up the files and the two apps agree. Returns True when asked."""
    import threading

    show = store.show_row(show_id)
    tvdb = str((show or {}).get("tvdb_id") or "").strip()
    if not tvdb:
        return False
    from curator import sonarr

    url, key = sonarr._settings()
    if not url or not key:
        return False
    threading.Thread(target=lambda: sonarr.rescan_series(tvdb_id=tvdb), name="sonarr-rescan-after-merge", daemon=True).start()
    return True


@router.patch("/items/{kind}/{item_id}")
def edit_item(kind: str, item_id: str, body: EditBody):
    if kind not in EDITABLE:
        raise AppError("Unknown item type", 400)
    row_id = _uuid(item_id)
    values = {}
    for field, value in body.fields.items():
        if field not in EDITABLE[kind]:
            raise AppError(f"{field} cannot be edited here", 400)
        values[field] = _coerce(field, value)
    if values.get("episode_order") not in (None, *config.ORDERS):
        raise AppError("Episode order is aired, dvd or absolute", 400)
    if "title" in values and not values["title"] and kind != "episode":
        raise AppError("The title cannot be empty", 400)
    if "name" in values and not values["name"]:
        raise AppError("The title cannot be empty", 400)
    if not values:
        raise AppError("Nothing to save", 400)
    if kind == "season":
        row = store.db.fetchone("SELECT show_id, season_number, locked FROM tv_seasons WHERE id = %s", (row_id,))
        if not row:
            raise AppError("That season is not in the library any more", 404)
        if row["locked"]:
            raise AppError("This season is locked. Unlock it to edit.", 409)
        renumbered = None
        if "season_number" in values:
            new_number = values.pop("season_number")
            if new_number is None or new_number < 0:
                raise AppError("The season number must be 0 or more", 400)
            try:
                renumbered = store.renumber_season(row_id, new_number, body.renumber_episodes, body.merge_seasons)
            except ValueError as exc:
                raise AppError(str(exc), 409) from exc
        merged = bool(renumbered) and body.merge_seasons and not store.season_row(row_id)
        if merged:
            # The edited season was folded into another one and is gone: write the show and tell Sonarr.
            sonarr_asked = _ask_sonarr(row["show_id"])
            cfg = config.current()
            if cfg["write_on_edit"]:
                try:
                    exports.write_show(str(row["show_id"]), cfg)
                except (OSError, AppError) as exc:
                    return {"ok": True, "nfo_error": str(exc), "sonarr": sonarr_asked}
            return {"ok": True, "nfo": None, "sonarr": sonarr_asked}
        naming = "season_name" in values
        season_name = values.pop("season_name", None) if naming else None
        locked = list(values)
        if naming:
            locked.append("season_name")
        if values:
            store.save_season_meta(row_id, values)
        if locked:
            store.db.execute(
                "UPDATE tv_seasons SET locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))) WHERE id = %s",
                (locked, row_id),
            )
        if naming:
            store.merge_season_name(row["show_id"], row["season_number"], season_name)
        cfg = config.current()
        nfo = None
        if cfg["write_on_edit"]:
            try:
                nfo = exports.write_season(row_id, cfg)
                if naming or renumbered:
                    exports.write_show(str(row["show_id"]), cfg)
            except (OSError, AppError) as exc:
                return {"ok": True, "nfo_error": str(exc)}
        return {"ok": True, "nfo": nfo}
    file_values = {}
    for key in ("source_format", "is_hybrid", "release_group"):
        if key in values:
            file_values[key] = values.pop(key)
    if kind == "episode" and "edition" in values:
        file_values["edition"] = values.pop("edition")
    if kind == "movie" and "edition" in values:
        file_values["edition"] = values["edition"]
    table = store.table_for(kind)
    row = store.db.fetchone(f"SELECT locked FROM {table} WHERE id = %s", (row_id,))
    if not row:
        raise AppError("That item is not in the library any more", 404)
    if row["locked"]:
        raise AppError("This item is locked. Unlock it to edit.", 409)
    if file_values:
        store.update_item_file(kind, row_id, file_values)
    if kind == "episode" and "season_number" in values:
        new_number = values.pop("season_number")
        if new_number is None or new_number < 0:
            raise AppError("The season number must be 0 or more", 400)
        try:
            store.move_episode(row_id, new_number)
        except ValueError as exc:
            raise AppError(str(exc), 409) from exc
    if kind == "episode" and "episode_number" in values:
        new_number = values.pop("episode_number")
        if new_number is None or new_number < 0:
            raise AppError("The episode number must be 0 or more", 400)
        try:
            store.set_episode_number(row_id, new_number)
        except ValueError as exc:
            raise AppError(str(exc), 409) from exc
    if values:
        store.edit(kind, row_id, values)
    return _write_edit_nfo(kind, row_id)


def _write_edit_nfo(kind, row_id):
    cfg = config.current()
    if not cfg["write_on_edit"]:
        return {"ok": True, "nfo": None}
    try:
        if kind == "movie":
            nfo = exports.write_movie(row_id, cfg)
        elif kind == "show":
            nfo = exports.write_show(row_id, cfg)
        elif kind == "set":
            nfo = exports.write_set(row_id, cfg)
        else:
            detail = store.episode_detail(row_id)
            nfo = exports.write_show(str(detail["show_id"]), cfg, episode_ids=[row_id]) if detail else None
    except (OSError, AppError) as exc:
        return {"ok": True, "nfo_error": str(exc)}
    return {"ok": True, "nfo": nfo}


BATCH_FIELDS = {
    "movie": {"mpaa", "genres", "countries", "studios", "tags", "source_format", "edition", "is_hybrid", "scrape_language", "watched", "set_name"},
    "show": {"mpaa", "genres", "countries", "studios", "tags", "show_status", "original_language", "scrape_language", "episode_order"},
    "episode": {"mpaa", "scrape_language", "source_format", "edition", "is_hybrid", "watched"},
}


class BatchEditBody(BaseModel):
    ids: list[str] = []
    fields: dict[str, Any] = {}


@router.post("/items/{kind}/batch")
def edit_items(kind: str, body: BatchEditBody):
    """Write the same shared fields onto many items. Titles and other identity fields are refused."""
    if kind not in BATCH_FIELDS:
        raise AppError("Batch edit is for movies, shows, and episodes", 400)
    values = {}
    for field, value in body.fields.items():
        if field not in BATCH_FIELDS[kind]:
            raise AppError(f"{field} cannot be edited on a batch", 400)
        values[field] = _coerce(field, value)
    if values.get("episode_order") not in (None, *config.ORDERS):
        raise AppError("Episode order is aired, dvd or absolute", 400)
    watched = values.pop("watched", None)
    if not values and watched is None:
        raise AppError("Nothing to save", 400)
    updated = skipped = 0
    nfo_error = None
    previous = {}
    backup.snapshot_before("a batch edit", len(body.ids))
    wanted = list(values) + (["watched"] if watched is not None else [])
    getter = {"movie": store.movie_detail, "show": store.show_detail, "episode": store.episode_detail}[kind]
    for row_id in _ids(body.ids):
        table = store.table_for(kind)
        row = store.db.fetchone(f"SELECT locked FROM {table} WHERE id = %s", (row_id,))
        if not row or row["locked"]:
            skipped += 1
            continue
        try:
            before = getter(row_id) or {}
            if all(field in before for field in wanted):
                previous[str(row_id)] = {field: before[field] for field in wanted}
        except Exception:
            pass
        file_values = {}
        item_values = dict(values)
        for key in ("source_format", "is_hybrid", "release_group"):
            if key in item_values:
                file_values[key] = item_values.pop(key)
        if kind == "episode" and "edition" in item_values:
            file_values["edition"] = item_values.pop("edition")
        if kind == "movie" and "edition" in item_values:
            file_values["edition"] = item_values["edition"]
        if watched is not None:
            store.set_watched(kind, row_id, watched)
        if file_values:
            store.update_item_file(kind, row_id, file_values)
        if item_values:
            store.edit(kind, row_id, item_values)
        written = _write_edit_nfo(kind, row_id)
        if written.get("nfo_error") and not nfo_error:
            nfo_error = written["nfo_error"]
        updated += 1
    if not updated:
        raise AppError("Every selected item is locked or gone", 409)
    # Old values go back only when every edited field was read for every changed item; a partial undo would mislead.
    undo = previous if len(previous) == updated else {}
    return {"ok": True, "updated": updated, "skipped": skipped, "nfo_error": nfo_error, "previous": undo}


class UnlockBody(BaseModel):
    fields: list[str]


@router.post("/items/{kind}/{item_id}/lock-fields")
def lock_fields(kind: str, item_id: str, body: UnlockBody):
    if kind not in EDITABLE:
        raise AppError("Unknown item type", 400)
    store.lock_fields(kind, _uuid(item_id), [field for field in body.fields if field in EDITABLE[kind]])
    return {"ok": True}


@router.post("/items/{kind}/{item_id}/unlock-fields")
def unlock_fields(kind: str, item_id: str, body: UnlockBody):
    if kind not in EDITABLE:
        raise AppError("Unknown item type", 400)
    store.unlock_fields(kind, _uuid(item_id), [field for field in body.fields if field in EDITABLE[kind]])
    return {"ok": True}
