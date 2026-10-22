"""Image-based subtitles: VobSub (.idx + .sub) and PGS (.sup).

Text subtitles can be retimed by editing the timestamps in the file. Picture subtitles can be
retimed the same way (the timing lives in the .idx lines, or in the PGS segment headers), but
the user cannot *read* them to pick anchor lines. So this module does two jobs:

* read: decode every subtitle bitmap, OCR it with tesseract and hand back the same cue shape
  `sub_sync.read` returns for .srt/.vtt/.ass. The OCR runs once, in the background, and is
  cached under the config directory. The cache is keyed by the stable identity of each picture
  (the .sub file offset for VobSub, the display-set ordinal for PGS), never by its timestamp,
  so retiming the file does not invalidate it.
* retime: rewrite only the timing fields, in place. The pictures themselves are never touched,
  so a saved sync stays a picture subtitle. The recognised text can additionally be exported
  as a plain .srt next to the original.

Everything below the "public" marker is what the routes use.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from resonance.errors import AppError
from resonance.paths import cache_dir


logger = logging.getLogger(__name__)

IMAGE_EXTS = {".idx", ".sup"}

_MAX_PIXELS = 4_000_000          # sanity cap for a single decoded subtitle bitmap
_MAX_CUE_MS = 60_000            # no picture subtitle is on screen longer than this
_SAVE_EVERY = 25                 # persist OCR progress every N recognised cues

# DVD sub-picture time unit: 1024 ticks of the 90 kHz clock.
_SPU_TICK_MS = 1024.0 / 90.0

# ISO 639-1 / 639-2 codes seen in .idx ids and filenames -> tesseract traineddata names.
_TESS = {
    "en": "eng", "eng": "eng", "nb": "nor", "nob": "nor", "no": "nor", "nor": "nor",
    "nn": "nor", "nno": "nor", "sv": "swe", "swe": "swe", "da": "dan", "dan": "dan",
    "fi": "fin", "fin": "fin", "de": "deu", "ger": "deu", "deu": "deu", "fr": "fra",
    "fre": "fra", "fra": "fra", "es": "spa", "spa": "spa", "it": "ita", "ita": "ita",
    "nl": "nld", "dut": "nld", "nld": "nld", "pt": "por", "por": "por", "pl": "pol",
    "pol": "pol", "ru": "rus", "rus": "rus", "cs": "ces", "cze": "ces", "ces": "ces",
    "hu": "hun", "hun": "hun", "tr": "tur", "tur": "tur", "el": "ell", "gre": "ell",
    "ell": "ell", "ro": "ron", "rum": "ron", "ron": "ron", "ja": "jpn", "jpn": "jpn",
    "ko": "kor", "kor": "kor", "zh": "chi_sim", "chi": "chi_sim", "ar": "ara", "ara": "ara",
    "he": "heb", "heb": "heb", "is": "isl", "ice": "isl", "isl": "isl", "hr": "hrv",
    "hrv": "hrv", "uk": "ukr", "ukr": "ukr", "bg": "bul", "bul": "bul",
}


# ======================================================================================
# helpers: paths, kinds
# ======================================================================================

def _ext(path):
    return os.path.splitext(path)[1].lower()


def is_image(path):
    return _ext(path) in IMAGE_EXTS


def resolve_source(path):
    """Map what the user clicked to the file that carries the timing.

    A VobSub is a pair: the .idx has the timestamps, the .sub has the pictures. Both rows show
    in the file list, so a .sub with an .idx beside it means the .idx. Anything else is
    returned unchanged.
    """
    if _ext(path) == ".sub":
        base = os.path.splitext(path)[0]
        for ext in (".idx", ".IDX", ".Idx"):
            if os.path.isfile(base + ext):
                return base + ext
    return path


def _source(path):
    """resolve_source plus a check that the result really is a picture subtitle (a lone
    MicroDVD .sub is text and must never be read as PGS)."""
    src = resolve_source(path)
    if _ext(src) not in IMAGE_EXTS:
        raise AppError(f"Cannot sync {_ext(src) or 'this'} subtitle format", 400)
    return src


def kind_of(path):
    return "vobsub" if _ext(path) == ".idx" else "pgs"


def _companion_sub(idx_path):
    base = os.path.splitext(idx_path)[0]
    for ext in (".sub", ".SUB", ".Sub"):
        if os.path.isfile(base + ext):
            return base + ext
    raise AppError("The .sub file that belongs to this .idx is missing", 404)


# ======================================================================================
# tesseract
# ======================================================================================

_LANGS = None


def tesseract_available():
    return bool(shutil.which("tesseract"))


def available_langs():
    """Installed tesseract languages (excluding the orientation model)."""
    global _LANGS
    if _LANGS is not None:
        return _LANGS
    langs = []
    if tesseract_available():
        try:
            proc = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20)
            for line in (proc.stdout or "").splitlines()[1:]:
                line = line.strip()
                if line and line != "osd":
                    langs.append(line)
        except (OSError, subprocess.SubprocessError):
            langs = []
    _LANGS = sorted(set(langs))
    return _LANGS


def _tess_lang(code):
    """Best installed tesseract language for a language code. Returns (lang, note)."""
    installed = available_langs()
    wanted = _TESS.get(str(code or "").strip().lower(), "")
    if wanted and wanted in installed:
        return wanted, ""
    if "eng" in installed or not installed:
        note = f"{wanted} is not installed, using eng" if wanted and wanted != "eng" else ""
        return "eng", note
    return installed[0], f"using {installed[0]}"


def detect_lang(src):
    """Language code from the .idx stream id or the file name, '' when unknown."""
    if kind_of(src) == "vobsub":
        try:
            for stream in parse_idx(src)["streams"]:
                if stream["entries"] and stream["id"]:
                    return stream["id"]
        except (OSError, AppError):
            pass
    tokens = os.path.basename(src).lower().split(".")[:-1]
    for token in reversed(tokens):
        if token in _TESS:
            return token
    return ""


def _tesseract(img, lang, psm):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    env = dict(os.environ)
    env["OMP_THREAD_LIMIT"] = "1"      # we run several of these side by side
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--psm", str(psm), "--dpi", "300"],
                          input=buf.getvalue(), capture_output=True, timeout=90, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace").strip()[:300] or "tesseract failed")
    return proc.stdout.decode("utf-8", "replace")


def _clean(text):
    lines = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip().replace("|", "I")
        if not line:
            continue
        if len(line) == 1 and not line.isalnum():
            continue
        lines.append(line)
    return "\n".join(lines)


def _prepare(img):
    """Upscale small DVD bitmaps (tesseract reads ~30px+ glyphs best) and pad them."""
    from PIL import Image, ImageOps

    w, h = img.size
    scale = 3 if h < 50 else 2 if h < 110 else 1
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
    return ImageOps.expand(img, border=24, fill=255)


def ocr_image(img, lang):
    from PIL import ImageOps

    prepared = _prepare(img)
    text = _clean(_tesseract(prepared, lang, 6))
    if not text:                        # a single short line reads better as a "line" page
        text = _clean(_tesseract(prepared, lang, 7))
    if not text:                        # light-on-dark guess went the wrong way round
        text = _clean(_tesseract(ImageOps.invert(prepared), lang, 6))
    return text


# ======================================================================================
# bitmap -> grey image shared by VobSub and PGS
# ======================================================================================

def _planes_to_image(planes, entries):
    """planes: [(w, h, indexed bytes, x, y)]; entries: {colour index: effective brightness}.

    Brightness is luminance weighted by opacity, so a transparent background and a black
    outline both drop out and the (brightest) text ends up black on white, which is what
    tesseract wants. Colours keep their relative brightness, so anti-aliasing survives.
    """
    from PIL import Image, ImageChops, ImageOps

    used = set()
    for _w, _h, data, _x, _y in planes:
        used.update(set(data) & entries.keys())
    if not used:
        return None
    values = [entries[c] for c in used]
    lo, hi = min(values), max(values)
    span = hi - lo
    table = bytearray([255] * 256)
    for colour in used:
        table[colour] = 0 if span < 8 else int(round(255 - (entries[colour] - lo) / span * 255))
    table = bytes(table)
    min_x = min(p[3] for p in planes)
    min_y = min(p[4] for p in planes)
    max_x = max(p[3] + p[0] for p in planes)
    max_y = max(p[4] + p[1] for p in planes)
    canvas = Image.new("L", (max_x - min_x, max_y - min_y), 255)
    for w, h, data, x, y in planes:
        part = Image.frombytes("L", (w, h), bytes(data).translate(table))
        box = (x - min_x, y - min_y, x - min_x + w, y - min_y + h)
        canvas.paste(ImageChops.darker(canvas.crop(box), part), box)
    bbox = ImageOps.invert(canvas).getbbox()
    if not bbox:
        return None
    return canvas.crop(bbox)


# ======================================================================================
# VobSub: .idx
# ======================================================================================

_TS_LINE = re.compile(r"(timestamp:\s*)([+-]?)(\d+):(\d+):(\d+):(\d+)", re.I)
_FILEPOS = re.compile(r"filepos:\s*([0-9a-fA-F]+)", re.I)


def _clock_ms(sign, h, m, s, ms):
    value = ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)
    return -value if sign == "-" else value


def _fmt_clock(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms3 = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ms3:03d}"


def parse_idx(path):
    """{lines, palette, size, delay_ms, streams: [{id, index, entries: [{line, ms, pos}]}]}."""
    with open(path, "rb") as handle:
        text = handle.read().decode("latin-1")
    lines = text.splitlines(keepends=True)
    info = {"lines": lines, "palette": [], "size": (720, 480), "delay_ms": 0, "streams": []}
    cur = None
    for n, line in enumerate(lines):
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("palette:"):
            palette = []
            for value in stripped.split(":", 1)[1].split(","):
                value = value.strip()
                try:
                    palette.append(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))
                except ValueError:
                    palette.append((0, 0, 0))
            info["palette"] = palette
        elif low.startswith("size:"):
            m = re.match(r"size:\s*(\d+)\s*x\s*(\d+)", low)
            if m:
                info["size"] = (int(m.group(1)), int(m.group(2)))
        elif low.startswith("delay:"):
            m = re.search(r"([+-]?)(\d+):(\d+):(\d+):(\d+)", low)
            if m:
                info["delay_ms"] = _clock_ms(*m.groups())
        elif low.startswith("id:"):
            m = re.match(r"id:\s*([^,]*),\s*index:\s*(\d+)", low)
            lang = m.group(1).strip() if m else ""
            cur = {"id": lang if lang.isalpha() else "",
                   "index": int(m.group(2)) if m else len(info["streams"]), "entries": []}
            info["streams"].append(cur)
        elif low.startswith("timestamp:"):
            t = _TS_LINE.search(line)
            p = _FILEPOS.search(line)
            if not t or not p:
                continue
            if cur is None:
                cur = {"id": "", "index": 0, "entries": []}
                info["streams"].append(cur)
            cur["entries"].append({"line": n, "ms": _clock_ms(*t.groups()[1:]), "pos": int(p.group(1), 16)})
    return info


# ======================================================================================
# VobSub: .sub (MPEG program stream carrying DVD sub-pictures)
# ======================================================================================

class _Buf:
    def __init__(self, handle, pos):
        self.handle = handle
        handle.seek(pos)
        self.data = bytearray()

    def need(self, n):
        while len(self.data) < n:
            chunk = self.handle.read(max(4096, n - len(self.data)))
            if not chunk:
                return False
            self.data += chunk
        return True


def _pes_payload(pes):
    """Payload of a private-stream-1 PES packet body (after the 6 byte start/length)."""
    if not pes:
        return b""
    if (pes[0] & 0xC0) == 0x80:                        # MPEG-2 PES header
        if len(pes) < 3:
            return b""
        return bytes(pes[3 + pes[2]:])
    i = 0                                              # MPEG-1 PES header
    while i < len(pes) and pes[i] == 0xFF:
        i += 1
    if i < len(pes) and (pes[i] & 0xC0) == 0x40:
        i += 2
    if i < len(pes):
        flag = pes[i]
        if (flag & 0xF0) == 0x20:
            i += 5
        elif (flag & 0xF0) == 0x30:
            i += 10
        else:
            i += 1
    return bytes(pes[i:])


def _read_spu(handle, pos, limit=1 << 20):
    """One complete sub-picture unit starting at file offset `pos`, or b''."""
    buf = _Buf(handle, pos)
    spu = bytearray()
    total = None
    substream = None
    i = 0
    while i < limit:
        if not buf.need(i + 4):
            break
        d = buf.data
        if d[i:i + 3] != b"\x00\x00\x01":
            break
        sid = d[i + 3]
        if sid == 0xBA:                                # pack header
            if not buf.need(i + 14):
                break
            i += 14 + (d[i + 13] & 7) if (d[i + 4] >> 6) == 1 else 12
            continue
        if not buf.need(i + 6):
            break
        plen = (d[i + 4] << 8) | d[i + 5]
        if sid == 0xBD:
            if not buf.need(i + 6 + plen):
                break
            payload = _pes_payload(buf.data[i + 6:i + 6 + plen])
            if payload and 0x20 <= payload[0] <= 0x3F:
                if substream is None:
                    substream = payload[0]
                if payload[0] == substream:
                    spu += payload[1:]
            if total is None and len(spu) >= 2:
                total = (spu[0] << 8) | spu[1]
            if total is not None and len(spu) >= (total or 2):
                break
        i += 6 + plen
    if total:
        return bytes(spu[:total])
    return bytes(spu)


def _u16(b, i):
    return (b[i] << 8) | b[i + 1]


def _parse_spu(spu):
    """Control data of one sub-picture, or None when it has no bitmap."""
    if len(spu) < 6:
        return None
    ctrl = _u16(spu, 2)
    info = {"start_date": None, "stop_date": None, "colors": [0, 1, 2, 3], "alphas": [0, 15, 15, 15],
            "area": None, "top": None, "bottom": None, "ctrl": ctrl}
    best_alpha = -1
    pos = ctrl
    guard = 0
    try:
        while 0 < pos < len(spu) and guard < 16:
            guard += 1
            date = _u16(spu, pos)
            nxt = _u16(spu, pos + 2)
            p = pos + 4
            while p < len(spu):
                cmd = spu[p]
                p += 1
                if cmd in (0x00, 0x01):
                    if info["start_date"] is None:
                        info["start_date"] = date
                elif cmd == 0x02:
                    info["stop_date"] = date
                elif cmd == 0x03:
                    a, b = spu[p], spu[p + 1]
                    info["colors"] = [b & 15, b >> 4, a & 15, a >> 4]
                    p += 2
                elif cmd == 0x04:
                    a, b = spu[p], spu[p + 1]
                    alphas = [b & 15, b >> 4, a & 15, a >> 4]
                    if sum(alphas) > best_alpha:
                        best_alpha = sum(alphas)
                        info["alphas"] = alphas
                    p += 2
                elif cmd == 0x05:
                    x1 = (spu[p] << 4) | (spu[p + 1] >> 4)
                    x2 = ((spu[p + 1] & 15) << 8) | spu[p + 2]
                    y1 = (spu[p + 3] << 4) | (spu[p + 4] >> 4)
                    y2 = ((spu[p + 4] & 15) << 8) | spu[p + 5]
                    info["area"] = (x1, y1, x2, y2)
                    p += 6
                elif cmd == 0x06:
                    info["top"], info["bottom"] = _u16(spu, p), _u16(spu, p + 2)
                    p += 4
                elif cmd == 0xFF:
                    break
                else:
                    break
            if nxt == pos or nxt <= pos:
                break
            pos = nxt
    except IndexError:
        pass
    if not info["area"] or info["top"] is None or info["bottom"] is None:
        return None
    x1, y1, x2, y2 = info["area"]
    info["w"], info["h"] = x2 - x1 + 1, y2 - y1 + 1
    if info["w"] <= 0 or info["h"] <= 0 or info["w"] * info["h"] > _MAX_PIXELS:
        return None
    return info


def _decode_vob_rle(spu, info):
    w, h = info["w"], info["h"]
    out = bytearray(w * h)
    fields = ((info["top"], info["bottom"]), (info["bottom"], info["ctrl"]))
    for field, (start, end) in enumerate(fields):
        data = spu[start:end]
        total = len(data) * 2
        k = 0
        y, x = field, 0

        def nib(at):
            return (data[at >> 1] >> (4 if at % 2 == 0 else 0)) & 15

        while y < h and k < total:
            v = nib(k)
            k += 1
            if v < 4:
                if k >= total:
                    break
                v = (v << 4) | nib(k)
                k += 1
                if v < 0x10:
                    if k >= total:
                        break
                    v = (v << 4) | nib(k)
                    k += 1
                    if v < 0x40:
                        if k >= total:
                            break
                        v = (v << 4) | nib(k)
                        k += 1
            run = v >> 2
            colour = v & 3
            if run == 0:
                run = w - x
            run = min(run, w - x)
            if colour and run > 0:
                out[y * w + x:y * w + x + run] = bytes([colour]) * run
            x += run
            if x >= w:
                x = 0
                y += 2
                if k & 1:
                    k += 1
    return out


def _render_vob(handle, item, palette):
    spu = _read_spu(handle, item["pos"])
    info = _parse_spu(spu)
    if not info:
        return None
    data = _decode_vob_rle(spu, info)
    entries = {}
    for slot in range(4):
        alpha = info["alphas"][slot]
        if alpha <= 0 or slot == 0:
            continue
        index = info["colors"][slot]
        r, g, b = palette[index] if index < len(palette) else (255, 255, 255)
        entries[slot] = (0.299 * r + 0.587 * g + 0.114 * b) * alpha / 15.0
    return _planes_to_image([(info["w"], info["h"], data, 0, 0)], entries)


def _date_ms(date):
    return int(round(date * _SPU_TICK_MS))


def _enumerate_vobsub(idx_path):
    info = parse_idx(idx_path)
    streams = [s for s in info["streams"] if s["entries"]]
    if not streams:
        raise AppError("That .idx has no subtitle entries", 400)
    entries = streams[0]["entries"]
    sub_path = _companion_sub(idx_path)
    delay = info["delay_ms"]
    palette = info["palette"] or [(i * 17, i * 17, i * 17) for i in range(16)]
    items = []
    with open(sub_path, "rb") as handle:
        for i, entry in enumerate(entries):
            try:
                spu_info = _parse_spu(_read_spu(handle, entry["pos"]))
            except (OSError, ValueError):
                spu_info = None
            if not spu_info:
                continue
            base = entry["ms"] + delay
            sd = spu_info["start_date"] or 0
            start = base + _date_ms(sd)
            end = None
            if spu_info["stop_date"] is not None and spu_info["stop_date"] > sd:
                end = base + _date_ms(spu_info["stop_date"])
            following = entries[i + 1]["ms"] + delay if i + 1 < len(entries) else None
            if end is None:
                end = following if following is not None else start + 3000
            # A sub-picture is replaced by the next one, so it can never outlast it. Some
            # encoders write an "until further notice" stop time, which would otherwise show up
            # as a cue lasting hours.
            if following is not None and following > start + 100:
                end = min(end, following)
            end = min(end, start + _MAX_CUE_MS)
            items.append({"key": str(entry["pos"]), "pos": entry["pos"], "start_ms": max(0, start),
                          "end_ms": max(end, start + 500)})
    if not items:
        raise AppError("Could not decode any subtitle pictures from that .sub", 400)
    return {"items": items, "palette": palette, "sub_path": sub_path}


# ======================================================================================
# PGS: .sup
# ======================================================================================

def _decode_pgs_rle(data, w, h):
    out = bytearray(w * h)
    x = y = i = 0
    n = len(data)
    while i < n and y < h:
        b = data[i]
        i += 1
        if b:
            colour, run = b, 1
        else:
            if i >= n:
                break
            b2 = data[i]
            i += 1
            if b2 == 0:
                x = 0
                y += 1
                continue
            flag = b2 & 0xC0
            if flag == 0x00:
                run, colour = b2 & 0x3F, 0
            elif flag == 0x40:
                if i >= n:
                    break
                run, colour = ((b2 & 0x3F) << 8) | data[i], 0
                i += 1
            elif flag == 0x80:
                if i >= n:
                    break
                run, colour = b2 & 0x3F, data[i]
                i += 1
            else:
                if i + 1 >= n:
                    break
                run, colour = ((b2 & 0x3F) << 8) | data[i], data[i + 1]
                i += 2
        run = min(run, w - x)
        if colour and run > 0:
            out[y * w + x:y * w + x + run] = bytes([colour]) * run
        x += max(run, 0)
    return out


def _enumerate_pgs(path):
    items = []
    palettes = {}
    objects = {}
    pcs = None
    open_item = None
    with open(path, "rb") as handle:
        pos = 0
        while True:
            handle.seek(pos)
            head = handle.read(13)
            if len(head) < 13 or head[:2] != b"PG":
                break
            pts, _dts, typ, length = struct.unpack(">IIBH", head[2:])
            body = pos + 13
            if typ == 0x16 and length >= 11:                    # presentation composition
                p = handle.read(length)
                _w, _h, _fr, _no, state, pal_flag, pal_id, count = struct.unpack(">HHBHBBBB", p[:11])
                if state & 0x80:                                # epoch start: forget everything
                    palettes.clear()
                    objects.clear()
                refs = []
                q = 11
                for _ in range(count):
                    if q + 8 > len(p):
                        break
                    oid, _wid, crop, x, y = struct.unpack(">HBBHH", p[q:q + 8])
                    q += 8 + (8 if crop & 0x40 else 0)
                    refs.append((oid, x, y))
                pcs = {"pts": pts, "pal_flag": pal_flag, "pal_id": pal_id, "objs": refs}
            elif typ == 0x14 and length >= 2:                   # palette
                p = handle.read(length)
                merged = dict(palettes.get(p[0], {}))
                for q in range(2, len(p) - 4, 5):
                    merged[p[q]] = (p[q + 1], p[q + 2], p[q + 3], p[q + 4])
                palettes[p[0]] = merged
            elif typ == 0x15 and length >= 4:                   # object (bitmap) data
                p = handle.read(min(length, 11))
                oid = _u16(p, 0)
                flags = p[3]
                if flags & 0x80 and len(p) >= 11:
                    w, h = _u16(p, 7), _u16(p, 9)
                    objects[oid] = {"w": w, "h": h, "refs": [(body + 11, length - 11)]}
                elif oid in objects:
                    objects[oid] = {**objects[oid], "refs": objects[oid]["refs"] + [(body + 4, length - 4)]}
            elif typ == 0x80 and pcs is not None:               # end of display set
                ms = pcs["pts"] // 90
                shown = [(oid, x, y) for oid, x, y in pcs["objs"] if oid in objects]
                if not shown:
                    if open_item is not None:
                        open_item["end_ms"] = max(ms, open_item["start_ms"] + 200)
                        open_item = None
                elif not (pcs["pal_flag"] & 0x80 and open_item is not None):
                    if open_item is not None:
                        open_item["end_ms"] = max(ms, open_item["start_ms"] + 200)
                    open_item = {"key": str(len(items)), "start_ms": ms, "end_ms": ms + 3000,
                                 "palette": palettes.get(pcs["pal_id"], {}),
                                 "objs": [(objects[oid]["w"], objects[oid]["h"], tuple(objects[oid]["refs"]), x, y)
                                          for oid, x, y in shown]}
                    items.append(open_item)
                pcs = None
            pos = body + length
    if not items:
        raise AppError("Could not find any subtitle pictures in that .sup", 400)
    return {"items": items}


def _render_pgs(handle, item):
    entries = {}
    for colour, (y, _cr, _cb, alpha) in item["palette"].items():
        if colour and alpha:
            entries[colour] = y * alpha / 255.0
    planes = []
    for w, h, refs, x, y in item["objs"]:
        if w * h > _MAX_PIXELS or w <= 0 or h <= 0:
            continue
        chunks = []
        for off, size in refs:
            handle.seek(off)
            chunks.append(handle.read(size))
        planes.append((w, h, _decode_pgs_rle(b"".join(chunks), w, h), x, y))
    if not planes:
        return None
    return _planes_to_image(planes, entries)


# ======================================================================================
# enumeration memo + OCR cache
# ======================================================================================

_ENUM = {}
_ENUM_LOCK = threading.Lock()


def _signature(src):
    parts = [kind_of(src), os.path.realpath(src)]
    for p in ([src, _companion_sub(src)] if kind_of(src) == "vobsub" else [src]):
        st = os.stat(p)
        parts += [str(st.st_size), str(st.st_mtime_ns)]
    return "|".join(parts)


def _items(src):
    sig = _signature(src)
    with _ENUM_LOCK:
        hit = _ENUM.get(sig)
    if hit:
        return hit
    data = _enumerate_vobsub(src) if kind_of(src) == "vobsub" else _enumerate_pgs(src)
    with _ENUM_LOCK:
        if len(_ENUM) > 6:
            _ENUM.pop(next(iter(_ENUM)))
        _ENUM[sig] = data
    return data


def _cache_path(src):
    """Identity of the pictures, not of the timing: a retime rewrites the .idx / .sup headers
    but must keep the recognised text. VobSub: the .sub (never modified by us). PGS: path and
    size (an in-place retime keeps the size)."""
    real = os.path.realpath(src)
    if kind_of(src) == "vobsub":
        sub = _companion_sub(src)
        st = os.stat(sub)
        ident = f"vob|{os.path.realpath(sub)}|{st.st_size}|{st.st_mtime_ns}"
    else:
        ident = f"pgs|{real}|{os.stat(src).st_size}"
    folder = os.path.join(cache_dir(), "video", "ocr")
    return os.path.join(folder, hashlib.sha1(ident.encode("utf-8", "replace")).hexdigest() + ".json")


def _cache_load(src):
    try:
        path = _cache_path(src)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        try:
            os.utime(path, None)
        except OSError:
            pass
        if isinstance(data, dict) and isinstance(data.get("texts"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"lang": "", "texts": {}}


def _cache_save(src, lang, texts):
    path = _cache_path(src)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"lang": lang, "texts": texts, "saved": int(time.time())}, handle)
    os.replace(tmp, path)


# ======================================================================================
# OCR jobs
# ======================================================================================

_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _status(src, items, cache):
    job = _JOBS.get(os.path.realpath(src))
    texts = cache.get("texts") or {}
    done = sum(1 for it in items if it["key"] in texts)
    detected = detect_lang(src)
    lang, note = _tess_lang(cache.get("lang") or detected)
    state = "done" if items and done >= len(items) else "needed"
    error = ""
    if job:
        if job["state"] == "running":
            state, done, error = "running", job["done"], ""
        elif job["state"] == "error":
            state, error = "error", job["error"]
        if job["state"] in ("running", "error"):
            lang = job["lang"]
    return {"state": state, "done": done, "total": len(items), "lang": lang, "lang_note": note,
            "detected": detected, "langs": available_langs(), "tesseract": tesseract_available(),
            "error": error}


def ocr_status(path):
    src = _source(path)
    return _status(src, _items(src)["items"], _cache_load(src))


def start_ocr(path, lang=None, force=False):
    src = _source(path)
    if not tesseract_available():
        raise AppError("tesseract is not installed in this container. Rebuild the image to enable OCR.", 500)
    data = _items(src)
    key = os.path.realpath(src)
    with _JOBS_LOCK:
        for other, job in _JOBS.items():
            if job["state"] == "running":
                if other == key:
                    return _status(src, data["items"], _cache_load(src))
                raise AppError(f"Another subtitle is being recognised ({os.path.basename(other)}). "
                               "Wait for it to finish or cancel it first.", 409)
        cache = _cache_load(src)
        chosen, _note = _tess_lang(lang or cache.get("lang") or detect_lang(src))
        job = {"state": "running", "done": 0, "total": len(data["items"]), "error": "", "lang": chosen,
               "cancel": False}
        _JOBS[key] = job
    thread = threading.Thread(target=_worker, args=(src, data, chosen, job, bool(force)), daemon=True,
                              name="sub-ocr")
    thread.start()
    return _status(src, data["items"], _cache_load(src))


def cancel_ocr(path):
    src = _source(path)
    job = _JOBS.get(os.path.realpath(src))
    if job and job["state"] == "running":
        job["cancel"] = True
    return ocr_status(src)


def _renderer(src, data):
    if kind_of(src) == "vobsub":
        palette = data["palette"]
        sub_path = data["sub_path"]

        def render(item):
            with open(sub_path, "rb") as handle:
                return _render_vob(handle, item, palette)
        return render

    def render_pgs(item):
        with open(src, "rb") as handle:
            return _render_pgs(handle, item)
    return render_pgs


def _worker(src, data, lang, job, force):
    from curator.video import work_track

    name = os.path.basename(src)
    track = work_track.Tracked("sub-ocr", f"Recognising {name}", len(data["items"]))
    try:
        cache = _cache_load(src)
        texts = dict(cache.get("texts") or {}) if (cache.get("lang") == lang and not force) else {}
        todo = [it for it in data["items"] if it["key"] not in texts]
        job["done"] = len(data["items"]) - len(todo)
        render = _renderer(src, data)
        stats = {"ok": 0, "fail": 0}

        def task(item):
            if job["cancel"]:
                return item, None
            try:
                img = render(item)
                text = ocr_image(img, lang) if img is not None else ""
                stats["ok"] += 1
                return item, text
            except Exception as exc:                    # one bad picture must not end the run
                stats["fail"] += 1
                logger.warning("ocr failed for %s cue %s: %s", os.path.basename(src), item["key"], exc)
                if stats["fail"] >= 10 and stats["ok"] == 0:
                    job["cancel"] = True
                    job["error"] = f"OCR keeps failing: {exc}"
                return item, ""

        since = 0
        workers = max(1, min(4, os.cpu_count() or 2))
        with ThreadPoolExecutor(workers) as pool:
            for item, text in pool.map(task, todo):
                if text is None:
                    continue
                texts[item["key"]] = text
                job["done"] += 1
                track.update(job["done"], f"Recognising {name}")
                since += 1
                if since >= _SAVE_EVERY:
                    _cache_save(src, lang, texts)
                    since = 0
        _cache_save(src, lang, texts)
        if job["error"]:
            job["state"] = "error"
        else:
            job["state"] = "cancelled" if job["cancel"] else "done"
        track.finish({"error": "failed", "cancelled": "cancelled"}.get(job["state"], "completed"),
                     {"error": f"OCR of {name} failed: {job['error'][:120]}",
                      "cancelled": f"OCR of {name} cancelled"}.get(job["state"], f"Recognised {name}"),
                     job["done"])
        _trim_cache()
    except Exception as exc:
        logger.exception("subtitle OCR failed for %s", src)
        job["state"] = "error"
        job["error"] = str(exc) or exc.__class__.__name__
        track.finish("failed", f"OCR of {name} failed: {job['error'][:120]}")


def _trim_cache():
    try:
        from curator.video import cache_store, config

        cache_store.trim_all(config.current(), keep=None)
    except Exception:
        logger.debug("cache trim skipped", exc_info=True)


# ======================================================================================
# public: read / retime / export
# ======================================================================================

def read(path):
    """Same shape as sub_sync.read, plus {image: True, ocr: {...}}. `cues` stays empty until
    the OCR has covered every picture."""
    src = _source(path)
    data = _items(src)
    cache = _cache_load(src)
    status = _status(src, data["items"], cache)
    texts = cache.get("texts") or {}
    cues = []
    if status["state"] == "done":
        for i, item in enumerate(data["items"], 1):
            cues.append({"index": i, "start_ms": item["start_ms"], "end_ms": item["end_ms"],
                         "text": texts.get(item["key"], "")})
    duration = max((it["end_ms"] for it in data["items"]), default=0)
    out = {"format": kind_of(src), "image": True, "duration_ms": duration, "cues": cues, "ocr": status}
    if kind_of(src) == "vobsub":
        try:
            streams = [s for s in parse_idx(src)["streams"] if s["entries"]]
            out["streams"] = [{"id": s["id"], "index": s["index"], "count": len(s["entries"])} for s in streams]
        except (OSError, AppError):
            out["streams"] = []
    return out


def _retime_idx(path, retime):
    info = parse_idx(path)
    lines = list(info["lines"])
    for stream in info["streams"]:
        for entry in stream["entries"]:
            line = lines[entry["line"]]
            new_ms = max(0, int(round(retime(entry["ms"]))))
            lines[entry["line"]] = _TS_LINE.sub(lambda m: m.group(1) + _fmt_clock(new_ms), line, count=1)
    with open(path, "wb") as handle:
        handle.write("".join(lines).encode("latin-1"))


def _tick(retime, value):
    return max(0, min(0xFFFFFFFF, int(round(retime(value / 90.0) * 90))))


def _retime_sup(path, retime):
    with open(path, "r+b") as handle:
        pos = 0
        while True:
            handle.seek(pos)
            head = handle.read(13)
            if len(head) < 13 or head[:2] != b"PG":
                break
            pts, dts, _typ, length = struct.unpack(">IIBH", head[2:])
            new_pts = _tick(retime, pts)
            new_dts = _tick(retime, dts) if dts else 0
            if (new_pts, new_dts) != (pts, dts):
                handle.seek(pos + 2)
                handle.write(struct.pack(">II", new_pts, new_dts))
            pos += 13 + length


def retime(path, retime_fn):
    """Back up, then rewrite the timing of every picture in place. `retime_fn(ms) -> ms`.

    VobSub: the timestamp of every entry in the .idx (all language streams, the video is the
    same). The .sub is untouched. PGS: the PTS/DTS of every segment in the .sup.
    """
    from curator.video import sub_sync

    src = _source(path)
    sub_sync.backup(src)
    try:
        if kind_of(src) == "vobsub":
            _retime_idx(src, retime_fn)
        else:
            _retime_sup(src, retime_fn)
    except Exception as exc:
        try:
            sub_sync.revert(src)
        except Exception:
            logger.exception("could not auto-revert %s after a failed retime", src)
        raise AppError(f"Could not write the subtitle: {exc}", 500)


def export_srt(path, cues, line_endings="lf", overwrite=False):
    """Write the recognised (and synced / edited) text as <name>.srt beside the picture sub."""
    from curator.video import sub_sync

    src = _source(path)
    target = os.path.splitext(src)[0] + ".srt"
    if os.path.exists(target):
        if not overwrite:
            raise AppError(f"{os.path.basename(target)} already exists", 409)
        sub_sync.backup(target)
    out = []
    n = 0
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        n += 1
        out += [str(n), f"{sub_sync._ms_to_srt(cue['start_ms'])} --> {sub_sync._ms_to_srt(cue['end_ms'])}", text, ""]
    if not n:
        raise AppError("There is no recognised text to export", 400)
    body = "\n".join(out)
    if line_endings == "crlf":
        body = body.replace("\n", "\r\n")
    try:
        with open(target, "wb") as handle:
            handle.write(body.encode("utf-8"))
    except OSError as exc:
        raise AppError(f"Could not write {os.path.basename(target)}: {exc}", 500)
    return target
