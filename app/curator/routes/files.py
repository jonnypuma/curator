import os

from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _ids
from curator.video import files, reprobe
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
    players: list[str] | None = None     # Clean fanart: the players to update afterwards (None: every enabled one)
    art_types: list[str] | None = None   # Replace artwork: the artwork types to replace (None: fanart)
    fill_missing: bool = True            # Clean artwork: also download missing clean pictures


def _picked(body):
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item", 400)
    return ids


class PlayerArtBody(BaseModel):
    kind: str
    ids: list[str] = []
    players: list[str] | None = None


@router.get("/players/art-targets")
def player_art_targets(media: str = "movies"):
    """The players an artwork refresh of movies or TV can go to, one box each in the windows."""
    from curator import library_queue

    return {"players": library_queue.art_players("tv" if media == "tv" else "movies")}


@router.post("/players/refresh-art")
def refresh_player_art(body: PlayerArtBody):
    """Show the current artwork of these movies or shows in the players without a rescan: Kodi forgets its cached
    copies and points each item at the files; Plex, Emby and Jellyfin refresh the items. One queue job per media."""
    from curator import library_queue
    from curator.video import art_pick, store

    if body.kind not in ("movie", "show"):
        raise AppError("Pick movies or shows", 400)
    items = []
    for item_id in _ids(body.ids):
        row = (store.movie_row(item_id) if body.kind == "movie" else store.show_row(item_id)) or {}
        art = {key: value for key, value in (row.get("artwork") or {}).items()
               if key in art_pick.PLAYER_ART and isinstance(value, str) and os.path.isfile(value)}
        found = art_pick.player_art_item(body.kind, item_id, art)
        if found:
            items.append(found[1])
    if not items:
        raise AppError("None of these have artwork files to show", 400)
    media = "movies" if body.kind == "movie" else "tv"
    if body.players is not None and not body.players:
        raise AppError("Tick at least one player", 400)
    queued, skipped = library_queue.queue_refresh(media, items, players=body.players)
    if not queued:
        raise AppError(" ".join(skipped) or "No player takes artwork refreshes for this library", 400)
    noun = ("movie" if body.kind == "movie" else "show") + ("" if len(items) == 1 else "s")
    return {"items": len(items), "players": queued, "skipped": skipped,
            "message": f"Artwork of {len(items)} {noun} queued for {', '.join(queued)}."}


@router.post("/files/preview")
def preview_files(body: FilesBody):
    return files.preview(body.op, body.kind, _picked(body))


@router.post("/files/run")
def run_files(body: FilesBody):
    from resonance import scan_queue

    picked = _picked(body)
    files._check_op(body.op, body.kind)
    label = f"{files.OPS[body.op]} {len(picked)} item{'' if len(picked) == 1 else 's'}"
    spec = {"kind": "files", "op": body.op, "media": body.kind, "ids": picked, "label": label}
    if body.players is not None:
        spec["players"] = [str(name).lower() for name in body.players]
    if body.art_types:
        spec["art_types"] = [str(name).lower() for name in body.art_types]
    if not body.fill_missing:
        spec["fill_missing"] = False
    outcome = scan_queue.submit(spec)
    if outcome == "duplicate":
        raise AppError("That file job is already queued", 409)
    return {"started": outcome == "started", "queued": max(1, scan_queue.depth()) if outcome != "started" else 0,
            "files": files.status(include_log=False)}


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
    tracks.mark_user_set(video)
    result["message"] = "Default track saved."
    return result


@router.post("/mediainfo")
def update_mediainfo(body: MediaInfoBody):
    return reprobe.refresh(body.kind, _picked(body))


@router.post("/files/cancel")
def cancel_files():
    if not files.cancel():
        raise AppError("No file job is running", 409)
    return files.status(include_log=False)
