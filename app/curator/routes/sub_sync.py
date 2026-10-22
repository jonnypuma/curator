"""External subtitle sync endpoints.

Endpoints under /api/v1/subs. Picture subtitles (VobSub .idx+.sub, PGS .sup) go through the same
read / sync / revert / preview endpoints; they additionally have /subs/ocr* to recognise the text
and /subs/export-srt to turn it into a text subtitle. All path-based reads/writes go through
`folders.servable()` the same way the artwork and media endpoints do, so this tool can only
touch files inside a configured library.
"""
import mimetypes
import os

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from curator import folders
from curator.video import cache_store, config, naming, preview_proxy, sub_auto, sub_ocr, sub_sync, sync_marks
from resonance.errors import AppError

router = APIRouter()


def _resolve(path):
    """Realpath + confinement check. Keeps the same shape as other read-by-path endpoints."""
    real = os.path.realpath(path or "")
    real = sub_ocr.resolve_source(real) if real else real     # a VobSub .sub row means its .idx
    if not real or not os.path.isfile(real) or not folders.servable(real):
        raise AppError("That subtitle is not in the library", 404)
    if real.lower().endswith(sub_sync.BACKUP_SUFFIX):
        raise AppError("That path is a sync backup, not a subtitle", 400)
    ext = os.path.splitext(real)[1].lower()
    if ext not in sub_sync.SUPPORTED_EXTS:
        raise AppError(f"Cannot sync {ext or 'this'} subtitle format", 400)
    return real


class Anchor(BaseModel):
    sub_ms: int
    video_ms: int


class CueEdit(BaseModel):
    index: int
    text: str


class SyncBody(BaseModel):
    path: str
    anchors: list[Anchor] = []
    preview: bool = False
    mode: str = "linear"  # "linear" (least-squares) or "piecewise"
    cue_edits: list[CueEdit] = []


class RevertBody(BaseModel):
    path: str


class OcrBody(BaseModel):
    path: str
    lang: str = ""
    force: bool = False


class ExportBody(BaseModel):
    path: str
    anchors: list[Anchor] = []
    mode: str = "linear"
    cue_edits: list[CueEdit] = []
    overwrite: bool = False


def _retimed(cues, anchors, mode):
    """Cues with the user's anchors applied. Same maths the text formats use."""
    segments = sub_sync.segments_for(anchors, mode)
    if segments is not None:
        return sub_sync.apply_segments(cues, segments)
    a, b = sub_sync.transform(anchors)
    return sub_sync.apply(cues, a, b)


@router.get("/subs")
def subs_read(path: str = Query(...)):
    real = _resolve(path)
    data = sub_sync.read(real)
    return {"path": real, "has_backup": sub_sync.has_backup(real), **data}


@router.get("/subs/raw")
def subs_raw(path: str = Query(...)):
    """Serve the sidecar's text so the <track> element can preview it live.

    Separate from /artwork and /media because the correct Content-Type and Cache-Control
    policy are different: no cache (the file is being edited), text media type, and the
    header the browser needs for cross-origin WebVTT loading.
    """
    real = _resolve(path)
    ext = os.path.splitext(real)[1].lower()
    media_type = {
        ".vtt": "text/vtt; charset=utf-8",
        ".srt": "application/x-subrip; charset=utf-8",
        ".ass": "text/x-ssa; charset=utf-8",
        ".ssa": "text/x-ssa; charset=utf-8",
    }.get(ext, "text/plain; charset=utf-8")
    headers = {"Cache-Control": "private, no-store"}
    return FileResponse(real, media_type=media_type, headers=headers)


