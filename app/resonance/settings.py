import json
import logging
import os
import secrets
import threading
from pathlib import Path

from resonance.errors import AppError
from resonance.paths import artwork_cache_dir, atomic_write, config_dir, additional_artwork_dir, undo_dir

logger = logging.getLogger(__name__)
_lock = threading.Lock()

APP_ROOT = Path(__file__).resolve().parent.parent

KNOWN_SOURCES = ["fanart.tv", "caa", "lastfm", "deezer", "theaudiodb"]
METADATA_FIELDS = {
    "biography": ["allmusic", "theaudiodb", "lastfm", "wikipedia"],
    "review": ["allmusic", "theaudiodb", "lastfm", "wikipedia"],
    "descriptors": ["allmusic", "theaudiodb", "lastfm"],
}
ENV_KEYS = {
    "lastfm_key": ("LASTFM_API_KEY", "LASTFM_KEY"),
    "lastfm_secret": ("LASTFM_API_SECRET", "LASTFM_SHARED_SECRET"),
    "fanart_key": ("FANART_API_KEY", "FANART_KEY"),
    "acoustid_key": ("ACOUSTID_API_KEY", "ACOUSTID_KEY"),
    "lidarr_api_key": ("LIDARR_API_KEY",),
    "radarr_api_key": ("RADARR_API_KEY",),
    "sonarr_api_key": ("SONARR_API_KEY",),
    "bazarr_api_key": ("BAZARR_API_KEY",),
    "tmdb_key": ("TMDB_API_KEY", "TMDB_KEY"),
    "tvdb_key": ("TVDB_API_KEY", "TVDB_KEY"),
    "omdb_key": ("OMDB_API_KEY", "OMDB_KEY"),
    "crawlbase_token": ("CRAWLBASE_TOKEN", "CRAWLBASE_JS_TOKEN"),
    "opensubtitles_key": ("OPENSUBTITLES_API_KEY",),
    "opensubtitles_password": ("OPENSUBTITLES_PASSWORD",),
    "kodi_password": ("KODI_PASSWORD",),
    "kodi_library_password": ("KODI_LIBRARY_PASSWORD",),
    "jellyfin_token": ("JELLYFIN_API_KEY", "JELLYFIN_TOKEN"),
    "plex_token": ("PLEX_TOKEN",),
    "emby_token": ("EMBY_API_KEY", "EMBY_TOKEN"),
    "webhook_emby_key": ("WEBHOOK_EMBY_API_KEY",),
    "webhook_jellyfin_key": ("WEBHOOK_JELLYFIN_API_KEY",),
    "webhook_navidrome_key": ("WEBHOOK_NAVIDROME_PASSWORD", "WEBHOOK_NAVIDROME_API_KEY"),
    "webhook_plex_key": ("WEBHOOK_PLEX_TOKEN",),
}
# Kodi 22 music types, plus Cover Art Archive pieces that do not have a Kodi slot.
# clearlogo is Kodi's logo (the old "logo" type is retired). fanart is the full-screen
# artist image. discart is the disc image, written as discart.png.
# A multi-disc album also gets discart1.png, discart2.png, and discart.png inside each CD folder.
ASSET_KEYS = [
    "front",
    "back",
    "discart",
    "spine",
    "artistthumb",
    "fanart",
    "banner",
    "clearlogo",
    "clearart",
    "landscape",
    "extrafanart",
    "booklet",
    "tray",
    "obi",
    "liner",
    "sticker",
    "poster",
    "matrix",
    "top",
    "bottom",
]
LEGACY_ASSETS = {
    "cdart": "discart",
    "logos": "clearlogo",
    "backdrop": "fanart",
    "sleeve": "tray",
}

