"""External subtitle sync: parse, transform and write back cue timings.

Supports .srt, .vtt and .ass/.ssa (text events). The transform is y = a*t + b, derived
from the user's anchor points: one anchor gives a constant offset (a=1), two or more give
a linear fit that corrects framerate drift as well as the global offset. Everything else in
the file - ASS style blocks, VTT cue IDs, blank lines - is preserved verbatim so the saved
sidecar is byte-identical outside the timestamp fields.

Guarded by `folders.servable()` upstream in the route layer, same as the artwork and media
endpoints. Picture subtitles (.idx+.sub VobSub, .sup PGS) are handled by `sub_ocr`: it OCRs them so
the cue list is readable and retimes them in place, leaving the pictures untouched.
"""
from __future__ import annotations

import logging
import os
import re
import shutil

from curator.video import subtitles
from resonance.errors import AppError

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".srt", ".vtt", ".ass", ".ssa", ".idx", ".sup"}
IMAGE_EXTS = {".idx", ".sup"}
BACKUP_SUFFIX = ".sync-backup"

_SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_VTT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})")
_ASS_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,2})")


def _ext_of(path):
    return os.path.splitext(path)[1].lower()


# ---------- read ----------------------------------------------------------------

def _read_text(path):
    """UTF-8 text with BOM stripped and line endings normalised to \\n."""
    with open(path, "rb") as handle:
        raw = handle.read()
    text = subtitles._decoded(raw)
    if text is None:
        raise AppError("Cannot decode this subtitle file", 400)
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def _srt_ms(h, m, s, ms):
    return int(h) * 3600_000 + int(m) * 60_000 + int(s) * 1000 + int(str(ms).ljust(3, "0")[:3])


def _ass_ms(h, m, s, cs):
    return int(h) * 3600_000 + int(m) * 60_000 + int(s) * 1000 + int(str(cs).ljust(2, "0")[:2]) * 10


def _ms_to_srt(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms3 = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms3:03d}"


def _ms_to_vtt(ms):
    return _ms_to_srt(ms).replace(",", ".")


