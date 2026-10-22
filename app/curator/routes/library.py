import mimetypes
import os
import shutil
import subprocess
import tempfile
import uuid

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from curator import folders
from curator.video import naming, scanner, store
from curator.video.artwork import is_image
from resonance import db
from resonance.errors import AppError
from resonance.library import clock
from resonance import thumbs

router = APIRouter()

THUMB_WIDTHS = thumbs.WIDTHS


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise AppError("Unknown item", 404) from exc


def _found(item):
    if item is None:
        raise AppError("That item is not in the library any more", 404)
    return item


@router.get("/movies")
def movies():
    import logging
    import time

    started = time.monotonic()
    rows = store.list_movies()
    built = time.monotonic() - started
    payload = db.clean({"movies": rows, "as_of": clock()})
    total = time.monotonic() - started
    if total > 3.0:
        logging.getLogger(__name__).info(
            "movie list: %d movies, %.1fs to build (query, paths, .nfo check), %.1fs to prepare the reply",
            len(rows), built, total - built)
    return payload


@router.get("/library/changes")
def library_changes(media: str = Query(...), since: str = Query(...)):
    """Movies or shows written after `since`, plus ids this scan has deleted."""
    if media not in {"movies", "tv"}:
        raise AppError("Unknown library", 400)
    payload = store.changes(media, since)
    payload["removed"] = scanner.removed_ids(media)
    return db.clean(payload)


@router.get("/movies/{movie_id}")
def movie(movie_id: str):
    return _found(store.movie_detail(_uuid(movie_id)))


@router.get("/sets")
def sets():
    return {"sets": store.list_sets()}


class CreateSetBody(BaseModel):
    name: str
    overview: str = ""
    tmdb_id: str | None = None
    movie_ids: list[str] = []


@router.post("/sets")
def create_set(body: CreateSetBody):
    name = (body.name or "").strip()
    if not name:
        raise AppError("Enter a movie set name", 400)
    set_id = store.save_set({"name": name, "overview": (body.overview or "").strip(), "tmdb_id": (body.tmdb_id or "").strip() or None})
    if body.movie_ids:
        for mid in body.movie_ids:
            try:
                store.edit("movie", _uuid(mid), {"set_name": name})
            except Exception:
                pass
    return _found(store.set_detail(str(set_id)))


@router.get("/sets/{set_id}")
def movie_set(set_id: str):
    return _found(store.set_detail(_uuid(set_id)))


@router.get("/tv/shows")
def shows():
    return db.clean({"shows": store.list_shows(), "as_of": clock()})


@router.get("/tv/shows/{show_id}")
def show(show_id: str):
    return _found(store.show_detail(_uuid(show_id)))


@router.get("/tv/episodes/{episode_id}")
def episode(episode_id: str):
    return _found(store.episode_detail(_uuid(episode_id)))


