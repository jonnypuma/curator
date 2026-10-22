"""Video and audio facts from ffprobe, MediaInfo and dovi_tool. Ported from video-analyzer.

summarize() is pure so it can be tested with captured JSON. analyze() runs the tools.
dovi_tool only runs when Dolby Vision is present and the enhancement layer type is still
unknown, so SDR and HDR10 files cost one ffprobe and one MediaInfo call.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading

from curator.video.dovi_isom import ISOM_EXTENSIONS, parse_isom_dovi_config
from curator.video.health import unknown_language
from curator.video.languages import (
    canonical_sub_flags,
    classify_sub_flags,
    format_channel_layout,
    is_default_flag,
    label_audio_codec,
    normalize_lang,
    sub_flags_from_mediainfo,
)
from curator.video.naming import ext
from curator.video.sources import (
    classify_edition, classify_path, classify_source, classify_stereo, edition_from_path, release_hybrid, video_source_for,
)

logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT = 120
MEDIAINFO_TIMEOUT = 180
DOVI_TIMEOUT = 180
ISO_TIMEOUT = 600
NOT_PROBED = {".iso", ".vob"}
TS_EXTS = {".m2ts", ".mts", ".ts"}

_CODECS = (
    ("hevc", "HEVC"), ("h265", "HEVC"), ("vvc", "VVC"), ("h266", "VVC"), ("av1", "AV1"),
    ("h264", "H.264"), ("avc", "H.264"), ("mpeg4", "MPEG-4"), ("mpeg2video", "MPEG-2"),
    ("mpeg1video", "MPEG-1"), ("vc1", "VC-1"), ("wmv3", "WMV3"), ("vp9", "VP9"), ("vp8", "VP8"),
)

_procs = set()
_procs_lock = threading.Lock()


class Cancelled(Exception):
    pass


def tools():
    return {name: bool(shutil.which(name)) for name in ("ffprobe", "ffmpeg", "mediainfo", "dovi_tool")}


def kill_all():
    with _procs_lock:
        running = list(_procs)
    for proc in running:
        try:
            proc.kill()
        except OSError:
            pass


def _run(cmd, timeout, cancel=None):
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    with _procs_lock:
        _procs.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f"{os.path.basename(cmd[0])} timed out after {timeout} s")
    finally:
        with _procs_lock:
            _procs.discard(proc)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _json(text):
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def _ratio(value):
    if not isinstance(value, str) or not value:
        return None
    sep = ":" if ":" in value else "/" if "/" in value else None
    if not sep:
        return None
    try:
        num, den = (float(part) for part in value.split(sep, 1))
    except ValueError:
        return None
    return num / den if den else None


def _mbps(value):
    try:
        return round(int(value) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def resolution_label(width, height):
    if width >= 7680 or height >= 4320:
        return "8K"
    if width >= 3800 or height >= 2100:
        return "4K"
    if width >= 1900 or height >= 1000:
        return "1080p"
    if width >= 1200 or height >= 700:
        return "720p"
    if width or height:
        return "SD"
    return None


def combined_release(file_name, folder_name=""):
    """Source, edition, hybrid and 3D from the file name, then the folder name when the file is silent.

    The file name wins when both name a value. An empty edition or source is returned as None so a
    replaced file can clear the previous release.
    """
    from curator.video.naming import release_group
    from curator.video.sources import canonical_edition

    file_facts = filename_facts(file_name) if file_name else {}
    folder_facts = filename_facts(folder_name) if folder_name else {}
    source = file_facts.get("source_format") or folder_facts.get("source_format")
    group = file_facts.get("video_source") or folder_facts.get("video_source")
    edition = canonical_edition(file_facts.get("edition") or folder_facts.get("edition"))
    stereo = file_facts.get("stereo_mode") or folder_facts.get("stereo_mode") or ""
    return {
        "source_format": source,
        "video_source": group,
        "edition": edition,
        "is_hybrid": bool(file_facts.get("is_hybrid") or folder_facts.get("is_hybrid")),
        "is_3d": bool(stereo),
        "stereo_mode": stereo,
        "release_group": release_group(file_name) or (release_group(folder_name) if folder_name else None),
    }


def filename_facts(name, resolution=None):
    source = classify_source(name, resolution)
    return {
        "video_source": video_source_for(source),
        "source_format": source,
        "edition": classify_edition(name),
        "is_hybrid": release_hybrid(name),
        "stereo_mode": classify_stereo(name),
        "is_3d": bool(classify_stereo(name)),
    }


def _codec(stream):
    name = str(stream.get("codec_name") or "").lower()
    for key, label in _CODECS:
        if key in name:
            return label
    return name.upper() or None


def _dv_profile_from_text(*values):
    """Profile from MediaInfo. dvhe.08.04 is P8.4, dvav.10.01 is P10.1, dvh1.20 is P20."""
    text = " ".join(str(value) for value in values if value).lower()
    if not any(token in text for token in ("dolby vision", "dovi", "dvhe", "dvh1", "dvav", "dva1", "dav1")):
        return None
    match = re.search(r"(?:dv(?:he|h1|av|a1)|dav1)\.(\d{1,2})(?:\.(\d{2}))?", text)
    if match:
        number = str(int(match.group(1)))
        compat_raw = match.group(2)
        if compat_raw is not None:
            compat_num = str(int(compat_raw))
            if compat_num == "1":
                return f"{number}.1"
            if compat_num == "2":
                return f"{number}.2"
            if compat_num == "4":
                return f"{number}.4"
        return number
    match = re.search(r"profile\s*([0-9]{1,2}(?:\.[0-9])?)", text)
    if match:
        return match.group(1)
    match = re.search(r"\bdovi?\s*p?([0-9]{1,2}(?:\.[0-9])?)\b", text)
    return match.group(1) if match else None


def _el_from_rpu_value(value):
    """FEL or MEL from a dovi_tool field. BL+EL only means an enhancement layer exists."""
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "FEL" in text or text == "F" or "FULL" in text:
        return "FEL"
    if "MEL" in text or text == "M" or "MINIMAL" in text:
        return "MEL"
    return None


def _el_from_dovi(dovi_data):
    if not isinstance(dovi_data, dict):
        return None
    if "disable_residual_flag" in dovi_data:
        try:
            flag = int(dovi_data["disable_residual_flag"])
            return "MEL" if flag == 1 else "FEL"
        except (TypeError, ValueError):
            pass
    for key in ("el_type", "enhancement_layer_type", "el", "enhancement_layer", "layer_type"):
        found = _el_from_rpu_value(dovi_data.get(key))
        if found:
            return found
    nested = dovi_data.get("rpu")
    if isinstance(nested, dict):
        if "disable_residual_flag" in nested:
            try:
                flag = int(nested["disable_residual_flag"])
                return "MEL" if flag == 1 else "FEL"
            except (TypeError, ValueError):
                pass
        for key in ("el_type", "enhancement_layer_type", "el", "enhancement_layer"):
            found = _el_from_rpu_value(nested.get(key))
            if found:
                return found
    return None


def _el_from_mediainfo(text):
    """A weak hint. BL+EL is not enough to call a file FEL; dovi_tool decides that."""
    upper = str(text or "").upper()
    if not upper:
        return None
    if "FEL" in upper:
        return "FEL"
    if "MEL" in upper or ("BL+RPU" in upper and "EL" not in upper):
        return "MEL"
    return None


def _enhancement_stream(data):
    for stream in (data or {}).get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        tags = stream.get("tags") or {}
        blob = " ".join(str(value) for value in tags.values()).lower()
        codec = str(stream.get("codec_name") or "").lower()
        title = str(tags.get("title") or "").strip().lower()
        if "enhancement" in codec or "enhancement" in blob or str(tags.get("enhancement") or "").strip() or title == "el":
            return True
    return False


def _profile7_el(data, dovi_data, hint):
    """Profile 7 layer. The RPU answer wins. MediaInfo is only a fallback."""
    if dovi_data:
        found = _el_from_dovi(dovi_data)
        if found:
            return found
        if _enhancement_stream(data):
            return "FEL"
        return "MEL"
    return hint or None


def _kbps(val):
    try:
        return int(float(val) / 1000)
    except (TypeError, ValueError):
        return None


def _ffprobe_tracks(data):
    audio, subs = [], []
    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        tags = {str(key).lower(): value for key, value in (stream.get("tags") or {}).items()}
        disposition = stream.get("disposition") or {}
        lang_raw = tags.get("language") or ""
        title = tags.get("title") or ""
        if kind == "audio":
            audio.append({
                "codec": label_audio_codec(codec_name=stream.get("codec_name") or "", profile=stream.get("profile") or ""),
                "lang": normalize_lang(lang_raw),
                "channels": format_channel_layout(stream.get("channels") or ""),
                "default": is_default_flag(disposition.get("default")),
                "title": title,
                "bitrate_kbps": _kbps(stream.get("bit_rate")),
            })
        elif kind == "subtitle":
            flags = classify_sub_flags(
                forced=disposition.get("forced"),
                hearing_impaired=disposition.get("hearing_impaired"),
                captions=disposition.get("captions"),
                title=title,
                language_raw=lang_raw,
            )
            subs.append({
                "lang": normalize_lang(lang_raw),
                "codec": str(stream.get("codec_name") or ""),
                "flags": flags,
                "default": is_default_flag(disposition.get("default")),
                "title": title,
            })
    return audio, subs


def _fill_languages(tracks, other):
    """MediaInfo's track list wins, but it can lack a language that ffprobe read, such as the languages a Blu-ray
    playlist names. When both lists have the same number of tracks, a track MediaInfo left unknown takes ffprobe's."""
    if not tracks or len(tracks) != len(other):
        return
    for mine, theirs in zip(tracks, other):
        if unknown_language(mine.get("lang")) and not unknown_language(theirs.get("lang")):
            mine["lang"] = theirs["lang"]