DEFAULTS = {
    "nfo_profile": "kodi",
    "nfo_dialect": "kodi",
    "nfo_backup": True,
    "min_resolution": 1000,
    "fanart_count": 5,
    "source_priority": ["fanart.tv", "caa", "lastfm", "deezer", "theaudiodb"],
    "sources_enabled": {key: True for key in KNOWN_SOURCES},
    "music_paths": [],
    "music_path_roles": {},
    "music_path_kinds": {},
    "assets": {
        "front": True,
        "back": True,
        "discart": True,
        "spine": False,
        "artistthumb": True,
        "fanart": False,
        "banner": False,
        "clearlogo": False,
        "clearart": False,
        "landscape": False,
        "extrafanart": False,
        "booklet": False,
        "tray": False,
        "obi": False,
        "liner": False,
        "sticker": False,
        "poster": False,
        "matrix": False,
        "top": False,
        "bottom": False,
    },
    "lastfm_key": "",
    "lastfm_secret": "",
    "fanart_key": "",
    "acoustid_key": "",
    "tmdb_key": "",
    "tvdb_key": "",
    "omdb_key": "",
    "crawlbase_token": "",
    "opensubtitles_key": "",
    "opensubtitles_password": "",
    "kodi_password": "",
    "kodi_library_password": "",
    "jellyfin_token": "",
    "plex_token": "",
    "emby_token": "",
    "lyrics_mode": "lrc",
    "musicbrainz_contact": "resonance@localhost",
    "rename_enabled": False,
    "rename_scope": "none",
    "rename_folder_pattern": "%albumartist%/[%year%] %album%$if(%multidisc%,/CD%discnumber%)",
    "rename_file_pattern": "Disc %discnumber% - $num(%tracknumber%,2) - %title%",
    "rename_clean_chars": True,
    "rename_move_sidecars": True,
    "rename_prune_empty": False,
    "rename_straight_quotes": False,
    "rename_strip_junk": False,
    "rename_transliterate": False,
    "title_suffix_types": {
        "album": False,
        "single": True,
        "ep": True,
        "live": True,
        "compilation": True,
    },
    "apply_writes": {
        "tags": True,
        "nfo": True,
        "lyrics": True,
    },
    "embed_artwork": False,
    "embed_max_px": 1000,
    "webhook_jellyfin": "",
    "webhook_jellyfin_key": "",
    "webhook_jellyfin_param": "",
    "webhook_jellyfin_enabled": True,
    "webhook_navidrome": "",
    "webhook_navidrome_user": "",
    "webhook_navidrome_key": "",
    "webhook_navidrome_param": "",
    "webhook_navidrome_enabled": True,
    "webhook_plex": "",
    "webhook_plex_key": "",
    "webhook_plex_param": "",
    "webhook_plex_enabled": True,
    "webhook_emby": "",
    "webhook_emby_key": "",
    "webhook_emby_param": "",
    "webhook_emby_enabled": True,
    "lidarr_enabled": False,
    "lidarr_import_scan": False,
    "lidarr_monitor_new": True,
    "sort_ignore_the": True,
    "prune_safety": True,
    "lidarr_token": "",
    "lidarr_paths": [],
    "lidarr_url": "",
    "lidarr_api_key": "",
    "lidarr": {},
    "radarr_url": "",
    "radarr_api_key": "",
    "radarr_enabled": True,
    "radarr_import_scan": True,
    "radarr": {},
    "sonarr_url": "",
    "sonarr_api_key": "",
    "sonarr_enabled": True,
    "sonarr_import_scan": True,
    "sonarr": {},
    "bazarr_url": "",
    "bazarr_api_key": "",
    "bazarr_enabled": True,
    "bazarr_import_scan": True,
    "schedule_enabled": False,
    "schedule_mode": "preset",
    "schedule_preset": "daily_0300",
    "schedule_time": "03:00",
    "schedule_weekday": 0,
    "schedule_day": 1,
    "schedule_cron": "0 3 * * *",
    "schedule_scan_mode": "incremental",
    "scan_schedules": [],
    "player_clean_schedules": [],
    "pending_path_removals": [],
    "schedule_interval": "daily",
    "scan_log_keep": 30,
    "backup_enabled": False,
    "backup_mode": "preset",
    "backup_preset": "daily_0400",
    "backup_time": "04:00",
    "backup_weekday": 0,
    "backup_day": 1,
    "backup_cron": "0 4 * * *",
    "backup_keep": 14,
    "backup_snapshot_before_bulk": False,
    "backup_folder": "",
    "choose_release_modes": {"incremental": False, "full": False, "deep": False, "forced": False},
    "artwork_lookup_modes": {"incremental": False, "full": False, "deep": False, "forced": False},
    "refresh_discography_during_scan": True,
    "fill_missing_during_scan": True,
    "fill_mb_metadata_during_incremental": True,
    "limited_artwork_during_scan": False,
    "metadata_miss_days": 30,
    "nfo_on_bio_save": True,
    "scan_rewrite_nfo": False,
    "biography_longest": True,
    "allmusic_enabled": True,
    "metadata_priority": {key: list(value) for key, value in METADATA_FIELDS.items()},
    "metadata_enabled": {key: {item: True for item in value} for key, value in METADATA_FIELDS.items()},
    "verbose_logging": False,
}

RENAME_SCOPES = {"none", "both", "folder", "file"}


def settings_path():
    return os.path.join(config_dir(), "settings.json")


def ensure():
    try:
        os.makedirs(config_dir(), exist_ok=True)
        os.makedirs(additional_artwork_dir(), exist_ok=True)
        os.makedirs(undo_dir(), exist_ok=True)
        if not os.path.exists(settings_path()):
            save(DEFAULTS)
    except OSError as exc:
        logger.warning("config directory is not writable: %s", exc)
    try:
        os.makedirs(artwork_cache_dir(), exist_ok=True)
    except OSError as exc:
        logger.warning("cache directory is not writable: %s", exc)


def _read_raw():
    path = settings_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not read settings: %s", exc)
        return {}


def load():
    return _apply_env(_normalize(_read_raw()))


load_settings = load


_verbose_cache = {"stamp": None, "on": False}


def verbose_enabled():
    """True when Settings has verbose logging on. Cached until settings.json changes."""
    path = settings_path()
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        stamp = None
    if _verbose_cache["stamp"] != stamp:
        _verbose_cache["stamp"] = stamp
        _verbose_cache["on"] = bool(load().get("verbose_logging"))
    return _verbose_cache["on"]


def vlog(logger, message, *args):
    """Write an info line to the container log when verbose logging is on."""
    if verbose_enabled():
        logger.info(message, *args)


def public():
    raw = _read_raw()
    data = _apply_env(_normalize(raw))
    view = dict(data)
    sources = data.get("key_sources") or {}
    status = {}
    for key in ENV_KEYS:
        if key in sources:
            status[key] = "environment"
        elif str(raw.get(key) or "").strip():
            status[key] = "saved"
        else:
            status[key] = ""
        view[key] = ""
    for name in ("emby", "jellyfin", "navidrome", "plex"):
        secret = f"webhook_{name}_key"
        if not status.get(secret) and str(data.get(secret) or "").strip():
            status[secret] = "saved"
        view[secret] = ""
        view[f"webhook_{name}_param"] = ""
    view["key_status"] = status
    from curator import outbound

    view["outbound"] = outbound.masked(data.get("outbound"))
    view["outbound_catalog"] = outbound.catalog()
    from resonance import cron

    view["schedule_summary"] = cron.schedule_summary(data)
    view["schedule_presets"] = cron.PRESETS
    view["backup_summary"] = cron.schedule_summary(cron.as_schedule(data, "backup"))
    from resonance import backup

    view["backup_default"] = backup.default_dir()
    enabled = bool(data.get("schedule_enabled"))
    view["scan_schedule_summaries"] = [
        cron.saved_schedule_summary(item, enabled) for item in (data.get("scan_schedules") or [])
    ]
    return view