@router.post("/tv/episodes/{episode_id}/thumb")
def generate_episode_thumb(episode_id: str):
    """Generate a thumbnail for an episode using ffmpeg.

    Samples from ~40% into the file and skips black/intro frames by seeking past
    the first 5% and last 10% of duration, then picks a non-black frame.
    """
    import glob as _glob

    ep = store.episode_detail(_uuid(episode_id))
    if not ep:
        raise AppError("Episode not found", 404)
    file_path = ep.get("path") or ""
    if not file_path or file_path.startswith("missing://") or file_path.startswith("wanted://"):
        raise AppError("No video file available for this episode", 400)
    if not os.path.isfile(file_path):
        raise AppError("Video file not found on disk", 400)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AppError("ffmpeg is required to generate thumbnails", 500)

    # Get duration with ffprobe
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path],
            capture_output=True, text=True, timeout=30
        )
        import json as _json
        probe_data = _json.loads(probe.stdout or "{}")
        duration = float((probe_data.get("format") or {}).get("duration") or 0)
    except Exception:
        duration = 0

    if duration < 30:
        raise AppError("File too short to generate a useful thumbnail", 400)

    # Target position: 40% into the file, never within first 5% or last 10%
    min_pos = max(30, duration * 0.05)
    max_pos = duration * 0.90
    target = min(max(duration * 0.40, min_pos), max_pos)

    # Determine output path: <video_stem>-thumb.jpg next to the video file
    folder = os.path.dirname(file_path)
    stem = os.path.splitext(os.path.basename(file_path))[0]
    season_num = ep.get("season_number")
    ep_num = ep.get("episode_number")
    if season_num is not None and ep_num is not None:
        from curator.video.naming import episode_mark
        ep_mark = episode_mark(season_num, ep_num)
        if ep_mark and ep_mark.lower() in stem.lower():
            thumb_name = f"{stem}-thumb.jpg"
        else:
            thumb_name = f"{stem}-{ep_mark}-thumb.jpg"
    else:
        thumb_name = f"{stem}-thumb.jpg"
    thumb_path = os.path.join(folder, thumb_name)

    # Use ffmpeg to extract a non-black frame near target position.
    # Strategy: seek to target - 60s, then use 'select' filter to skip black frames,
    # take the first frame that has a scene score > 0.05 within a 120s window.
    seek_start = max(0, target - 60)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", str(seek_start),
                "-i", file_path,
                "-t", "120",
                "-vf", r"select=gt(scene\,0.05),scale=1280:-2",
                "-frames:v", "1",
                "-q:v", "2",
                tmp_path,
            ],
            capture_output=True, timeout=60
        )
        if result.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            # Fallback: just grab a frame at the target position without scene filter
            result2 = subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-ss", str(target),
                    "-i", file_path,
                    "-vf", "scale=1280:-2",
                    "-frames:v", "1",
                    "-q:v", "2",
                    tmp_path,
                ],
                capture_output=True, timeout=30
            )
            if result2.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise AppError("ffmpeg could not extract a frame from this file", 500)

        import shutil as _shutil
        _shutil.move(tmp_path, thumb_path)
        art = dict(ep.get("artwork") or {})
        art["thumb"] = thumb_path
        store.set_artwork("tv_episodes", _uuid(episode_id), art)
    except AppError:
        raise
    except subprocess.TimeoutExpired:
        raise AppError("Thumbnail generation timed out", 500)
    except Exception as exc:
        raise AppError(f"Thumbnail generation failed: {exc}", 500)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return {"thumb_path": thumb_path, "thumb_name": thumb_name}



class StatusBody(BaseModel):
    kind: str
    ids: list[str]
    status: str


@router.post("/status")
def set_status(body: StatusBody):
    if body.status not in {"NEW", "PROCESSED", "IGNORED"}:
        raise AppError("Unknown status change", 400)
    ids = [_uuid(item) for item in body.ids][:5000]
    if body.kind == "set":
        store.mark_sets(ids, body.status)
        return {"updated": len(ids)}
    tables = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes"}
    if body.kind not in tables:
        raise AppError("Unknown status change", 400)
    import logging
    import time

    started = time.monotonic()
    store.mark(tables[body.kind], ids, body.status)
    waited = time.monotonic() - started
    if waited > 2:
        logging.getLogger(__name__).warning("status change on %d %s row(s) took %.1fs (the database was busy)", len(ids), body.kind, waited)
    return {"updated": len(ids)}


def _thumbnail(path, width):
    return thumbs.thumbnail(path, width, "video/thumbs")


@router.get("/artwork")
def artwork(path: str = Query(...), w: int = Query(0)):
    """Serve local artwork from a movie or TV folder. w picks a cached thumbnail width."""
    real = os.path.realpath(path)
    if not is_image(real) or not os.path.isfile(real) or not folders.servable(real):
        raise AppError("Artwork is not available", 404)
    headers = {"Cache-Control": "private, max-age=3600"}
    if w and not real.lower().endswith(".tbn"):
        width = min(THUMB_WIDTHS, key=lambda item: abs(item - w))
        try:
            thumb = _thumbnail(real, width)
            media = "image/png" if thumb.lower().endswith(".png") else "image/jpeg"
            return FileResponse(thumb, media_type=media, headers=headers)
        except (OSError, ValueError):
            pass
    media_type = mimetypes.guess_type(real)[0] or "image/jpeg"
    return FileResponse(real, media_type=media_type, headers=headers)


