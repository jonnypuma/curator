import logging
import os
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

_SKIP_FS = {
    "proc",
    "sysfs",
    "cgroup",
    "cgroup2",
    "devtmpfs",
    "devpts",
    "tmpfs",
    "squashfs",
    "mqueue",
    "securityfs",
    "pstore",
    "bpf",
    "tracefs",
    "debugfs",
    "configfs",
    "fusectl",
    "ramfs",
    "nsfs",
    "autofs",
    "binfmt_misc",
    "rpc_pipefs",
    "nfsd",
}
_BLOCKED_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/app",
    "/usr",
    "/lib",
    "/bin",
    "/sbin",
    "/etc",
    "/var",
    "/tmp",
    "/root",
    "/opt",
    "/config",
    "/cache",
)


def music_dir():
    return default_music_dir()


def default_music_dir():
    return os.path.realpath(os.environ.get("MUSIC_DIR", "/music"))


def config_dir():
    return os.path.realpath(os.environ.get("CONFIG_DIR", "/config"))


def cache_dir():
    """Files the app can rebuild: thumbnails, downloaded artwork candidates, video previews. Safe to delete."""
    return os.path.realpath(os.environ.get("CACHE_DIR", "/cache"))


def artwork_cache_dir():
    """Music artwork downloaded from a web address. It is fetched again when missing."""
    return os.path.join(cache_dir(), "music")


def previous_artwork_cache_dir():
    """Where the downloaded music artwork was in v1.3.5, before the cache folder was split by media type."""
    return os.path.join(cache_dir(), "artwork")


def data_dir():
    """Files the app cannot fetch or rebuild but that are not settings: uploaded and replaced artwork."""
    return os.path.realpath(os.environ.get("DATA_DIR", "/data"))


def custom_brands_dir():
    """Logos you added in Settings → Files, next to the ones shipped with the app. One sub-folder per logo set."""
    return os.path.join(data_dir(), "brands")


def additional_artwork_dir():
    """Artwork the app cannot fetch again: uploaded files and copies kept when a file is replaced."""
    return os.path.join(data_dir(), "artwork", "additional")


def additional_media_dir(media):
    """The folder inside additional_artwork_dir for one media type: music, movie, tv or sets."""
    return os.path.join(additional_artwork_dir(), media)


def previous_additional_artwork_dir():
    """Where that artwork was before the data folder existed (v1.3.7 to v1.4.2)."""
    return os.path.join(config_dir(), "artwork", "additional")


def undo_dir():
    """Files kept so a change can be undone. Today that is the previous artwork file; it is not artwork storage."""
    return os.path.join(config_dir(), "undo")


def legacy_artwork_cache_dir():
    """Where all of the above lived before the cache folder existed."""
    return os.path.join(config_dir(), "artwork", "cache")


def inside(root, path):
    if not path:
        return False
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    try:
        return os.path.commonpath([root_real, path_real]) == root_real
    except ValueError:
        return False


def path_kind(path):
    """artists: each child folder is an artist. artist: this folder is one artist."""
    from resonance.settings import load

    kinds = load().get("music_path_kinds") or {}
    real = os.path.realpath(path) if path and os.path.exists(path) else os.path.normpath(path or "")
    for root, kind in kinds.items():
        root_real = os.path.realpath(root) if root and os.path.exists(root) else os.path.normpath(root or "")
        if root_real == real:
            return "artist" if kind == "artist" else "artists"
    return "artists"


def path_role(path):
    """Every music folder is part of the library."""
    return "library"


