"""Subtitle sidecars: UTF-8 without BOM, one line-ending style, and <stem>.<lang>[.flags].<ext> names.

Language tags follow the configured standard (ISO 639-1 "en" or ISO 639-2 "eng"); Brazilian
Portuguese and Simplified/Traditional Chinese keep their regional tag. Flags are written in a fixed
order: forced, default, sdh (cc and hi become sdh), commentary.

Duplicates are found by a SHA-256 of the subtitle text (encoding, BOM and line endings ignored),
against the other sidecars of the same video and against its embedded text subtitle streams.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

from charset_normalizer import from_bytes

from curator.video import languages, naming, writes
from resonance.errors import AppError

EMBED_TIMEOUT = 900

TEXT_EXTS = {".srt", ".vtt", ".ass", ".ssa", ".smi"}
PREFERRED = ("utf_8", "cp1252", "iso8859_15", "iso8859_1", "cp1250", "cp1251", "cp1253", "cp1254", "cp1255",
             "cp1256", "cp1257", "iso8859_2", "koi8_r", "gb18030", "big5", "shift_jis", "euc_kr")
FLAG_ORDER = ("forced", "default", "sdh", "commentary")
_FLAGS = {"forced": "forced", "foreign": "forced", "default": "default", "sdh": "sdh", "cc": "sdh", "hi": "sdh",
          "commentary": "commentary", "comment": "commentary"}
_REGIONAL = {"pt-br": ("pt-br", "pob"), "pob": ("pt-br", "pob"), "pt-pt": ("pt-pt", "por"),
             "zh-hans": ("zh-hans", "chi"), "zh-cn": ("zh-hans", "chi"), "zh-hant": ("zh-hant", "zho"),
             "zh-tw": ("zh-hant", "zho")}
_ISO1 = {}
for _alias, _code in languages._LANG_ALIASES.items():
    if len(_alias) == 2 and _code not in _ISO1:
        _ISO1[_code] = _alias


def lang_tag(code, standard):
    if standard == "iso639-1":
        return _ISO1.get(code, code)
    return code


def parse(video_stem, sub_name):
    """{lang, region, flags, rest, ext} for a sidecar of this video, or None when it belongs to another file."""
    stem, ext = os.path.splitext(sub_name)
    lowered, video = stem.lower(), video_stem.lower()
    if lowered != video and not lowered.startswith(video + "."):
        return None
    lang, region, flags, rest = "", None, set(), []
    for token in [token for token in stem[len(video_stem):].split(".") if token]:
        low = token.lower()
        if not lang and low in _REGIONAL:
            region = low
            lang = _REGIONAL[low][1]
            continue
        if low in _FLAGS:
            flags.add(_FLAGS[low])
            continue
        code = languages._LANG_ALIASES.get(low.replace("_", "-"), "")
        if code and code != "und":
            if not lang:
                lang = code
                continue
            if code == languages.normalize_lang(lang):
                continue  # the same language written twice, such as nor.nb or en.eng
        rest.append(token)
    return {"lang": lang, "region": region, "flags": [flag for flag in FLAG_ORDER if flag in flags],
            "rest": rest, "ext": ext.lower()}


def target_name(video_stem, info, standard):
    if not info["lang"]:
        return None
    if info["region"]:
        iso1, iso2 = _REGIONAL[info["region"]]
        tag = iso1 if standard == "iso639-1" else iso2
    else:
        tag = lang_tag(info["lang"], standard)
    tokens = [tag] + info["flags"] + info["rest"]
    return f"{video_stem}.{'.'.join(tokens)}{info['ext']}"


def _best_match(raw):
    """Short subtitles often score the same in several code pages; prefer the ones subtitles really use."""
    results = list(from_bytes(raw))
    if not results:
        return None
    floor = min(result.chaos for result in results)
    close = [result for result in results if result.chaos <= floor + 0.01]

    def rank(result):
        name = result.encoding.lower()
        return PREFERRED.index(name) if name in PREFERRED else len(PREFERRED)

    return min(close, key=lambda result: (rank(result), -result.coherence))


def normalize_text(path, line_endings="lf", threshold=0.8, write=True):
    """Rewrite a text subtitle as UTF-8 without BOM. Returns (changed, encoding read).

    With write=False nothing is written; the answer says what a real run would do."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw:
        return False, None
    try:
        text, encoding = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        best = _best_match(raw)
        if best is None or best.chaos > 1 - threshold:
            return False, None
        text, encoding = str(best), best.encoding
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if line_endings == "crlf":
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if data == raw:
        return False, encoding
    if write:
        writes.atomic_write(path, data)
    return True, encoding


