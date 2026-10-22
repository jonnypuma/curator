"""Movie and TV scraper settings. Lives under settings["video"] and is normalized on every load."""
from __future__ import annotations

import os
import re

MOVIE_SOURCES = ("tmdb", "tvdb", "omdb", "rottentomatoes", "metacritic", "trakt", "anilist", "ofdb", "fanart")
TV_SOURCES = ("tmdb", "tvdb", "tvmaze", "omdb", "rottentomatoes", "metacritic", "trakt", "anilist", "ofdb", "fanart")
ART_SOURCES = ("fanart", "tmdb", "tvdb")
TV_ART_SOURCES = ART_SOURCES + ("tvmaze",)
MOVIE_META = ("title", "original_title", "english_title", "mpaa", "certification", "tagline", "plot",
              "year", "release_date", "rating", "top250", "runtime", "genres", "language", "country",
              "studio", "tags", "set", "trailer", "actors", "crew", "director", "premiered", "credits", "ids")
SHOW_META = ("title", "original_title", "english_title", "tagline", "plot", "aired", "year", "rating", "tags",
             "runtime", "certification", "genres", "language", "country", "studio", "trailer", "actors", "crew")
SEASON_META = ("title", "season_name", "sort_title", "year", "plot", "premiered",
               "id_tmdb", "id_imdb", "id_tvdb", "id_trakt", "id_tvmaze", "id_wikidata")
EPISODE_META = ("title", "original_title", "english_title", "plot", "aired", "rating", "tags", "runtime",
                "actors", "crew", "ids", "credits", "director", "premiered")
MOVIE_ART = ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart",
             "squareart", "extrafanart", "extrathumbs")
TV_ART = ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "characterart",
          "discart", "squareart", "extrafanart", "extrathumbs")
SEASON_ART = ("poster", "banner", "landscape", "fanart")
SET_ART = ("poster", "fanart", "clearlogo", "clearart", "banner", "landscape", "discart", "keyart", "squareart")
DIALECTS = ("kodi", "emby", "plex")
POLICIES = ("overwrite", "merge", "missing")
ORDERS = ("aired", "dvd", "absolute")
RATING_SOURCES = ("themoviedb", "imdb", "tvdb", "trakt", "tomatometerallcritics",
                  "tomatometeravguseraudience", "metacritic", "metacriticuser", "anilist", "ofdb")
LANG_STANDARDS = ("iso639-1", "iso639-2")
TRAILER_RESOLUTIONS = ("2160p", "1080p", "720p")

DEFAULT_MIN_WIDTH = {"poster": 1000, "fanart": 1920, "clearlogo": 400, "clearart": 500, "banner": 758,
                     "landscape": 1000, "discart": 500, "keyart": 1000, "characterart": 0, "squareart": 1000}


def _flag(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def _chain(value, allowed, default):
    items = value if isinstance(value, list) else default
    chain = []
    for item in items:
        name = str(item).strip().lower()
        if name in allowed and name not in chain:
            chain.append(name)
    return chain


def _include(chain, names):
    """Add a source that did not exist when this list was saved, without turning others back on."""
    found = list(chain)
    for name in names:
        if name not in found:
            found.append(name)
    return found


def _meta_fields(value, allowed):
    """Enabled scrape fields. A missing list means every field. An empty list means none."""
    if not isinstance(value, list):
        return list(allowed)
    chosen = []
    for item in value:
        name = str(item).strip()
        if name in allowed and name not in chosen:
            chosen.append(name)
    return chosen


def _kinds(value, allowed, default):
    if not isinstance(value, dict):
        return {kind: kind in default for kind in allowed}
    return {kind: _flag(value.get(kind), kind in default) for kind in allowed}


def _language(value, default):
    text = str(value or "").strip()
    return text if re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", text) else default


def _art_languages(value):
    """Primary artwork language, then up to three fallbacks. "none" means textless. Blank slots are unused."""
    raw = value if isinstance(value, list) else ["en"]
    cleaned = []
    for index, item in enumerate(list(raw)[:4]):
        text = str(item or "").strip().lower()
        if text in {"none", "textless", "null"}:
            cleaned.append("none")
        elif re.fullmatch(r"[a-z]{2}", text):
            cleaned.append(text)
        elif re.fullmatch(r"[a-z]{2}-[a-z]{2}", text):
            cleaned.append(text[:2])
        else:
            cleaned.append("en" if index == 0 else "")
    while len(cleaned) < 4:
        cleaned.append("")
    if not cleaned[0]:
        cleaned[0] = "en"
    return cleaned


def _folder(value):
    text = str(value or "").strip().replace("\\", "/")
    if not text.startswith("/") and not re.match(r"^[A-Za-z]:/", text) and not text.startswith("//"):
        return ""
    return text.rstrip("/") or "/"


def default_policy():
    raw = os.environ.get("CMM_OVERWRITE_ALL", "").strip().lower()
    return "overwrite" if raw in {"1", "true", "yes", "on"} else "merge"


def default_overwrite():
    """CMM_OVERWRITE_ALL is the starting overwrite switch until Settings are saved."""
    return default_policy() == "overwrite"


POLICY_MEDIA = ("movies", "tv", "sets")
POLICY_SIDES = ("metadata", "artwork")


def _as_overwrite(value, fallback):
    """True replaces existing values. False fills blanks. Older merge and missing values fill blanks."""
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"overwrite", "true", "1", "yes", "on"}:
        return True
    if text in {"merge", "missing", "false", "0", "no", "off"}:
        return False
    return fallback


