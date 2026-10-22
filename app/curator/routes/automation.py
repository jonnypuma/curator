import hmac
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from curator import automation, env, ingest, kodi_sources, notify, outbound
from resonance.errors import AppError

logger = logging.getLogger(__name__)
router = APIRouter()


def _key_ok(request: Request):
    expected = env.load().api_key
    if not expected:
        raise AppError("Webhooks are off until CMM_API_KEY is set in docker-compose", 503)
    provided = (request.headers.get("x-curator-key") or request.query_params.get("apikey")
                or request.query_params.get("key") or "")
    if not hmac.compare_digest(expected.encode(), provided.strip().encode()):
        raise AppError("The apikey on the webhook address was not accepted", 401)


@router.post("/webhooks/arr")
async def arr_webhook(request: Request):
    """Radarr, Sonarr, Bazarr and Lidarr post here. The key goes in ?apikey=."""
    _key_ok(request)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise AppError("The webhook body is not JSON", 400) from exc
    if not isinstance(payload, dict):
        raise AppError("The webhook body is not a JSON object", 400)
    return await run_in_threadpool(ingest.accept, payload)


@router.get("/queue/status")
def queue_status():
    from curator import arr_queue, library_queue

    data = ingest.snapshot()
    try:
        data["arr"] = arr_queue.snapshot()
    except Exception:
        data["arr"] = []
    try:
        data["library"] = library_queue.snapshot()
    except Exception:
        data["library"] = []
    return {**data, "items": ingest.items()}


@router.get("/queue/events")
def queue_events(limit: int = 100):
    from curator import work_log

    cap = max(1, min(limit, 500))
    scans, arr, library = [], [], []
    try:
        scans = work_log.recent("scan", cap)
        arr = work_log.recent("arr", cap)
        library = work_log.recent("library", cap)
    except Exception:
        logger.exception("could not read the scan or ARR history")
    return {"events": ingest.recent(cap), "scans": scans, "arr": arr, "library": library}


@router.post("/queue/flush")
def queue_flush():
    if not ingest.force_flush():
        raise AppError("The queue is empty", 409)
    return {"ok": True}


class LibraryUpdate(BaseModel):
    kind: str
    ids: list[str] = []
    players: list[str] = []


def _library_names(players):
    labels = {"kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex"}
    names = [labels.get(name, name) for name in players]
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


@router.post("/library/arr-rescan")
def library_arr_rescan(body: LibraryUpdate):
    """Ask Radarr, Sonarr or Lidarr to rescan the chosen movies, shows or artists."""
    from resonance import db, lidarr
    from curator import radarr, sonarr

    kind = (body.kind or "").strip().lower()
    ids = []
    for item in body.ids or []:
        try:
            ids.append(str(uuid.UUID(str(item))))
        except (ValueError, AttributeError):
            continue
    if kind not in {"movie", "show", "artist"} or not ids:
        raise AppError("Choose a movie, a TV show, or an artist", 400)
    sent = 0
    if kind == "movie":
        app, noun = "Radarr", "movie"
        rows = db.fetchall("SELECT tmdb_id FROM movies WHERE id = ANY(%s::uuid[])", (ids,))
        sent = sum(1 for row in rows if str(row.get("tmdb_id") or "").strip() and radarr.rescan_movie(tmdb_id=str(row["tmdb_id"]).strip()))
    elif kind == "show":
        app, noun = "Sonarr", "show"
        rows = db.fetchall("SELECT tvdb_id FROM tv_shows WHERE id = ANY(%s::uuid[])", (ids,))
        sent = sum(1 for row in rows if str(row.get("tvdb_id") or "").strip() and sonarr.rescan_series(tvdb_id=str(row["tvdb_id"]).strip()))
    else:
        app, noun = "Lidarr", "artist"
        rows = db.fetchall("SELECT musicbrainz_artist_id AS mbid FROM artists WHERE id = ANY(%s::uuid[])", (ids,))
        seen = set()
        notes = []
        for row in rows:
            mbid = str(row.get("mbid") or "").strip()
            if mbid and mbid not in seen:
                seen.add(mbid)
                info = lidarr.rescan_artist(artist_mbid=mbid, strict=True)
                if info:
                    sent += 1
                    if isinstance(info, dict):
                        notes.append(info)
    total = len(rows)
    if not sent:
        return {"sent": 0, "message": f"{app} has none of the selected {noun}s, or {app} is not set up."}
    plural = "" if sent == 1 else "s"
    skipped = f" {total - sent} not found in {app}." if total > sent else ""
    where = ""
    if app == "Lidarr" and notes:
        ahead = sorted({name for info in notes for name in info.get("ahead", [])})
        if ahead:
            where = f" It is queued behind {len(ahead)} other task{'s' if len(ahead) != 1 else ''} ({', '.join(ahead[:4])}), so it may take a while to start."
        elif all(info.get("status") == "started" for info in notes):
            where = " Lidarr has started on it."
        else:
            where = " It is first in Lidarr's queue."
        where += " Lidarr then fetches fresh artist data before it rescans the folder."
    return {"sent": sent, "message": f"{app} was asked to rescan {sent} {noun}{plural}.{skipped}{where}"}