def save(patch):
    incoming = dict(patch) if isinstance(patch, dict) else {}
    previous = _read_raw()
    clear = {str(item) for item in incoming.get("clear_keys") or [] if isinstance(item, str)}
    for key in ENV_KEYS:
        incoming[key] = kept_secret(incoming.get(key), previous.get(key), key in clear)
    for name in ("emby", "jellyfin", "navidrome", "plex"):
        secret_name = f"webhook_{name}_key"
        _url, embedded, param = webhook_parts(previous.get(f"webhook_{name}"))
        incoming[secret_name] = kept_secret(
            incoming.get(secret_name),
            previous.get(secret_name) or embedded,
            secret_name in clear,
        )
        if not str(incoming.get(f"webhook_{name}_param") or "").strip():
            incoming[f"webhook_{name}_param"] = param
    from curator import outbound

    incoming["outbound"] = outbound.keep_secrets(incoming.get("outbound"), previous.get("outbound"))
    incoming["lidarr_token"] = kept_secret(
        incoming.get("lidarr_token"), previous.get("lidarr_token"), "lidarr_token" in clear
    )
    if _flag(incoming.get("lidarr_enabled")) and not str(incoming.get("lidarr_token") or "").strip():
        incoming["lidarr_token"] = secrets.token_urlsafe(24)
    normalized = _normalize(incoming, strict_paths=True)
    normalized["pending_path_removals"] = record_path_removals(previous, normalized)
    set_folder = normalized["video"].get("set_folder")
    if set_folder and not os.path.isdir(set_folder):
        raise AppError(f"The movie set folder {set_folder} does not exist inside the container. Create it first.", 400)
    from curator.video import renamer

    for key, template in normalized["video"]["rename"].items():
        try:
            renamer.validate(template)
        except ValueError as exc:
            raise AppError(f"The {key.replace('_', ' ')} pattern is not valid Jinja2: {exc}", 400) from exc
    if normalized["backup_folder"] and normalized["backup_folder"] != str(previous.get("backup_folder") or ""):
        from resonance import backup

        backup.check_folder(normalized["backup_folder"])
    _verbose_cache["stamp"] = None
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as exc:
        raise AppError(f"Config directory is not writable: {exc}", 500) from exc
    payload = json.dumps(normalized, indent=2) + "\n"
    with _lock:
        atomic_write(path, payload, binary=False)
    from curator.video import writes

    writes.forget_roots()
    _drop_removed_libraries(previous, normalized)
    return normalized


def _path_set(paths):
    found = set()
    for item in paths or []:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip()
        found.add(os.path.realpath(raw) if os.path.exists(raw) else os.path.normpath(raw))
    return found


def _drop_removed_libraries(previous, normalized):
    """A library folder taken out of Settings no longer has a scan that can prune it."""
    if not isinstance(previous, dict):
        return
    dropped = []
    for key, label in (("movie_paths", "movies"), ("tv_paths", "shows")):
        old = previous.get(key)
        if not isinstance(old, list):
            continue
        new = normalized.get(key) or []
        if _path_set(old) == set(new):
            continue
        dropped.append((key, new, label))
    if not dropped:
        return
    from curator.video import store

    movies = shows = 0
    for key, paths, _label in dropped:
        if key == "movie_paths":
            movies, _shows = store.drop_unconfigured(paths, None)
        else:
            _movies, shows = store.drop_unconfigured(None, paths)
    if movies or shows:
        logger.info("Removed %s movies and %s shows whose library folder is no longer configured", movies, shows)


# Kodi has VideoLibrary.Clean / AudioLibrary.Clean and Plex has Empty Trash on a section.
# Emby and Jellyfin drop missing items during an ordinary scan, so they only ever update.
PLAYER_CLEAN_SUPPORT = {"kodi", "plex"}


def _pending_path_removals(data):
    """Library paths the user took out of Settings, waiting for a scan to remove their items.

    A path that is simply absent from the configured list is NOT the same as a path the user
    removed: a mount that is away, an excluded folder or a hand-edited config all look like
    that. Only an explicit removal is recorded here, and only what sits under the recorded
    path is ever removed from the database. No file is ever touched.
    """
    raw = data.get("pending_path_removals", None)
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        kind = str(entry.get("kind") or "").strip().lower()
        if not path or kind not in {"music", "movies", "tv"}:
            continue
        row = {"path": path, "kind": kind}
        if row not in items:
            items.append(row)
        if len(items) >= 200:
            break
    return items


def record_path_removals(previous, normalized):
    """Add to the pending list every library path that this save took away."""
    keys = (("music_paths", "music"), ("movie_paths", "movies"), ("tv_paths", "tv"))
    pending = list(normalized.get("pending_path_removals") or [])
    for key, kind in keys:
        before = [p for p in (previous.get(key) or []) if isinstance(p, str) and p.strip()]
        after = {p.strip() for p in (normalized.get(key) or []) if isinstance(p, str) and p.strip()}
        for path in before:
            cleaned = path.strip()
            if cleaned and cleaned not in after:
                row = {"path": cleaned, "kind": kind}
                if row not in pending:
                    pending.append(row)
    return pending[:200]


