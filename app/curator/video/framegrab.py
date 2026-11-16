"""One still frame from a video file, correct for SDR, HDR10, HLG and Dolby Vision sources.

A plain ffmpeg grab of an HDR file comes out washed out, and Dolby Vision profile 5 (which has no HDR10 base layer)
comes out purple and green. HDR frames are tone mapped to SDR (BT.709) before they are written.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache

SCENE_FILTER = r"select=gt(scene\,0.05)"
WIDTH = 1280
logger = logging.getLogger(__name__)
_TRANSFER = {"smpte2084": "smpte2084", "arib-std-b67": "arib-std-b67"}


@lru_cache(maxsize=1)
def _filters():
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            names.add(parts[1])
    return frozenset(names)


def probe(path):
    """Duration and colour description of the first video stream."""
    info = {"duration": 0.0, "transfer": "", "primaries": "", "matrix": "", "dv_profile": None, "hdr": False, "hlg": False}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
             "-select_streams", "v:0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout
        data = json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return info
    try:
        info["duration"] = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    stream = (data.get("streams") or [{}])[0]
    info["transfer"] = str(stream.get("color_transfer") or "")
    info["primaries"] = str(stream.get("color_primaries") or "")
    info["matrix"] = str(stream.get("color_space") or "")
    for side in stream.get("side_data_list") or []:
        if "dovi" in str(side.get("side_data_type") or "").lower() or "dolby" in str(side.get("side_data_type") or "").lower():
            try:
                info["dv_profile"] = int(side.get("dv_profile"))
            except (TypeError, ValueError):
                info["dv_profile"] = 0
    info["hlg"] = info["transfer"] == "arib-std-b67"
    info["hdr"] = (info["transfer"] in _TRANSFER or info["dv_profile"] is not None
                   or (info["primaries"] == "bt2020" and "10" in str(stream.get("pix_fmt") or "")))
    return info


def _zscale_chain(info):
    """HDR to SDR with zimg and the tonemap filter. Input properties that the file does not tag are filled in."""
    transfer = "arib-std-b67" if info["hlg"] else "smpte2084"
    head = f"zscale=tin={transfer}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=100"
    return (f"{head},format=gbrpf32le,tonemap=tonemap=hable:desat=0,"
            "zscale=p=bt709:t=bt709:m=bt709:r=tv,format=yuvj420p")


def _candidates(info):
    """(extra input args, filter chain) pairs, best first."""
    names = _filters()
    out = []
    scale = f"scale={WIDTH}:-2"
    if not info["hdr"]:
        out.append(([], f"{SCENE_FILTER},{scale}"))
        out.append(([], scale))
        return out
    if info["dv_profile"] == 5 and "libplacebo" in names:
        # The Trickplay add-on's chain: libplacebo uploads the frame itself and applies the Dolby Vision metadata, and
        # the scale comes after it so the metadata is not touched first.
        placebo = ("libplacebo=apply_dolbyvision=1:tonemapping=hable:peak_detect=1:gamut_mode=perceptual"
                   ":color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=pc,format=yuvj420p")
        vulkan = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk"]
        # The plain seek first: it is the form that was checked by hand on a real profile 5 file.
        out.append((vulkan, f"{placebo},{scale},format=yuvj420p"))
        out.append((vulkan, f"{SCENE_FILTER},{placebo},{scale},format=yuvj420p"))
    if info["dv_profile"] == 5:
        # Profile 5 has no HDR10 base layer. Its pixels are IPT-PQ-c2 and only the Dolby Vision metadata turns them
        # into colours, so any other chain gives a green or purple frame. libplacebo is the only way; otherwise none.
        return out
    if "zscale" in names and "tonemap" in names:
        chain = _zscale_chain(info)
        out.append(([], f"{SCENE_FILTER},{scale},{chain}"))
        out.append(([], f"{scale},{chain}"))
    else:
        # Without zimg the colours cannot be mapped properly; at least squeeze the range into SDR.
        out.append(([], f"{SCENE_FILTER},{scale},eq=contrast=1.0"))
        out.append(([], scale))
    return out


last_error = ""


def _run(args, out_path, timeout):
    global last_error
    try:
        if os.path.exists(out_path):
            os.unlink(out_path)
        result = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        last_error = f"ffmpeg took longer than {timeout} seconds"
        return False
    ok = result.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    if ok:
        last_error = ""
    else:
        text = (result.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        last_error = (text[-1] if text else "ffmpeg wrote no frame")[:300]
    return ok


_SPOTS = (0.40, 0.25, 0.55, 0.70, 0.15, 0.85)


def grab(path, out_path, info=None):
    """Write a JPEG still from about 40% into the file. Returns True when a frame was written.

    A black frame (a fade, a scene change) is never kept: the next spot in the file is tried instead."""
    global last_error
    last_error = ""
    if not shutil.which("ffmpeg"):
        last_error = "ffmpeg is not installed"
        return False
    info = info or probe(path)
    duration = info["duration"]
    if duration < 30:
        return False
    tried_black = False
    for fraction in _SPOTS:
        target = min(max(duration * fraction, max(30, duration * 0.05)), duration * 0.90)
        if not _grab_at(path, out_path, info, target):
            return False
        if _mostly_black(out_path):
            tried_black = True
            os.unlink(out_path)
            continue
        return True
    if tried_black:
        last_error = "every frame tried was black, so no thumbnail was made"
    return False


def _grab_at(path, out_path, info, target):
    global last_error
    window_start = max(0, target - 60)
    candidates = _candidates(info)
    for pre, chain in candidates:
        if "select=" in chain:
            seek, span = window_start, ["-t", "120"]
        else:
            seek, span = target, []
        colour = (["-pix_fmt", "yuvj420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                   "-color_range", "pc"] if info["hdr"] else [])
        args = ["ffmpeg", "-y", "-v", "error", "-strict", "unofficial", *pre, "-ss", str(seek), "-i", path, *span,
                "-vf", chain, "-frames:v", "1", "-q:v", "2", *colour, out_path]
        ok = _run(args, out_path, 90 if info["hdr"] else 60)
        logger.info("frame grab %s: %s", "ok" if ok else f"failed ({last_error})", " ".join(args))
        if ok:
            if info["dv_profile"] is not None and _mostly_green(out_path):
                last_error = ("the frame came out green, so the Dolby Vision metadata was not applied "
                              "(profile 5 needs ffmpeg with libplacebo and a working Vulkan device)")
                os.unlink(out_path)
                continue
            return True
    if info["dv_profile"] == 5:
        return _grab_profile5(path, out_path, target)
    return False


def _mostly_black(path):
    """True for a frame that is black or nearly so (average brightness under about 8%)."""
    try:
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "signalstats,metadata=print:file=-", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    values = dict(re.findall(r"lavfi\.signalstats\.(YAVG|YHIGH)=([0-9.]+)", out))
    try:
        return float(values["YAVG"]) < 20 and float(values["YHIGH"]) < 90
    except (KeyError, ValueError):
        return False


def _mostly_green(path):
    """True for the green frame a Dolby Vision profile 5 file gives when its metadata is not applied."""
    try:
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "signalstats,metadata=print:file=-", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    values = dict(re.findall(r"lavfi\.signalstats\.([UV]AVG)=([0-9.]+)", out))
    try:
        return float(values["UAVG"]) < 104 and float(values["VAVG"]) < 104
    except (KeyError, ValueError):
        return False


# The add-on's fallback for profile 5 when libplacebo cannot run: dovi_tool mode 3, then the HDR10 tone map.
_P5_CHAIN = ("setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,"
             "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
             f"zscale=t=bt709:m=bt709:r=full,format=yuvj420p,scale={WIDTH}:-2")
_P5_SECONDS = 8


def _grab_profile5(path, out_path, target):
    """A short stream copy converted with dovi_tool, then tone mapped. A green result is refused like any other."""
    global last_error
    if not shutil.which("dovi_tool"):
        return False
    with tempfile.TemporaryDirectory(prefix="curator-dovi-") as work:
        segment = os.path.join(work, "segment.hevc")
        converted = os.path.join(work, "converted.hevc")
        steps = [
            (["ffmpeg", "-y", "-v", "error", "-ss", str(target), "-i", path, "-t", str(_P5_SECONDS), "-map", "0:v:0",
              "-c:v", "copy", "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", segment], segment, 120),
            (["dovi_tool", "-m", "3", "convert", segment, "-o", converted], converted, 180),
        ]
        for args, wanted, timeout in steps:
            try:
                result = subprocess.run(args, capture_output=True, timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                last_error += f" | {args[0]}: {exc}"
                return False
            if result.returncode != 0 or not os.path.isfile(wanted) or os.path.getsize(wanted) == 0:
                text = (result.stderr or result.stdout or b"").decode("utf-8", "replace").strip().splitlines()
                last_error += f" | {args[0]} failed" + (f": {text[-1][:150]}" if text else "")
                return False
        args = ["ffmpeg", "-y", "-v", "error", "-strict", "unofficial", "-f", "hevc", "-i", converted, "-ss", "1",
                "-vf", _P5_CHAIN, "-frames:v", "1", "-q:v", "2", "-pix_fmt", "yuvj420p", "-color_primaries", "bt709",
                "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "pc", out_path]
        if not _run(args, out_path, 120):
            last_error = f"dovi_tool route: {last_error}"
            return False
        if _mostly_green(out_path):
            last_error += " | the dovi_tool route also came out green"
            os.unlink(out_path)
            return False
        return True
