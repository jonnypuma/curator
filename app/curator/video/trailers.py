"""Download a movie's YouTube trailer with yt-dlp and store it where Kodi or Plex/Jellyfin look for it."""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import tempfile
import threading

from resonance.errors import AppError

from curator.video import delete, naming, renamer, store, writes, ytdlp_update

_YOUTUBE = (
    re.compile(r"[?&](?:video_?id|v)=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube(?:-nocookie)?\.com/(?:embed|shorts|v|live)/([A-Za-z0-9_-]{11})"),
)
_BARE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TIMEOUT = 600
STALE_AFTER_DAYS = 120
_versions = {}


def ytdlp_version(binary):
    """The version yt-dlp reports (a date such as 2025.03.31), or "" when it cannot be asked."""
    if binary not in _versions:
        try:
            result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
            _versions[binary] = (result.stdout or "").strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
        except (OSError, subprocess.TimeoutExpired):
            _versions[binary] = ""
    return _versions[binary]


def version_age_days(version, today=None):
    """Days since the release a yt-dlp version names, or None when it is not a date."""
    match = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})", str(version or ""))
    if not match:
        return None
    try:
        released = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return ((today or datetime.date.today()) - released).days


def ytdlp_failure(title, result, binary):
    """The message for a failed yt-dlp run. YouTube changes often and an old yt-dlp stops working,
    so the message names the version and says when it is old enough to be the likely cause."""
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    reason = lines[-1] if lines else "no output"
    version = ytdlp_version(binary) if binary else ""
    text = f"{title}: yt-dlp {version} failed: {reason}" if version else f"{title}: yt-dlp failed: {reason}"
    age = version_age_days(version)
    if age is not None and age > STALE_AFTER_DAYS:
        text = text.rstrip(".") + f". This yt-dlp is {age // 30} months old and YouTube has probably changed since; press Update yt-dlp in the About window, or rebuild the image"
    return text


def youtube_id(trailer):
    value = str(trailer or "").strip()
    if _BARE.match(value):
        return value
    for pattern in _YOUTUBE:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return None


def _height(resolution):
    return int(str(resolution).rstrip("p")) if str(resolution).rstrip("p").isdigit() else 1080