def join_under(root, relative):
    from resonance.errors import AppError

    root_real = os.path.realpath(root)
    rel = str(relative or "").replace("\\", "/").strip("/")
    parts = [part for part in rel.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise AppError("That folder is outside the mount", 400)
    target = os.path.realpath(os.path.join(root_real, *parts)) if parts else root_real
    if target != root_real and not inside(root_real, target):
        raise AppError("That folder is outside the mount", 400)
    return target, "/".join(parts)


def choose_roots(requested, configured):
    from resonance.errors import AppError

    known = []
    for item in configured or []:
        if not item:
            continue
        real = os.path.realpath(item) if os.path.exists(item) else os.path.normpath(item)
        if real not in known:
            known.append(real)
    if not requested:
        return known
    chosen = []
    for item in requested:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip()
        real = os.path.realpath(raw) if os.path.exists(raw) else os.path.normpath(raw)
        if real not in known:
            raise AppError(f"{raw} is not a configured music path", 400)
        if real not in chosen:
            chosen.append(real)
    if not chosen:
        raise AppError("Choose a music path to scan", 400)
    return chosen


def browse_directory(root, relative=""):
    from resonance.errors import AppError

    if not root or not isinstance(root, str):
        raise AppError("Choose a mounted volume", 400)
    mounts = {os.path.realpath(item["path"]) for item in discover_mounts()}
    root_real = os.path.realpath(root) if os.path.exists(root) else os.path.normpath(root)
    if root_real not in mounts and not any(inside(mount, root_real) for mount in mounts):
        raise AppError("That folder is not on a mounted volume", 400)
    target, rel = join_under(root_real, relative)
    if not os.path.isdir(target):
        raise AppError("That folder is not available", 404)
    names = []
    try:
        entries = os.listdir(target)
    except OSError as exc:
        raise AppError(f"Cannot read that folder: {exc}", 400) from exc
    for name in sorted(entries, key=str.lower):
        if name.startswith(".") or name.lower() in {"lost+found", "@eadir"}:
            continue
        if os.path.isdir(os.path.join(target, name)):
            names.append(name)
    return {"root": root_real, "path": rel, "current": target, "dirs": names}


def music_roots():
    from resonance.settings import load

    roots = []
    for item in load().get("music_paths") or []:
        if item and os.path.isdir(item):
            real = os.path.realpath(item)
            if real not in roots:
                roots.append(real)
    if not roots and os.path.isdir(default_music_dir()):
        roots.append(default_music_dir())
    return roots


LIBRARY_PATH_KEYS = {"music": "music_paths", "movies": "movie_paths", "tv": "tv_paths"}


def configured_library_paths(kind, cfg=None):
    """Every path in Settings for one library kind, offline, excluded and empty ones included."""
    from resonance.settings import load

    data = cfg if isinstance(cfg, dict) else load()
    return _configured_paths(data, LIBRARY_PATH_KEYS[kind])


def readable_dir(path):
    """True when the path is a directory this container can actually list.

    os.path.isdir alone is not enough: an NFS or CIFS mount that has gone away can still
    answer isdir while every read fails, so the contents are probed as well.
    """
    try:
        if not path or not os.path.isdir(path):
            return False
        with os.scandir(path) as entries:
            next(iter(entries), None)
        return True
    except OSError:
        return False


def _configured_paths(data, key):
    out = []
    for item in data.get(key) or []:
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def offline_library_paths(cfg=None):
    """Configured library paths that are not a directory right now: the mount is away.

    A configured path whose mount is away must never be mistaken for a path the user
    removed. A scan leaves its indexed items alone; taking the path out in Settings and
    scanning again is what removes them from the database.
    """
    from resonance.settings import load

    data = cfg if isinstance(cfg, dict) else load()
    return {
        kind: [path for path in _configured_paths(data, key) if not os.path.isdir(path)]
        for kind, key in LIBRARY_PATH_KEYS.items()
    }


def unreadable_library_paths(cfg=None):
    """Configured library paths that are a directory but cannot be listed.

    A permission problem, or a mount that is still attached while every read fails. It is
    worth telling apart from an away mount, because the fix is different, but it is treated
    exactly as carefully: the scan will not prune anything under it.
    """
    from resonance.settings import load

    data = cfg if isinstance(cfg, dict) else load()
    found = {}
    for kind, key in LIBRARY_PATH_KEYS.items():
        bad = []
        for path in _configured_paths(data, key):
            if os.path.isdir(path) and not readable_dir(path):
                bad.append(path)
        found[kind] = bad
    return found


def unscannable_library_paths(kind, cfg=None):
    """Both of the above for one library kind: every path a scan must not prune under."""
    offline = offline_library_paths(cfg).get(kind) or []
    unreadable = unreadable_library_paths(cfg).get(kind) or []
    return offline + [path for path in unreadable if path not in offline]


def mount_for(path):
    """The longest detected mount that contains this path, or "" when none does.

    A mount can hold several library paths, of different media types, so a mount coming back
    half-populated has to be judged across all of them at once rather than one path at a time.
    """
    real = os.path.realpath(str(path or ""))
    best = ""
    for mount in _cached_mounts():
        base = str((mount or {}).get("path") or "").rstrip("/")
        if not base:
            continue
        if (real == base or real.startswith(base + "/")) and len(base) > len(best):
            best = base
    return best


def empty_library_paths(cfg=None):
    """Configured library paths that are readable but hold nothing, keyed by library kind.

    This is what a mount that remounted empty looks like, and it is also what a folder the
    user emptied looks like. Either way a scan will not prune it, so the user is told: if the
    folder really is finished with, the path should come out of Settings.
    """
    from resonance.settings import load

    data = cfg if isinstance(cfg, dict) else load()
    found = {}
    for kind, key in LIBRARY_PATH_KEYS.items():
        blank = []
        for item in data.get(key) or []:
            if not isinstance(item, str) or not item.strip():
                continue
            path = item.strip()
            if not readable_dir(path):
                continue
            try:
                with os.scandir(path) as entries:
                    if next(iter(entries), None) is None and path not in blank:
                        blank.append(path)
            except OSError:
                continue
        found[kind] = blank
    return found


def protected_prefixes(paths):
    """Both spellings of each path, so a prune cannot reach under it."""
    out = []
    for item in paths or []:
        for candidate in (str(item or ""), os.path.realpath(str(item or ""))):
            cleaned = candidate.rstrip("/")
            if cleaned and cleaned not in out:
                out.append(cleaned)
    return out


def discover_mounts():
    found = []
    seen = set()
    mounts_file = "/proc/mounts"
    if os.path.isfile(mounts_file):
        try:
            with open(mounts_file, encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except OSError:
            lines = []
        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            target = _unescape_mount(parts[1])
            fstype = parts[2]
            options = parts[3].split(",")
            if fstype in _SKIP_FS or target == "/" or _blocked(target):
                continue
            real = os.path.realpath(target)
            if not os.path.isdir(real) or real in seen or _blocked(real):
                continue
            seen.add(real)
            found.append(
                {
                    "path": real,
                    "fstype": fstype,
                    "writable": "rw" in options,
                }
            )
    default = default_music_dir()
    if os.path.isdir(default) and default not in seen and not _blocked(default):
        found.append(
            {
                "path": default,
                "fstype": "bind",
                "writable": os.access(default, os.W_OK),
            }
        )
    found.sort(key=lambda item: item["path"].lower())
    return found


_alias_cache = {}
_alias_guard = threading.Lock()
_display_cache = {"at": 0.0, "mounts": None, "roots": None}


def _cached_mounts():
    now = time.monotonic()
    if _display_cache["mounts"] is not None and now - _display_cache["at"] < 15:
        return _display_cache["mounts"]
    mounts = discover_mounts()
    _display_cache["mounts"] = mounts
    _display_cache["at"] = now
    _display_cache["roots"] = None
    return mounts


def display_path(path):
    """The path as it sits on the longest mounted volume that contains the same file.

    A library folder mounted at /movies and again under /EC2480/Media/Movies is shown
    as /EC2480/Media/Movies/... when both refer to the same directory.
    """
    if not path or not isinstance(path, str):
        return path or ""
    try:
        if not os.path.exists(path):
            return path
        real = os.path.realpath(path)
        stat = os.stat(real)
    except OSError:
        return path
    root = _library_root(real)
    if not root:
        return real
    relative = real[len(root):].lstrip("/")
    best = real
    for mount in _cached_mounts():
        mount_path = str(mount.get("path") or "").rstrip("/")
        if not mount_path or mount_path == root:
            continue
        if real == mount_path or real.startswith(mount_path + "/"):
            if len(real) > len(best):
                best = real
            continue
        alias = _alias_dir(mount_path, root)
        if not alias:
            continue
        candidate = os.path.join(alias, relative) if relative else alias
        try:
            other = os.stat(candidate)
        except OSError:
            continue
        same_inode = other.st_ino == stat.st_ino and other.st_dev == stat.st_dev
        same_bytes = other.st_size == stat.st_size and abs(other.st_mtime - stat.st_mtime) < 2
        if (same_inode or same_bytes) and len(candidate) > len(best):
            best = candidate
    return best


_prefix_shown = {}
_PREFIX_SECONDS = 600


def display_path_fast(path):
    """display_path for lists: the same answer for files below a library folder, but the disk is
    consulted once per library folder instead of several times per file.

    A list of thousands of movies called display_path for every path, folder and .nfo, each one
    checking the file, resolving links and comparing it with every other mount; on a network share
    that took over a minute. Here the library folder is resolved once (and remembered for ten
    minutes) and the rest of the path is appended. A path outside any library folder takes the
    full route. Links inside a library folder are not followed.
    """
    if not path or not isinstance(path, str):
        return path or ""
    root = _library_root(path)
    if not root:
        return display_path(path)
    now = time.monotonic()
    held = _prefix_shown.get(root)
    if held is None or now - held[1] > _PREFIX_SECONDS:
        held = (display_path(root) or root, now)
        _prefix_shown[root] = held
    return held[0].rstrip("/") + path[len(root):]


def _library_root(path):
    now = time.monotonic()
    roots = _display_cache["roots"]
    if roots is None or now - _display_cache["at"] >= 15:
        roots = []
        try:
            from resonance.settings import load

            cfg = load()
            for key in ("music_paths", "movie_paths", "tv_paths"):
                roots.extend(cfg.get(key) or [])
        except Exception:
            logger.debug("library roots unavailable for path display", exc_info=True)
        for mount in _cached_mounts():
            roots.append(mount.get("path") or "")
        _display_cache["roots"] = roots
    best = ""
    for root in roots:
        base = str(root or "").rstrip("/")
        if base and (path == base or path.startswith(base + "/")) and len(base) > len(best):
            best = base
    return best


def _alias_dir(mount_path, root):
    key = (mount_path, root)
    with _alias_guard:
        if key in _alias_cache:
            return _alias_cache[key]
    found = ""
    try:
        root_stat = os.stat(root)
    except OSError:
        with _alias_guard:
            _alias_cache[key] = ""
        return ""
    base = os.path.basename(root).lower()
    found = ""
    named = ""
    try:
        with os.scandir(mount_path) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                    st = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
                if st.st_dev == root_stat.st_dev and st.st_ino == root_stat.st_ino:
                    found = entry.path
                    break
                if entry.name.lower() == base:
                    named = entry.path
    except OSError:
        found = ""
    found = found or named
    with _alias_guard:
        _alias_cache[key] = found
    return found


def assert_library_path(path, label="music"):
    from resonance.errors import AppError

    if not path or not os.path.isabs(path):
        raise AppError(f"{label.capitalize()} paths must be absolute container paths")
    real = os.path.realpath(path)
    if _blocked(real) or real == os.path.realpath("/"):
        raise AppError(f"{path} is not a {label} library mount")
    if not os.path.isdir(real):
        raise AppError(
            f"{path} is not mounted in this container. Add the volume in docker-compose, recreate the container, then add the path."
        )
    mounts = discover_mounts()
    if not mounts:
        return real
    for mount in mounts:
        if inside(mount["path"], real):
            return real
    raise AppError(f"{path} is not on a mounted volume. Mount it in docker-compose first.")


def _blocked(path):
    real = os.path.realpath(path) if path and os.path.exists(path) else os.path.normpath(path or "")
    if real in {"/", "/app", "/config", "/cache"}:
        return True
    for prefix in _BLOCKED_PREFIXES:
        if real == prefix or real.startswith(prefix + os.sep):
            return True
    try:
        if os.path.realpath(real) == config_dir() or inside(config_dir(), real):
            return True
    except Exception:
        pass
    return False


def _unescape_mount(value):
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def allowed(path):
    if inside(config_dir(), path):
        return True
    if inside(cache_dir(), path):
        return True
    if inside(data_dir(), path):
        return True
    for root in music_roots():
        if inside(root, path):
            return True
    return inside(default_music_dir(), path)


def mount_writable(path):
    real = os.path.realpath(path) if path and os.path.exists(path) else os.path.abspath(path or "")
    matches = []
    for mount in discover_mounts():
        mount_path = mount.get("path") or ""
        if mount_path and (os.path.realpath(mount_path) == real or inside(mount_path, real)):
            matches.append(mount)
    if matches:
        mount = max(matches, key=lambda item: len(item.get("path") or ""))
        if not mount.get("writable", True):
            return False
    parent = real if os.path.isdir(real) else os.path.dirname(real)
    return os.access(parent, os.W_OK) if parent else False


def assert_library_writable(path):
    from resonance.errors import AppError

    if not path or not mount_writable(path):
        raise AppError("This music folder is mounted read-only", 403)


def assert_readable(path):
    from resonance.errors import AppError

    if not path or not os.path.isfile(path) or not allowed(path):
        raise AppError("File is not available", 404)
    return os.path.realpath(path)


def assert_writable_target(path):
    from resonance.errors import AppError

    parent = os.path.realpath(os.path.dirname(path))
    if not allowed(parent) and not allowed(path):
        raise AppError("Refusing to write outside the music library or config directory", 403)
    os.makedirs(parent, exist_ok=True)
    return os.path.join(parent, os.path.basename(path))


def atomic_write(path, data, binary=False):
    path = assert_writable_target(path)
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".resonance-", suffix=".tmp")
    try:
        if binary:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        else:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def like_prefix(root):
    cleaned = (root or "").rstrip("/\\")
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    sep = "\\\\" if ("\\" in (root or "") and "/" not in (root or "")) else "/"
    return escaped + sep + "%"