def overwrite_on(cfg, media, side):
    """Whether a scan replaces existing metadata or artwork for this library."""
    media = {"episodes": "tv", "seasons": "tv"}.get(media, media)
    if media not in POLICY_MEDIA:
        media = "movies"
    block = ((cfg or {}).get("policies") or {}).get(media) or {}
    if side in block:
        return _as_overwrite(block.get(side), False)
    return _as_overwrite((cfg or {}).get("overwrite_policy"), default_overwrite())


def policy_for(cfg, media, side):
    """overwrite replaces enabled values. merge fills the empty ones."""
    return "overwrite" if overwrite_on(cfg, media, side) else "merge"


def choose_policy(explicit, shared, cfg, media, side):
    """A scrape can force overwrite for this run. Otherwise the saved switch for that library is used."""
    for value in (explicit, shared):
        text = str(value or "").strip().lower()
        if text in POLICIES:
            return text
    return policy_for(cfg, media, side)


def _policies(data, fallback):
    raw = data.get("policies") if isinstance(data.get("policies"), dict) else {}
    out = {}
    for media in POLICY_MEDIA:
        block = raw.get(media) if isinstance(raw.get(media), dict) else {}
        out[media] = {}
        for side in POLICY_SIDES:
            if side in block:
                out[media][side] = _as_overwrite(block.get(side), fallback)
            else:
                out[media][side] = fallback
    return out


def probe_workers_default():
    """CMM_PROBE_WORKERS, clamped to 1–20. Compose uses 8 when the variable is unset."""
    raw = os.environ.get("CMM_PROBE_WORKERS", "").strip()
    try:
        number = int(raw) if raw else 8
    except ValueError:
        number = 8
    return max(1, min(8, number))


