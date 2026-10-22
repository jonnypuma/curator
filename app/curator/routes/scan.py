import uuid
from fastapi import APIRouter
from pydantic import BaseModel

from curator import folders
from curator import scan_logs
from curator.video import scanner, store
from resonance import backup
from resonance.errors import AppError

router = APIRouter()


def _valid_uuid(val: str, label: str = "Item") -> str:
    try:
        return str(uuid.UUID(str(val)))
    except (ValueError, TypeError):
        raise AppError(f"That {label.lower()} is not in the library", 404)


class ScanBody(BaseModel):
    media: str
    mode: str = "incremental"
    roots: list[str] = []
    targets: list[str] = []
    verbose: bool = False


@router.post("/scan")
def start_scan(body: ScanBody):
    kind = folders.kind_for_media(body.media)
    if kind == "music":
        raise AppError("Music scans use /api/scan", 400)
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    from resonance import scan_queue

    roots = folders.choose(kind, body.roots)
    targets = [item for item in body.targets if isinstance(item, str) and item.strip()]
    outcome = scan_queue.submit({
        "media": kind,
        "mode": body.mode or "incremental",
        "kind": "library",
        "roots": roots,
        "targets": targets,
        "verbose": bool(body.verbose),
    })
    return {
        "started": outcome == "started",
        "queued": outcome in {"queued", "duplicate"},
        "duplicate": outcome == "duplicate",
        "scan": scanner.status(include_log=False),
        "scan_queue": scan_queue.snapshot(),
    }


class RescanBody(BaseModel):
    mode: str = "deep"


def _rescan_mode(value, episode=False):
    mode = value if value in ("incremental", "full", "deep") else "deep"
    if episode and mode == "incremental":
        return "deep"
    return mode


@router.post("/tv/seasons/{season_id}/rescan")
def rescan_season(season_id: str, body: RescanBody | None = None):
    """Read one season again. The rest of the show is not pruned or re-probed."""
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    valid_id = _valid_uuid(season_id, "season")
    season = store.season_row(valid_id)
    show = store.show_row(season["show_id"]) if season else None
    if not show:
        raise AppError("That season is not in the library", 404)
    from resonance import scan_queue

    number = int(season["season_number"])
    label = "Specials" if number == 0 else f"season {number}"
    mode = _rescan_mode(body.mode if body else "deep")
    word = {"incremental": "Incremental", "full": "Full", "deep": "Deep"}[mode]
    outcome = scan_queue.submit({
        "media": "tv",
        "mode": mode,
        "kind": "library",
        "roots": [show["root"]],
        "targets": [],
        "season_id": str(season["id"]),
        "label": f"{word} scan of {show['title']} {label}",
    })
    return {
        "started": outcome == "started",
        "queued": outcome in {"queued", "duplicate"},
        "duplicate": outcome == "duplicate",
        "scan": scanner.status(include_log=False),
        "scan_queue": scan_queue.snapshot(),
    }


@router.post("/tv/episodes/{episode_id}/rescan")
def rescan_episode(episode_id: str, body: RescanBody | None = None):
    """Read one episode file again. The rest of the show is not pruned or re-probed."""
    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    valid_id = _valid_uuid(episode_id, "episode")
    episode = store.episode_detail(valid_id)
    show = store.show_row(episode["show_id"]) if episode else None
    if not show or not episode.get("path"):
        raise AppError("That episode is not in the library", 404)
    from resonance import scan_queue

    code = f"S{int(episode['season_number']):02d}E{int(episode['episode_number']):02d}"
    mode = _rescan_mode(body.mode if body else "deep", episode=True)
    word = {"full": "Full", "deep": "Deep"}.get(mode, "Deep")
    outcome = scan_queue.submit({
        "media": "tv",
        "mode": mode,
        "kind": "library",
        "roots": [show["root"]],
        "targets": [],
        "episode_id": str(episode["id"]),
        "label": f"{word} scan of {show['title']} {code}",
    })
    return {
        "started": outcome == "started",
        "queued": outcome in {"queued", "duplicate"},
        "duplicate": outcome == "duplicate",
        "scan": scanner.status(include_log=False),
        "scan_queue": scan_queue.snapshot(),
    }


@router.get("/scan/status")
def scan_status(media: str | None = None):
    return scanner.status(media=media)


@router.post("/scan/cancel")
def cancel_scan():
    if not scanner.cancel():
        raise AppError("No movie or TV scan is running", 409)
    return scanner.status(include_log=False)


@router.post("/scan/cancel-import")
def cancel_import_scan():
    if not scanner.cancel_import():
        raise AppError("No webhook scan is running", 409)
    return scanner.status(include_log=False)


@router.get("/scan/logs")
def scan_log_list(media: str | None = None):
    return {"logs": scan_logs.list_logs(media=media)}


@router.get("/scan/logs/{name}")
def scan_log_text(name: str):
    return scan_logs.read_log(name)


@router.get("/folders")
def library_folders():
    return {kind: folders.mounted(kind) for kind in folders.KEYS}
