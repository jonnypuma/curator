"""Language codes, subtitle flags and audio codec labels. Ported from video-analyzer."""
from __future__ import annotations

import re
from typing import Any, Optional

# Canonical ISO 639-2/T codes, except Czech (cze), Greek (gre), Chinese (chi),
# and Romanian (rum) which use the bibliographic 639-2/B codes common on discs.
# Aliases include ISO 639-1, the other 639-2 form, and English names.
_LANG_ALIASES: dict[str, str] = {
    "en": "eng", "eng": "eng", "english": "eng", "en-us": "eng", "en-gb": "eng", "en-au": "eng",
    "sv": "swe", "swe": "swe", "swedish": "swe",
    "de": "deu", "deu": "deu", "ger": "deu", "german": "deu",
    "no": "nor", "nor": "nor", "nob": "nor", "norwegian": "nor",
    "nb": "nor", "nb-no": "nor", "no-no": "nor", "bokmal": "nor", "bokm\u00e5l": "nor", "norsk": "nor",
    "nn": "nno", "nno": "nno", "nn-no": "nno", "nynorsk": "nno",
    "da": "dan", "dan": "dan", "danish": "dan",
    "fi": "fin", "fin": "fin", "finnish": "fin",
    "nl": "nld", "nld": "nld", "dut": "nld", "dutch": "nld",
    "fr": "fra", "fra": "fra", "fre": "fra", "french": "fra",
    "es": "spa", "spa": "spa", "spanish": "spa",
    "it": "ita", "ita": "ita", "italian": "ita",
    "pt": "por", "por": "por", "portuguese": "por", "pt-br": "por",
    "pl": "pol", "pol": "pol", "polish": "pol",
    "ru": "rus", "rus": "rus", "russian": "rus",
    "ja": "jpn", "jpn": "jpn", "japanese": "jpn",
    "ko": "kor", "kor": "kor", "korean": "kor",
    "zh": "chi", "zho": "chi", "chi": "chi", "chn": "chi", "chinese": "chi", "cmn": "chi",
    "ar": "ara", "ara": "ara", "arabic": "ara",
    "hi": "hin", "hin": "hin", "hindi": "hin",
    "cs": "cze", "ces": "cze", "cze": "cze", "czech": "cze",
    "hu": "hun", "hun": "hun", "hungarian": "hun",
    "ro": "rum", "ron": "rum", "rum": "rum", "romanian": "rum",
    "tr": "tur", "tur": "tur", "turkish": "tur",
    "el": "gre", "ell": "gre", "gre": "gre", "greek": "gre",
    "he": "heb", "heb": "heb", "hebrew": "heb",
    "th": "tha", "tha": "tha", "thai": "tha",
    "vi": "vie", "vie": "vie", "vietnamese": "vie",
    "uk": "ukr", "ukr": "ukr", "ukrainian": "ukr",
    "is": "isl", "isl": "isl", "ice": "isl", "icelandic": "isl",
    "et": "est", "est": "est", "estonian": "est",
    "lv": "lav", "lav": "lav", "latvian": "lav",
    "lt": "lit", "lit": "lit", "lithuanian": "lit",
    "sk": "slk", "slk": "slk", "slo": "slk", "slovak": "slk",
    "sl": "slv", "slv": "slv", "slovenian": "slv",
    "bg": "bul", "bul": "bul", "bulgarian": "bul",
    "hr": "hrv", "hrv": "hrv", "croatian": "hrv",
    "sr": "srp", "srp": "srp", "serbian": "srp",
    "und": "und", "unknown": "und",
}

