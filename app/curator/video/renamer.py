"""Jinja2 folder and file names for movies and TV, with the spec's sanitize and pad filters.

Templates render one path component each. Forbidden characters are stripped from the result, empty
brackets and doubled separators left by missing values are removed, and the extension is appended
in lowercase.
"""
from __future__ import annotations

import re
from functools import lru_cache

from jinja2 import ChainableUndefined, TemplateError, Undefined
from jinja2.sandbox import SandboxedEnvironment

from curator.video import naming

FORBIDDEN = re.compile(r'[/\\:*?"<>|]')
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SPACES = re.compile(r"\s+")

_HEAD = (
    "{{ movie.title | dot }}{% if movie.year %}.{{ movie.year }}{% endif %}"
    "{% if movie.edition %}.{{ movie.edition | dot }}{% endif %}"
)
_MEDIA = (
    "{% if media.quality %}.{{ media.quality }}{% endif %}"
    "{% if media.source %}.{{ media.source | dot }}{% endif %}"
    "{% if media.resolution %}.{{ media.resolution }}{% endif %}"
    "{% if media.audio_codec %}.{{ media.audio_codec | dot }}{% endif %}"
    "{% if media.audio_channels %}.{{ media.audio_channels }}{% endif %}"
    "{% if media.hdr and media.hdr != 'SDR' %}.{{ media.hdr | dot }}{% endif %}"
    "{% if media.video_codec %}.{{ media.video_codec | dot }}{% endif %}"
    "{% if media.hybrid %}.{{ media.hybrid }}{% endif %}"
    "{% if media.format %}.{{ media.format }}{% endif %}"
)
_GROUP = "{% if media.release_group %}-{{ media.release_group }}{% endif %}"

DEFAULTS = {
    "movie_folder": _HEAD + _MEDIA + _GROUP,
    "movie_file": _HEAD + _MEDIA + "{% if movie.part %}.{{ movie.part }}{% endif %}" + _GROUP,
    "show_folder": (
        "{{ show.title | dot }}{% if show.year %}.{{ show.year }}{% endif %}"
        "{% if show.id.tvdb %}.tvdbid-{{ show.id.tvdb }}{% endif %}"
    ),
    "season_folder": "{% if episode.season_raw == 0 %}Specials{% else %}Season {{ episode.season_raw }}{% endif %}",
    "episode_file": (
        "{{ show.title | dot }}.S{{ episode.season | pad(2) }}E{{ episode.number | pad(2) }}"
        "{% if episode.title %}.{{ episode.title | dot }}{% endif %}"
        + _MEDIA
        + _GROUP
    ),
}