@router.post("/subs/sync")
def subs_sync(body: SyncBody):
    real = _resolve(body.path)
    if sub_sync.is_image(real):
        return _sync_image(real, body)
    data = sub_sync.read(real)
    anchors = [anchor.dict() for anchor in (body.anchors or [])]
    mode = (body.mode or "linear").lower()
    segments = sub_sync.segments_for(anchors, mode)
    if segments is not None:
        new_cues = sub_sync.apply_segments(data["cues"], segments)
        a, b = float("nan"), float("nan")  # not a single pair in piecewise mode
    else:
        a, b = sub_sync.transform(anchors)
        new_cues = sub_sync.apply(data["cues"], a, b)
    # Overlay cue-text edits (same cue index). The transform does not touch text, so edits
    # survive the timing recompute and vice versa.
    edits = {int(e.index): str(e.text) for e in (body.cue_edits or [])}
    if edits:
        new_cues = [{**c, "text": edits.get(int(c["index"]), c.get("text"))} for c in new_cues]
    drift = sub_sync.anchor_drift(data["cues"], anchors, a if a == a else 1.0, b if b == b else 0.0)
    # Piecewise has no single scale/offset (NaN above); NaN is not valid JSON, so send null.
    out = {"path": real, "format": data["format"], "scale": a if a == a else None,
           "offset_ms": b if b == b else None,
           "duration_ms": data["duration_ms"], "cues": new_cues, "anchor_drift": drift,
           "mode": sub_sync.effective_mode(anchors, mode),
           "has_backup": sub_sync.has_backup(real)}
    if body.preview:
        out["written"] = False
        return out
    cfg = config.current()
    line_endings = str(cfg.get("sub_line_endings") or "lf").lower()
    sub_sync.write(real, new_cues, line_endings=line_endings)
    out["written"] = True
    out["has_backup"] = sub_sync.has_backup(real)
    _after_sync_notify(real, cfg)
    from curator.video import work_track

    work_track.record("sub-sync", f"Synced {os.path.basename(real)}")
    return out


def _sync_image(real, body):
    """Picture subtitle: preview returns the retimed cue list; save rewrites only the timing
    fields in place (the pictures are untouched). Cue text edits never apply here - they are
    carried by /subs/export-srt."""
    anchors = [anchor.dict() for anchor in (body.anchors or [])]
    mode = sub_sync.effective_mode(anchors, body.mode)
    data = sub_ocr.read(real)
    a, b = sub_sync.transform(anchors)
    out = {"path": real, "format": data["format"], "image": True, "scale": a, "offset_ms": b, "mode": mode,
           "duration_ms": data["duration_ms"], "anchor_drift": sub_sync.anchor_drift(data["cues"], anchors, a, b),
           "ocr": data["ocr"]}
    if body.preview:
        out.update(cues=_retimed(data["cues"], anchors, mode), written=False,
                   has_backup=sub_sync.has_backup(real))
        return out
    if not anchors:
        raise AppError("Mark at least one anchor before saving", 400)
    sub_ocr.retime(real, sub_sync.retimer(anchors, mode))
    fresh = sub_ocr.read(real)
    out.update(cues=fresh["cues"], duration_ms=fresh["duration_ms"], written=True,
               has_backup=sub_sync.has_backup(real))
    _after_sync_notify(real, config.current())
    return out


@router.post("/subs/ocr")
def subs_ocr_start(body: OcrBody):
    """Start recognising a picture subtitle in the background. Safe to call again while it runs."""
    real = _resolve(body.path)
    if not sub_sync.is_image(real):
        raise AppError("That subtitle is already text", 400)
    return sub_ocr.start_ocr(real, lang=(body.lang or "").strip() or None, force=body.force)


@router.get("/subs/ocr-status")
def subs_ocr_status(path: str = Query(...)):
    real = _resolve(path)
    if not sub_sync.is_image(real):
        raise AppError("That subtitle is already text", 400)
    return sub_ocr.ocr_status(real)


@router.post("/subs/ocr-cancel")
def subs_ocr_cancel(body: RevertBody):
    real = _resolve(body.path)
    return sub_ocr.cancel_ocr(real)