def take_path_removals(kind):
    """Pop and return the pending removals for one library kind.

    Read-modify-write of just this key, so a scan clearing its own removals cannot disturb
    anything else the user has saved meanwhile.
    """
    wanted = str(kind or "").strip().lower()
    if wanted == "sets":
        wanted = "movies"
    if wanted not in {"music", "movies", "tv"}:
        return []
    raw = _read_raw()
    pending = _pending_path_removals(raw)
    mine = [row["path"] for row in pending if row.get("kind") == wanted]
    if not mine:
        return []
    keep = [row for row in pending if row.get("kind") != wanted]
    raw["pending_path_removals"] = keep
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write(path, json.dumps(raw, indent=2) + "\n")
    except OSError:
        logger.warning("could not clear pending path removals for %s", wanted, exc_info=True)
        return []
    _verbose_cache["stamp"] = None
    return mine


def _player_clean_schedules(data):
    """Saved player schedules: [{player, kind, media, cron}].

    `kind` is "clean" or "update". A clean asked of a player with no separate clean call is
    stored as "update" rather than dropped, so the schedule still does the useful thing.
    """
    from resonance import cron

    raw = data.get("player_clean_schedules", None)
    if not isinstance(raw, list):
        return []
    valid_players = {"kodi", "emby", "jellyfin", "plex"}
    valid_media = {"video", "music"}
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        player = str(entry.get("player") or "").strip().lower()
        if player not in valid_players:
            continue
        media = str(entry.get("media") or "video").strip().lower()
        if media not in valid_media:
            media = "video"
        kind = str(entry.get("kind") or "clean").strip().lower()
        if kind not in {"clean", "update"}:
            kind = "update"
        if kind == "clean" and player not in PLAYER_CLEAN_SUPPORT:
            kind = "update"
        expr = " ".join(str(entry.get("cron") or "").split())[:120]
        if not cron.validate_cron(expr):
            continue
        items.append({"player": player, "kind": kind, "media": media, "cron": expr})
        if len(items) >= 20:
            break
    return items

def _scan_schedules(data, merged):
    """Saved scan schedules. A scheduler that was already on keeps its single cron."""
    from resonance import cron

    raw = data.get("scan_schedules", None)
    if isinstance(raw, list):
        items = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            mode = str(entry.get("scan_mode") or "").strip().lower()
            if mode not in {"incremental", "full", "deep"}:
                mode = "incremental"
            expr = " ".join(str(entry.get("cron") or "").split())[:120]
            if not cron.validate_cron(expr):
                continue
            media = str(entry.get("media") or "music").strip().lower()
            if media not in {"music", "movies", "tv", "sets"}:
                media = "music"
            items.append({"scan_mode": mode, "cron": expr, "media": media})
            if len(items) >= 20:
                break
        return items
    if not _schedule_was_configured(merged):
        return []
    expr = cron.get_effective_cron(merged)
    mode = merged.get("schedule_scan_mode") or "incremental"
    if mode not in {"incremental", "full", "deep"}:
        mode = "incremental"
    if cron.validate_cron(expr):
        return [{"scan_mode": mode, "cron": expr, "media": "music"}]
    return []


def _schedule_was_configured(merged):
    """True when the single schedule was turned on or changed from the factory default."""
    if merged.get("schedule_enabled"):
        return True
    if (merged.get("schedule_scan_mode") or "incremental") != "incremental":
        return True
    if (merged.get("schedule_mode") or "preset") != "preset":
        return True
    if (merged.get("schedule_preset") or "daily_0300") != "daily_0300":
        return True
    if str(merged.get("schedule_time") or "03:00")[:5] != "03:00":
        return True
    try:
        if int(merged.get("schedule_weekday") or 0) != 0:
            return True
    except (TypeError, ValueError):
        return True
    try:
        if int(merged.get("schedule_day") or 1) != 1:
            return True
    except (TypeError, ValueError):
        return True
    cron_expr = " ".join(str(merged.get("schedule_cron") or "").split())
    return bool(cron_expr and cron_expr != "0 3 * * *")


def _apply_clock(merged, data, prefix, default_preset, default_time, default_cron, legacy=False):
    from resonance import cron

    mode = str(data.get(f"{prefix}_mode") or "").strip().lower()
    if mode in {"preset", "daily", "weekly", "monthly", "custom"}:
        merged[f"{prefix}_mode"] = mode
    elif legacy and data.get("schedule_interval") == "nightly":
        merged[f"{prefix}_mode"] = "daily"
    elif legacy and data.get("schedule_interval") == "weekly":
        merged[f"{prefix}_mode"] = "weekly"
    else:
        merged[f"{prefix}_mode"] = "preset"

    preset = str(data.get(f"{prefix}_preset") or "").strip()
    merged[f"{prefix}_preset"] = preset if preset in cron.PRESETS_BY_ID else default_preset

    hour, minute = cron.parse_time_parts(str(data.get(f"{prefix}_time") or "").strip() or default_time)
    merged[f"{prefix}_time"] = f"{hour:02d}:{minute:02d}"

    try:
        raw_w = data.get(f"{prefix}_weekday", 0)
        if isinstance(raw_w, str) and raw_w.upper() in cron.DAYS_MAP:
            merged[f"{prefix}_weekday"] = cron.DAYS_MAP[raw_w.upper()]
        else:
            merged[f"{prefix}_weekday"] = int(raw_w) % 7
    except (ValueError, TypeError):
        merged[f"{prefix}_weekday"] = 0

    try:
        raw_d = int(data.get(f"{prefix}_day", 1))
        merged[f"{prefix}_day"] = max(1, min(raw_d, 31))
    except (ValueError, TypeError):
        merged[f"{prefix}_day"] = 1

    custom_cron = " ".join(str(data.get(f"{prefix}_cron") or "").split())[:120]
    merged[f"{prefix}_cron"] = custom_cron if custom_cron else default_cron


