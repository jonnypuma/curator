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
from curator.video import activity, art_extra, art_pick, config, delete, exports, files, scanner, scrape, store
from resonance import backup
from resonance.errors import AppError

router = APIRouter()

TEXT = {"title", "name", "original_title", "sort_title", "tagline", "outline", "plot", "overview", "mpaa", "premiered", "aired",
        "show_status", "trailer", "edition", "original_language", "episode_order", "scrape_language"}
NUMBERS = {"year", "runtime_minutes", "top250", "votes", "display_season", "display_episode"}
DECIMALS = {"rating", "user_rating"}
SECONDS = {"resume_position", "resume_total"}
LISTS = {"genres", "countries", "studios", "tags", "directors", "writers", "producers", "languages"}
EDITABLE = {
    "movie": TEXT - {"name", "overview", "aired", "show_status", "episode_order"} | NUMBERS | DECIMALS | LISTS
            | {"source_format", "is_hybrid", "release_group", "set_name", "set_overview", "set"},
    "show": (TEXT - {"name", "overview", "aired", "edition"}) | {"year", "runtime_minutes", "votes", "top250", "original_language", "trailer"} | DECIMALS
            | {"genres", "countries", "studios", "tags", "directors"},
    "episode": {"title", "plot", "aired", "runtime_minutes", "mpaa", "votes", "rating", "user_rating", "directors", "writers",
                "scrape_language",
                "display_season", "display_episode", "resume_position", "resume_total",
                "source_format", "is_hybrid", "edition", "release_group"},
    "season": {"title", "season_name", "plot", "premiered", "year", "trailer"},
    "set": {"name", "overview"},
}


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise AppError("Unknown item", 404) from exc


def _ids(values):
    return [_uuid(item) for item in values][:5000]


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
    if scanner.running() or files.running():
        raise AppError("Wait for the running scan or file job to finish", 409)
    item_id = _uuid(body.id)
    try:
        peers = store.set_match(body.kind, item_id, body.source, source_id, body.ids)
    except ValueError as exc:
        raise AppError(f"{body.source} cannot match a {body.kind}", 400) from exc
    if peers is None:
        raise AppError("That item is locked or gone. Unlock it first.", 409)
    media = "movies" if body.kind == "movie" else "sets" if body.kind == "set" else "tv"
    if scrape.running():
        place = scrape.queue_fix(media, item_id)
        return {"started": False, "queued": place, "scrape": scrape.status(include_log=False), "peers": peers}
    if not scrape.start(media, "selected", [item_id], policy="overwrite", label="fix match"):
        place = scrape.queue_fix(media, item_id)
        return {"started": False, "queued": place, "scrape": scrape.status(include_log=False), "peers": peers}
    return {"started": True, "scrape": scrape.status(include_log=False), "peers": peers}


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
    if scanner.running() or scrape.running() or files.running():
        raise AppError("Wait for the running scan, scrape or file job to finish", 409)
    ids = [_uuid(item) for item in body.ids] if body and body.ids is not None else None
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


@router.post("/remove")
def remove_items(body: ItemsBody):
    if body.kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Unknown item type", 400)
    free, held = _without_busy(body.kind, _ids(body.ids))
    backup.snapshot_before("removing items", len(free))
    removed, peers = store.remove(body.kind, free) if free else ([], [])
    return {"removed": len(removed), "ids": removed, "busy": len(held), "peers": peers}


@router.post("/delete")
def delete_items(body: ItemsBody):
    if body.kind not in delete.KINDS:
        raise AppError("Unknown item type", 400)
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item to delete", 400)
    free, held = _without_busy(body.kind, ids)
    backup.snapshot_before("deleting items", len(free))
    result = delete.delete_items(body.kind, free) if free else {"deleted": [], "errors": [], "ids": []}
    for item_id in held:
        result["errors"].append(f"{delete.label(body.kind, item_id)}: {BUSY_ITEM}")
    return result


