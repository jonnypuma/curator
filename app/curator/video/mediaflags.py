"""Media-flag cards for a movie or episode file.

Left pane order is resolution, aspect ratio, video codec, audio codec, HDR,
secondary HDR, channel count, then source format. The room pane is the screen
frame with that layout's speaker map on top.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from curator.video.brands import file_for, fold

# Folded probe label -> icon file stem in media/codecs.
_CODEC = {
    "truehdatmos": "Dolby_TrueHD_Atmos",
    "atmos": "Dolby_Digital_Plus_Atmos",
    "truehd": "Dolby_TrueHD",
    "mlp": "Dolby_TrueHD",
    "eac3atmos": "Dolby_Digital_Plus_Atmos",
    "dolbydigitalplusatmos": "Dolby_Digital_Plus_Atmos",
    "dtshdma": "DTS-HD-MA",
    "dtshdmasteraudio": "DTS-HD-MA",
    "dtsma": "DTS-HD-MA",
    "dtshdhra": "DTS-HD-HRA",
    "dtsx": "DTSX",
    "dts9624": "DTS-96-24",
    "dtses": "DTS-ES",
    "dtsexpress": "DTS-Express",
    "dts": "DTS",
    "ac3": "Dolby_Digital",
    "dolbydigital": "Dolby_Digital",
    "dd": "Dolby_Digital",
    "eac3": "Dolby_Digital_Plus",
    "dolbydigitalplus": "Dolby_Digital_Plus",
    "ddp": "Dolby_Digital_Plus",
    "aac": "AAC",
    "aaclc": "AAC-LC",
    "heaac": "HE-AAC",
    "heaacv2": "HE_AAC_v2",
    "flac": "FLAC",
    "pcm": "PCM",
    "lpcm": "PCM",
    "opus": "OPUS",
    "vorbis": "VORBIS",
    "ogg": "OGG",
    "aaclatm": "AAC_LATM",
    "aacltp": "AAC_LTP",
    "aacssr": "AAC_SSR",
    "cdda": "cdda",
    "ape": "ape",
    "aiff": "aiff",
    "aif": "aif",
    "aifc": "aifc",
    "dsf": "dsf",
    "dsd": "dsf",
    "auro3d": "auro3d",
    "auro": "auro3d",
    "dolbyprologic": "dolby_pro_logic_ii",
    "dolbyprologicii": "dolby_pro_logic_ii",
    "prologic": "dolby_pro_logic_ii",
    "dolbysurround": "dolby_surround",
    "dolbystereo": "dolby_stereo",
    "av2": "av2",
    "flv": "flv",
    "svq3": "svq3",
    "mp3": "MP3",
    "mp2": "MP2",
    "mp1": "MP1",
    "wma": "WMA",
    "alac": "apple_lossless",
    "applelossless": "apple_lossless",
    "mpeg2": "mpeg2",
    "mpeg2video": "mpeg2",
    "mpeg1": "mpeg1",
    "mpeg1video": "mpeg1",
    "mpeg4": "mpeg-video",
    "mpegvideo": "mpeg-video",
    "vc1": "vc-1",
    "av1": "av1",
    "vp9": "vp9",
    "vp8": "vp8",
    "divx": "divx",
    "xvid": "xvid",
    "wmv": "wmv",
    "wmv3": "wmv",
    "dovi": "Dolby_Vision",
    "dolbyvision": "Dolby_Vision",
    "dolbyvisionimax": "Dolby_Vision_IMAX",
    "hdr10plus": "HDR10Plus",
    "hdr10plusimax": "HDR10Plus_IMAX",
    "hdr10": "HDR10",
    "hdr10imax": "HDR10_IMAX",
    "hlg": "HLG",
    "sdr": "SDR",
    "imax": "IMAX",
}

# Folded source label -> icon file stem in media/format.
_FORMAT = {
    "uhdremux": "uhd-bluray",
    "uhdbluray": "uhd-bluray",
    "completeuhdbluray": "uhd-bluray",
    "uhdrip": "uhd-bluray",
    "blurayremux": "bluray_disc",
    "bdremux": "bluray_disc",
    "brremux": "bluray_disc",
    "remux": "remux",
    "blurayrip": "bluray_rip",
    "bdrip": "bluray_rip",
    "brrip": "bluray_rip",
    "completebluray": "bluray_disc",
    "bluray": "bluray_disc",
    "brdisk": "bluray_disc",
    "3dbluray": "3d_bluray",
    "dvdrip": "dvd_rip",
    "dvd": "dvd",
    "hddvdremux": "hddvd",
    "hddvd": "hddvd",
    "webdl": "web-dl",
    "webrip": "web-dl",
    "webcap": "web-dl",
    "web": "web-dl",
    "hdtv": "hdtv",
    "pdtv": "sdtv",
    "sdtv": "sdtv",
    "dsr": "sdtv",
    "tvrip": "sdtv",
    "vhsrip": "vhs",
    "vhs": "vhs",
    "imaxenhanced": "imax_enhanced",
    "imax": "imax",
}

# Folded resolution label -> icon stem. 2160p and 4K share the 4K badge.
_RESOLUTION = {
    "4k": "4K", "2160": "4K", "2160p": "4K", "uhd": "4K", "3840": "4K",
    "1080": "1080", "1080p": "1080", "1080i": "1080", "fhd": "1080",
    "720": "720", "720p": "720",
    "576": "576", "576p": "576", "576i": "576", "pal": "576",
    "540": "540", "540p": "540",
    "480": "480", "480p": "480", "480i": "480", "ntsc": "480", "sd": "480",
    "288": "288", "288p": "288",
}
_HEIGHTS = ((2160, "4K"), (1080, "1080"), (720, "720"), (576, "576"), (540, "540"), (480, "480"), (288, "288"))
# Decimal ratio -> aspectratios stem. 9:16 (0.56) has no file, so it is skipped.
_ASPECTS = (
    (0.56, "0.56"), (1.25, "1.25"), (1.33, "1.33"), (1.37, "1.37"), (1.43, "1.43"),
    (1.50, "1.50"), (1.60, "1.60"), (1.66, "1.66"), (1.75, "1.75"), (1.78, "1.78"),
    (1.85, "1.85"), (1.90, "1.90"), (2.00, "2.00"), (2.20, "2.20"), (2.39, "2.39"),
    (2.40, "2.40"), (2.55, "2.55"), (2.59, "2.59"), (2.76, "2.76"), (3.00, "3.00"),
)
# Folded channel layout -> speaker map in audiochannels_room.
_ROOM = {
    "1": "1.0", "10": "1.0", "mono": "1.0",
    "2": "2.0", "20": "2.0", "stereo": "2.0",
    "21": "2.1", "31": "3.1", "41": "4.1",
    "51": "5.1", "512": "5.1.2", "61": "6.1",
    "71": "7.1", "712": "7.1.2",
}
_HDR = {"dovi", "dolbyvision", "dolbyvisionimax", "hdr10plus", "hdr10plusimax", "hdr10", "hdr10imax", "hlg", "sdr"}


def _icon(kind, stem, label):
    filename = file_for(stem, kind)
    if not filename:
        return None
    return {"name": label, "src": f"/media/{kind}/{quote(filename)}"}


def _codec_icon(label, imax=False):
    key = fold(label)
    if imax and key in {"dovi", "dolbyvision"}:
        key = "dolbyvisionimax"
    elif imax and key in {"hdr10plus", "hdr10plusimax"}:
        key = "hdr10plusimax"
    elif imax and key == "hdr10":
        key = "hdr10imax"
    stem = _CODEC.get(key)
    if not stem:
        stem = label
    return _icon("codecs", stem, str(label or stem))


def _format_icon(label):
    key = fold(label)
    stem = _FORMAT.get(key)
    if not stem:
        return None
    return _icon("format", stem, str(label))


def _resolution_stem(file):
    label = str(file.get("resolution") or "")
    stem = _RESOLUTION.get(fold(label))
    if stem:
        return stem
    match = re.search(r"(\d{3,4})", label)
    if match:
        stem = _RESOLUTION.get(fold(match.group(1)))
        if stem:
            return stem
    try:
        height = int(file.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    if not height:
        return None
    nearest, stem = min(_HEIGHTS, key=lambda item: abs(item[0] - height))
    if abs(nearest - height) <= 40:
        return stem
    return None


def _aspect_value(raw):
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    if ":" in text or "/" in text:
        left, _, right = text.replace(":", "/").partition("/")
        try:
            width = float(left)
            height = float(right)
        except ValueError:
            return None
        return width / height if height else None
    try:
        return float(text)
    except ValueError:
        return None


def _aspect_stem(raw):
    value = _aspect_value(raw)
    if not value:
        return None
    nearest, stem = min(_ASPECTS, key=lambda item: abs(item[0] - value))
    if abs(nearest - value) <= 0.045:
        return stem
    return None


def _audio(file):
    tracks = [item for item in (file.get("audio_tracks") or []) if isinstance(item, dict)]
    if tracks:
        return next((item for item in tracks if item.get("default")), tracks[0]), tracks
    codec = file.get("audio_codec") or ""
    channels = file.get("audio_channels") or ""
    if codec or channels:
        return {"codec": codec, "channels": channels}, []
    return {}, []


def _channel_text(file):
    main, _tracks = _audio(file)
    return str(main.get("channels") or file.get("audio_channels") or "").strip()


def _channel_count(text):
    parts = [int(item) for item in re.findall(r"\d+", text or "")]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return sum(parts)


def _room(file):
    text = _channel_text(file)
    stem = _ROOM.get(fold(text))
    overlay = _icon("audiochannels_room", stem, text) if stem else None
    if not overlay:
        count = _channel_count(text)
        overlay = _icon("audiochannels", str(count), text) if count is not None else None
    base = _icon("audiochannels_room", "layer", "Room")
    if not base or not overlay:
        return None
    return {"slot": "room", "name": text or overlay["name"], "base": base["src"], "overlay": overlay["src"]}


def cards(file):
    """Flags in pane order, then the room layout when the channel map is known."""
    if not file:
        return []
    edition = str(file.get("edition") or "")
    imax = "imax" in edition.lower()
    found = []
    seen = set()

    def add(icon):
        if not icon or icon.get("slot") == "room" or icon["src"] in seen:
            return
        seen.add(icon["src"])
        found.append(icon)

    add(_icon("resolution", _resolution_stem(file) or "", file.get("resolution") or ""))
    aspect = _aspect_stem(file.get("aspect_ratio"))
    add(_icon("aspectratios", aspect or "", aspect or ""))
    video_key = fold(file.get("video_codec") or "")
    if video_key not in _HDR:
        add(_codec_icon(file.get("video_codec") or ""))
    _main, tracks = _audio(file)
    if tracks:
        for track in tracks:
            add(_codec_icon(track.get("codec") or ""))
    elif _main.get("codec"):
        add(_codec_icon(_main.get("codec") or ""))
    hdr = str(file.get("hdr_format") or "")
    if hdr:
        add(_codec_icon(hdr, imax=imax))
    secondary = str(file.get("hdr_secondary") or "")
    if secondary:
        add(_codec_icon(secondary))
    count = _channel_count(_channel_text(file))
    add(_icon("audiochannels", str(count) if count is not None else "", _channel_text(file)))
    source = str(file.get("source_format") or "")
    group = str(file.get("video_source") or "")
    add(_format_icon(source or group))
    if source and group:
        add(_format_icon(group))
    if "remux" in fold(source) or "remux" in fold(group):
        add(_format_icon("Remux"))
    if imax:
        add(_format_icon("IMAX Enhanced" if "enhanced" in edition.lower() else "IMAX"))
    if file.get("is_3d"):
        add(_format_icon("3D Blu-ray"))
    room = _room(file)
    if room:
        found.append(room)
    return found


def unique(rows):
    """Cards from several episode files, each icon once. One room, from the first file that has one."""
    found = []
    seen = set()
    room = None
    for row in rows or []:
        for icon in row or []:
            if icon.get("slot") == "room":
                if room is None:
                    room = icon
                continue
            if icon["src"] in seen:
                continue
            seen.add(icon["src"])
            found.append(icon)
    if room:
        found.append(room)
    return found
