"""Movie, show and episode names from folder and file names."""
from __future__ import annotations

import fnmatch
import os
import re
import time

VIDEO_EXTS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".mts", ".mpg", ".mpeg",
    ".webm", ".flv", ".iso", ".vob", ".divx", ".ogm", ".3gp", ".mk3d",
}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".sup", ".vtt", ".smi"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tbn"}
SKIP_DIRS = {
    "@eadir", "#recycle", "#snapshot", ".@__thumb", "lost+found", ".actors", "metadata", ".deletedbytmm",
    "extrafanart", "extrathumbs", "trickplay",
    # Windows / QNAP / macOS system folders
    "$recycle.bin", "system volume information", "@recycle", "@recently-snapshot",
    ".spotlight-v100", ".trashes",
}

# User-defined skip patterns from CMM_SKIP_PATTERNS env var (comma-separated glob patterns).
# Example: CMM_SKIP_PATTERNS=".unwanted,extras.*"
_ENV_SKIP_PATTERNS: list[str] = [
    p.strip() for p in os.environ.get("CMM_SKIP_PATTERNS", "").split(",") if p.strip()
]

# Runtime-loaded patterns from the DB skip_patterns setting; updated by the app at startup/change.
_db_skip_patterns: list[str] = []


def set_skip_patterns(patterns: list[str]) -> None:
    """Update the DB-sourced skip patterns at runtime (called when settings change)."""
    global _db_skip_patterns
    _db_skip_patterns = list(patterns)
EXTRA_DIRS = {
    "extras", "extra", "featurettes", "featurette", "behind the scenes", "deleted scenes", "interviews",
    "scenes", "shorts", "trailers", "trailer", "other", "others", "sample", "samples", "bonus",
}
DISC_DIRS = {"bdmv": "BDMV", "video_ts": "VIDEO_TS"}

_EXTRA_SUFFIX = re.compile(r"-(trailer|behindthescenes|deleted|deletedscene|featurette|interview|scene|short|other|extra)s?$", re.I)
_SAMPLE = re.compile(r"(?:^|[-._ ])sample$", re.I)
_STACK = re.compile(r"^(.*?)[ _.-]*(?:cd|dvd|part|pt|disc|disk)[ _.-]*(\d{1,2})(\D.*)?$", re.I)
_YEAR = re.compile(r"[(\[ ._-]((?:19|20)\d{2})(?=[)\] ._-])")
_ID_TAGS = re.compile(r"[\[{]\s*(imdb|imdbid|tmdb|tmdbid|tvdb|tvdbid)\s*[-=]\s*([a-z0-9]+)\s*[\]}]", re.I)
_EDITION_TAG = re.compile(r"\{\s*edition\s*-\s*([^}]+)\}", re.I)
_JUNK = re.compile(
    r"\b(4320p|2160p|1080p|1080i|720p|576p|480p|8k|4k|uhd|hdr10\+?|hdr|dolby[ .]?vision|dovi|dv|bd[-.\s]?remux|br[-.\s]?remux|remux|"
    r"blu[- ]?ray|bdrip|brrip|web[- .]?dl|webrip|web|hdtv|dvd[-.\s_]?rip|x265|x264|xvid|divx|hevc|avc|h[ .]?26[45]|"
    r"aac|dts(?:-hd)?|truehd|atmos|ddp?5[ .]1|dd\+|eac3|ac3|10bit|8bit|proper|repack|nf|amzn|dsnp|hmax|atvp)\b",
    re.I,
)
_EPISODE_SXE = re.compile(r"(?<![a-z0-9])s(\d{1,4})[ ._-]*e(\d{1,4})", re.I)
_EPISODE_X = re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![0-9])", re.I)
_EPISODE_ONLY = re.compile(r"^(?:e|ep|episode)[ ._-]*(\d{1,4})(?![0-9])", re.I)
_EPISODE_LEADING = re.compile(r"^(\d{1,3})(?:[ ._]+-?[ ._]*|[ ._]*-[ ._]*)(?!\d)")
_MORE_EPISODES = re.compile(r"^(?:[ ._]*(-)[ ._]*e?|[ ._]*e)(\d{1,4})(?![0-9pi])", re.I)
_RANGE_SAME = re.compile(
    r"^[ ._-]*-[ ._-]*(?:s(\d{1,4})[ ._-]*e(\d{1,4})|(\d{1,2})x(\d{2,3}))(?![0-9])",
    re.I,
)
_EP_RANGE = re.compile(
    r"(?<![a-z0-9])(?:ep|episode)[ ._-]*(\d{1,4})[ ._-]*-[ ._-]*(?:ep|episode)[ ._-]*(\d{1,4})(?![0-9])",
    re.I,
)
_E_RUN = re.compile(r"(?<![a-z0-9])e(\d{1,4})((?:[ ._-]+e?\d{1,4})+)(?![0-9a-z])", re.I)
_E_PIECE = re.compile(r"[ ._-]+e?(\d{1,4})", re.I)
_SEASON_BEFORE = re.compile(r"(?<![a-z0-9])s(\d{1,4})[ ._-]*$", re.I)
_SEASON_DIR = re.compile(r"^(?:season|series|staffel|saison|temporada|s)[ ._-]*(\d{1,4})$", re.I)
_SPECIALS_DIR = re.compile(r"^specials?$", re.I)
_RELEASE_GROUP = re.compile(r"(?<=\S)-([A-Za-z][A-Za-z0-9@]{1,40})$")
# A repost keeps the original file name, including its .mkv, then adds another tag and .mkv.
# Thor...-FraMeSToR.mkv-WtF-xpost.mkv → the group is FraMeSToR.
_DOUBLE_MKV = re.compile(r"\.mkv-.+$", re.I)
_STACK_TAIL = re.compile(r"[-._ ]*(?:cd|dvd|part|pt|disc|disk)[-._ ]*\d{1,2}$", re.I)
# Words that trail the real group, as in Name-CiNEPHiLES-xpost. They are not the group.
_GROUP_NOISE = {"xpost", "repost"}
_DEFAULT_NOISE = "xpost, repost"
_noise_cache = {"at": 0.0, "words": None}
# Quality and source words that sit after a hyphen and are not a release group (WEB-DL, x265).
_NOT_A_GROUP = {
    "dl", "rip", "bluray", "blu", "ray", "web", "webdl", "webrip", "hdtv", "dvdrip", "dvd-rip", "bdrip", "brrip",
    "remux", "brremux", "bdremux", "proper", "repack", "internal", "hybrid", "hdr", "hdr10", "dv", "dovi", "sdr", "hlg",
    "x264", "x265", "xvid", "divx", "h264", "h265", "hevc", "avc", "aac", "dts", "truehd", "atmos", "ac3", "eac3",
    "10bit", "8bit", "multi", "subbed", "dubbed", "nf", "amzn", "dsnp", "hmax", "atvp",
    "criterion", "recut", "vinegarsyndrome",
}