@router.post("/library/update")
def library_update(body: LibraryUpdate):
    """Queue a movie, TV, or music folder scan on the players the user picked."""
    import posixpath
    from curator import library_queue
    from resonance import db

    kind = (body.kind or "").strip().lower()
    if kind not in {"movie", "show", "artist", "album", "music"}:
        raise AppError("Choose a movie, a TV show, or an artist", 400)
    ids = []
    for item in body.ids or []:
        try:
            ids.append(str(uuid.UUID(str(item))))
        except (ValueError, AttributeError):
            continue
    if not ids:
        raise AppError("Choose a movie, a TV show, or an artist", 400)
    if kind == "movie":
        rows = db.fetchall("SELECT title, path, folder FROM movies WHERE id = ANY(%s::uuid[])", (ids,))
        pairs = [(row.get("folder") or row.get("path"), row.get("title")) for row in rows]
        media = "movies"
    elif kind == "show":
        rows = db.fetchall("SELECT title, path FROM tv_shows WHERE id = ANY(%s::uuid[])", (ids,))
        pairs = [(row.get("path"), row.get("title")) for row in rows]
        media = "tv"
    elif kind in {"artist", "music"}:
        rows = db.fetchall("SELECT name AS title, path FROM artists WHERE id = ANY(%s::uuid[])", (ids,))
        pairs = [(row.get("path"), row.get("title")) for row in rows]
        media = "music"
    else:
        rows = db.fetchall(
            """
            SELECT al.title, al.path, ar.path AS artist_path, ar.name AS artist_name
            FROM albums al
            LEFT JOIN artists ar ON ar.id = al.artist_id
            WHERE al.id = ANY(%s::uuid[])
            """,
            (ids,),
        )
        pairs = []
        for r in rows:
            f = r.get("artist_path") or (posixpath.dirname(r["path"]) if r.get("path") else None)
            pairs.append((f or r.get("path"), r.get("artist_name") or r.get("title")))
        media = "music"
    folders, titles = [], []
    for folder, title in pairs:
        if not folder or str(folder).startswith(("wanted://", "missing://")):
            continue
        if folder not in folders:
            folders.append(folder)
        if title and title not in titles:
            titles.append(title)
    if not folders:
        raise AppError("Those items have no folder to update", 400)
    _, cfg = automation.current()
    chosen, skipped = library_queue.pick_players(body.players, library_queue.enabled_players(cfg))
    if not chosen:
        raise AppError("Turn on a library under Settings, Integrations, and give it an address and a key.", 400)
    library_queue.queue_for(chosen, media, folders, False, "Library update", cfg, titles)
    message = f"Queued {_library_names(chosen)}."
    if skipped:
        message += f" {_library_names(skipped)} {'was' if len(skipped) == 1 else 'were'} left out."
    return {"queued": chosen, "skipped": skipped, "message": message}


class KodiLibrary(BaseModel):
    media: str