# Patterns saved before dots and a trailing release group. These load as the current defaults.
LEGACY = {
    "movie_folder": {
        "{{ movie.title | sanitize }} ({{ movie.year }}){% if movie.edition %} [{{ movie.edition | sanitize }}]{% endif %}{% if movie.id.tmdb %} [tmdbid-{{ movie.id.tmdb }}]{% endif %}",
        "{{ movie.title | sanitize }} ({{ movie.year }}){% if movie.edition %} [{{ movie.edition | sanitize }}]{% endif %}{% if movie.id.tmdb %} [tmdbid-{{ movie.id.tmdb }}]{% endif %}{% if media.release_group %}-{{ media.release_group }}{% endif %}",
    },
    "movie_file": {
        "{{ movie.title | sanitize }} ({{ movie.year }}){% if movie.edition %} [{{ movie.edition | sanitize }}]{% endif %} - [{{ media.resolution }} {{ media.source }} {{ media.video_codec }}{% if media.hdr and media.hdr != 'SDR' %} {{ media.hdr }}{% endif %} {{ media.audio_codec }} {{ media.audio_channels }}]{% if movie.part %}-{{ movie.part }}{% endif %}",
        (
            "{{ movie.title | dot }}{% if movie.year %}.{{ movie.year }}{% endif %}"
            "{% if movie.edition %}.{{ movie.edition | dot }}{% endif %}"
            "{% if media.resolution %}.{{ media.resolution }}{% endif %}"
            "{% if media.source %}.{{ media.source | dot }}{% endif %}"
            "{% if media.source_format %}.{{ media.source_format | dot }}{% endif %}"
            "{% if media.video_codec %}.{{ media.video_codec | dot }}{% endif %}"
            "{% if media.hdr and media.hdr != 'SDR' %}.{{ media.hdr | dot }}{% endif %}"
            "{% if media.audio_codec %}.{{ media.audio_codec | dot }}{% endif %}"
            "{% if media.audio_channels %}.{{ media.audio_channels }}{% endif %}"
            "{% if movie.part %}.{{ movie.part }}{% endif %}"
            "{% if media.release_group %}-{{ media.release_group }}{% endif %}"
        ),
    },
    "show_folder": {
        "{{ show.title | sanitize }} ({{ show.year }}){% if show.id.tvdb %} [tvdbid-{{ show.id.tvdb }}]{% endif %}",
    },
    "season_folder": {
        "{% if episode.season_raw == 0 %}Specials{% else %}Season {{ episode.season | pad(2) }}{% endif %}",
        "{% if episode.season_raw == 0 %}Specials{% else %}Season.{{ episode.season | pad(2) }}{% endif %}",
    },
    "episode_file": {
        "{{ show.title | sanitize }} - S{{ episode.season | pad(2) }}E{{ episode.number | pad(2) }} - {{ episode.title | sanitize }}{% if media.resolution %} [{{ media.resolution }} {{ media.video_codec }}]{% endif %}",
        (
            "{{ show.title | dot }}.S{{ episode.season | pad(2) }}E{{ episode.number | pad(2) }}"
            "{% if episode.title %}.{{ episode.title | dot }}{% endif %}"
            "{% if media.resolution %}.{{ media.resolution }}{% endif %}"
            "{% if media.source %}.{{ media.source | dot }}{% endif %}"
            "{% if media.source_format %}.{{ media.source_format | dot }}{% endif %}"
            "{% if media.video_codec %}.{{ media.video_codec | dot }}{% endif %}"
            "{% if media.hdr and media.hdr != 'SDR' %}.{{ media.hdr | dot }}{% endif %}"
            "{% if media.audio_codec %}.{{ media.audio_codec | dot }}{% endif %}"
            "{% if media.audio_channels %}.{{ media.audio_channels }}{% endif %}"
            "{% if media.release_group %}-{{ media.release_group }}{% endif %}"
        ),
    },
}

_RESOLUTIONS = {"8K": "4320p", "4K": "2160p"}
_HDR = {"hdr10plus": "HDR10P", "hdr10": "HDR10", "hlg": "HLG", "sdr": "SDR"}
_RELEASE = {
    "uhd remux": ("UHD", "BluRay", "REMUX"),
    "uhd blu-ray": ("UHD", "BluRay", ""),
    "uhd bluray": ("UHD", "BluRay", ""),
    "uhd rip": ("UHD", "BluRay", ""),
    "blu-ray remux": ("", "BluRay", "REMUX"),
    "bluray remux": ("", "BluRay", "REMUX"),
    "blu-ray": ("", "BluRay", ""),
    "bluray": ("", "BluRay", ""),
    "blu-ray rip": ("", "BDRip", ""),
    "bd-rip": ("", "BDRip", ""),
    "complete uhd blu-ray": ("UHD", "COMPLETE.BLURAY", ""),
    "complete blu-ray": ("", "COMPLETE.BLURAY", ""),
    "web-dl": ("", "WEB-DL", ""),
    "webrip": ("", "WEBRip", ""),
    "web-rip": ("", "WEBRip", ""),
    "webcap": ("", "WEBCap", ""),
    "hdtv": ("", "HDTV", ""),
    "dvd": ("", "DVD", ""),
    "dvdrip": ("", "DVDRip", ""),
}


def _blank(value):
    return value is None or isinstance(value, Undefined)


def sanitize(value):
    """Strip characters no file system accepts. A colon becomes " - " and a slash a dash."""
    if _blank(value):
        return ""
    text = str(value).replace(":", " - ").replace("/", "-").replace("\\", "-")
    text = FORBIDDEN.sub("", CONTROL.sub("", text))
    return SPACES.sub(" ", text).strip()


def dot(value):
    """Sanitize, then join words with dots. Hyphens stay, so DTS-HD MA becomes DTS-HD.MA."""
    if _blank(value):
        return ""
    text = str(value).replace(":", ".").replace("/", ".").replace("\\", ".")
    text = FORBIDDEN.sub("", CONTROL.sub("", text))
    text = re.sub(r"[\s_]+", ".", text)
    text = re.sub(r"(?:\.-+)+", ".", text)
    text = re.sub(r"\.{2,}", ".", text)
    return text.strip(".")