def split_noise(text):
    """Words from a comma, semicolon, or line-separated list."""
    words = set()
    for part in re.split(r"[,;\n]+", str(text or "")):
        word = part.strip().lower()
        if word:
            words.add(word)
    return words


def noise_words():
    """Filename words Settings says are not a release group. Defaults to xpost and repost."""
    now = time.monotonic()
    cached = _noise_cache["words"]
    if cached is not None and now - _noise_cache["at"] < 5:
        return cached
    raw = None
    try:
        from resonance.settings import load

        raw = (load().get("video") or {}).get("filename_noise")
    except Exception:
        raw = None
    words = set(_GROUP_NOISE) if raw is None else split_noise(raw)
    _noise_cache["at"] = now
    _noise_cache["words"] = words
    return words


def release_group(name, noise=None):
    """Scene group at the end of a release name, such as -CINEPHILES. Empty when there is none.

    The hyphen has to sit against the previous character, so "Title - Episode Name" is not a group.
    A trailing word from Settings, Files (xpost, repost, and whatever else is listed) is skipped.
    A name that already ends in .mkv, then more text, then another .mkv, keeps the group in front of
    the first .mkv. The .mkv-tag tail is dropped first, for a file or a folder.
    """
    skipped = noise_words() if noise is None else split_noise("\n".join(noise))
    base = os.path.basename(str(name or ""))
    stem, extension = os.path.splitext(base)
    if extension.lower() == ".mkv":
        stem = _DOUBLE_MKV.sub("", stem)
    stem = _STACK_TAIL.sub("", stem).rstrip(" ._-")
    while stem:
        match = _RELEASE_GROUP.search(stem)
        if not match:
            return ""
        group = match.group(1)
        if group.lower() in skipped:
            stem = stem[:match.start()].rstrip(" ._-")
            continue
        if group.lower() in _NOT_A_GROUP:
            return ""
        return group
    return ""


def ext(name):
    return os.path.splitext(name)[1].lower()