@router.post("/queue/kodi")
def queue_kodi_library(body: KodiLibrary):
    """Queue a Kodi scan of every mounted movie, TV, or music folder."""
    from curator import automation, folders
    from curator.library_queue import enqueue
    from curator.notify import _kodi_folder, _library_target, _skip_reason

    media = (body.media or "").strip().lower()
    if media not in {"movies", "tv", "music"}:
        raise AppError("Choose movies, TV, or music", 400)
    roots = folders.mounted(media)
    label = {"movies": "movie", "tv": "TV", "music": "music"}[media]
    if not roots:
        raise AppError(f"No {label} folders are mounted. Add one in Settings.", 400)
    _, cfg = automation.current()
    kind = "music" if media == "music" else "video"
    if not _library_target(cfg):
        raise AppError(_skip_reason(cfg, kind), 400)
    paths = []
    for root in roots:
        folder = _kodi_folder(root, cfg.get("kodi_paths") or [])
        if folder:
            paths.append(folder)
    if not paths:
        raise AppError("None of those folders have a Kodi path. Add one under Settings.", 400)
    title = f"Kodi {label} library update · {len(paths)} folder{'s' if len(paths) != 1 else ''}"
    enqueue("kodi", media, False, paths, False, title)
    skipped = len(roots) - len(paths)
    message = f"{title} queued."
    if skipped:
        message += f" {skipped} folder{'s' if skipped != 1 else ''} had no Kodi path."
    return {"queued": True, "folders": len(paths), "skipped": skipped, "message": message}


class ManualLibrary(BaseModel):
    player: str
    media: str = ""
    action: str = "scan"


@router.post("/queue/library/manual")
def queue_manual_library(body: ManualLibrary):
    """Queue a library scan or a Kodi clean started from the queue window."""
    from curator import automation, folders
    from curator.library_queue import PLAYERS, enabled_players, enqueue, queue_for

    player = (body.player or "").strip().lower()
    action = (body.action or "scan").strip().lower()
    media = (body.media or "").strip().lower()
    if player not in PLAYERS:
        raise AppError("Choose Kodi, Emby, Jellyfin, Plex, or Navidrome", 400)
    _, cfg = automation.current()
    if player not in enabled_players(cfg):
        if player == "navidrome":
            raise AppError("Turn on Navidrome under Settings, Integrations, and set the address, user name, and password.", 400)
        raise AppError("Turn on that player under Settings, Integrations, and give it an address and a key.", 400)
    if action == "clean":
        if player != "kodi" or media not in {"video", "music"}:
            raise AppError("Only Kodi can clean a video or music library from here.", 400)
        stored = "music" if media == "music" else "video"
        enqueue("kodi", stored, False, [], False, f"Clean the Kodi {media} library", clean_only=True)
        return {"message": f"Kodi {media} library clean queued."}
    if player == "navidrome" and media != "music":
        raise AppError("Navidrome scans its music library.", 400)
    if media not in {"movies", "tv", "music"}:
        raise AppError("Choose movies, TV, or music", 400)
    roots = folders.mounted(media)
    label = {"movies": "movie", "tv": "TV", "music": "music"}[media]
    if not roots:
        raise AppError(f"No {label} folders are mounted. Add one in Settings.", 400)
    queued = queue_for([player], media, roots, False, "Manual library update", cfg)
    if not queued:
        raise AppError("That library update was not queued.", 400)
    name = {"kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex", "navidrome": "Navidrome"}[player]
    return {"message": f"{name} {label} library update queued."}


@router.post("/queue/clear")
def queue_clear():
    return ingest.clear()


@router.post("/queue/scans/clear")
def queue_clear_scans():
    from resonance import scan_queue

    return {"cleared": scan_queue.clear_waiting()}


@router.post("/queue/arr/clear")
def queue_clear_arr():
    from curator import arr_queue

    return {"cleared": arr_queue.clear_waiting()}


class LibraryRetry(BaseModel):
    id: str


@router.post("/queue/library/retry")
def queue_retry_library(body: LibraryRetry):
    from curator import library_queue
    from resonance import db

    try:
        key = str(uuid.UUID(body.id))
    except ValueError as exc:
        raise AppError("Unknown history item", 404) from exc
    row = db.fetchone(
        "SELECT source, event_type, path, outcome, message FROM work_events WHERE lane = 'library' AND id = %s",
        (key,),
    )
    if not row:
        row = db.fetchone(
            "SELECT source, event_type, path, outcome, message FROM ingest_events WHERE id = %s",
            (key,),
        )
    if not row:
        raise AppError("That history item is gone", 404)
    if row["outcome"] != "error":
        raise AppError("Only a failed library update can be retried", 400)
    label = library_queue.retry_logged(row["source"], row["message"], row["path"])
    if not label:
        raise AppError("This update has no folder to scan again", 400)
    return {"ok": True, "message": f"Queued again: {label}"}