def pad(value, width=2):
    if _blank(value):
        return ""
    try:
        return str(value).zfill(int(width))
    except (TypeError, ValueError):
        return str(value)


@lru_cache(maxsize=1)
def _env():
    env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True, undefined=ChainableUndefined)
    env.filters["sanitize"] = sanitize
    env.filters["dot"] = dot
    env.filters["pad"] = pad
    return env


@lru_cache(maxsize=64)
def _compiled(template):
    return _env().from_string(template)


def validate(template):
    """Raise ValueError with a readable reason when the template does not compile or render."""
    try:
        _compiled(template).render(movie={}, show={}, episode={}, media={}, sub={}, stem="")
    except TemplateError as exc:
        raise ValueError(str(exc)) from exc


def tidy(text):
    text = SPACES.sub(" ", CONTROL.sub(" ", text))
    text = re.sub(r"\[\s+", "[", re.sub(r"\s+\]", "]", text))
    text = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", text))
    text = re.sub(r"\[\]|\(\)|\{\}", "", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"(?:\s+-){2,}\s+", " - ", text)
    text = FORBIDDEN.sub("", text)
    text = SPACES.sub(" ", text).strip()
    text = re.sub(r"^[\s\-_.]+", "", text)
    return re.sub(r"[\s\-_.]+$", "", text)


def render(template, context, extension=""):
    rendered = tidy(_compiled(template).render(**context))
    if extension:
        ext = extension.lower()
        return f"{rendered}{ext if ext.startswith('.') else '.' + ext}"
    return rendered


# Template contexts from stored rows.

def release_tokens(source_format, video_source):
    """Quality, disc or web source, and edition such as REMUX. UHD Remux becomes UHD, BluRay, REMUX."""
    label = str(source_format or "").strip().lower()
    group = str(video_source or "").strip().lower()
    if label in _RELEASE:
        return _RELEASE[label]
    remux = "REMUX" if "remux" in label else ""
    if group in {"uhd bluray", "uhd blu-ray"}:
        return ("UHD", "BluRay", remux)
    if group == "bluray":
        return ("", "BluRay", remux)
    if group in {"web-dl", "web-rip", "hdtv", "dvd"}:
        return ("", group.upper() if group == "web-dl" else group.replace("-", " ").title().replace(" ", "-"), "")
    raw = source_format or video_source or ""
    return ("", raw, "")


def media_context(file, folder=""):
    file = file or {}
    group = str(file.get("release_group") or "").strip()
    if not group:
        group = naming.release_group(file.get("path") or "") or naming.release_group(folder or "")
    audio = file.get("audio_tracks") or []
    main = next((track for track in audio if track.get("default")), audio[0] if audio else {})
    fmt = (file.get("hdr_format") or "").lower()
    if fmt == "dovi":
        second = _HDR.get((file.get("hdr_secondary") or "").lower())
        hdr = f"DV {second}" if second and second != "SDR" else "DV"
    else:
        hdr = _HDR.get(fmt, "SDR" if not fmt else fmt.upper())
    resolution = file.get("resolution") or ""
    quality, source, release_format = release_tokens(file.get("source_format"), file.get("video_source"))
    if not source and not file.get("source_format"):
        source = file.get("video_source") or ""
    return {
        "resolution": _RESOLUTIONS.get(resolution, resolution),
        "quality": quality,
        "source": source,
        "format": release_format,
        "source_format": file.get("source_format") or "",
        "video_codec": file.get("video_codec") or "",
        "hdr": hdr,
        "audio_codec": main.get("codec") or "",
        "audio_channels": main.get("channels") or "",
        "bit_depth": file.get("bit_depth") or "",
        "container": file.get("container") or "",
        "hybrid": "HYBRID" if file.get("is_hybrid") else "",
        "three_d": "3D" if file.get("is_3d") else "",
        "release_group": group,
    }


def _ids(row):
    ids = dict(row.get("ids") or {})
    for key in ("tmdb", "imdb", "tvdb"):
        value = row.get(f"{key}_id")
        if value and not ids.get(key):
            ids[key] = value
    return ids