@router.get("/media")
def media_file(path: str = Query(...)):
    """Stream a video or theme audio file that sits in a movie or TV folder."""
    real = os.path.realpath(path)
    is_theme = os.path.basename(real).lower() in {"theme.mp3", "theme.m4a", "theme.flac", "theme.ogg", "theme.wav"}
    if (not naming.is_video(real) and not is_theme) or not os.path.isfile(real) or not folders.servable(real):
        raise AppError("That media file is not in the library", 404)
    media_type = mimetypes.guess_type(real)[0] or ("audio/mpeg" if is_theme else "video/mp4")
    return FileResponse(real, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/tv/episodes/{episode_id}/stream")
def episode_stream(episode_id: str, request: Request):
    """Range-aware video stream for the episode split player."""
    row = db.fetchone("SELECT * FROM tv_episodes WHERE id = %s", (_uuid(episode_id),))
    if not row:
        raise AppError("Episode not found", 404)
    real = os.path.realpath(str(row.get("path") or ""))
    if not real or not os.path.isfile(real) or not folders.servable(real):
        raise AppError("File not accessible", 404)
    file_size = os.path.getsize(real)
    media_type = mimetypes.guess_type(real)[0] or "video/mp4"
    range_header = request.headers.get("Range")
    if not range_header:
        return StreamingResponse(
            _iter_file(real, 0, file_size - 1),
            status_code=200,
            media_type=media_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, no-store",
            },
        )
    # Parse: bytes=start-end
    try:
        byte_range = range_header.strip().replace("bytes=", "")
        start_str, end_str = byte_range.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
    except (ValueError, AttributeError):
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    end = min(end, file_size - 1)
    if start > end or start < 0:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    length = end - start + 1
    return StreamingResponse(
        _iter_file(real, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
        },
    )


def _iter_file(path: str, start: int, end: int, chunk: int = 1 << 20):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@router.get("/nfo/{kind}/{item_id}")
def nfo_text(kind: str, item_id: str):
    """The .nfo file already stored for a movie, show, season, or episode."""
    from resonance import db

    tables = {
        "movie": "movies", "show": "tv_shows", "season": "tv_seasons",
        "episode": "tv_episodes", "set": "movie_sets",
    }
    table = tables.get(kind)
    if not table:
        raise AppError("Unknown item", 404)
    row = db.fetchone(f"SELECT * FROM {table} WHERE id = %s", (_uuid(item_id),))
    path = (row or {}).get("nfo_path") or ""
    real = os.path.realpath(path) if path else ""
    if not real or not os.path.isfile(real) or not folders.servable(real) or not real.lower().endswith(".nfo"):
        raise AppError("No .nfo file for this item", 404)
    try:
        with open(real, encoding="utf-8", errors="replace") as handle:
            text = handle.read(2_000_000)
    except OSError as exc:
        raise AppError("The .nfo file could not be read", 404) from exc
    from curator.video import nfo as video_nfo
    from curator.video import nfo_digest

    seasons = None
    if kind == "show" and row:
        seasons = db.fetchall(
            "SELECT id, season_number, plot FROM tv_seasons WHERE show_id = %s ORDER BY season_number",
            (row["id"],),
        )
    digest_table = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes", "set": "movie_sets"}[kind]
    row = dict(row)
    if nfo_digest.collapse_studios(digest_table, row):
        db.execute(f"UPDATE {table} SET studios = %s WHERE id = %s", (row["studios"], row["id"]))
    diff = video_nfo.changes(kind, row, text, seasons)
    file_stale = nfo_digest.changed(dict(row), digest_table)
    if not diff.get("changes") and not diff.get("notes") and file_stale:
        nfo_digest.remember(digest_table, row["id"])
        file_stale = False
    if kind == "show":
        diff = {**diff, "changes": list(diff.get("changes") or []) + _family_nfo_changes(row["id"])}
    stale = file_stale or bool(diff.get("changes"))
    return {"name": os.path.basename(real), "text": text, "stale": stale, "file_stale": file_stale, "diff": diff}


class KeepNfoBody(BaseModel):
    kind: str
    id: str
    field: str
    from_kind: str = ""
    from_id: str = ""


@router.post("/nfo/keep")
def keep_nfo_field(body: KeepNfoBody):
    """Copy one .nfo value into the database and leave the file as it is."""
    from curator.video import nfo as video_nfo

    kind = body.kind
    field = body.field
    if kind in {"album", "artist"}:
        from resonance import library as music_library

        return music_library.keep_music_field(kind, body.id, field, body.from_kind, body.from_id)
    if kind not in {"movie", "show", "season", "episode", "set"}:
        raise AppError("Unknown item", 404)
    if kind == "set":
        allowed = {"name", "title", "original_title", "overview"}
    elif kind == "season":
        allowed = {"title", "season_name", "sort_title", "plot", "premiered", "year"}
    else:
        allowed = set(store.FIELDS[store.table_for(kind)])
    if field not in allowed:
        raise AppError("That field stays in the .nfo", 400)
    target = _nfo_row(kind, body.id)
    source_kind = body.from_kind or kind
    source = target if source_kind == kind and (not body.from_id or body.from_id == body.id) else _nfo_row(source_kind, body.from_id or body.id)
    text = _nfo_file_text(source.get("nfo_path") or "")
    if not text:
        raise AppError("No .nfo file for this item", 404)
    season_number = target.get("season_number") if kind == "season" and source_kind == "show" else None
    value = video_nfo.file_field(source_kind, source, text, field, season_number)
    if value is None and field not in {"plot", "outline", "tagline"}:
        raise AppError("That field is not in the .nfo", 400)
    _write_kept_field(kind, target, field, value)
    return {"ok": True}