def preview(video_path, cfg):
    """What Normalize subtitles would do to one video's sidecars, without touching a file.

    Entries are {from, to, dir}; `to` is the new name for a rename, or a short note for the other changes.
    A sidecar that is renamed and also re-encoded is listed once for each."""
    moves, texts = plan(video_path, cfg)
    entries = [dict(move) for move in moves]
    for path in texts:
        try:
            changed, encoding = normalize_text(path, cfg.get("sub_line_endings", "lf"), write=False)
        except OSError:
            continue
        if changed:
            entries.append({"from": path, "to": f"Re-encode to UTF-8 (read as {encoding})", "dir": False})
        elif encoding is None:
            entries.append({"from": path, "to": "Left alone: encoding not recognised with confidence", "dir": False})
    try:
        for path, kept in external_duplicates(video_path, cfg):
            note = "Remove" if cfg.get("sub_purge_duplicates", False) else "Duplicate (purging is off)"
            entries.append({"from": path, "to": f"{note}: same text as {os.path.basename(kept)}", "dir": False})
    except OSError:
        pass
    return entries


def plan(video_path, cfg):
    """Renames for the subtitle sidecars of one video: [{from, to}] plus the files to re-encode."""
    folder, name = os.path.split(video_path)
    video_stem = os.path.splitext(name)[0]
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return [], []
    moves, texts = [], []
    for other in names:
        if naming.ext(other) not in naming.SUBTITLE_EXTS:
            continue
        info = parse(video_stem, other)
        if not info:
            continue
        path = os.path.join(folder, other)
        if cfg.get("sub_charset", True) and info["ext"] in TEXT_EXTS:
            texts.append(path)
        if cfg.get("sub_rename", True):
            target = target_name(video_stem, info, cfg.get("sub_lang_standard", "iso639-2"))
            if not target and other != f"{os.path.splitext(other)[0]}{info['ext']}":
                target = f"{os.path.splitext(other)[0]}{info['ext']}"
            if target and target != other:
                moves.append({"from": path, "to": os.path.join(folder, target), "dir": False})
    return moves, texts