def _normalize(data, strict_paths=False):
    merged = dict(DEFAULTS)
    merged["assets"] = dict(DEFAULTS["assets"])
    merged["title_suffix_types"] = dict(DEFAULTS["title_suffix_types"])
    merged["apply_writes"] = dict(DEFAULTS["apply_writes"])
    if not isinstance(data, dict):
        data = {}
    merged["music_paths"] = _music_paths(data, strict_paths)
    merged["music_path_roles"] = _path_roles(data, merged["music_paths"])
    merged["music_path_kinds"] = _path_kinds(data, merged["music_paths"])
    merged["movie_paths"] = _video_paths(data, "movie_paths", "MOVIES_DIR", "/movies", strict_paths)
    merged["tv_paths"] = _video_paths(data, "tv_paths", "TV_DIR", "/tv", strict_paths)
    merged["pending_path_removals"] = _pending_path_removals(data)
    merged["scan_excluded"] = _scan_excluded(data, merged)
    if strict_paths:
        _check_folder_types(merged)
    profile = data.get("nfo_profile", merged["nfo_profile"])
    merged["nfo_profile"] = profile if profile in {"kodi", "emby"} else "kodi"
    dialect = data.get("nfo_dialect", merged.get("nfo_dialect", "kodi"))
    merged["nfo_dialect"] = dialect if dialect in {"kodi", "emby", "plex"} else "kodi"
    merged["nfo_backup"] = _flag(data.get("nfo_backup", True))
    merged["nfo_on_bio_save"] = _flag(data.get("nfo_on_bio_save", True))
    merged["scan_rewrite_nfo"] = _flag(data.get("scan_rewrite_nfo", False))
    merged["allmusic_enabled"] = _flag(data.get("allmusic_enabled", True))
    merged["metadata_priority"], merged["metadata_enabled"] = _metadata_priority(data)
    merged["verbose_logging"] = _flag(data.get("verbose_logging", False))
    try:
        resolution = int(data.get("min_resolution", merged["min_resolution"]))
    except (TypeError, ValueError):
        resolution = merged["min_resolution"]
    merged["min_resolution"] = max(0, min(resolution, 10000))
    try:
        fanart_count = int(data.get("fanart_count", merged["fanart_count"]))
    except (TypeError, ValueError):
        fanart_count = merged["fanart_count"]
    merged["fanart_count"] = max(1, min(fanart_count, 20))
    priority = []
    incoming = data.get("source_priority")
    if isinstance(incoming, list):
        for item in incoming:
            if item in KNOWN_SOURCES and item not in priority:
                priority.append(item)
    for item in DEFAULTS["source_priority"]:
        if item not in priority:
            priority.append(item)
    merged["source_priority"] = priority
    merged["sources_enabled"] = _sources_enabled(data)
    assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
    for old, new in LEGACY_ASSETS.items():
        if old in assets and new not in assets:
            assets[new] = assets[old]
    if "artistthumb" not in assets and "front" in assets:
        merged["assets"]["artistthumb"] = bool(assets["front"])
    for key in ASSET_KEYS:
        if key in assets:
            merged["assets"][key] = bool(assets[key])
    for key in ("lastfm_key", "lastfm_secret", "fanart_key", "acoustid_key", "tmdb_key", "tvdb_key", "omdb_key", "crawlbase_token", "opensubtitles_key", "opensubtitles_password", "kodi_password",
                "kodi_library_password", "jellyfin_token", "plex_token", "emby_token", "musicbrainz_contact"):
        value = data.get(key, merged[key])
        merged[key] = value.strip() if isinstance(value, str) else merged[key]
    if not merged["musicbrainz_contact"]:
        merged["musicbrainz_contact"] = DEFAULTS["musicbrainz_contact"]
    lyrics = data.get("lyrics_mode", merged["lyrics_mode"])
    merged["lyrics_mode"] = lyrics if lyrics in {"lrc", "txt"} else "lrc"
    merged["rename_enabled"] = _flag(data.get("rename_enabled", False))
    scope = data.get("rename_scope", merged["rename_scope"])
    merged["rename_scope"] = scope if scope in RENAME_SCOPES else "none"
    merged["rename_folder_pattern"] = _upgrade_pattern(
        _pattern(data.get("rename_folder_pattern"), merged["rename_folder_pattern"]),
        "%albumartist%/[%year%] %album%",
        DEFAULTS["rename_folder_pattern"],
    )
    merged["rename_file_pattern"] = _upgrade_pattern(
        _pattern(data.get("rename_file_pattern"), merged["rename_file_pattern"]),
        "$num(%tracknumber%,2) - %title%",
        DEFAULTS["rename_file_pattern"],
    )
    merged["rename_clean_chars"] = _flag(data.get("rename_clean_chars", True))
    merged["rename_move_sidecars"] = _flag(data.get("rename_move_sidecars", True))
    merged["rename_prune_empty"] = _flag(data.get("rename_prune_empty", False))
    merged["rename_straight_quotes"] = _flag(data.get("rename_straight_quotes", False))
    merged["rename_strip_junk"] = _flag(data.get("rename_strip_junk", False))
    merged["rename_transliterate"] = _flag(data.get("rename_transliterate", False))
    merged["title_suffix_types"] = _title_suffix_types(data)
    merged["apply_writes"] = _apply_writes(data)
    merged["choose_release_modes"] = _scan_mode_flags(
        data, "choose_release_modes", "choose_release_during_deep_scan"
    )
    merged["artwork_lookup_modes"] = _scan_mode_flags(
        data, "artwork_lookup_modes", "artwork_lookup_during_deep_scan"
    )
    merged["refresh_discography_during_scan"] = _flag(data.get("refresh_discography_during_scan", True))
    merged["fill_missing_during_scan"] = _flag(data.get("fill_missing_during_scan", True))
    merged["fill_mb_metadata_during_incremental"] = _flag(data.get("fill_mb_metadata_during_incremental", True))
    merged["limited_artwork_during_scan"] = _flag(data.get("limited_artwork_during_scan", False))
    merged["biography_longest"] = _flag(data.get("biography_longest", True))
    merged["metadata_miss_days"] = _metadata_miss_days(data.get("metadata_miss_days", merged["metadata_miss_days"]))
    merged["embed_artwork"] = _flag(data.get("embed_artwork", False))
    try:
        embed_px = int(data.get("embed_max_px", merged["embed_max_px"]))
    except (TypeError, ValueError):
        embed_px = 1000
    if embed_px <= 0:
        merged["embed_max_px"] = 0
    else:
        merged["embed_max_px"] = max(200, min(embed_px, 10000))
    for name in ("emby", "jellyfin", "navidrome", "plex"):
        _store_webhook(data, merged, name)
    merged["lidarr_enabled"] = _flag(data.get("lidarr_enabled", False))
    merged["lidarr_import_scan"] = _flag(data.get("lidarr_import_scan", False))
    merged["lidarr_monitor_new"] = _flag(data.get("lidarr_monitor_new", True))
    merged["sort_ignore_the"] = _flag(data.get("sort_ignore_the", True))
    merged["prune_safety"] = _flag(data.get("prune_safety", True))
    token = data.get("lidarr_token", "")
    merged["lidarr_token"] = token.strip() if isinstance(token, str) else ""
    merged["lidarr_paths"] = _lidarr_paths(data)
    url = data.get("lidarr_url", "")
    merged["lidarr_url"] = url.strip().rstrip("/") if isinstance(url, str) else ""
    secret = data.get("lidarr_api_key", "")
    merged["lidarr_api_key"] = secret.strip() if isinstance(secret, str) else ""
    from resonance.lidarr import normalize as normalize_lidarr

    merged["lidarr"] = normalize_lidarr(data.get("lidarr"))
    url = data.get("radarr_url", "")
    merged["radarr_url"] = url.strip().rstrip("/") if isinstance(url, str) else ""
    secret = data.get("radarr_api_key", "")
    merged["radarr_api_key"] = secret.strip() if isinstance(secret, str) else ""
    merged["radarr_enabled"] = _flag(data.get("radarr_enabled", True))
    merged["radarr_import_scan"] = _flag(data.get("radarr_import_scan", True))
    from curator import radarr

    merged["radarr"] = radarr.normalize(data.get("radarr"))
    url = data.get("sonarr_url", "")
    merged["sonarr_url"] = url.strip().rstrip("/") if isinstance(url, str) else ""
    secret = data.get("sonarr_api_key", "")
    merged["sonarr_api_key"] = secret.strip() if isinstance(secret, str) else ""
    merged["sonarr_enabled"] = _flag(data.get("sonarr_enabled", True))
    merged["sonarr_import_scan"] = _flag(data.get("sonarr_import_scan", True))
    from curator import sonarr

    merged["sonarr"] = sonarr.normalize(data.get("sonarr"))
    url = data.get("bazarr_url", "")
    merged["bazarr_url"] = url.strip().rstrip("/") if isinstance(url, str) else ""
    secret = data.get("bazarr_api_key", "")
    merged["bazarr_api_key"] = secret.strip() if isinstance(secret, str) else ""
    merged["bazarr_enabled"] = _flag(data.get("bazarr_enabled", True))
    merged["bazarr_import_scan"] = _flag(data.get("bazarr_import_scan", True))
    merged["schedule_enabled"] = _flag(data.get("schedule_enabled", False))
    _apply_clock(merged, data, "schedule", "daily_0300", "03:00", "0 3 * * *", legacy=True)

    scan_mode = str(data.get("schedule_scan_mode") or "").strip().lower()
    merged["schedule_scan_mode"] = scan_mode if scan_mode in {"full", "deep"} else "incremental"
    try:
        scan_logs = int(data.get("scan_log_keep", merged["scan_log_keep"]))
    except (TypeError, ValueError):
        scan_logs = 10
    merged["scan_log_keep"] = max(1, min(scan_logs, 100))
    merged["scan_schedules"] = _scan_schedules(data, merged)
    merged["player_clean_schedules"] = _player_clean_schedules(data)

    if merged["schedule_mode"] == "weekly":
        merged["schedule_interval"] = "weekly"
    elif merged["schedule_mode"] == "daily":
        merged["schedule_interval"] = "nightly"
    else:
        merged["schedule_interval"] = "nightly"

    merged["backup_enabled"] = _flag(data.get("backup_enabled", False))
    _apply_clock(merged, data, "backup", "daily_0400", "04:00", "0 4 * * *")
    try:
        keep = int(data.get("backup_keep", merged["backup_keep"]))
    except (TypeError, ValueError):
        keep = 14
    merged["backup_keep"] = max(1, min(keep, 100))
    merged["backup_snapshot_before_bulk"] = _flag(data.get("backup_snapshot_before_bulk", False))
    folder = str(data.get("backup_folder") or "").strip().replace("\\", "/").rstrip("/")
    merged["backup_folder"] = folder if folder.startswith("/") else ""
    from curator import automation
    from curator.video import config as video_config

    merged["video"] = video_config.normalize(data.get("video"))
    merged["automation"] = automation.normalize(data.get("automation"))
    merged["notify"] = automation.normalize_notify(data.get("notify"))
    from curator import outbound

    merged["outbound"] = outbound.normalize(data.get("outbound"))
    return merged