def normalize(data):
    data = data if isinstance(data, dict) else {}
    widths = data.get("min_width") if isinstance(data.get("min_width"), dict) else {}
    policy = str(data.get("overwrite_policy") or "").strip().lower()
    dialect = str(data.get("nfo_dialect") or "").strip().lower()
    order = str(data.get("episode_order") or "").strip().lower()
    rating = str(data.get("default_rating") or "").strip().lower()
    nfo_name = str(data.get("movie_nfo_name") or "").strip().lower()
    return {
        "movie_sources": _chain(data.get("movie_sources"), MOVIE_SOURCES, list(MOVIE_SOURCES)),
        "tv_sources": _include(_chain(data.get("tv_sources"), TV_SOURCES, list(TV_SOURCES)), ("tvmaze",)),
        "art_sources": _chain(data.get("art_sources"), ART_SOURCES, list(ART_SOURCES)),
        "tv_art_sources": _include(_chain(
            data.get("tv_art_sources") if "tv_art_sources" in data else data.get("art_sources"),
            TV_ART_SOURCES,
            list(data.get("art_sources") or ART_SOURCES),
        ), ("tvmaze",)),
        "movie_fields": _meta_fields(data.get("movie_fields"), MOVIE_META),
        "show_fields": _meta_fields(data.get("show_fields"), SHOW_META),
        "season_fields": _meta_fields(data.get("season_fields"), SEASON_META),
        "episode_fields": _meta_fields(data.get("episode_fields"), EPISODE_META),
        "language": _language(data.get("language"), "en-US"),
        "country": str(data.get("country") or "US").strip().upper()[:2] or "US",
        "art_languages": _art_languages(data.get("art_languages")),
        "episode_order": order if order in ORDERS else "aired",
        "tv_primary": "tvdb" if str(data.get("tv_primary") or "").strip().lower() == "tvdb" else "tmdb",
        "default_rating": rating if rating in RATING_SOURCES else "themoviedb",
        "movie_art": _kinds(data.get("movie_art"), MOVIE_ART, ("poster", "fanart", "clearlogo", "clearart",
                                                                "banner", "landscape", "discart", "squareart",
                                                                "extrafanart", "extrathumbs")),
        "tv_art": _kinds(data.get("tv_art"), TV_ART, ("poster", "fanart", "clearlogo", "clearart", "banner",
                                                      "landscape", "characterart", "squareart", "extrafanart", "extrathumbs")),
        # Extra thumbs and extra fanart each stop at their own count.
        "extra_art_count": _int(data.get("extra_art_count"), 10, 1, 20),
        "extrafanart_count": _int(data.get("extrafanart_count"), 10, 1, 20),
        "season_art": _kinds(data.get("season_art"), SEASON_ART, ("poster",)),
        "episode_thumbs": _flag(data.get("episode_thumbs"), True),
        "scan_generate_ep_thumb": _flag(data.get("scan_generate_ep_thumb"), True),
        "min_width": {kind: _int(widths.get(kind), default, 0, 8000) for kind, default in DEFAULT_MIN_WIDTH.items()},
        "nfo_dialect": dialect if dialect in DIALECTS else "kodi",
        "movie_nfo_name": nfo_name if nfo_name in {"filename", "movie"} else "filename",
        "nfo_backup": _flag(data.get("nfo_backup"), True),
        "overwrite_policy": "overwrite" if _as_overwrite(policy, default_overwrite()) else "merge",
        "policies": _policies(data, _as_overwrite(policy, default_overwrite())),
        "write_nfo": _flag(data.get("write_nfo"), True),
        "download_artwork": _flag(data.get("download_artwork"), True),
        "scan_fill_missing": _flag(data.get("scan_fill_missing"), True),
        "scan_limited_art": _flag(data.get("scan_limited_art"), False),
        "scan_download_trailers": _flag(data.get("scan_download_trailers"), False),
        "scan_download_tv_trailers": _flag(data.get("scan_download_tv_trailers"), False),
        "scan_download_themes": _flag(data.get("scan_download_themes"), False),
        "scan_download_tv_themes": _flag(data.get("scan_download_tv_themes"), False),
        "scan_rewrite_nfo": _flag(data.get("scan_rewrite_nfo"), False),
        "scan_iso": _flag(data.get("scan_iso"), True),
        "collapse_versions": _flag(data.get("collapse_versions"), False),
        "omdb_patron": _flag(data.get("omdb_patron"), False),
        "write_on_edit": _flag(data.get("write_on_edit"), True),
        "actor_thumbs": _flag(data.get("actor_thumbs"), True),
        "keywords_as_tags": _flag(data.get("keywords_as_tags"), False),
        "concurrency": _int(data.get("concurrency"), 4, 1, 12),
        "probe_workers": _int(data.get("probe_workers"), probe_workers_default(), 1, 20),
        "set_folder": _folder(data.get("set_folder")) or _folder(os.environ.get("CMM_SET_FOLDER")),
        "set_art": _kinds(data.get("set_art"), SET_ART, ("poster", "fanart", "clearlogo", "landscape", "keyart", "squareart")),
        "set_nfo": _flag(data.get("set_nfo"), True),
        "rename": _templates(data.get("rename")),
        "filename_noise": _noise_text(data.get("filename_noise")),
        "sub_lang_standard": _choice(data.get("sub_lang_standard"), LANG_STANDARDS, _env_standard()),
        "sub_line_endings": _choice(data.get("sub_line_endings"), ("lf", "crlf"), "lf"),
        "sub_charset": _flag(data.get("sub_charset"), True),
        "sub_rename": _flag(data.get("sub_rename"), True),
        "sub_on_webhook": _flag(data.get("sub_on_webhook"), True),
        "sub_purge_duplicates": _flag(data.get("sub_purge_duplicates"),
                                      _flag(os.environ.get("CMM_PURGE_DUPLICATE_SUBS"), False)),
        "extras_layout": _choice(data.get("extras_layout"), ("kodi", "plex"), "kodi"),
        "trailer_resolution": _choice(data.get("trailer_resolution"), TRAILER_RESOLUTIONS, "1080p"),
        "trailer_on_webhook": _flag(data.get("trailer_on_webhook"), False),
        "trailer_on_sonarr_season": _flag(data.get("trailer_on_sonarr_season"), False),
        "theme_on_webhook": _flag(data.get("theme_on_webhook"), False),
        "trakt_sync_mode": _choice(data.get("trakt_sync_mode"), ("both", "pull", "push"), "both"),
        "trakt_sync_hours": _int(data.get("trakt_sync_hours"), 0, 0, 168),
        "export_format": _choice(data.get("export_format"), ("csv", "xml"), "csv"),
        "split_chapter_window": _num(data.get("split_chapter_window"), 15, 1, 120),
        "split_detect_window": _num(data.get("split_detect_window"), 15, 1, 120),
        "split_wide_window": _num(data.get("split_wide_window"), 45, 1, 300),
        "subs_download_movies": _flag(data.get("subs_download_movies"), False),
        "subs_download_tv": _flag(data.get("subs_download_tv"), False),
        "subs_languages": str(data.get("subs_languages") or "en").strip()[:80] or "en",
        "subs_hearing_impaired": _choice(data.get("subs_hearing_impaired"), ("exclude", "include", "only"), "exclude"),
        "subs_sync_after": _flag(data.get("subs_sync_after"), False),
        "subs_username": str(data.get("subs_username") or "").strip()[:120],
        "split_cut_at": _choice(data.get("split_cut_at"), ("start", "middle", "end"), "start"),
        "split_black_seconds": _num(data.get("split_black_seconds"), 0.3, 0.05, 5),
        "split_black_pic": _num(data.get("split_black_pic"), 0.98, 0.5, 1),
        "split_black_pix": _num(data.get("split_black_pix"), 0.10, 0, 1),
        "split_silence_db": _num(data.get("split_silence_db"), -50, -90, -10),
        "split_silence_seconds": _num(data.get("split_silence_seconds"), 0.4, 0.05, 5),
        "split_overlap_seconds": _num(data.get("split_overlap_seconds"), 0.25, 0.05, 5),
        "split_ambiguous_anchor": _num(data.get("split_ambiguous_anchor"), 5, 0.5, 30),
        "split_ambiguous_apart": _num(data.get("split_ambiguous_apart"), 3, 0.5, 30),
        "split_min_part": _num(data.get("split_min_part"), 30, 1, 600),
        "scan_split_notify": _flag(data.get("scan_split_notify"), False),
        "sub_sync_notify": _flag(data.get("sub_sync_notify"), False),
        "preview_cache_gb": _num(data.get("preview_cache_gb"), 5.0, 0.0, 500.0),
        "ocr_cache_mb": _num(data.get("ocr_cache_mb"), 100.0, 0.0, 5000.0),
        "ui_movie_year": _flag(data.get("ui_movie_year"), True),
        "ui_movie_edition": _flag(data.get("ui_movie_edition"), True),
        "ui_movie_date_added": _flag(data.get("ui_movie_date_added"), True),
        "ui_movie_processed": _flag(data.get("ui_movie_processed"), True),
        "ui_movie_art_badges": _flag(data.get("ui_movie_art_badges"), True),
        "ui_tv_year": _flag(data.get("ui_tv_year"), True),
        "ui_tv_seasons": _flag(data.get("ui_tv_seasons"), True),
        "ui_tv_episodes": _flag(data.get("ui_tv_episodes"), True),
        "ui_tv_date_added": _flag(data.get("ui_tv_date_added"), True),
        "ui_tv_processed": _flag(data.get("ui_tv_processed"), True),
        "ui_tv_progress": _flag(data.get("ui_tv_progress"), True),
        "ui_tv_art_badges": _flag(data.get("ui_tv_art_badges"), True),
        "ui_set_art_badges": _flag(data.get("ui_set_art_badges"), True),
        "ui_set_processed": _flag(data.get("ui_set_processed"), True),
        "ui_movie_poster_badges": _flag(data.get("ui_movie_poster_badges"), True),
        "ui_tv_poster_badges": _flag(data.get("ui_tv_poster_badges"), True),
        "ui_set_poster_badges": _flag(data.get("ui_set_poster_badges"), True),
        "ui_music_poster_badges": _flag(data.get("ui_music_poster_badges"), True),
        "ui_music_art_badges": _flag(data.get("ui_music_art_badges"), True),
        "ui_music_edition_badge": _flag(data.get("ui_music_edition_badge"), True),
        "ui_music_date_added": _flag(data.get("ui_music_date_added"), True),
        "ui_music_processed": _flag(data.get("ui_music_processed"), True),
        "export_format_music": _choice(data.get("export_format_music"), ("csv", "xml"), "csv"),
    }


def _num(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def _choice(value, allowed, default):
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _env_standard():
    raw = os.environ.get("CMM_SUBTITLE_LANG_STANDARD", "").strip().lower()
    return raw if raw in LANG_STANDARDS else "iso639-2"


def _noise_text(value):
    """Comma or line separated words. Missing means the built-in xpost, repost list. Blank means none."""
    if value is None:
        return "xpost, repost"
    return str(value).strip()


def _templates(value):
    from curator.video import renamer

    value = value if isinstance(value, dict) else {}
    found = {}
    for key, default in renamer.DEFAULTS.items():
        text = str(value.get(key) or "").strip()
        if text in renamer.LEGACY.get(key, ()):
            text = ""
        found[key] = text or default
    return found


def current():
    from resonance.settings import load

    data = load()
    video = dict(data.get("video") or normalize({}))
    for key in ("tmdb_key", "tvdb_key", "omdb_key", "fanart_key", "crawlbase_token", "opensubtitles_key", "opensubtitles_password"):
        video[key] = data.get(key) or ""
    if not video.get("subs_username"):
        video["subs_username"] = os.environ.get("OPENSUBTITLES_USERNAME", "").strip()
    return video