def is_video(name):
    base = os.path.basename(str(name or ""))
    if ".split-source-eps-" in base.lower():
        return False
    return ext(name) in VIDEO_EXTS


def is_extra_dir(name, tv=False):
    lowered = name.strip().lower()
    if tv and lowered in {"specials", "special"}:
        return False
    return lowered in EXTRA_DIRS


def skip_dir(name):
    lowered = name.strip().lower()
    if not lowered or lowered.startswith(".") or lowered in SKIP_DIRS or lowered.endswith(".trickplay"):
        return True
    # User-defined glob patterns (env var + DB setting)
    for pattern in _ENV_SKIP_PATTERNS + _db_skip_patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def is_extra_file(name):
    stem = os.path.splitext(name)[0]
    return bool(_EXTRA_SUFFIX.search(stem) or _SAMPLE.search(stem) or stem.lower() == "trailer")


_PART_DIR = re.compile(r"^(?:cd|dvd|part|pt|disc|disk)[ _.-]*(\d{1,2})$", re.I)


def part_dir_number(name):
    """1 for a folder named CD1, Disc 2, or part.3. None for any other folder."""
    match = _PART_DIR.match(str(name or "").strip())
    return int(match.group(1)) if match else None


def part_release_dir(folder, parts=(), root=""):
    """Folder that holds CD1 and CD2. None when the video is not inside a disc folder.

    The release folder is the parent of those disc folders. A disc folder sitting
    directly in the library root has no release folder above it.
    """
    found = []
    base = os.path.basename(os.path.normpath(folder or ""))
    if part_dir_number(base) is not None:
        found.append(os.path.dirname(os.path.normpath(folder)))
    for part in parts or []:
        parent = os.path.basename(os.path.dirname(part))
        if part_dir_number(parent) is None:
            continue
        found.append(os.path.dirname(os.path.dirname(os.path.normpath(part))))
    found = [item for item in found if item]
    if not found or len(set(found)) != 1:
        return None
    release = found[0]
    if root and os.path.normpath(release) == os.path.normpath(root):
        return None
    return release


def disc_file(name):
    """True when the file name is one disc of a set, such as Movie-cd1 or Movie.disc2."""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    return bool(re.search(r"(?:^|[ _.-])(?:cd|dvd|disc|disk)[ _.-]*\d{1,2}(?:\D|$)", stem, re.I))


def release_nfo_dir(folder, parts=(), root=""):
    """Folder whose name is the .nfo for a two-disc release. None for any other movie.

    Disc folders (CD1, CD2) use their parent. Disc files sitting in the movie folder
    (Movie-cd1.avi and Movie-cd2.avi, no subfolders) use that movie folder. A disc
    file loose in the library root does not.
    """
    nested = part_release_dir(folder, parts, root)
    if nested:
        return nested
    folder = os.path.normpath(folder or "")
    if not folder or (root and os.path.normpath(root) == folder):
        return None
    files = [os.path.normpath(part) for part in (parts or [])]
    if len(files) < 2 or any(os.path.dirname(part) != folder for part in files):
        return None
    if not all(disc_file(part) for part in files):
        return None
    keys = []
    for part in files:
        stacked = stack_key(os.path.basename(part))
        if not stacked:
            return None
        keys.append(stacked[0])
    if len(set(keys)) != 1:
        return None
    return folder


def stack_key(name):
    """Return (key, part) when a file name looks like one part of a multi-part movie."""
    stem = os.path.splitext(name)[0]
    match = _STACK.match(stem)
    if not match:
        return None
    head = (match.group(1) or "").strip(" ._-")
    tail = (match.group(3) or "").strip(" ._-")
    return f"{head}|{tail}".lower(), int(match.group(2))


def stack_head(name):
    """Shared movie name without the part token, keeping the file's own spelling."""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    match = _STACK.match(stem)
    if not match:
        return ""
    return (match.group(1) or "").strip(" ._-")


def movie_art_stem(parts):
    """File stem used for movie artwork. A stack uses the shared name, not part1."""
    if not parts:
        return ""
    if len(parts) > 1:
        head = stack_head(parts[0])
        if head:
            return head
    return os.path.splitext(os.path.basename(parts[0]))[0]


def group_stacks(names):
    """Group video file names into movies. Parts of one movie (cd1, cd2) become one group."""
    keyed = {}
    singles = []
    for name in sorted(names, key=str.lower):
        stacked = stack_key(name)
        if stacked:
            keyed.setdefault(stacked[0], []).append((stacked[1], name))
        else:
            singles.append([name])
    groups = singles[:]
    for parts in keyed.values():
        if len(parts) > 1:
            groups.append([name for _, name in sorted(parts)])
        else:
            groups.append([parts[0][1]])
    groups.sort(key=lambda group: group[0].lower())
    return groups