def container_name(value):
    """The label stored and shown for a container. Matroska files are MKV."""
    text = str(value or "").split(",")[0].strip()
    if text.lower() in {"matroska", "mkv"}:
        return "MKV"
    return text or None


def summarize(name, ffprobe_data, mediainfo_data=None, dovi_data=None, isom=None):
    """Turn the tool output for one file into video_files columns."""
    facts = filename_facts(name)
    result = {
        "container": None, "duration_seconds": None, "bitrate_mbps": None, "video_bitrate_mbps": None,
        "video_codec": None, "video_profile": None, "width": None, "height": None, "resolution": None,
        "fps": None, "aspect_ratio": None, "bit_depth": None, "hdr_format": "sdr", "hdr_secondary": None,
        "is_hybrid": False, "dovi_profile": None, "dovi_el_type": None, "dovi_bl_compat": None,
        "max_cll": None, "max_fall": None, "is_3d": facts["is_3d"], "video_source": facts["video_source"],
        "source_format": facts["source_format"], "edition": facts["edition"], "chapters": 0,
        "audio_tracks": [], "subtitle_tracks": [], "probe_error": None,
    }
    data = ffprobe_data or {}
    streams = data.get("streams") or []
    videos = [stream for stream in streams if stream.get("codec_type") == "video"
              and not (stream.get("disposition") or {}).get("attached_pic")]
    if not videos:
        result["probe_error"] = "No video stream"
        return result
    video = videos[0]
    fmt = data.get("format") or {}
    result["container"] = container_name(str(fmt.get("format_name") or "").split(",")[0] or ext(name).lstrip(".")) or None
    try:
        result["duration_seconds"] = int(float(fmt.get("duration") or video.get("duration") or 0)) or None
    except ValueError:
        pass
    result["bitrate_mbps"] = _mbps(fmt.get("bit_rate"))
    result["video_bitrate_mbps"] = _mbps(video.get("bit_rate"))
    result["video_codec"] = _codec(video)
    named_codec = _named_video(name)
    if named_codec in {"DivX", "XviD"} and str(result["video_codec"] or "").upper() in {"", "MPEG-4", "MPEG4", "MPEG-4 VISUAL"}:
        result["video_codec"] = named_codec
    result["video_profile"] = video.get("profile") or None
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    result["width"], result["height"] = width or None, height or None
    result["resolution"] = resolution_label(width, height)
    fps = _ratio(video.get("avg_frame_rate")) or _ratio(video.get("r_frame_rate"))
    result["fps"] = round(fps, 3) if fps else None
    aspect = _ratio(video.get("display_aspect_ratio")) or (width / height if width and height else None)
    result["aspect_ratio"] = f"{aspect:.2f}" if aspect else None
    depth = video.get("bits_per_raw_sample")
    if not str(depth or "").isdigit():
        match = re.search(r"p(\d{2})", str(video.get("pix_fmt") or ""))
        depth = match.group(1) if match else (8 if video.get("pix_fmt") else None)
    result["bit_depth"] = int(depth) if depth else None
    result["chapters"] = len(data.get("chapters") or [])

    secondary = []
    hlg = False
    transfer = str(video.get("color_transfer") or "")
    side = video.get("side_data_list") or []
    if any("HDR Dynamic Metadata" in str(item.get("side_data_type")) or "HDR10+" in str(item.get("side_data_type")) for item in side):
        secondary.append("HDR10+")
    if "arib-std-b67" in transfer:
        hlg = True
        secondary.append("HLG")
    elif "smpte2084" in transfer:
        secondary.append("HDR10")
    for item in side:
        if item.get("side_data_type") == "Content light level metadata":
            result["max_cll"] = str(item.get("max_content") or "") or None
            result["max_fall"] = str(item.get("max_average") or "") or None

    profile = None
    compat = None
    dv_record = next((item for item in side if "DOVI configuration" in str(item.get("side_data_type"))), None)
    if dv_record:
        value = dv_record.get("dv_profile")
        profile = str(value) if value is not None else _dv_profile_from_text(dv_record.get("side_data_type"))
        compat_value = dv_record.get("dv_bl_signal_compatibility_id")
        compat = str(compat_value) if compat_value is not None else None
    el_hint = None
    if mediainfo_data:
        mi_video = None
        mi_audio, mi_subs = [], []
        for track in (mediainfo_data.get("media") or {}).get("track") or []:
            kind = track.get("@type")
            if kind == "Video" and mi_video is None:
                mi_video = track
            elif kind == "Audio":
                mi_audio.append(track)
            elif kind == "Text":
                mi_subs.append(track)
        if mi_video:
            fields = [mi_video.get(key) for key in (
                "HDR_Format", "HDR_Format_Compatibility", "HDR_Format_Profile", "HDR_Format_String",
                "HDR_Format_Settings", "HDR_Format_Version", "CodecID")]
            if not profile:
                profile = _dv_profile_from_text(*fields)
            el_hint = _el_from_mediainfo(mi_video.get("HDR_Format_Settings"))
            compat_text = " ".join(str(value) for value in fields if value).upper()
            if ("HDR10+" in compat_text or "SMPTE ST 2094" in compat_text) and "HDR10+" not in secondary:
                secondary.append("HDR10+")
            if "HDR10" in compat_text.replace("HDR10+", "") and "HDR10" not in secondary:
                secondary.append("HDR10")
            if "HLG" in compat_text and "HLG" not in secondary:
                hlg = True
                secondary.append("HLG")
            cll = mi_video.get("MaxCLL") or mi_video.get("MaximumContentLightLevel")
            fall = mi_video.get("MaxFALL") or mi_video.get("MaximumFrameAverageLightLevel")
            if cll and not result.get("max_cll"):
                result["max_cll"] = str(cll).replace("cd/m2", "").strip() or None
            if fall and not result.get("max_fall"):
                result["max_fall"] = str(fall).replace("cd/m2", "").strip() or None
            if str(mi_video.get("BitDepth") or "").isdigit():
                result["bit_depth"] = int(mi_video["BitDepth"])
        audio = []
        for track in mi_audio:
            channels = track.get("Channels") or track.get("Channel(s)") or ""
            match = re.search(r"\d+(?:\.\d+)?", str(channels))
            bitrate = track.get("BitRate")
            audio.append({
                "codec": label_audio_codec(
                    format=track.get("Format") or "",
                    commercial=track.get("Format_Commercial_IfAny") or track.get("Format_Commercial") or "",
                    additional=track.get("Format_AdditionalFeatures") or "",
                ),
                "lang": normalize_lang(track.get("Language")),
                "channels": format_channel_layout(match.group(0) if match else channels),
                "default": is_default_flag(track.get("Default")),
                "title": track.get("Title") or "",
                "bitrate_kbps": _kbps(bitrate),
            })
        subs = []
        for track in mi_subs:
            subs.append({
                "lang": normalize_lang(track.get("Language")),
                "codec": str(track.get("Format") or "").lower(),
                "flags": sub_flags_from_mediainfo(track),
                "default": is_default_flag(track.get("Default")),
                "title": track.get("Title") or "",
            })
        result["audio_tracks"], result["subtitle_tracks"] = audio, subs
    ff_audio, ff_subs = _ffprobe_tracks(data)
    _fill_languages(result["audio_tracks"], ff_audio)
    _fill_languages(result["subtitle_tracks"], ff_subs)
    if not result["audio_tracks"]:
        result["audio_tracks"] = ff_audio
    if not result["subtitle_tracks"]:
        result["subtitle_tracks"] = ff_subs
    elif len(ff_subs) == len(result["subtitle_tracks"]):
        for mine, theirs in zip(result["subtitle_tracks"], ff_subs):
            mine["flags"] = canonical_sub_flags(list(mine["flags"]) + list(theirs["flags"]))

    if dovi_data and dovi_data.get("dovi_profile") is not None:
        profile = str(dovi_data.get("dovi_profile"))
    if isom and isom.get("dovi_profile"):
        profile = str(isom["dovi_profile"])
    if isom and isom.get("bl_compatibility_id") is not None:
        compat = str(isom["bl_compatibility_id"])
    if isom and isom.get("is_stereo"):
        result["is_3d"] = True
    if profile:
        result["hdr_format"] = "dovi"
        result["dovi_bl_compat"] = compat
        if profile in ("8", "10"):
            if hlg or compat == "4":
                profile = f"{profile}.4"
            elif compat == "1" or "HDR10" in secondary or "HDR10+" in secondary:
                profile = f"{profile}.1"
            elif compat == "2":
                profile = f"{profile}.2"
        result["dovi_profile"] = profile
        if profile.split(".")[0] == "7":
            result["dovi_el_type"] = _profile7_el(data, dovi_data, None)
            result["_el_hint"] = el_hint
        if profile.split(".")[0] == "20":
            result["stereo_mode"] = result.get("stereo_mode") or "MVC"
            result["is_3d"] = True
        if profile.split(".")[0] == "5":
            secondary = [label for label in secondary if label != "HDR10"]
        for label in ("HDR10+", "HDR10", "HLG"):
            if label in secondary:
                result["hdr_secondary"] = label
                break
    elif hlg:
        result["hdr_format"] = "hlg"
    elif "HDR10+" in secondary:
        result["hdr_format"] = "hdr10plus"
    elif "HDR10" in secondary:
        result["hdr_format"] = "hdr10"
    if result["hdr_format"] != "dovi":
        main = {"hdr10plus": "HDR10+", "hdr10": "HDR10", "hlg": "HLG"}.get(result["hdr_format"])
        rest = [label for label in ("HDR10+", "HDR10", "HLG") if label in secondary and label != main]
        if result["hdr_format"] == "hdr10plus":
            rest = [label for label in rest if label != "HDR10"]
        result["hdr_secondary"] = rest[0] if rest else None
    facts = filename_facts(name, result.get("resolution"))
    result["video_source"] = facts["video_source"]
    result["source_format"] = facts["source_format"]
    result["edition"] = facts["edition"]
    result["stereo_mode"] = facts["stereo_mode"] or result.get("stereo_mode")
    result["is_3d"] = bool(result["stereo_mode"]) or facts["is_3d"]
    result["is_hybrid"] = facts["is_hybrid"]
    return result