_LANG_LABELS: dict[str, str] = {
    "eng": "English", "swe": "Swedish", "deu": "German", "nor": "Norwegian", "nno": "Norwegian Nynorsk",
    "dan": "Danish", "fin": "Finnish", "nld": "Dutch", "fra": "French",
    "spa": "Spanish", "ita": "Italian", "por": "Portuguese", "pol": "Polish",
    "rus": "Russian", "jpn": "Japanese", "kor": "Korean", "chi": "Chinese",
    "ara": "Arabic", "hin": "Hindi", "cze": "Czech", "hun": "Hungarian",
    "rum": "Romanian", "tur": "Turkish", "gre": "Greek", "heb": "Hebrew",
    "tha": "Thai", "vie": "Vietnamese", "ukr": "Ukrainian", "isl": "Icelandic",
    "est": "Estonian", "lav": "Latvian", "lit": "Lithuanian", "slk": "Slovak",
    "slv": "Slovenian", "bul": "Bulgarian", "hrv": "Croatian", "srp": "Serbian",
    "und": "Unknown",
}

_LANG_TOKEN_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2,8})?|[A-Za-z]+")


def normalize_lang(value: Any) -> str:
    """Return a canonical 3-letter (or original lowercased) language code."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.lower().replace("_", "-")
    if key in _LANG_ALIASES:
        return _LANG_ALIASES[key]
    match = _LANG_TOKEN_RE.search(key)
    if match:
        token = match.group(0)
        if token in _LANG_ALIASES:
            return _LANG_ALIASES[token]
        base = token.split("-", 1)[0]
        if base in _LANG_ALIASES:
            return _LANG_ALIASES[base]
        if len(base) in (2, 3):
            return base
    return key


def language_label(code: str) -> str:
    canon = normalize_lang(code)
    if not canon:
        return ""
    name = _LANG_LABELS.get(canon)
    return f"{name} ({canon})" if name else canon


def is_default_flag(value: Any) -> bool:
    """True for MediaInfo Default=Yes / ffprobe disposition.default=1."""
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    if not text or text in {"0", "no", "false", "n"}:
        return False
    return text.startswith("yes") or text in {"1", "true", "default"}


SUB_FLAG_SDH = "sdh"
SUB_FLAG_HI = "hi"
SUB_FLAG_FORCED = "forced"
_SUB_FLAG_ORDER = (SUB_FLAG_SDH, SUB_FLAG_HI, SUB_FLAG_FORCED)

_SDH_TEXT_RE = re.compile(
    r"\b(?:sdh|cc|closed\s*captions?|captions?|hearing(?:[\s_-]*impaired)?)\b",
    re.I,
)
_FORCED_TEXT_RE = re.compile(
    r"\b(?:forced|force|signs(?:[\s/&+_:-]*songs?)?)\b",
    re.I,
)
_ENG_HI_RE = re.compile(
    r"(?<![a-z])(?:en|eng|english)\s*[-_/]?\s*hi\b",
    re.I,
)
_FLAG_ALIAS = {
    "sdh": SUB_FLAG_SDH,
    "hi": SUB_FLAG_HI,
    "cc": SUB_FLAG_SDH,
    "caption": SUB_FLAG_SDH,
    "captions": SUB_FLAG_SDH,
    "forced": SUB_FLAG_FORCED,
    "force": SUB_FLAG_FORCED,
}


def canonical_sub_flags(values: Any) -> list[str]:
    """Return ordered unique flags from a stored slot or a list of tokens."""
    found: set[str] = set()
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        tokens: list[str] = []
        for value in values:
            tokens.extend(str(value).lower().replace(",", " ").split())
    else:
        tokens = str(values).lower().replace(",", " ").split()
    for token in tokens:
        flag = _FLAG_ALIAS.get(token)
        if flag:
            found.add(flag)
    return [flag for flag in _SUB_FLAG_ORDER if flag in found]


def join_sub_flags(values: Any) -> str:
    return " ".join(canonical_sub_flags(values))


def format_sub_label(lang: str, flags: Any = None) -> str:
    code = lang or "und"
    extra = join_sub_flags(flags)
    return f"{code} {extra}".strip() if extra else code


def _remainder_after_lang(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    lowered = text.lower().replace("_", "-")
    match = _LANG_TOKEN_RE.search(lowered)
    if not match:
        return text
    return (lowered[: match.start()] + " " + lowered[match.end() :]).strip(" -_/(),[]")


def classify_sub_flags(
    *,
    forced: Any = None,
    hearing_impaired: Any = None,
    captions: Any = None,
    title: Any = None,
    language_raw: Any = None,
    extra_text: Any = None,
) -> list[str]:
    """Detect SDH / Forced from container flags plus title/language text.

    Lone ``hi`` is Hindi, not hearing-impaired. ``eng hi`` / ``en hi`` is the HI flag.
    """
    found: set[str] = set()
    if is_default_flag(forced):
        found.add(SUB_FLAG_FORCED)
    if is_default_flag(hearing_impaired) or is_default_flag(captions):
        found.add(SUB_FLAG_SDH)
    blob = " ".join(str(part or "") for part in (title, language_raw, extra_text))
    if blob.strip():
        if _SDH_TEXT_RE.search(blob):
            found.add(SUB_FLAG_SDH)
        if _FORCED_TEXT_RE.search(blob):
            found.add(SUB_FLAG_FORCED)
        if _ENG_HI_RE.search(blob):
            found.add(SUB_FLAG_HI)
    lang_raw = str(language_raw or "").strip()
    if lang_raw and normalize_lang(lang_raw) != "hin":
        rest = _remainder_after_lang(lang_raw).lower().replace("-", " ").replace("_", " ").strip()
        if rest == "hi" or rest.startswith("hi "):
            found.add(SUB_FLAG_HI)
    return [flag for flag in _SUB_FLAG_ORDER if flag in found]


def sub_flags_from_mediainfo(track: dict[str, Any] | None) -> list[str]:
    track = track or {}
    extra = track.get("extra") if isinstance(track.get("extra"), dict) else {}
    if not extra and isinstance(track.get("Extra"), dict):
        extra = track["Extra"]
    extra_text = " ".join(str(v) for v in extra.values() if isinstance(v, (str, int)))
    return classify_sub_flags(
        forced=track.get("Forced") or extra.get("Forced"),
        hearing_impaired=(
            track.get("HearingImpaired")
            or track.get("Hearing_Impaired")
            or extra.get("HearingImpaired")
        ),
        title=track.get("Title") or extra.get("Title") or "",
        language_raw=track.get("Language") or "",
        extra_text=extra_text,
    )


def split_track_list(raw: Any) -> list[str]:
    """Split a comma-separated scan field, keeping empty slots."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return ["" if v in (None, "") else str(v).strip() for v in raw]
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",")]