def _spaced(text):
    if " " not in text.strip():
        text = text.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip(" -._")


def _ids(text):
    found = {}
    for kind, value in _ID_TAGS.findall(text):
        key = kind.lower().replace("id", "")
        found[key] = value
    return found, _ID_TAGS.sub(" ", text)


def parse_title(name, strip_ext=False):
    """Title, year, edition and ids from "Title (Year) {edition-X} [imdbid-tt1]" style names."""
    base = os.path.splitext(name)[0] if strip_ext else name
    ids, text = _ids(base)
    edition = None
    match = _EDITION_TAG.search(text)
    if match:
        from curator.video.sources import canonical_edition

        edition = canonical_edition(match.group(1).strip())
        text = _EDITION_TAG.sub(" ", text)
    year = None
    title = text
    padded = f" {text} "
    for chosen in reversed(list(_YEAR.finditer(padded))):
        before = padded[: chosen.start()]
        if before.strip(" ._-(["):
            title = before
            year = int(chosen.group(1))
            break
    if year is None:
        junk = _JUNK.search(_spaced(text))
        title = _spaced(text)[: junk.start()] if junk and junk.start() > 0 else text
    title = re.sub(r"[\[{(][^\]})]*[\]})]", " ", _spaced(title))
    title = _spaced(title)
    return {"title": title or _spaced(base), "year": year, "edition": edition, "ids": ids}


def season_from_dir(name):
    if _SPECIALS_DIR.match(name.strip()):
        return 0
    match = _SEASON_DIR.match(name.strip())
    return int(match.group(1)) if match else None


def _filled(start, end):
    """Every episode from start through end. A gap wider than 50 is left alone."""
    if end < start or end - start > 50:
        return None
    return list(range(start, end + 1))


def _more_episodes(rest, first):
    numbers = [first]
    while True:
        match = _MORE_EPISODES.match(rest)
        if not match:
            break
        value = int(match.group(2))
        if value <= numbers[-1] or value - numbers[-1] > 50:
            break
        if match.group(1) and value - numbers[-1] > 1:
            numbers.extend(range(numbers[-1] + 1, value + 1))
        else:
            numbers.append(value)
        rest = rest[match.end():]
    return numbers, rest


def _episode_title(rest):
    text = _spaced(re.sub(r"[\[{(][^\]})]*[\]})]", " ", rest))
    junk = _JUNK.search(text)
    if junk:
        text = text[: junk.start()]
    text = text.strip(" -._")
    return text or None


def episode_mark(season, episode):
    """Kodi v22 suffix for one episode inside a multi-episode file: S01E02."""
    return f"S{int(season):02d}E{int(episode):02d}"


def span_text(name):
    """The episode span as it is written in the file name, such as S01E81-82 or S01E01-E04."""
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    match = _EPISODE_SXE.search(stem) or _EPISODE_X.search(stem)
    if match:
        rest = stem[match.end():]
        season = int(match.group(1))
        first = int(match.group(2))
        while True:
            _episodes, rest = _consume_block(rest, season, first)
            trimmed = rest.lstrip(" ._-")
            nxt = _EPISODE_SXE.match(trimmed) or _EPISODE_X.match(trimmed)
            if not nxt:
                break
            rest = trimmed[nxt.end():]
            season = int(nxt.group(1))
            first = int(nxt.group(2))
        return stem[match.start():len(stem) - len(rest)]
    run = _E_RUN.search(stem)
    if not run:
        return None
    start = run.start()
    season_match = _SEASON_BEFORE.search(stem[:start])
    if season_match:
        start = season_match.start()
    return stem[start:run.end()]


def episode_pairs(parsed):
    """(season, episode) for every episode in the file, including a second season."""
    if not parsed:
        return []
    parts = parsed.get("parts")
    if not parts:
        return [(parsed["season"], number) for number in parsed.get("episodes") or []]
    return [(int(part["season"]), int(number)) for part in parts for number in part.get("episodes") or []]


def _pack(parts, title):
    return {
        "season": parts[0]["season"],
        "episodes": parts[0]["episodes"],
        "parts": parts,
        "title": title,
    }