def format_selector(resolution):
    height = _height(resolution)
    return (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/b[height<={height}][ext=mp4]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b")


def needs_upgrade(current, wanted, available):
    """True when the file is below the chosen quality and YouTube has a taller copy.

    A missing height, or a file that already meets the setting, stays as it is.
    """
    if not current or not wanted or not available:
        return False
    return current < wanted and available > current


def _file_height(path):
    binary = shutil.which("ffprobe")
    if not binary or not path or not os.path.isfile(path):
        return None
    try:
        result = subprocess.run(
            [binary, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height", "-of", "csv=p=0", "--", path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or "").strip().splitlines()
    if not line or not line[0].strip().isdigit():
        return None
    return int(line[0].strip())


def _available_height(binary, video_id):
    try:
        result = subprocess.run(
            [binary, "--no-download", "--no-playlist", "--no-warnings", "--quiet",
             "-f", "bv*", "--print", "%(height)s", f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    heights = [int(line) for line in (result.stdout or "").splitlines() if line.strip().isdigit()]
    return max(heights) if heights else None


def find_trailer(folder, stems, suffix=False):
    """A video in folder whose name is one of stems, or the first video in a Trailers folder.

    suffix also accepts any <filename>-trailer video, which is how Kodi names a trailer next to a file.
    """
    if not folder or not os.path.isdir(folder):
        return None
    wanted = {str(stem).lower() for stem in stems if stem}
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in sorted(names):
        stem = os.path.splitext(name)[0].lower()
        if naming.is_video(name) and (stem in wanted or (suffix and stem.endswith("-trailer"))):
            return os.path.join(folder, name)
    for sub in ("Trailers", "trailers"):
        path = os.path.join(folder, sub)
        if not os.path.isdir(path):
            continue
        videos = sorted(name for name in os.listdir(path) if naming.is_video(name))
        if videos:
            return os.path.join(path, videos[0])
    return None


def local_trailer(row):
    """Path of a trailer already next to the movie, or None."""
    folder = row["folder"]
    main = sorted(row.get("parts") or [row["path"]])[0]
    stem = os.path.splitext(os.path.basename(main))[0]
    stems = [f"{stem}-trailer"]
    if row["path"] == folder:
        stems.append("trailer")
    return find_trailer(folder, stems, suffix=True)


def local_theme(folder):
    """Path of a theme.mp3 / theme.m4a / theme.flac / theme.ogg already in the folder, or None."""
    if not folder or not os.path.isdir(folder):
        return None
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for name in sorted(names):
        if name.lower() in {"theme.mp3", "theme.m4a", "theme.flac", "theme.ogg", "theme.wav"}:
            return os.path.join(folder, name)
    return None


def _note_files(kind, item_id):
    """Tell the library list that this movie or show now has the file, so the Missing filters stay right."""
    from curator.video import local_extras

    local_extras.refresh_item(kind, item_id)


def download_theme(kind, item_id, cfg, log, quiet_skip=False):
    """Download a theme song (theme.mp3) from YouTube using yt-dlp."""
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        folder, root, library_name = row["folder"], row["root"], "movies"
    elif kind == "show":
        row = store.show_row(item_id)
        if not row:
            raise AppError("Show not found", 404)
        title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        folder, root, library_name = row["path"], row["root"], "tv"
    else:
        raise AppError("Theme songs are downloaded for a movie or show", 400)
    if not folder:
        raise AppError(f"{title} has no folder on disk")
    delete._guard(folder, root, library_name)
    existing = local_theme(folder)
    if existing:
        if not quiet_skip:
            log(f"{title}: already has a local theme song ({os.path.basename(existing)})")
        return None
    binary = ytdlp_update.binary()
    if not binary:
        raise AppError("yt-dlp is not installed in the container")
    target = os.path.join(folder, "theme.mp3")
    writes.ensure_dir(folder)
    writes.check(folder)
    work = tempfile.mkdtemp(prefix=".curator-theme-", dir=folder)
    query = f"ytsearch1:{title} theme song soundtrack"
    try:
        command = [
            binary, "--no-playlist", "--no-progress", "--quiet", "--no-warnings",
            "-x", "--audio-format", "mp3", "--audio-quality", "192K",
            "--match-filter", "duration < 420",
            "-o", os.path.join(work, "theme.%(ext)s"),
            query,
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            raise AppError(f"{title}: theme download timed out") from None
        if result.returncode != 0:
            raise AppError(ytdlp_failure(title, result, binary))
        files = [name for name in os.listdir(work) if name.lower().endswith((".mp3", ".m4a", ".ogg", ".opus", ".flac"))]
        if not files:
            raise AppError(f"{title}: yt-dlp did not produce an audio file")
        source = os.path.join(work, files[0])
        ext = os.path.splitext(files[0])[1].lower()
        target = os.path.join(folder, f"theme{ext}")
        os.replace(source, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    log(f"{title}: saved {os.path.basename(target)}")
    _note_files(kind, item_id)
    return target


def show_trailer(show):
    title = show.get("title") or ""
    return find_trailer(show.get("path"), ["tvshow-trailer", "trailer", f"{title}-trailer"], suffix=True)


def season_trailer(show, season):
    folder = season.get("path") or ""
    if not folder or os.path.normpath(folder) == os.path.normpath(show.get("path") or ""):
        folder = show.get("path")
    number = season.get("season_number") or 0
    label = "Specials" if number == 0 else f"Season {int(number):02d}"
    stems = [f"{label}-trailer", f"season{int(number):02d}-trailer"]
    if season.get("path") and os.path.normpath(season["path"]) != os.path.normpath(show.get("path") or ""):
        stems.append("trailer")
    return find_trailer(folder, stems, suffix=True)


def target_path(row, layout):
    main = sorted(row.get("parts") or [row["path"]])[0]
    stem = os.path.splitext(os.path.basename(main))[0]
    if layout == "plex" and row["path"] == row["folder"]:
        title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        return os.path.join(row["folder"], "Trailers", f"{renamer.sanitize(title)}.mp4")
    return os.path.join(row["folder"], f"{stem}-trailer.mp4")


def show_target(show, layout):
    title = f"{show['title']} ({show['year']})" if show.get("year") else show["title"]
    if layout == "plex":
        return os.path.join(show["path"], "Trailers", f"{renamer.sanitize(title)}.mp4")
    return os.path.join(show["path"], "tvshow-trailer.mp4")


def season_target(show, season, layout):
    number = season.get("season_number") or 0
    label = "Specials" if number == 0 else f"Season {int(number):02d}"
    own = season.get("path") and os.path.normpath(season["path"]) != os.path.normpath(show.get("path") or "")
    folder = season["path"] if own else show["path"]
    if layout == "plex":
        return os.path.join(folder, "Trailers", f"{renamer.sanitize(label)}.mp4")
    return os.path.join(folder, f"{label}-trailer.mp4")


def _subject(kind, item_id, layout):
    if kind == "movie":
        row = store.movie_row(item_id)
        if not row:
            raise AppError("Movie not found", 404)
        title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        return {
            "title": title, "folder": row["folder"], "root": row["root"], "library": "movies",
            "remote": row.get("trailer"), "existing": local_trailer(row), "target": target_path(row, layout),
        }
    if kind == "show":
        row = store.show_row(item_id)
        if not row:
            raise AppError("Show not found", 404)
        title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
        return {
            "title": title, "folder": row["path"], "root": row["root"], "library": "tv",
            "remote": row.get("trailer"), "existing": show_trailer(row), "target": show_target(row, layout),
        }
    if kind == "season":
        season = store.season_row(item_id)
        if not season:
            raise AppError("Season not found", 404)
        show = store.show_row(season["show_id"])
        label = "Specials" if season["season_number"] == 0 else f"Season {season['season_number']:02d}"
        return {
            "title": f"{show['title']} {label}", "folder": season.get("path") or show["path"],
            "root": show["root"], "library": "tv", "remote": season.get("trailer"),
            "existing": season_trailer(show, season), "target": season_target(show, season, layout),
        }
    raise AppError("Trailers are downloaded for a movie, show or season", 400)


_busy = threading.Lock()
_inflight = set()


def download(kind, item_id, cfg, log, quiet_skip=False):
    """Fetch one YouTube trailer. Returns the saved path, or None when skipped.

    kind is movie, show or season. A movie call used to pass the id only; that form is still accepted.
    A second call for the same item while the first is still downloading does nothing.
    """
    if not isinstance(kind, str) or kind not in {"movie", "show", "season"}:
        kind, item_id, cfg, log = "movie", kind, item_id, cfg
    key = (kind, str(item_id))
    with _busy:
        if key in _inflight:
            return None
        _inflight.add(key)
    try:
        return _download(kind, item_id, cfg, log, quiet_skip)
    finally:
        with _busy:
            _inflight.discard(key)


def _download(kind, item_id, cfg, log, quiet_skip=False):
    if not isinstance(kind, str) or kind not in {"movie", "show", "season"}:
        kind, item_id, cfg, log = "movie", kind, item_id, cfg
    subject = _subject(kind, item_id, cfg.get("extras_layout", "kodi"))
    title, folder, target = subject["title"], subject["folder"], subject["target"]
    if not folder:
        raise AppError(f"{title} has no folder on disk")
    delete._guard(folder, subject["root"], subject["library"])
    existing = subject["existing"]
    video = youtube_id(subject["remote"])
    replace = False
    current = None
    if existing:
        if not video:
            if not quiet_skip:
                log(f"{title}: already has a local trailer ({os.path.basename(existing)})")
            return None
        current = _file_height(existing)
        wanted = _height(cfg.get("trailer_resolution", "1080p"))
        binary = ytdlp_update.binary()
        available = _available_height(binary, video) if binary and current and current < wanted else None
        replace = needs_upgrade(current, wanted, available)
        if not replace:
            if not quiet_skip:
                if current and current >= wanted:
                    log(f"{title}: trailer is already {current}p")
                elif current and available and available <= current:
                    log(f"{title}: trailer is {current}p and YouTube has nothing taller")
                else:
                    log(f"{title}: already has a local trailer ({os.path.basename(existing)})")
            return None
        if not binary:
            raise AppError("yt-dlp is not installed in the container")
    else:
        if not video:
            if not quiet_skip:
                log(f"{title}: no YouTube trailer is known; scrape it first")
            return None
        binary = ytdlp_update.binary()
    if not binary:
        raise AppError("yt-dlp is not installed in the container")
    writes.ensure_dir(os.path.dirname(target))
    writes.check(os.path.dirname(target))
    work = tempfile.mkdtemp(prefix=".curator-trailer-", dir=folder)
    try:
        command = [binary, "--no-playlist", "--no-progress", "--quiet", "--no-warnings",
                   "-f", format_selector(cfg.get("trailer_resolution", "1080p")),
                   "--merge-output-format", "mp4", "-o", os.path.join(work, "trailer.%(ext)s"),
                   f"https://www.youtube.com/watch?v={video}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise AppError(f"{title}: the trailer download took longer than {TIMEOUT // 60} minutes") from None
        if result.returncode != 0:
            raise AppError(ytdlp_failure(title, result, binary))
        files = [name for name in os.listdir(work) if naming.is_video(name)]
        if not files:
            raise AppError(f"{title}: yt-dlp did not produce a video file")
        source = os.path.join(work, files[0])
        fresh = _file_height(source)
        if replace and fresh and current and fresh <= current:
            if not quiet_skip:
                log(f"{title}: trailer is {current}p and the new copy is no taller")
            return None
        ext = os.path.splitext(files[0])[1].lower()
        target = os.path.splitext(target)[0] + ext
        os.replace(source, target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if replace and existing and os.path.normcase(os.path.abspath(existing)) != os.path.normcase(os.path.abspath(target)):
        try:
            os.remove(existing)
        except OSError:
            pass
    if replace and current:
        log(f"{title}: replaced {current}p trailer with {os.path.relpath(target, folder)}")
    else:
        log(f"{title}: saved {os.path.relpath(target, folder)}")
    _note_files(kind, item_id)
    return target