@router.post("/queue/library/clear")
def queue_clear_library():
    from curator import library_queue

    return {"cleared": library_queue.clear_waiting()}


@router.delete("/queue/library/{item_id}")
def queue_drop_library(item_id: str):
    from curator import library_queue

    try:
        key = str(uuid.UUID(item_id))
    except ValueError as exc:
        raise AppError("Unknown queue item", 404) from exc
    status = library_queue.cancel(key)
    if status is None:
        raise AppError("That update is already gone", 404)
    return {"ok": True, "status": status}


@router.delete("/queue/arr/{item_id}")
def queue_drop_arr(item_id: str):
    from curator import arr_queue

    try:
        key = str(uuid.UUID(item_id))
    except ValueError as exc:
        raise AppError("Unknown queue item", 404) from exc
    if not arr_queue.drop(key):
        raise AppError("That item is already running or gone", 409)
    return {"ok": True}


@router.delete("/queue/scans/{item_id}")
def queue_drop_scan(item_id: str):
    from resonance import scan_queue

    if not scan_queue.drop(item_id):
        raise AppError("That scan is already running or gone", 409)
    return {"ok": True}


@router.post("/queue/scans/{item_id}/cancel")
def queue_cancel_scan(item_id: str):
    from resonance import scan_queue

    if not scan_queue.cancel(item_id):
        raise AppError("That scan is no longer running", 409)
    return {"ok": True}


@router.post("/queue/items/{item_id}/cancel")
def queue_cancel_item(item_id: str):
    try:
        key = str(uuid.UUID(item_id))
    except ValueError as exc:
        raise AppError("Unknown queue item", 404) from exc
    status = ingest.cancel(key)
    if status is None:
        raise AppError("That import is already gone", 404)
    return {"ok": True, "status": status}


@router.delete("/queue/items/{item_id}")
def queue_drop(item_id: str):
    try:
        key = str(uuid.UUID(item_id))
    except ValueError as exc:
        raise AppError("Unknown queue item", 404) from exc
    if not ingest.drop(key):
        raise AppError("That item is already running or gone", 409)
    return {"ok": True}


class TestBody(BaseModel):
    target: str
    url: str = ""
    user: str = ""
    secret: str = ""


class SourcesBody(BaseModel):
    xml: str = ""


class SourcesProbeBody(BaseModel):
    rows: list[dict] = []


@router.post("/notify/test")
def notify_test(body: TestBody):
    from resonance.connections import PLAYERS, clear, note

    name = PLAYERS.get(body.target, body.target)
    try:
        message = notify.test(body.target, {"url": body.url, "user": body.user, "secret": body.secret})
    except RuntimeError as exc:
        note(name, str(exc))
        raise AppError(str(exc), 502) from exc
    except Exception as exc:
        logger.warning("connection test %s failed", body.target, exc_info=True)
        note(name, f"The test failed: {exc}")
        raise AppError(f"The test failed: {exc}", 502) from exc
    clear(name)
    return {"message": message}


@router.post("/kodi/sources")
def kodi_sources_suggest(body: SourcesBody):
    try:
        return kodi_sources.suggest(body.xml)
    except ValueError as exc:
        raise AppError(str(exc), 400) from exc


@router.post("/kodi/sources/test")
def kodi_sources_test(body: SourcesProbeBody):
    try:
        return {"results": kodi_sources.probe(body.rows)}
    except RuntimeError as exc:
        raise AppError(str(exc), 502) from exc
    except Exception as exc:
        logger.warning("Kodi path probe failed", exc_info=True)
        raise AppError(f"The test failed: {exc}", 502) from exc


class OutboundTest(BaseModel):
    target: dict


@router.post("/outbound/test")
def outbound_test(body: OutboundTest):
    """Send a test message. Empty secret boxes use the ones already saved for the same target id."""
    from resonance import settings

    saved = settings.load().get("outbound") or []
    target = (outbound.keep_secrets([body.target], saved) or [{}])[0]
    try:
        return {"ok": True, "message": outbound.test(target)}
    except RuntimeError as exc:
        raise AppError(str(exc), 502) from exc


@router.get("/automation/info")
def automation_info():
    cfg = env.load()
    return {"webhook_key_set": bool(cfg.api_key), "env": automation.env_hints()}