@router.post("/subs/export-srt")
def subs_export_srt(body: ExportBody):
    """Write the recognised text, with the current anchors and any text edits applied, as a
    .srt beside the picture subtitle. The picture subtitle itself is not changed."""
    real = _resolve(body.path)
    if not sub_sync.is_image(real):
        raise AppError("Only picture subtitles can be exported as SRT", 400)
    data = sub_ocr.read(real)
    if not data["cues"]:
        raise AppError("Recognise the text first (Run OCR)", 409)
    anchors = [anchor.dict() for anchor in (body.anchors or [])]
    cues = _retimed(data["cues"], anchors, body.mode)
    edits = {int(e.index): str(e.text) for e in (body.cue_edits or [])}
    if edits:
        cues = [{**c, "text": edits.get(int(c["index"]), c.get("text"))} for c in cues]
    cfg = config.current()
    target = sub_ocr.export_srt(real, cues, line_endings=str(cfg.get("sub_line_endings") or "lf").lower(),
                                overwrite=body.overwrite)
    _after_sync_notify(target, cfg)
    return {"path": target, "name": os.path.basename(target), "cues": sum(1 for c in cues if (c.get("text") or "").strip())}


def _after_sync_notify(sub_path, cfg):
    """When `sub_sync_notify` is on, tell the players and Bazarr the subtitle changed.

    Players go through the same path as a webhook ingest (the Kodi stale-prune step fires and
    Watch Folders pick up the retimed file). Bazarr gets a real "scan disk" call for the movie or
    show, which needs only the Radarr/Sonarr id, so it lists the new file instead of waiting for
    its next pass. Both are best effort: a failure here never fails the write.
    """
    import logging

    if not cfg.get("sub_sync_notify"):
        return
    log = logging.getLogger(__name__)
    try:
        from curator import notify as player_notify

        folder = os.path.dirname(sub_path)
        if folder:
            player_notify.request("video", folders=[folder], items=[os.path.basename(sub_path)],
                                  message=f"Subtitle synced: {os.path.basename(sub_path)}")
    except Exception:
        log.warning("sub-sync notify failed", exc_info=True)
    _bazarr_scan(sub_path)


def _bazarr_scan(sub_path):
    """Ask Bazarr to re-read the subtitles beside this file. Best effort: a failure is only logged."""
    import logging

    try:
        from curator import bazarr

        bazarr.scan_subtitles(sub_path)
    except Exception:
        logging.getLogger(__name__).warning("sub-sync Bazarr scan failed", exc_info=True)


class VideoBody(BaseModel):
    path: str


def _video(path):
    real = os.path.realpath(path or "")
    if not naming.is_video(real) or not os.path.isfile(real) or not folders.servable(real):
        raise AppError("That video is not in the library", 404)
    return real


def _video_state(real):
    state = preview_proxy.status(real)
    from urllib.parse import quote

    state["url"] = (f"/api/v1/media?path={quote(real)}" if state["mode"] == "direct"
                    else f"/api/v1/subs/proxy?path={quote(real)}")
    return state


@router.post("/subs/video")
def subs_video(body: VideoBody):
    """What the sync window should play. A video a browser can play is streamed as it is; any
    other (XviD AVI, AC-3 audio, HEVC, ...) gets a small H.264 copy built in the background."""
    real = _video(body.path)
    preview_proxy.start(real)
    return _video_state(real)


@router.post("/subs/synced")
def subs_mark_synced(body: RevertBody):
    """Sync OK: remember that this subtitle was checked and is in sync."""
    real = _resolve(body.path)
    result = sync_marks.mark(real)
    if config.current().get("sub_sync_notify"):
        # Bazarr can be slow to answer; Sync OK should not wait for it.
        import threading

        threading.Thread(target=_bazarr_scan, args=(real,), name="bazarr-scan", daemon=True).start()
    return result


@router.post("/subs/video-discard")
def subs_video_discard(body: VideoBody):
    """The sync window's Done button: delete the preview copy made for this video."""
    return {"freed": preview_proxy.discard(_video(body.path))}


@router.get("/subs/video-status")
def subs_video_status(path: str = Query(...)):
    return _video_state(_video(path))


