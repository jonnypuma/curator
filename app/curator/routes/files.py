import os

from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _ids
from curator.video import files, reprobe, scanner
from resonance import backup
from resonance.errors import AppError

router = APIRouter()


class PatternBody(BaseModel):
    rename: dict[str, str] = {}


@router.post("/files/patterns")
def pattern_examples(body: PatternBody):
    from curator.video import renamer

    return renamer.examples(body.rename)


class FilesBody(BaseModel):
    op: str
    kind: str
    ids: list[str]


def _picked(body):
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item", 400)
    return ids


@router.post("/files/preview")
def preview_files(body: FilesBody):
    return files.preview(body.op, body.kind, _picked(body))


@router.post("/files/run")
def run_files(body: FilesBody):
    picked = _picked(body)
    if not files.running():
        backup.snapshot_before("a file job", len(picked))
    if not files.start(body.op, body.kind, picked):
        raise AppError("A file job is already running", 409)
    return {"started": True, "files": files.status(include_log=False)}


class MoveBody(BaseModel):
    media: str
    ids: list[str]
    dest: str


@router.post("/move/preview")
def preview_move(body: MoveBody):
    ids = _picked(body)
    if body.media == "music":
        from resonance import relocate as music_move

        return music_move.preview(ids, body.dest)
    from curator.video import relocate

    return relocate.preview(body.media, ids, body.dest)


@router.post("/move")
def start_move(body: MoveBody):
    from resonance import scan_queue

    ids = _picked(body)
    if body.media == "music":
        from resonance import relocate as music_move

        dest = music_move.destination(body.dest)
        noun = "artist"
    else:
        from curator.video import relocate

        if body.media not in {"movies", "tv"}:
            raise AppError("Move movies, TV shows, or artists", 400)
        dest = relocate.destination(body.media, body.dest)
        noun = "movie" if body.media == "movies" else "show"
    label = f"Move {len(ids)} {noun}{'' if len(ids) == 1 else 's'} to {os.path.basename(dest.rstrip('/')) or dest}"
    outcome = scan_queue.submit({"kind": "move", "media": body.media, "ids": ids, "dest": dest, "label": label})
    if outcome == "duplicate":
        raise AppError("That move is already queued", 409)
    return {"status": outcome, "scan_queue": scan_queue.snapshot(), "files": files.status(include_log=False)}


@router.get("/files/status")
def files_status():
    return files.status()


class MediaInfoBody(BaseModel):
    kind: str
    ids: list[str]


class SubtitleBody(BaseModel):
    kind: str
    id: str
    file: str
    lang: str = ""
    flags: list[str] = []


class DefaultTrackBody(BaseModel):
    kind: str
    id: str
    track: str
    index: int


class TrackLanguageBody(BaseModel):
    kind: str
    id: str
    track: str = "audio"
    index: int
    lang: str


@router.post("/tracks/language")
def track_language(body: TrackLanguageBody):
    """Set the language of one embedded audio or subtitle track of an MKV."""
    from curator.video import store, tracks

    if body.kind not in {"movie", "episode"}:
        raise AppError("The language is set on a movie or an episode", 400)
    if body.track not in {"audio", "subtitle"}:
        raise AppError("Choose an audio or subtitle track", 400)
    row_id = _ids([body.id])[0]
    detail = store.movie_detail(row_id) if body.kind == "movie" else store.episode_detail(row_id)
    if not detail:
        raise AppError("That item is not in the library any more", 404)
    file = detail.get("file") or {}
    video = file.get("path") or detail.get("path")
    if not video or not os.path.isfile(video):
        raise AppError("That item has no video file", 400)
    stored = file.get("audio_tracks") if body.track == "audio" else file.get("subtitle_tracks")
    code = tracks.set_language(video, body.track, body.index, stored or [], body.lang)
    result = reprobe.refresh(body.kind, [row_id])
    result["message"] = f"Language set to {code}."
    return result


@router.post("/subtitles")
def update_subtitle(body: SubtitleBody):
    from curator.video import config, exports, store, subtitles

    if body.kind not in {"movie", "episode"}:
        raise AppError("Subtitles are edited on a movie or an episode", 400)
    if scanner.running() or files.running():
        raise AppError("Wait for the running scan or file job to finish", 409)
    row_id = _ids([body.id])[0]
    detail = store.movie_detail(row_id) if body.kind == "movie" else store.episode_detail(row_id)
    if not detail:
        raise AppError("That item is not in the library any more", 404)
    video = (detail.get("file") or {}).get("path") or detail.get("path")
    if not video or not os.path.isfile(video):
        raise AppError("That item has no video file", 400)
    name = subtitles.retag(video, body.file, body.lang, body.flags, config.current().get("sub_lang_standard") or "iso639-2")
    cfg = config.current()
    if cfg.get("write_nfo"):
        try:
            if body.kind == "movie":
                exports.write_movie(row_id, cfg)
            else:
                exports.write_show(str(detail["show_id"]), cfg, episode_ids=[row_id])
        except (OSError, AppError):
            pass
    return {"ok": True, "file": name}


@router.post("/tracks/default")
def default_track(body: DefaultTrackBody):
    from curator.video import store, tracks

    if body.kind not in {"movie", "episode"}:
        raise AppError("Default tracks are set on a movie or an episode", 400)
    if body.track not in {"audio", "subtitle"}:
        raise AppError("Choose an audio or subtitle track", 400)
    row_id = _ids([body.id])[0]
    detail = store.movie_detail(row_id) if body.kind == "movie" else store.episode_detail(row_id)
    if not detail:
        raise AppError("That item is not in the library any more", 404)
    file = detail.get("file") or {}
    video = file.get("path") or detail.get("path")
    if not video or not os.path.isfile(video):
        raise AppError("That item has no video file", 400)
    stored = file.get("audio_tracks") if body.track == "audio" else file.get("subtitle_tracks")
    tracks.apply(video, body.track, body.index, stored or [])
    result = reprobe.refresh(body.kind, [row_id])
    result["message"] = "Default track saved."
    return result


@router.post("/mediainfo")
def update_mediainfo(body: MediaInfoBody):
    if scanner.running() or files.running():
        raise AppError("Wait for the running scan or file job to finish", 409)
    return reprobe.refresh(body.kind, _picked(body))


@router.post("/files/cancel")
def cancel_files():
    if not files.cancel():
        raise AppError("No file job is running", 409)
    return files.status(include_log=False)