def join_track_list(values: list[Any], keep_empty: bool = False) -> str:
    if keep_empty:
        parts = ["" if v in (None, "") else str(v).strip() for v in values]
        while parts and parts[-1] == "":
            parts.pop()
        return ", ".join(parts)
    return ", ".join(str(v).strip() for v in values if v not in (None, ""))


def first_default_index(flags: list[bool]) -> Optional[int]:
    """1-based index of the first default flag, or None."""
    for i, flag in enumerate(flags):
        if flag:
            return i + 1
    return None


def lang_at(langs: list[str], idx: Optional[int]) -> Optional[str]:
    if not idx or idx < 1 or idx > len(langs):
        return None
    code = normalize_lang(langs[idx - 1])
    return code or None


def format_channel_layout(raw: Any) -> str:
    """Turn MediaInfo/ffprobe channel counts into 2.0 / 5.1 / 7.1 when possible."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if re.match(r"^\d+\.\d+$", text):
        return text
    try:
        count = int(float(text.replace(",", ".")))
    except ValueError:
        return text
    return {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}.get(count, str(count))


def build_audio_tracks(
    codecs: Any,
    langs: Any,
    channels: Any,
    default_idx: Optional[int],
) -> list[dict[str, Any]]:
    codec_list = split_track_list(codecs)
    lang_list = split_track_list(langs)
    ch_list = split_track_list(channels)
    n = max(len(codec_list), len(lang_list), len(ch_list))
    tracks = []
    for i in range(n):
        lang = normalize_lang(lang_list[i] if i < len(lang_list) else "")
        tracks.append({
            "idx": i + 1,
            "codec": codec_list[i] if i < len(codec_list) else "",
            "lang": lang,
            "channels": format_channel_layout(ch_list[i] if i < len(ch_list) else ""),
            "is_default": default_idx == i + 1,
        })
    return tracks


def build_sub_tracks(
    subtitles: Any,
    default_idx: Optional[int],
    subtitle_flags: Any = None,
) -> list[dict[str, Any]]:
    lang_list = split_track_list(subtitles)
    flag_list = split_track_list(subtitle_flags)
    tracks = []
    for i, raw in enumerate(lang_list):
        lang = normalize_lang(raw)
        flags = canonical_sub_flags(flag_list[i] if i < len(flag_list) else "")
        if not flags:
            flags = classify_sub_flags(language_raw=raw, title="")
        tracks.append({
            "idx": i + 1,
            "lang": lang,
            "flags": flags,
            "is_sdh": SUB_FLAG_SDH in flags,
            "is_forced": SUB_FLAG_FORCED in flags,
            "is_default": default_idx == i + 1,
            "label": format_sub_label(lang, flags),
        })
    return tracks


_AUDIO_CODEC_RANK = (
    "truehd atmos",
    "atmos",
    "dts:x",
    "dts-x",
    "truehd",
    "dts-hd ma",
    "flac",
    "pcm",
    "lpcm",
    "dts-hd hra",
    "dts-hd",
    "dts",
    "e-ac-3",
    "eac3",
    "ac3",
    "aac",
)


def label_audio_codec(
    *,
    format: str = "",
    commercial: str = "",
    additional: str = "",
    codec_name: str = "",
    profile: str = "",
) -> str:
    """Normalize MediaInfo/ffprobe audio names to a short label (DTS-HD MA vs DTS vs PCM)."""
    commercial = str(commercial or "").strip()
    fmt = str(format or "").strip()
    extra = str(additional or "").strip()
    codec_name = str(codec_name or "").strip()
    profile = str(profile or "").strip()
    blob = " ".join((commercial, fmt, extra, codec_name, profile)).lower()
    extra_compact = extra.upper().replace(" ", "")

    if "atmos" in blob:
        if "truehd" in blob or fmt.upper() in {"MLP", "MLP FBA"}:
            return "TrueHD Atmos"
        return "Atmos"
    if extra_compact in {"XLLX"} or "xll x" in extra.lower() or "dts:x" in blob or "dts-x" in blob:
        return "DTS:X"
    if "truehd" in blob or fmt.upper() in {"MLP", "MLP FBA"}:
        return "TrueHD"
    if extra_compact == "XLL" or "master" in blob or "dts-hd ma" in blob:
        return "DTS-HD MA"
    if extra_compact == "XBR" or "high res" in blob or "dts-hd hra" in blob:
        return "DTS-HD HRA"
    if fmt.upper().startswith("DTS") or codec_name.lower() == "dts" or "dts" in blob:
        if commercial and commercial.upper() not in {"DTS"}:
            if "master" in commercial.lower():
                return "DTS-HD MA"
            return commercial
        return "DTS"
    if "pcm" in blob or codec_name.lower().startswith("pcm"):
        return "PCM"
    if commercial:
        return commercial
    return fmt or codec_name or profile


def _channel_score(raw: Any) -> float:
    text = str(raw or "").strip().replace(",", ".")
    match = re.match(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


def _audio_codec_rank(codec: Any) -> int:
    text = str(codec or "").strip().lower()
    if not text:
        return 0
    best = 0
    for i, name in enumerate(_AUDIO_CODEC_RANK):
        if name in text:
            best = max(best, len(_AUDIO_CODEC_RANK) - i)
    return best


def find_lang_index(
    tracks: list[dict[str, Any]],
    want: str,
    *,
    prefer_full: bool = False,
) -> Optional[int]:
    target = normalize_lang(want)
    if not target:
        return None
    matches = [track for track in tracks if normalize_lang(track.get("lang")) == target]
    if not matches:
        return None
    if prefer_full:
        def _sub_rank(track: dict[str, Any]) -> tuple[int, int]:
            if track.get("is_forced"):
                return (2, int(track.get("idx") or 0))
            if track.get("is_sdh"):
                return (1, int(track.get("idx") or 0))
            return (0, int(track.get("idx") or 0))
        matches = sorted(matches, key=_sub_rank)
    elif any(track.get("codec") or track.get("channels") for track in matches):
        def _audio_rank(track: dict[str, Any]) -> tuple[float, int, int]:
            return (
                -_channel_score(track.get("channels")),
                -_audio_codec_rank(track.get("codec")),
                int(track.get("idx") or 0),
            )
        matches = sorted(matches, key=_audio_rank)
    return int(matches[0]["idx"])


def default_is_not_language(stored: Any, want: str) -> bool:
    """True when stored default is missing or a different language than want."""
    target = normalize_lang(want)
    if not target:
        return False
    current = normalize_lang(stored)
    return current != target


def default_is_language(stored: Any, want: str) -> bool:
    """True when stored default is set and matches want."""
    target = normalize_lang(want)
    if not target:
        return False
    return normalize_lang(stored) == target


def tracks_include_language(raw: Any, want: str) -> bool:
    """True when a comma-separated track-language field includes want."""
    target = normalize_lang(want)
    if not target:
        return False
    return any(normalize_lang(token) == target for token in split_track_list(raw) if token)


def collect_unique_langs(*raw_fields: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for field in raw_fields:
        for token in split_track_list(field):
            code = normalize_lang(token)
            if code and code != "und" and code not in seen:
                seen.add(code)
                ordered.append(code)
    ordered.sort(key=lambda c: (language_label(c).lower(), c))
    return ordered


def tracks_from_ffprobe(probe_data: dict | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Audio and subtitle track dicts from ffprobe JSON (1-based idx per type)."""
    audio: list[dict[str, Any]] = []
    subs: list[dict[str, Any]] = []
    if not probe_data:
        return audio, subs
    for stream in probe_data.get("streams") or []:
        kind = stream.get("codec_type")
        tags = stream.get("tags") or {}
        lang = normalize_lang(tags.get("language") or tags.get("LANGUAGE") or "")
        disp = stream.get("disposition") or {}
        is_def = is_default_flag(disp.get("default"))
        if kind == "audio":
            audio.append({
                "idx": len(audio) + 1,
                "codec": label_audio_codec(
                    codec_name=stream.get("codec_name") or "",
                    profile=stream.get("profile") or "",
                ),
                "lang": lang,
                "channels": format_channel_layout(stream.get("channels") or ""),
                "is_default": is_def,
            })
        elif kind in ("subtitle", "text"):
            lang_raw = tags.get("language") or tags.get("LANGUAGE") or ""
            title = tags.get("title") or tags.get("TITLE") or tags.get("handler_name") or ""
            flags = classify_sub_flags(
                forced=disp.get("forced"),
                hearing_impaired=disp.get("hearing_impaired"),
                captions=disp.get("captions"),
                title=title,
                language_raw=lang_raw,
            )
            subs.append({
                "idx": len(subs) + 1,
                "lang": lang,
                "flags": flags,
                "is_sdh": SUB_FLAG_SDH in flags,
                "is_forced": SUB_FLAG_FORCED in flags,
                "is_default": is_def,
                "label": format_sub_label(lang, flags),
            })
    return audio, subs