@router.get("/subs/proxy")
def subs_proxy(path: str = Query(...)):
    real = _video(path)
    out = preview_proxy.proxy_file(real)
    if not os.path.isfile(out):
        raise AppError("The preview copy is not ready", 404)
    return FileResponse(out, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/subs/revert")
def subs_revert(body: RevertBody):
    real = _resolve(body.path)
    sub_sync.revert(real)
    data = sub_sync.read(real)
    return {"path": real, "format": data["format"], "duration_ms": data["duration_ms"],
            "cues": data["cues"], "has_backup": False, "reverted": True}


@router.get("/subs/preview-track")
def subs_preview_track(path: str = Query(...)):
    """Return a WebVTT representation of the sidecar - whatever the format - so the browser
    can render it in a <track> element. Used only for live preview; the file on disk is
    untouched.
    """
    real = _resolve(path)
    data = sub_sync.read(real)
    return _vtt_response(data["cues"])


class PreviewBody(BaseModel):
    path: str
    anchors: list[Anchor] = []
    mode: str = "linear"
    cue_edits: list[CueEdit] = []


@router.post("/subs/preview-track")
def subs_preview_track_live(body: PreviewBody):
    """Same as /subs/preview-track but applies the user's anchors first so the overlay in
    the player updates as they stamp new anchor points. Honours piecewise mode and cue
    text edits for a true live preview."""
    real = _resolve(body.path)
    data = sub_sync.read(real)
    anchors = [anchor.dict() for anchor in (body.anchors or [])]
    segments = sub_sync.segments_for(anchors, body.mode)
    if segments is not None:
        cues = sub_sync.apply_segments(data["cues"], segments)
    else:
        a, b = sub_sync.transform(anchors)
        cues = sub_sync.apply(data["cues"], a, b)
    edits = {int(e.index): str(e.text) for e in (body.cue_edits or [])}
    if edits:
        cues = [{**c, "text": edits.get(int(c["index"]), c.get("text"))} for c in cues]
    return _vtt_response(cues)


def _vtt_response(cues):
    from fastapi.responses import Response

    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{sub_sync._ms_to_vtt(cue['start_ms'])} --> {sub_sync._ms_to_vtt(cue['end_ms'])}")
        lines.append(cue.get("text") or "")
        lines.append("")
    body = "\n".join(lines).encode("utf-8")
    return Response(content=body, media_type="text/vtt; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


class CacheBody(BaseModel):
    which: str


@router.get("/subs/cache")
def subs_cache():
    """What the subtitle tools keep on disk, their caps, and what OCR can recognise."""
    cfg = config.current()
    cap = cache_store.limits(cfg)
    caches = {}
    for which in cache_store.CACHES:
        info = cache_store.usage(which)
        caches[which] = {**info, "limit_bytes": cap[which]}
    available = sub_ocr.tesseract_available()
    return {"caches": caches, "tesseract": available, "languages": sub_ocr.available_langs() if available else [],
            "alass": sub_auto.available()}


@router.post("/subs/cache/clear")
def subs_cache_clear(body: CacheBody):
    if body.which not in cache_store.CACHES:
        raise AppError("Unknown cache", 400)
    return {"removed": cache_store.clear(body.which)}


class AutoBody(BaseModel):
    path: str
    video: str = ""
    mode: str = "fine"        # fine (small shifts only) | shift (one shift, any size) | cuts


@router.post("/subs/auto")
def subs_auto_start(body: AutoBody):
    """Start automatic sync (alass) of one subtitle against its video, in the background."""
    real = _resolve(body.path)
    video = _video(body.video)
    return sub_auto.start(real, video, mode=body.mode)


@router.get("/subs/auto-status")
def subs_auto_status(path: str = Query(...)):
    real = _resolve(path)
    return sub_auto.status(real)


@router.post("/subs/auto-cancel")
def subs_auto_cancel(body: RevertBody):
    return sub_auto.cancel(_resolve(body.path))