def _needs_dovi_tool(summary):
    if summary.get("hdr_format") != "dovi":
        return False
    base = str(summary.get("dovi_profile") or "").split(".")[0]
    return base in ("", "7") and not summary.get("dovi_el_type")


def _dovi_rpu(path, video_count, cancel=None):
    if not shutil.which("ffmpeg") or not shutil.which("dovi_tool"):
        return None
    indexes = list(range(1, video_count)) + [0] if video_count > 1 else [0]
    best = None
    for index in indexes:
        handle, rpu = tempfile.mkstemp(prefix="curator-rpu-", suffix=".bin")
        os.close(handle)
        try:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            ffmpeg = subprocess.Popen(
                ["ffmpeg", "-v", "error", "-i", path, "-map", f"0:v:{index}", "-c:v", "copy", "-t", "2", "-f", "hevc", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                extract = subprocess.Popen(
                    ["dovi_tool", "extract-rpu", "-", "-o", rpu],
                    stdin=ffmpeg.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                )
            except Exception:
                ffmpeg.kill()
                try:
                    ffmpeg.communicate()
                except Exception:
                    pass
                raise
            ffmpeg.stdout.close()
            with _procs_lock:
                _procs.update((ffmpeg, extract))
            try:
                extract.wait(timeout=DOVI_TIMEOUT)
                ffmpeg.wait(timeout=10)
            except subprocess.TimeoutExpired:
                ffmpeg.kill()
                extract.kill()
                try:
                    ffmpeg.communicate()
                    extract.communicate()
                except Exception:
                    pass
            finally:
                with _procs_lock:
                    _procs.discard(ffmpeg)
                    _procs.discard(extract)
            if extract.returncode == 0 and os.path.getsize(rpu) > 0:
                _, out, _ = _run(["dovi_tool", "info", "-i", rpu, "-f", "0"], 60, cancel)
                info = _json(out)
                if info:
                    info = dict(info)
                    info["_rpu_size"] = os.path.getsize(rpu)
                    best = info
                    if _el_from_dovi(info) == "FEL":
                        break
        finally:
            try:
                os.remove(rpu)
            except OSError:
                pass
    return best


def disc_image_summary(path):
    """Facts read from a disc image name. The image itself is not opened."""
    name = os.path.basename(str(path or ""))
    folder = os.path.basename(os.path.dirname(str(path or "")))
    if folder in {"", ".", ".."}:
        folder = ""
    facts = filename_facts(name)
    folder_facts = filename_facts(folder) if folder else {}
    source = classify_path(path) or facts.get("source_format") or folder_facts.get("source_format")
    resolution, width, height = _named_frame(name)
    if not resolution and folder:
        resolution, width, height = _named_frame(folder)
    codec = _named_video(name) or (_named_video(folder) if folder else None)
    bit_depth = None
    if not codec and source == "Complete UHD Blu-ray":
        codec = "HEVC"
        bit_depth = 10
    audio = _named_audio(name) or (_named_audio(folder) if folder else None)
    hdr = _named_hdr(name) or (_named_hdr(folder) if folder else None) or "sdr"
    return {
        "container": ext(name).lstrip(".") or "iso",
        "duration_seconds": None, "bitrate_mbps": None, "video_bitrate_mbps": None,
        "video_codec": codec, "video_profile": None,
        "width": width, "height": height, "resolution": resolution,
        "fps": None, "aspect_ratio": None, "bit_depth": bit_depth,
        "hdr_format": hdr, "hdr_secondary": None,
        "is_hybrid": bool(facts.get("is_hybrid") or folder_facts.get("is_hybrid")),
        "dovi_profile": None, "dovi_el_type": None, "dovi_bl_compat": None,
        "max_cll": None, "max_fall": None,
        "is_3d": bool(facts.get("is_3d") or folder_facts.get("is_3d")),
        "stereo_mode": facts.get("stereo_mode") or folder_facts.get("stereo_mode") or None,
        "video_source": video_source_for(source),
        "source_format": source,
        "edition": facts.get("edition") or folder_facts.get("edition"),
        "chapters": 0,
        "audio_tracks": [audio] if audio else [],
        "subtitle_tracks": [],
        "probe_error": None,
    }


_NAMED_VIDEO = (
    (re.compile(r"\b(?:hevc|h\.?265|x265)\b", re.I), "HEVC"),
    (re.compile(r"\bav1\b", re.I), "AV1"),
    (re.compile(r"\b(?:h\.?264|x264|avc)\b", re.I), "AVC"),
    (re.compile(r"\bmpeg-?2\b", re.I), "MPEG-2"),
    (re.compile(r"\bvc-?1\b", re.I), "VC-1"),
    (re.compile(r"\bxvid\b", re.I), "XviD"),
    (re.compile(r"\bdivx\b", re.I), "DivX"),
)
_NAMED_AUDIO = (
    (re.compile(r"truehd[.\s_-]*atmos|atmos[.\s_-]*truehd", re.I), "TrueHD Atmos"),
    (re.compile(r"\btruehd\b", re.I), "TrueHD"),
    (re.compile(r"\bdts[.\s_-]*x\b", re.I), "DTS:X"),
    (re.compile(r"dts[.\s_-]*hd[.\s_-]*ma", re.I), "DTS-HD MA"),
    (re.compile(r"\bdts[.\s_-]*hd\b", re.I), "DTS-HD"),
    (re.compile(r"\b(?:lpcm|pcm)\b", re.I), "PCM"),
    (re.compile(r"\bdts\b", re.I), "DTS"),
    (re.compile(r"\b(?:eac3|ddp|dd\+)\b", re.I), "E-AC-3"),
    (re.compile(r"\b(?:ac3)\b", re.I), "AC3"),
    (re.compile(r"\baac\b", re.I), "AAC"),
    (re.compile(r"\bflac\b", re.I), "FLAC"),
)
_NAMED_CHANNELS = re.compile(r"\b([2-9]\.[0-1])\b")
_NAMED_HDR = (
    (re.compile(r"\b(?:dolby[.\s_-]?vision|dovi)\b|\bdv\b", re.I), "dovi"),
    (re.compile(r"hdr10\+", re.I), "hdr10plus"),
    (re.compile(r"\bhdr10\b|\bhdr\b", re.I), "hdr10"),
    (re.compile(r"\bhlg\b", re.I), "hlg"),
)


def _named_frame(name):
    text = os.path.splitext(os.path.basename(str(name or "")))[0]
    if re.search(r"\b(?:4320p?|8k)\b", text, re.I):
        return "8K", 7680, 4320
    if re.search(r"\b(?:2160p?|4k)\b", text, re.I):
        return "4K", 3840, 2160
    if re.search(r"\b1080p?\b", text, re.I):
        return "1080p", 1920, 1080
    if re.search(r"\b720p\b", text, re.I):
        return "720p", 1280, 720
    if re.search(r"\buhd\b", text, re.I):
        return "4K", 3840, 2160
    return None, None, None


def _named_video(name):
    text = os.path.splitext(os.path.basename(str(name or "")))[0]
    for pattern, label in _NAMED_VIDEO:
        if pattern.search(text):
            return label
    return None


def _named_audio(name):
    text = os.path.splitext(os.path.basename(str(name or "")))[0]
    codec = None
    for pattern, label in _NAMED_AUDIO:
        if pattern.search(text):
            codec = label
            break
    if codec == "TrueHD" and re.search(r"\batmos\b", text, re.I):
        codec = "TrueHD Atmos"
    match = _NAMED_CHANNELS.search(text)
    channels = match.group(1) if match else ""
    if not codec and not channels:
        return None
    return {"codec": codec or "", "channels": channels, "default": True}


def _named_hdr(name):
    text = os.path.splitext(os.path.basename(str(name or "")))[0]
    for pattern, label in _NAMED_HDR:
        if pattern.search(text):
            return label
    return None


def scan_iso():
    """True when Settings says a scan may open .iso files."""
    try:
        from curator.video import config

        return bool(config.current().get("scan_iso"))
    except Exception:
        return False


def _mediainfo(path, cancel, timeout):
    if not shutil.which("mediainfo"):
        return None
    try:
        # --ParseSpeed=0 skips frame-level analysis and cuts runtime significantly.
        code, out, _ = _run(["mediainfo", "--ParseSpeed=0", "--Output=JSON", path], timeout, cancel)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.warning("mediainfo skipped for %s: %s", path, exc)
        return None
    return _json(out) if code == 0 else None


def _mi_codec_name(value):
    text = str(value or "").lower()
    if "hevc" in text or "h.265" in text or "h265" in text:
        return "hevc"
    if "avc" in text or "h.264" in text or "h264" in text:
        return "h264"
    if "mpeg video" in text or "mpeg-2" in text or "mpeg2" in text:
        return "mpeg2video"
    if "vc-1" in text or "vc1" in text:
        return "vc1"
    if "av1" in text:
        return "av1"
    return text


def _shape_from_mediainfo(mediainfo):
    """A small ffprobe-shaped document so summarize() can read a disc MediaInfo opened."""
    tracks = ((mediainfo or {}).get("media") or {}).get("track") or []
    general = next((track for track in tracks if track.get("@type") == "General"), {})
    streams = []
    for track in tracks:
        kind = track.get("@type")
        if kind == "Video":
            rate = str(track.get("FrameRate") or "")
            aspect = str(track.get("DisplayAspectRatio") or "")
            streams.append({
                "codec_type": "video",
                "codec_name": _mi_codec_name(track.get("Format")),
                "profile": track.get("Format_Profile"),
                "width": int(track.get("Width") or 0),
                "height": int(track.get("Height") or 0),
                "avg_frame_rate": f"{rate}/1" if rate else "",
                "display_aspect_ratio": f"{aspect}/1" if aspect and "/" not in aspect and ":" not in aspect else aspect,
                "bits_per_raw_sample": track.get("BitDepth"),
                "duration": track.get("Duration"),
                "bit_rate": track.get("BitRate"),
            })
        elif kind == "Audio":
            streams.append({"codec_type": "audio", "codec_name": str(track.get("Format") or "").lower()})
        elif kind == "Text":
            streams.append({"codec_type": "subtitle", "codec_name": str(track.get("Format") or "").lower()})
    return {
        "streams": streams,
        "format": {
            "format_name": "iso",
            "duration": general.get("Duration"),
            "bit_rate": general.get("OverallBitRate"),
        },
        "chapters": [],
    }


def _analyze_iso(path, cancel):
    """Open a disc image. Blu-ray goes through ffprobe's bluray input; MediaInfo covers DVD and HDR."""
    name = os.path.basename(path)
    probe = None
    try:
        code, out, _err = _run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", f"bluray:{path}"],
            ISO_TIMEOUT, cancel,
        )
        probe = _json(out) if code == 0 else None
    except FileNotFoundError:
        summary = disc_image_summary(path)
        summary["probe_error"] = "ffprobe is not installed"
        return summary
    except RuntimeError as exc:
        logger.warning("bluray probe skipped for %s: %s", path, exc)
    videos = [stream for stream in (probe or {}).get("streams") or [] if stream.get("codec_type") == "video"]
    mediainfo = _mediainfo(path, cancel, ISO_TIMEOUT)
    if not videos and mediainfo:
        probe = _shape_from_mediainfo(mediainfo)
        videos = [stream for stream in probe.get("streams") or [] if stream.get("codec_type") == "video"]
    if not videos:
        summary = disc_image_summary(path)
        summary["probe_error"] = "Could not read streams from this disc image"
        return summary
    summary = summarize(name, probe, mediainfo, None, None)
    if not summary.get("source_format"):
        source = classify_path(path, summary.get("resolution"))
        if source:
            summary["source_format"] = source
            summary["video_source"] = video_source_for(source)
    if not summary.get("edition"):
        summary["edition"] = edition_from_path(path)
    return summary


def _has_video(probe):
    return any(
        stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
        for stream in (probe or {}).get("streams") or []
    )


def _ffprobe_document(path, cancel, extra=()):
    code, out, err = _run(
        ["ffprobe", "-v", "error", *extra, "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
        FFPROBE_TIMEOUT, cancel,
    )
    return (_json(out) if code == 0 else None), err, code


def _prefer_video_probe(probe, mediainfo):
    """Keep ffprobe when it saw a picture. Otherwise use a MediaInfo video track."""
    if _has_video(probe):
        return probe
    shaped = _shape_from_mediainfo(mediainfo) if mediainfo else None
    if _has_video(shaped):
        return shaped
    return probe


def analyze(path, cancel=None, *, open_iso=None):
    """Probe one file. Returns video_files columns, with probe_error set when a step failed.

    open_iso overrides the Movies setting. A TV scan passes False so a disc image stays a file name.
    """
    name = os.path.basename(path)
    if ext(name) == ".iso":
        allow = scan_iso() if open_iso is None else bool(open_iso)
        if not allow:
            return disc_image_summary(path)
        return _analyze_iso(path, cancel)
    if ext(name) in NOT_PROBED:
        return disc_image_summary(path)
    try:
        probe, err, code = _ffprobe_document(path, cancel)
        if ext(name) in TS_EXTS and not _has_video(probe):
            deeper, deeper_err, deeper_code = _ffprobe_document(
                path, cancel, ("-probesize", "50000000", "-analyzeduration", "50000000", "-f", "mpegts"),
            )
            if _has_video(deeper):
                probe = deeper
            elif deeper:
                err, code = deeper_err, deeper_code
    except FileNotFoundError:
        summary = summarize(name, {})
        summary["probe_error"] = "ffprobe is not installed"
        return summary
    except RuntimeError as exc:
        summary = summarize(name, {})
        summary["probe_error"] = str(exc)
        return summary
    # Only skip MediaInfo when ffprobe gave us codec details AND there is no Dolby Vision
    # configuration record in the stream.  DV files need MediaInfo for HDR_Format_Profile
    # (the dvhe.08.04 string that gives us profile + compat id), HDR_Format_Settings
    # (the FEL/MEL hint for P7), HDR10/HLG cross-compat flags, and audio commercial names.
    # For plain SDR / HDR10 files ffprobe is sufficient and MediaInfo is skipped.
    _dv_present = any(
        "DOVI configuration" in str(item.get("side_data_type", ""))
        for stream in (probe or {}).get("streams") or []
        for item in (stream.get("side_data_list") or [])
    )
    _ffprobe_has_detail = (
        _has_video(probe)
        and not _dv_present
        and bool(probe and any(
            s.get("codec_name") for s in (probe.get("streams") or [])
            if s.get("codec_type") == "video"
        ))
    )
    mediainfo = None if _ffprobe_has_detail else _mediainfo(path, cancel, MEDIAINFO_TIMEOUT)
    probe = _prefer_video_probe(probe, mediainfo)
    if not probe:
        summary = summarize(name, {})
        summary["probe_error"] = f"ffprobe failed: {(err or '').strip()[:300] or f'exit code {code}'}"
        return summary
    isom = parse_isom_dovi_config(path) if ext(name).lower() in ISOM_EXTENSIONS else None
    summary = summarize(name, probe, mediainfo, None, isom)
    if not summary.get("source_format"):
        source = classify_path(path, summary.get("resolution"))
        if source:
            summary["source_format"] = source
            summary["video_source"] = video_source_for(source)
    if _needs_dovi_tool(summary):
        videos = [s for s in probe.get("streams") or [] if s.get("codec_type") == "video"]
        try:
            dovi = _dovi_rpu(path, len(videos), cancel)
        except (OSError, RuntimeError) as exc:
            logger.warning("dovi_tool skipped for %s: %s", path, exc)
            dovi = None
        if dovi:
            summary = summarize(name, probe, mediainfo, dovi, isom)
    if str(summary.get("dovi_profile") or "").split(".")[0] == "7" and not summary.get("dovi_el_type"):
        summary["dovi_el_type"] = summary.get("_el_hint")
    summary.pop("_el_hint", None)
    if not summary.get("edition"):
        summary["edition"] = edition_from_path(path)
    return summary