def _ms_to_ass(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms3 = divmod(rem, 1000)
    cs = round(ms3 / 10)
    if cs == 100:
        cs = 0
        ss += 1
    return f"{hh:01d}:{mm:02d}:{ss:02d}.{cs:02d}"


def read(path):
    """Return {format, duration_ms, cues: [{index, start_ms, end_ms, text}]}.

    Cues are in file order; `index` is 1-based so the frontend can render it directly.
    """
    ext = _ext_of(path)
    if ext in IMAGE_EXTS or ext == ".sub":
        from curator.video import sub_ocr

        return sub_ocr.read(path)
    if ext not in SUPPORTED_EXTS:
        raise AppError(f"Cannot sync {ext or 'this'} subtitle format", 400)
    text = _read_text(path)
    if ext == ".srt":
        cues = _parse_srt(text)
        fmt = "srt"
    elif ext == ".vtt":
        cues = _parse_vtt(text)
        fmt = "vtt"
    else:
        cues = _parse_ass(text)
        fmt = "ass"
    if not cues:
        raise AppError("No subtitle cues found in that file", 400)
    duration = max(cue["end_ms"] for cue in cues)
    return {"format": fmt, "duration_ms": duration, "cues": cues}


def _parse_srt(text):
    # Blocks separated by blank line(s): index\nHH:MM:SS,mmm --> HH:MM:SS,mmm\ntext...
    cues = []
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    for block in blocks:
        lines = block.split("\n")
        # First line may be the numeric index, or the timestamp line itself.
        time_line_i = 1 if lines and lines[0].strip().isdigit() else 0
        if time_line_i >= len(lines):
            continue
        times = _SRT_TIME.findall(lines[time_line_i])
        if len(times) < 2:
            continue
        start = _srt_ms(*times[0])
        end = _srt_ms(*times[1])
        body = "\n".join(lines[time_line_i + 1:]).rstrip()
        cues.append({"index": len(cues) + 1, "start_ms": start, "end_ms": end, "text": body})
    return cues


def _parse_vtt(text):
    cues = []
    # Drop the WEBVTT header and anything up to the first blank line.
    body = re.split(r"\n[ \t]*\n", text, maxsplit=1)
    chunks = re.split(r"\n[ \t]*\n", body[1] if len(body) > 1 else text)
    for chunk in chunks:
        lines = chunk.strip().split("\n")
        if not lines:
            continue
        # Optional cue id (no "-->" on it).
        time_line_i = 0 if "-->" in lines[0] else (1 if len(lines) > 1 and "-->" in lines[1] else -1)
        if time_line_i < 0:
            continue
        times = _VTT_TIME.findall(lines[time_line_i])
        if len(times) < 2:
            continue
        start = _srt_ms(*times[0])
        end = _srt_ms(*times[1])
        txt = "\n".join(lines[time_line_i + 1:]).rstrip()
        cues.append({"index": len(cues) + 1, "start_ms": start, "end_ms": end, "text": txt})
    return cues


def _parse_ass(text):
    cues = []
    for line in text.split("\n"):
        if not line.startswith("Dialogue:"):
            continue
        # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = line[len("Dialogue:"):].split(",", 9)
        if len(parts) < 10:
            continue
        start_m = _ASS_TIME.match(parts[1].strip())
        end_m = _ASS_TIME.match(parts[2].strip())
        if not start_m or not end_m:
            continue
        cues.append({
            "index": len(cues) + 1,
            "start_ms": _ass_ms(*start_m.groups()),
            "end_ms": _ass_ms(*end_m.groups()),
            "text": parts[9].rstrip(),
        })
    return cues


# ---------- transform -----------------------------------------------------------

def transform(anchors):
    """Return (scale a, offset_ms b) from the user's anchor points.

    One anchor = constant offset (a = 1). Two or more anchors = linear least-squares fit so
    extra anchors act as drift checks the user can validate against. Anchors are
    [{sub_ms, video_ms}] in subtitle time -> video time.
    """
    pairs = [(float(a["sub_ms"]), float(a["video_ms"]))
             for a in (anchors or []) if a.get("sub_ms") is not None and a.get("video_ms") is not None]
    if not pairs:
        return 1.0, 0.0
    if len(pairs) == 1:
        return 1.0, pairs[0][1] - pairs[0][0]
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    denom = n * sxx - sx * sx
    if denom == 0:
        # All anchors at the same subtitle time; fall back to offset-only.
        return 1.0, pairs[-1][1] - pairs[-1][0]
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    return a, b


def transform_segments(anchors):
    """Piecewise linear fit over sorted anchors. Returns [(sub_from_ms, sub_to_ms, a, b)].

    One segment per gap between consecutive anchors. The first extends to -inf and the last
    to +inf, so every cue time lands in exactly one segment. Fewer than two anchors falls
    back to the single linear fit so callers can treat it uniformly.
    """
    pairs = [(float(a["sub_ms"]), float(a["video_ms"]))
             for a in (anchors or []) if a.get("sub_ms") is not None and a.get("video_ms") is not None]
    if len(pairs) < 2:
        a, b = transform(anchors)
        return [(float("-inf"), float("inf"), a, b)]
    pairs.sort(key=lambda p: p[0])
    out = []
    for i in range(len(pairs) - 1):
        x1, y1 = pairs[i]
        x2, y2 = pairs[i + 1]
        span = max(1.0, x2 - x1)
        aa = (y2 - y1) / span
        bb = y1 - aa * x1
        start = x1 if i > 0 else float("-inf")
        end = x2 if i < len(pairs) - 2 else float("inf")
        out.append((start, end, aa, bb))
    return out


def transform_steps(anchors):
    """Stepwise fit: each anchor starts a stretch that is shifted by that anchor's own constant
    offset (video - subtitle time). The first stretch also covers everything before it. This is
    what automatic sync (alass) produces when a file was cut: every piece has a different offset
    but no piece is stretched. Returns [(sub_from_ms, sub_to_ms, 1.0, offset_ms)]."""
    pairs = sorted((float(a["sub_ms"]), float(a["video_ms"]))
                   for a in (anchors or []) if a.get("sub_ms") is not None and a.get("video_ms") is not None)
    if not pairs:
        return [(float("-inf"), float("inf"), 1.0, 0.0)]
    out = []
    for i, (x, y) in enumerate(pairs):
        start = x if i > 0 else float("-inf")
        end = pairs[i + 1][0] if i + 1 < len(pairs) else float("inf")
        out.append((start, end, 1.0, y - x))
    return out


def segments_for(anchors, mode):
    """The segment list for a non-linear mode, or None when the single linear fit applies."""
    mode = str(mode or "").lower()
    if mode == "steps" and anchors:
        return transform_steps(anchors)
    if mode == "piecewise" and len(anchors or []) >= 2:
        return transform_segments(anchors)
    return None


def effective_mode(anchors, mode):
    return "steps" if segments_for(anchors, mode) is not None and str(mode).lower() == "steps" else (
        "piecewise" if segments_for(anchors, mode) is not None else "linear")


def apply_segments(cues, segments):
    """Apply piecewise segments to cues, picking the segment by each cue's start time."""
    if not segments:
        return [dict(cue) for cue in cues]
    out = []
    for cue in cues:
        t = float(cue["start_ms"])
        seg = segments[-1]
        for s_from, s_to, aa, bb in segments:
            if s_from <= t < s_to:
                seg = (s_from, s_to, aa, bb)
                break
        aa, bb = seg[2], seg[3]
        new_start = max(0, int(round(aa * cue["start_ms"] + bb)))
        new_end = max(new_start + 1, int(round(aa * cue["end_ms"] + bb)))
        row = dict(cue)
        row["start_ms"] = new_start
        row["end_ms"] = new_end
        out.append(row)
    return out


def is_image(path):
    return _ext_of(path) in IMAGE_EXTS


def retimer(anchors, mode="linear"):
    """A function ms -> ms for callers that retime raw timestamps (picture subtitles) rather
    than parsed cues. Same maths as `apply` / `apply_segments`."""
    segments = segments_for(anchors, mode)
    if segments is not None:
        def piecewise(t):
            seg = segments[-1]
            for s_from, s_to, aa, bb in segments:
                if s_from <= t < s_to:
                    seg = (s_from, s_to, aa, bb)
                    break
            return seg[2] * t + seg[3]
        return piecewise
    a, b = transform(anchors)
    return lambda t: a * t + b


def apply(cues, a, b):
    """Return new cues with timings transformed by t' = a*t + b. Order preserved."""
    out = []
    for cue in cues:
        new_start = max(0, int(round(a * cue["start_ms"] + b)))
        new_end = max(new_start + 1, int(round(a * cue["end_ms"] + b)))
        row = dict(cue)
        row["start_ms"] = new_start
        row["end_ms"] = new_end
        out.append(row)
    return out


def anchor_drift(cues, anchors, a, b):
    """For each anchor, how far the fit missed the user's stamp (ms). The middle anchors in
    a 3+ anchor fit are the ones that catch nonlinear drift; a value over ~500ms is a sign
    something is off (ad breaks removed, variable rate reencode, etc).
    """
    out = []
    for anchor in (anchors or []):
        sub_ms = float(anchor.get("sub_ms") or 0)
        want = float(anchor.get("video_ms") or 0)
        got = a * sub_ms + b
        out.append({"sub_ms": int(sub_ms), "video_ms": int(want), "fitted_ms": int(round(got)),
                    "drift_ms": int(round(got - want))})
    return out


# ---------- write ---------------------------------------------------------------

def _rewrite_srt(text, cues_by_index):
    out = []
    idx = 0
    blocks = re.split(r"(\n[ \t]*\n)", text.rstrip() + "\n")
    for part in blocks:
        if "-->" not in part:
            out.append(part)
            continue
        idx += 1
        new = cues_by_index.get(idx)
        if not new:
            out.append(part)
            continue
        lines = part.split("\n")
        time_i = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                lines[i] = f"{_ms_to_srt(new['start_ms'])} --> {_ms_to_srt(new['end_ms'])}"
                time_i = i
                break
        if time_i >= 0 and new.get("text") is not None:
            lines = lines[: time_i + 1] + str(new.get("text") or "").split("\n")
        out.append("\n".join(lines))
    return "".join(out)


def _rewrite_vtt(text, cues_by_index):
    out = []
    idx = 0
    blocks = re.split(r"(\n[ \t]*\n)", text.rstrip() + "\n")
    for part in blocks:
        if "-->" not in part:
            out.append(part)
            continue
        idx += 1
        new = cues_by_index.get(idx)
        if not new:
            out.append(part)
            continue
        lines = part.split("\n")
        time_i = -1
        for i, line in enumerate(lines):
            if "-->" in line:
                trail = ""
                m2 = re.search(r"\s+[A-Za-z]+:[^\s]+.*$", line)
                if m2:
                    trail = line[m2.start():]
                lines[i] = f"{_ms_to_vtt(new['start_ms'])} --> {_ms_to_vtt(new['end_ms'])}{trail}"
                time_i = i
                break
        if time_i >= 0 and new.get("text") is not None:
            lines = lines[: time_i + 1] + str(new.get("text") or "").split("\n")
        out.append("\n".join(lines))
    return "".join(out)


def _rewrite_ass(text, cues_by_index):
    idx = 0
    out_lines = []
    for line in text.split("\n"):
        if not line.startswith("Dialogue:"):
            out_lines.append(line)
            continue
        idx += 1
        new = cues_by_index.get(idx)
        if not new:
            out_lines.append(line)
            continue
        parts = line[len("Dialogue:"):].split(",", 9)
        if len(parts) < 10 or not _ASS_TIME.match(parts[1].strip()) or not _ASS_TIME.match(parts[2].strip()):
            out_lines.append(line)
            continue
        parts[1] = _ms_to_ass(new["start_ms"])
        parts[2] = _ms_to_ass(new["end_ms"])
        if new.get("text") is not None:
            parts[9] = str(new.get("text") or "")
        out_lines.append("Dialogue:" + ",".join(parts))
    return "\n".join(out_lines)


def rewrite(path, cues):
    """Serialise the file with new timings, preserving everything else verbatim."""
    text = _read_text(path)
    by_index = {int(cue["index"]): cue for cue in (cues or []) if cue.get("index")}
    ext = _ext_of(path)
    if ext == ".srt":
        return _rewrite_srt(text, by_index)
    if ext == ".vtt":
        return _rewrite_vtt(text, by_index)
    return _rewrite_ass(text, by_index)


def backup(path):
    """Copy the sidecar to <path>.sync-backup. One backup per sidecar - the next sync
    overwrites it, so there is always one undo and no indefinite accumulation."""
    try:
        shutil.copy2(path, path + BACKUP_SUFFIX)
    except OSError as exc:
        raise AppError(f"Could not back up the sidecar: {exc}", 500)


def revert(path):
    """Restore from <path>.sync-backup and remove the backup. Fails loudly if no backup."""
    backup_path = path + BACKUP_SUFFIX
    if not os.path.isfile(backup_path):
        raise AppError("No sync backup is available for this sidecar", 404)
    try:
        shutil.copy2(backup_path, path)
        os.unlink(backup_path)
    except OSError as exc:
        raise AppError(f"Could not restore the backup: {exc}", 500)


def write(path, cues, line_endings="lf"):
    """Backup once, then write the rewritten text through subtitles.normalize_text so the
    saved file matches the encoding/BOM/line-ending conventions the scanner uses.
    """
    serialised = rewrite(path, cues)
    backup(path)
    try:
        data = serialised.encode("utf-8")
        if line_endings == "crlf":
            data = serialised.replace("\n", "\r\n").encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        # Try to restore from the backup we just took, so a failed write never leaves a
        # half-written sidecar behind.
        try:
            revert(path)
        except Exception:
            logger.exception("could not auto-revert sidecar %s after failed write", path)
        raise AppError(f"Could not write the sidecar: {exc}", 500)


def has_backup(path):
    return os.path.isfile(path + BACKUP_SUFFIX)