def _nfo_row(kind, item_id):
    tables = {
        "movie": "movies", "show": "tv_shows", "season": "tv_seasons",
        "episode": "tv_episodes", "set": "movie_sets",
    }
    table = tables.get(kind)
    if not table:
        raise AppError("Unknown item", 404)
    row = db.fetchone(f"SELECT * FROM {table} WHERE id = %s", (_uuid(item_id),))
    if not row:
        raise AppError("That item is not in the library any more", 404)
    return dict(row)


def _write_kept_field(kind, row, field, value):
    row_id = row["id"]
    if row.get("locked"):
        raise AppError("This item is locked. Unlock it to keep the .nfo value.", 409)
    if kind == "set":
        column = "name" if field in {"name", "title", "original_title"} else "overview"
        db.execute(f"UPDATE movie_sets SET {column} = %s, updated_at = NOW() WHERE id = %s", (value, row_id))
        return
    if kind == "season":
        if field == "season_name":
            store.merge_season_name(row["show_id"], row["season_number"], value)
        else:
            store.save_season_meta(row_id, {field: value})
        db.execute(
            "UPDATE tv_seasons SET locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))) WHERE id = %s",
            ([field], row_id),
        )
        return
    values = {field: value}
    if field in {"imdb_id", "tmdb_id", "tvdb_id", "trakt_id"} and value:
        ids = dict(row.get("ids") or {})
        ids[field.split("_")[0]] = value
        values["ids"] = ids
    if not store.edit(kind, row_id, values):
        raise AppError("That field stays in the .nfo", 400)


def _nfo_file_text(path):
    real = os.path.realpath(path) if path else ""
    if not real or not os.path.isfile(real) or not folders.servable(real) or not real.lower().endswith(".nfo"):
        return ""
    try:
        with open(real, encoding="utf-8", errors="replace") as handle:
            return handle.read(2_000_000)
    except OSError:
        return ""


def _family_nfo_changes(show_id):
    """Season and episode fields that differ, for the show's NFO changes list."""
    from curator.video import nfo as video_nfo
    from curator.video import nfo_digest

    found = []
    seasons = db.fetchall(
        "SELECT * FROM tv_seasons WHERE show_id = %s AND nfo_path IS NOT NULL ORDER BY season_number",
        (show_id,),
    )
    for season in seasons:
        season = dict(season)
        if not nfo_digest.changed(season, "tv_seasons"):
            continue
        text = _nfo_file_text(season.get("nfo_path") or "")
        if not text:
            continue
        name = str(season.get("title") or "").strip() or f"Season {season.get('season_number')}"
        diff = video_nfo.changes("season", season, text)
        if not diff.get("changes") and not diff.get("notes"):
            nfo_digest.remember("tv_seasons", season["id"])
            continue
        found.extend(video_nfo.named_changes(name, diff.get("changes")))
    episodes = db.fetchall(
        """
        SELECT * FROM tv_episodes
        WHERE show_id = %s AND nfo_path IS NOT NULL
        ORDER BY season_number, episode_number
        """,
        (show_id,),
    )
    for episode in episodes:
        episode = dict(episode)
        if not nfo_digest.changed(episode, "tv_episodes"):
            continue
        text = _nfo_file_text(episode.get("nfo_path") or "")
        if not text:
            continue
        season_number = episode.get("season_number")
        episode_number = episode.get("episode_number")
        if season_number is None or episode_number is None:
            code = "Episode"
        else:
            code = f"S{int(season_number):02d}E{int(episode_number):02d}"
        diff = video_nfo.changes("episode", episode, text)
        if not diff.get("changes") and not diff.get("notes"):
            nfo_digest.remember("tv_episodes", episode["id"])
            continue
        found.extend(video_nfo.named_changes(code, diff.get("changes")))
    return found