def movie_context(movie, file=None, part=None, stem=""):
    return {
        "movie": {
            "title": movie.get("title") or "",
            "original_title": movie.get("original_title") or "",
            "sort_title": movie.get("sort_title") or "",
            "year": movie.get("year") or "",
            "edition": movie.get("edition") or "",
            "part": part or "",
            "set": movie.get("set_name") or "",
            "certification": movie.get("mpaa") or "",
            "id": _ids(movie),
            "stem": stem,
        },
        "media": media_context(file, movie.get("folder") or movie.get("path") or ""),
    }


def show_context(show):
    return {
        "show": {
            "title": show.get("title") or "",
            "original_title": show.get("original_title") or "",
            "year": show.get("year") or "",
            "id": _ids(show),
        },
    }


def _episode_span(numbers):
    """Kodi v22 writes a contiguous run as 01-E04. A gap stays E01E03 so the missing number is not implied."""
    numbers = sorted({int(number) for number in numbers})
    if len(numbers) == 1:
        return f"{numbers[0]:02d}"
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"{numbers[0]:02d}-E{numbers[-1]:02d}"
    return "E".join(f"{number:02d}" for number in numbers)


def episode_context(show, episodes, file=None):
    """episodes are the rows that share one file.

    One season renders as S01E01-E04. A file that continues into the next season renders as
    S01E05-E08S02E01-E04. The episode title is left off when the file holds more than one episode.
    """
    episodes = sorted(episodes, key=lambda row: (row["season_number"], row["episode_number"]))
    first = episodes[0]
    groups = []
    for row in episodes:
        if not groups or groups[-1][0] != row["season_number"]:
            groups.append((row["season_number"], []))
        groups[-1][1].append(row["episode_number"])
    number = _episode_span(groups[0][1])
    for season, values in groups[1:]:
        number += f"S{season:02d}E{_episode_span(values)}"
    titles = [row.get("title") for row in episodes if row.get("title")]
    return {
        **show_context(show),
        "episode": {
            "season": f"{first['season_number']:02d}",
            "number": number,
            "season_raw": first["season_number"],
            "number_raw": first["episode_number"],
            "title": titles[0] if len(episodes) == 1 else "",
            "aired": first.get("aired") or "",
        },
        "media": media_context(file),
    }


def examples(templates=None):
    """Rendered sample of each pattern, using one movie and one episode that carry a release group."""
    movie_file = {
        "path": "Avatar fire and ash 2025 4k-FraMeSToR.mkv",
        "resolution": "4K", "source_format": "UHD Remux", "video_source": "UHD Bluray", "video_codec": "HEVC",
        "hdr_format": "dovi", "hdr_secondary": "hdr10plus", "is_hybrid": True,
        "audio_tracks": [{"codec": "TrueHD Atmos", "channels": "7.1", "default": True}],
    }
    movie = movie_context(
        {"title": "Avatar: Fire and Ash", "year": 2025, "folder": "Avatar fire and ash 2025 4k-FraMeSToR"},
        movie_file,
    )
    episode = episode_context(
        {"title": "Severance", "year": 2022, "ids": {"tvdb": "371980"}},
        [{"season_number": 1, "episode_number": 3, "title": "In Perpetuity"}],
        {"path": "Severance.S01E03.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-TRiToN.mkv",
         "resolution": "1080p", "video_source": "Bluray", "source_format": "Remux", "video_codec": "AVC",
         "audio_tracks": [{"codec": "DTS-HD MA", "channels": "5.1", "default": True}]},
    )
    contexts = {
        "movie_folder": movie, "movie_file": movie, "show_folder": show_context({"title": "Severance", "year": 2022, "ids": {"tvdb": "371980"}}),
        "season_folder": episode, "episode_file": episode,
    }
    incoming = templates if isinstance(templates, dict) else {}
    found, errors = {}, {}
    for key, default in DEFAULTS.items():
        template = str(incoming.get(key) or "").strip() or default
        try:
            found[key] = render(template, contexts[key], ".mkv" if key.endswith("_file") else "")
        except (TemplateError, ValueError) as exc:
            found[key] = ""
            errors[key] = str(exc)
    return {"examples": found, "errors": errors}


def part_label(index, count):
    """part1, part2 for stacked movies; empty for a single file."""
    return f"part{index + 1}" if count > 1 else ""