def kept_secret(incoming, previous, clear=False):
    if clear:
        return ""
    if isinstance(incoming, str):
        text = incoming.strip()
        if text and set(text) - {"*", "•"}:
            return text
    return previous if isinstance(previous, str) else ""


_WEBHOOK_SECRET_QUERY = {"api_key", "apikey", "token", "x-plex-token", "t", "p"}


def webhook_parts(url):
    """Return the address, a secret query value, and that query's name."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    text = str(url or "").strip()
    if not text:
        return "", "", ""
    parts = urlsplit(text)
    kept = []
    key = ""
    param = ""
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if not key and name.lower() in _WEBHOOK_SECRET_QUERY and value:
            key = value
            param = name
            continue
        kept.append((name, value))
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return clean, key, param


def _store_webhook(data, merged, name):
    url, embedded, param = webhook_parts(data.get(f"webhook_{name}"))
    if name == "navidrome" and param.lower() == "t":
        embedded = ""
        param = ""
    merged[f"webhook_{name}"] = url
    secret_name = f"webhook_{name}_key"
    typed = data.get(secret_name)
    if embedded:
        merged[secret_name] = embedded
    elif isinstance(typed, str) and typed.strip() and set(typed.strip()) - {"*", "•"}:
        merged[secret_name] = typed.strip()
    else:
        merged[secret_name] = ""
    stored_param = data.get(f"webhook_{name}_param")
    merged[f"webhook_{name}_param"] = "" if name == "navidrome" else (
        param or (stored_param.strip() if isinstance(stored_param, str) else "")
    )
    merged[f"webhook_{name}_enabled"] = _flag(data.get(f"webhook_{name}_enabled", True))
    if name == "navidrome":
        user = data.get("webhook_navidrome_user")
        text = user.strip() if isinstance(user, str) else ""
        if not text:
            from urllib.parse import parse_qsl, urlsplit

            found = dict(parse_qsl(urlsplit(str(data.get("webhook_navidrome") or "")).query, keep_blank_values=True))
            text = str(found.get("u") or "").strip()
        merged["webhook_navidrome_user"] = text


def apply_steps(cfg=None):
    """Categories Apply match writes. Tags also mark the album processed."""
    data = cfg if isinstance(cfg, dict) and isinstance(cfg.get("apply_writes"), dict) else load()
    raw = data.get("apply_writes") or {}
    steps = [key for key in ("tags", "nfo", "lyrics") if raw.get(key)]
    if "tags" in steps:
        steps.append("processed")
    return steps


def _apply_writes(data):
    defaults = DEFAULTS["apply_writes"]
    raw = data.get("apply_writes")
    if not isinstance(raw, dict):
        return dict(defaults)
    return {key: _flag(raw.get(key, defaults[key])) for key in defaults}


def _title_suffix_types(data):
    keys = ("album", "single", "ep", "live", "compilation")
    defaults = DEFAULTS["title_suffix_types"]
    raw = data.get("title_suffix_types")
    if isinstance(raw, dict):
        return {key: _flag(raw.get(key, defaults[key])) for key in keys}
    if _flag(data.get("album_title_suffix")):
        return {key: key != "album" for key in keys}
    return dict(defaults)


def _lidarr_paths(data):
    raw = data.get("lidarr_paths")
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = str(item.get("lidarr") or "").strip()
        target = str(item.get("resonance") or "").strip()
        if not source or not target or len(source) > 500 or len(target) > 500:
            continue
        rows.append({"lidarr": source, "resonance": target})
        if len(rows) >= 20:
            break
    return rows


def _scan_mode_flags(data, key, legacy_key):
    """Per-scan switches. An older single checkbox applied to every scan mode."""
    names = ("incremental", "full", "deep", "forced")
    raw = data.get(key)
    if isinstance(raw, dict):
        return {name: _flag(raw.get(name, False)) for name in names}
    legacy = _flag(data.get(legacy_key, False))
    return {name: legacy for name in names}


def prune_safety_on():
    """True when scans must hold back removals that break the 20 % limits (the default)."""
    return load().get("prune_safety") is not False


def _flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _pattern(value, default):
    if not isinstance(value, str):
        return default
    text = " ".join(value.splitlines()).strip()
    if not text or len(text) > 400:
        return default
    return text


def _upgrade_pattern(value, previous, current):
    if value == previous:
        return current
    return value


def _metadata_miss_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = 30
    return max(0, min(days, 3650))


def metadata_sources(purpose):
    """Enabled metadata sources for one job, first match wins."""
    if purpose not in METADATA_FIELDS:
        return []
    data = load()
    order = list((data.get("metadata_priority") or {}).get(purpose) or METADATA_FIELDS[purpose])
    enabled = (data.get("metadata_enabled") or {}).get(purpose) or {}
    if not data.get("allmusic_enabled", True):
        order = [item for item in order if item != "allmusic"]
    return [item for item in order if enabled.get(item, True)]


def _metadata_priority(data):
    raw_order = data.get("metadata_priority") if isinstance(data.get("metadata_priority"), dict) else {}
    raw_enabled = data.get("metadata_enabled") if isinstance(data.get("metadata_enabled"), dict) else {}
    order = {}
    enabled = {}
    for purpose, default in METADATA_FIELDS.items():
        chosen = []
        incoming = raw_order.get(purpose)
        if isinstance(incoming, list):
            for item in incoming:
                if item in default and item not in chosen:
                    chosen.append(item)
        for item in default:
            if item not in chosen:
                chosen.append(item)
        flags = raw_enabled.get(purpose) if isinstance(raw_enabled.get(purpose), dict) else {}
        order[purpose] = chosen
        enabled[purpose] = {item: _flag(flags[item]) if item in flags else True for item in default}
    return order, enabled


def _sources_enabled(data):
    raw = data.get("sources_enabled") if isinstance(data.get("sources_enabled"), dict) else {}
    return {key: bool(raw[key]) if key in raw else True for key in KNOWN_SOURCES}


def _apply_env(data):
    sources = {}
    for key, names in ENV_KEYS.items():
        if data.get(key):
            continue
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                data[key] = value
                sources[key] = name
                break
    data["key_sources"] = sources
    if not str(data.get("lidarr_url") or "").strip():
        url = os.environ.get("LIDARR_URL", "").strip().rstrip("/")
        if url:
            data["lidarr_url"] = url
    if not str(data.get("radarr_url") or "").strip():
        url = os.environ.get("RADARR_URL", "").strip().rstrip("/")
        if url:
            data["radarr_url"] = url
    if not str(data.get("sonarr_url") or "").strip():
        url = os.environ.get("SONARR_URL", "").strip().rstrip("/")
        if url:
            data["sonarr_url"] = url
    if not str(data.get("bazarr_url") or "").strip():
        url = os.environ.get("BAZARR_URL", "").strip().rstrip("/")
        if url:
            data["bazarr_url"] = url
    return data


def _path_kinds(data, paths):
    incoming = data.get("music_path_kinds") if isinstance(data, dict) else None
    if not isinstance(incoming, dict):
        incoming = {}
    kinds = {}
    for path in paths:
        kind = incoming.get(path)
        if kind not in {"artists", "artist"}:
            for key, value in incoming.items():
                if os.path.normpath(str(key)) == os.path.normpath(path) and value in {"artists", "artist"}:
                    kind = value
                    break
        kinds[path] = "artist" if kind == "artist" else "artists"
    return kinds


def _path_roles(data, paths):
    return {path: "library" for path in paths}


def _scan_excluded(data, merged):
    """Folders kept in the library but left out of scans. Only configured paths are kept."""
    known = []
    for key in ("music_paths", "movie_paths", "tv_paths"):
        known.extend(merged.get(key) or [])
    known_set = set(known)
    raw = data.get("scan_excluded") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        raw_path = item.strip()
        path = os.path.realpath(raw_path) if os.path.exists(raw_path) else os.path.normpath(raw_path)
        if path in known_set and path not in cleaned:
            cleaned.append(path)
    return cleaned


def _music_paths(data, strict):
    from resonance.paths import assert_library_path, default_music_dir

    incoming = data.get("music_paths") if isinstance(data, dict) else None
    if not isinstance(incoming, list) or not incoming:
        return [default_music_dir()]
    cleaned = []
    for item in incoming:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip()
        if not os.path.isabs(raw):
            if strict:
                raise AppError(f"{raw} must be an absolute path inside the container")
            continue
        path = os.path.realpath(raw) if os.path.exists(raw) else os.path.normpath(raw)
        if strict:
            assert_library_path(path)
        if path not in cleaned:
            cleaned.append(path)
    if cleaned:
        return cleaned
    if strict:
        raise AppError("Add at least one mounted music path")
    return [default_music_dir()]


FOLDER_TYPES = (("music_paths", "Music"), ("movie_paths", "Movies"), ("tv_paths", "TV Shows"))


def _video_paths(data, key, env_name, fallback, strict):
    """Movie or TV folders. Until the list is saved once, the compose mount is used when it exists."""
    from resonance.paths import assert_library_path

    label = "movie" if key == "movie_paths" else "TV"
    incoming = data.get(key) if isinstance(data, dict) else None
    if not isinstance(incoming, list):
        default = os.path.realpath(os.environ.get(env_name, fallback))
        return [default] if os.path.isdir(default) else []
    cleaned = []
    for item in incoming:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip()
        if not os.path.isabs(raw):
            if strict:
                raise AppError(f"{raw} must be an absolute path inside the container")
            continue
        path = os.path.realpath(raw) if os.path.exists(raw) else os.path.normpath(raw)
        if strict:
            assert_library_path(path, label)
        if path not in cleaned:
            cleaned.append(path)
    return cleaned


def _check_folder_types(merged):
    """A folder belongs to one media type, so a scan of one library never walks another."""
    from resonance.paths import inside

    seen = []
    for key, label in FOLDER_TYPES:
        for path in merged.get(key) or []:
            for other, other_label, other_key in seen:
                if other_key == key:
                    continue
                if path == other or inside(other, path) or inside(path, other):
                    raise AppError(
                        f"{path} overlaps the {other_label} folder {other}. Each folder can have only one media type."
                    )
            seen.append((path, label, key))