def _decoded(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        best = _best_match(raw)
        return str(best) if best is not None else None


def text_digest(text):
    """SHA-256 of subtitle text with BOM, line endings, trailing spaces and blank-line runs ignored."""
    lines = [line.rstrip() for line in text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    kept, blank = [], False
    for line in lines:
        if not line:
            if kept and not blank:
                kept.append("")
            blank = True
            continue
        kept.append(line)
        blank = False
    return hashlib.sha256("\n".join(kept).strip().encode("utf-8")).hexdigest()


def file_digest(path):
    """Content hash of one sidecar: normalized text for text formats, raw bytes otherwise."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if naming.ext(path) in TEXT_EXTS:
        text = _decoded(raw)
        if text is not None:
            return text_digest(text)
    return hashlib.sha256(raw).hexdigest()


def _keep_rank(video_stem, name, info, standard):
    conforms = target_name(video_stem, info, standard) == name
    return (not info["lang"], not conforms, -len(info["flags"]), len(name), name)


def external_duplicates(video_path, cfg):
    """Sidecars of one video with the same content as another sidecar: [(duplicate, kept)]."""
    folder, name = os.path.split(video_path)
    video_stem = os.path.splitext(name)[0]
    standard = cfg.get("sub_lang_standard", "iso639-2")
    groups = {}
    for other in sorted(os.listdir(folder)):
        if naming.ext(other) not in naming.SUBTITLE_EXTS or naming.ext(other) in (".idx", ".sub"):
            continue
        info = parse(video_stem, other)
        if not info:
            continue
        try:
            digest = file_digest(os.path.join(folder, other))
        except OSError:
            continue
        groups.setdefault(digest, []).append((other, info))
    found = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: _keep_rank(video_stem, item[0], item[1], standard))
        keep, keep_info = members[0]
        for other, info in members[1:]:
            if info["lang"] and keep_info["lang"] and info["lang"] != keep_info["lang"]:
                continue
            found.append((os.path.join(folder, other), os.path.join(folder, keep)))
    return found


_EMBED_FORMATS = {"subrip": ("copy", "srt"), "ass": ("copy", "ass"), "ssa": ("copy", "ass"),
                  "webvtt": ("copy", "webvtt"), "mov_text": ("srt", "srt"), "text": ("srt", "srt")}


def embedded_digests(video_path, timeout=EMBED_TIMEOUT):
    """Hashes of the embedded text subtitle streams, extracted with ffmpeg in one pass."""
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return {}
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
                            "stream=index,codec_name:stream_tags=language", "-of", "json", "--", video_path],
                           capture_output=True, text=True, timeout=60)
    try:
        streams = json.loads(probe.stdout or "{}").get("streams") or []
    except ValueError:
        return {}
    streams = [stream for stream in streams if stream.get("codec_name") in _EMBED_FORMATS]
    if not streams:
        return {}
    work = tempfile.mkdtemp(prefix="curator-subs-")
    try:
        command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", video_path]
        outputs = {}
        for stream in streams:
            codec, fmt = _EMBED_FORMATS[stream["codec_name"]]
            out = os.path.join(work, f"{stream['index']}.{fmt}")
            command += ["-map", f"0:{stream['index']}", "-c:s", codec, "-f", fmt, out]
            label = (stream.get("tags") or {}).get("language") or "und"
            outputs[out] = f"embedded track {stream['index']} ({label})"
        subprocess.run(command, capture_output=True, timeout=timeout)
        found = {}
        for out, label in outputs.items():
            if os.path.isfile(out) and os.path.getsize(out):
                with open(out, "rb") as handle:
                    text = _decoded(handle.read())
                if text:
                    found.setdefault(text_digest(text), label)
        return found
    finally:
        shutil.rmtree(work, ignore_errors=True)


def purge_duplicates(video_path, cfg, log):
    """Remove sidecars that repeat another sidecar or an embedded stream. Returns the number removed.

    With sub_purge_duplicates off the duplicates are only logged. Comparing with embedded streams
    reads the whole video file, so it only runs when purging is on.
    """
    purge = cfg.get("sub_purge_duplicates", False)
    found = [(path, os.path.basename(kept)) for path, kept in external_duplicates(video_path, cfg)]
    if purge:
        flagged = {path for path, _ in found}
        texts = [os.path.join(os.path.dirname(video_path), name) for name in sorted(os.listdir(os.path.dirname(video_path)))
                 if naming.ext(name) in TEXT_EXTS
                 and parse(os.path.splitext(os.path.basename(video_path))[0], name)]
        texts = [path for path in texts if path not in flagged]
        if texts:
            try:
                embedded = embedded_digests(video_path)
            except (OSError, subprocess.SubprocessError) as exc:
                log(f"Could not read the embedded subtitles of {os.path.basename(video_path)}: {exc}")
                embedded = {}
            for path in texts:
                try:
                    label = embedded.get(file_digest(path))
                except OSError:
                    continue
                if label:
                    found.append((path, label))
    removed = 0
    for path, kept in found:
        if not purge:
            log(f"Duplicate subtitle {os.path.basename(path)} has the same text as {kept}. Purging is off.")
            continue
        try:
            writes.check(path)
            os.remove(path)
            removed += 1
            log(f"Removed {os.path.basename(path)}: same text as {kept}")
        except (OSError, AppError) as exc:
            log(f"Could not remove {os.path.basename(path)}: {exc}")
    return removed


def process(video_path, cfg, log):
    """Purge duplicates, then re-encode and rename the sidecars of one video. Returns (renamed, converted)."""
    purged = purge_duplicates(video_path, cfg, log)
    moves, texts = plan(video_path, cfg)
    converted = renamed = 0
    for path in texts:
        try:
            changed, encoding = normalize_text(path, cfg.get("sub_line_endings", "lf"))
        except OSError as exc:
            log(f"Could not read {os.path.basename(path)}: {exc}")
            continue
        if changed:
            converted += 1
            log(f"Converted {os.path.basename(path)} from {encoding} to UTF-8")
        elif encoding is None:
            log(f"Left {os.path.basename(path)} alone: its encoding could not be detected with confidence")
    done = set()
    for move in moves:
        if move["from"] in done:
            continue
        target = move["to"]
        group = [move]
        stem, ext = os.path.splitext(move["from"])
        if ext.lower() in (".idx", ".sub"):
            # A VobSub pair moves together or not at all.
            partner = next((m for m in moves if m is not move and m["from"] not in done
                            and os.path.splitext(m["from"])[0].lower() == stem.lower()
                            and os.path.splitext(m["from"])[1].lower() in (".idx", ".sub")), None)
            if partner:
                group.append(partner)
        blocked = next((m for m in group if os.path.exists(m["to"]) and not _same(m["from"], m["to"])), None)
        if blocked:
            log(f"Kept {os.path.basename(move['from'])}: {os.path.basename(blocked['to'])} already exists")
            done.update(m["from"] for m in group)
            continue
        moved = []
        try:
            for item in group:
                writes.check(item["to"])
                os.rename(item["from"], item["to"])
                moved.append(item)
        except (OSError, AppError) as exc:
            for item in reversed(moved):
                try:
                    os.rename(item["to"], item["from"])
                except OSError:
                    pass
            log(f"Could not rename {os.path.basename(move['from'])}: {exc}")
            done.update(m["from"] for m in group)
            continue
        for item in group:
            renamed += 1
            log(f"Renamed {os.path.basename(item['from'])} to {os.path.basename(item['to'])}")
        done.update(m["from"] for m in group)
    if renamed or converted or purged:
        from curator.video import store

        store.refresh_external_subs(video_path)
    return renamed + purged, converted


def retag(video_path, subtitle_name, lang, flags, standard="iso639-2"):
    """Rename one sidecar to the chosen language and flags, then refresh the stored list."""
    if not subtitle_name or os.path.basename(subtitle_name) != subtitle_name or "/" in subtitle_name or "\\" in subtitle_name:
        raise AppError("Invalid subtitle filename", 400)
    folder, video_name = os.path.split(video_path)
    video_stem = os.path.splitext(video_name)[0]
    info = parse(video_stem, subtitle_name)
    if not info:
        raise AppError("That subtitle does not belong to this video")
    code = languages.normalize_lang(lang)
    if not code or code == "und":
        raise AppError("Choose a language, such as en or eng")
    chosen = [flag for flag in FLAG_ORDER if flag in set(flags or []) and flag != "default"]
    # Changing only the flags of a Brazilian or Traditional Chinese file must not turn it into plain Portuguese or Chinese.
    region = info.get("region") if code == languages.normalize_lang(info.get("lang")) else None
    info.update({"lang": code, "region": region, "flags": chosen, "rest": info.get("rest") or []})
    new_name = target_name(video_stem, info, standard)
    if not new_name:
        raise AppError("Choose a language, such as en or eng")
    source = os.path.join(folder, subtitle_name)
    target = os.path.join(folder, new_name)
    if not os.path.isfile(source):
        raise AppError("That subtitle file is no longer next to the video")
    # A VobSub is a pair (.idx timing + .sub pictures) that only works under one shared name.
    pair = _vobsub_partner(folder, subtitle_name, new_name)
    if pair and not _same(pair[0], pair[1]) and os.path.exists(pair[1]):
        raise AppError(f"{os.path.basename(pair[1])} already exists")
    _move(source, target, info["ext"], new_name)
    if pair:
        _move(pair[0], pair[1], os.path.splitext(pair[1])[1], os.path.basename(pair[1]))
    from curator.video import store
    store.refresh_external_subs(video_path)
    return new_name


def _vobsub_partner(folder, subtitle_name, new_name):
    """(current path, new path) of the other half of a VobSub pair, or None."""
    stem, ext = os.path.splitext(subtitle_name)
    other = {".idx": ".sub", ".sub": ".idx"}.get(ext.lower())
    if not other:
        return None
    for name in os.listdir(folder):
        if name.lower() == (stem + other).lower():
            return os.path.join(folder, name), os.path.join(folder, os.path.splitext(new_name)[0] + os.path.splitext(name)[1])
    return None


def _move(source, target, ext, new_name):
    if not _same(source, target):
        if os.path.exists(target):
            raise AppError(f"{new_name} already exists")
        os.replace(source, target)
    elif os.path.basename(source) != os.path.basename(target):
        tmp_target = os.path.join(os.path.dirname(target), f".tmp-retag-{int(time.time()*1000)}{ext}")
        os.replace(source, tmp_target)
        os.replace(tmp_target, target)


def _same(source, target):
    try:
        return os.path.samefile(source, target)
    except OSError:
        return False