def _consume_block(rest, season, first):
    """Episodes that follow one season token, including s01e01-e04 and s01e01-s01e04."""
    episodes, rest = _more_episodes(rest, first)
    match = _RANGE_SAME.match(rest)
    if not match:
        return episodes, rest
    end_season = int(match.group(1) or match.group(3))
    end_episode = int(match.group(2) or match.group(4))
    if end_season != season:
        return episodes, rest
    filled = _filled(episodes[0], end_episode)
    if not filled:
        return episodes, rest
    rest = rest[match.end():]
    extra, rest = _more_episodes(rest, filled[-1])
    if extra and extra[0] == filled[-1]:
        filled.extend(extra[1:])
    return filled, rest


def _season_blocks(stem):
    """One or more season ranges. S01E05-E08S02E01-E04 is two ranges."""
    match = _EPISODE_SXE.search(stem) or _EPISODE_X.search(stem)
    if not match:
        return None
    rest = stem[match.end():]
    season = int(match.group(1))
    first = int(match.group(2))
    parts = []
    while True:
        episodes, rest = _consume_block(rest, season, first)
        parts.append({"season": season, "episodes": episodes})
        trimmed = rest.lstrip(" ._-")
        nxt = _EPISODE_SXE.match(trimmed) or _EPISODE_X.match(trimmed)
        if not nxt:
            return parts, _episode_title(rest)
        season = int(nxt.group(1))
        first = int(nxt.group(2))
        rest = trimmed[nxt.end():]


def _e_run(stem, folder_season):
    """E01-02-03 is those episodes. E01-04 is episode 1 through 4.

    A season token just before the E is used. Otherwise the season folder is used, or season 1.
    """
    match = _E_RUN.search(stem)
    if not match:
        return None
    numbers = [int(match.group(1))]
    for piece in _E_PIECE.finditer(match.group(2)):
        value = int(piece.group(1))
        if value <= numbers[-1] or value - numbers[-1] > 50:
            return None
        numbers.append(value)
    if len(numbers) == 2 and numbers[1] - numbers[0] > 1:
        numbers = _filled(numbers[0], numbers[1])
        if not numbers:
            return None
    season_match = _SEASON_BEFORE.search(stem[: match.start()])
    if season_match:
        season = int(season_match.group(1))
    elif folder_season is not None:
        season = folder_season
    else:
        season = 1
    return _pack([{"season": season, "episodes": numbers}], _episode_title(stem[match.end():]))


def parse_episode(name, folder_season=None):
    """Season, episode numbers and a title guess from an episode file name.

    Kodi v22 ranges include every episode in between: S01E01-E04, S01E01-S01E04,
    1x01-1x04, and ep01-ep04 (season 1). S01E05-E08S02E01-E04 is two seasons.
    Also S01E02, S01E02E03, E01-02-03, E01-04, and E02 or "02 - Title" inside a season folder.
    Returns None when the name has no episode number.
    """
    stem = os.path.splitext(name)[0]
    found = _season_blocks(stem)
    if found:
        parts, title = found
        return _pack(parts, title)
    ranged = _EP_RANGE.search(stem)
    if ranged:
        filled = _filled(int(ranged.group(1)), int(ranged.group(2)))
        if filled:
            return _pack([{"season": 1, "episodes": filled}], _episode_title(stem[ranged.end():]))
    listed = _e_run(stem, folder_season)
    if listed:
        return listed
    if folder_season is None:
        return None
    cleaned = _spaced(stem)
    match = _EPISODE_ONLY.match(cleaned) or _EPISODE_LEADING.match(cleaned)
    if not match:
        return None
    episodes, rest = _more_episodes(cleaned[match.end():], int(match.group(1)))
    return _pack([{"season": folder_season, "episodes": episodes}], _episode_title(rest))


def subtitle_info(video_name, subtitle_name):
    """Language and flags from "Movie.en.forced.srt" next to "Movie.mkv". None when it belongs elsewhere."""
    from curator.video.languages import classify_sub_flags, normalize_lang

    video_stem = os.path.splitext(video_name)[0].lower()
    stem, extension = os.path.splitext(subtitle_name)
    lowered = stem.lower()
    if lowered != video_stem and not lowered.startswith(video_stem + "."):
        return None
    tokens = [token for token in stem[len(video_stem):].split(".") if token]
    lang = ""
    for token in tokens:
        code = normalize_lang(token)
        if code and len(code) == 3 and token.lower() not in {"sdh", "cc", "hi", "forced"}:
            lang = code
            break
    flags = classify_sub_flags(title=" ".join(tokens), language_raw="")
    return {"file": subtitle_name, "lang": lang, "format": extension.lstrip(".").lower(), "flags": flags}