@router.post("/nfo")
def write_nfo(body: ItemsBody):
    cfg = config.current()
    ids = _ids(body.ids)
    written = 0
    try:
        if body.kind == "movie":
            for item_id in ids:
                written += 1 if exports.write_movie(item_id, cfg) else 0
        elif body.kind == "show":
            for item_id in ids:
                written += len(exports.write_show(item_id, cfg))
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
                written += len(exports.write_show(show_id, cfg, episode_ids=episode_ids))
        else:
            raise AppError("Unknown item type", 400)
    except OSError as exc:
        raise AppError(f"Could not write the .nfo: {exc}", 500) from exc
    return {"written": written}


class ArtBody(BaseModel):
    kind: str
    id: str


@router.post("/artwork/fetch")
def fetch_artwork(body: ArtBody):
    if body.kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork download works on a movie, show, season, episode or set", 400)
    if scanner.running() or scrape.running() or files.running():
        raise AppError("Wait for the running scan, scrape or file job to finish", 409)
    if body.kind in {"season", "episode", "set"}:
        art_pick_result = art_pick.download_missing(body.kind, _uuid(body.id))
        return {"started": False, "saved": bool(art_pick_result.get("saved")), "scrape": scrape.status(include_log=False)}
    media = "movies" if body.kind == "movie" else "tv"
    if not scrape.start(media, "selected", [_uuid(body.id)], policy="missing", label="artwork", art_only=True):
        raise AppError("A scrape is already running", 409)
    return {"started": True, "scrape": scrape.status(include_log=False)}


class ChoiceBody(BaseModel):
    url: str
    art_kind: str = "poster"


@router.get("/artwork/choices/{kind}/{item_id}")
def artwork_choices(kind: str, item_id: str):
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork choices work on a movie, show, season, episode or set", 400)
    try:
        return art_pick.choices(kind, _uuid(item_id))
    except Exception as exc:
        raise AppError(str(exc), 400) from exc


@router.post("/artwork/upload/{kind}/{item_id}")
async def upload_artwork(kind: str, item_id: str, file: UploadFile = File(...), art_kind: str = Form("poster")):
    """Use an image from the user's computer as this item's artwork."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    if file is None or not file.filename:
        raise AppError("Choose an image file", 400)
    data = await file.read(art_pick.MAX_UPLOAD_BYTES + 1)
    item = _uuid(item_id)
    return await run_in_threadpool(art_pick.choose_upload, kind, item, data, art_kind)


@router.get("/artwork/extra/{extra_id}")
def kept_artwork(extra_id: str):
    """An uploaded or replaced image kept in the data folder."""
    return FileResponse(art_extra.path_for(extra_id), headers={"Cache-Control": "private, no-cache"})


@router.delete("/artwork/{kind}/{item_id}/{art_kind}")
def remove_artwork(kind: str, item_id: str, art_kind: str):
    """Delete one artwork image of a movie, show, season, episode or set."""
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork works on a movie, show, season, episode or set", 400)
    return art_pick.remove(kind, _uuid(item_id), art_kind)


@router.post("/artwork/choices/{kind}/{item_id}")
def choose_artwork(kind: str, item_id: str, body: ChoiceBody):
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Artwork choices work on a movie, show, season, episode or set", 400)
    try:
        return art_pick.choose(kind, _uuid(item_id), body.url, body.art_kind)
    except Exception as exc:
        raise AppError(str(exc), 400) from exc



def _coerce(field, value):
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


@router.post("/ratings/{kind}/{item_id}")
def update_ratings(kind: str, item_id: str):
    if kind not in {"movie", "show", "episode"}:
        raise AppError("Ratings can be updated for a movie, a show or an episode", 400)
    if scrape.running() or scanner.running():
        raise AppError("Wait for the running scan or scrape to finish", 409)
    try:
        return scrape.refresh_ratings(kind, _uuid(item_id))
    except ScrapeError as exc:
        raise AppError(str(exc), 400) from exc


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
                if naming:
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
