"""Scrape jobs for movies and TV shows.

Each item asks its sources in parallel, merges the answers field by field in chain order, writes the
result under the overwrite policy (locked items and locked fields are never touched), downloads art and
writes the .nfo. Runs one job at a time in a worker thread with its own event loop.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime

from curator import trakt as trakt_auth
from curator.scrapers import merge
from curator.scrapers.fanart import Fanart
from curator.scrapers.http import Client, ScrapeError
from curator.scrapers.anilist import AniList
from curator.scrapers.metacritic import Metacritic
from curator.scrapers.ofdb import Ofdb
from curator.scrapers.omdb import Omdb
from curator.scrapers.rottentomatoes import RottenTomatoes
from curator.scrapers.tmdb import Tmdb
from curator.scrapers.trakt import TraktRatings
from curator.scrapers.tvdb import Tvdb
from curator.scrapers.tvmaze import Tvmaze
from curator.video import activity, actor_art, art_fetch, config, exports, naming, nfo_write, sets, store, writes
from resonance.errors import AppError

logger = logging.getLogger(__name__)

SCOPES = ("selected", "missing", "all")
LOG_LINES = 3000
LIST_LIMIT = 200
RATING_FIELDS = ("rating", "votes")
SCRAPE_GROUPS = (
    "story", "certification", "people", "details", "ratings", "ids", "trailer", "artwork", "set",
)
PRIMARY_SOURCES = ("tmdb", "tvdb", "omdb", "trakt")
_GROUP_FIELDS = {
    "story": {"title", "original_title", "english_title", "sort_title", "year", "tagline", "outline", "plot",
              "runtime_minutes", "premiered", "aired", "show_status"},
    "certification": {"mpaa", "certifications"},
    "people": {"directors", "writers", "producers", "actors", "guest_stars"},
    "details": {"genres", "studios", "countries", "tags", "languages", "original_language",
                "edition", "episode_order"},
    "ratings": {"ratings", "rating", "votes", "rating_imdb", "rating_tmdb", "rating_rt",
                "rating_rt_audience", "rating_metacritic", "rating_metacritic_user", "rating_trakt",
                "rating_anilist", "rating_ofdb", "rating_tvdb"},
    "ids": {"ids", "imdb_id", "tmdb_id", "tvdb_id", "anilist_id", "ofdb_id", "trakt_id"},
    "trailer": {"trailer"},
}
_METADATA_GROUPS = {"story", "certification", "people", "details", "ratings", "ids", "trailer"}

_lock = threading.Lock()
_cancel = threading.Event()
_listeners = []
_state = {"status": "idle", "media": None, "scope": None, "message": "Idle", "processed": 0, "total": 0,
          "current": "", "started_at": None, "finished_at": None, "result": {}, "id": None,
          "art_only": False, "embedded": False}
_log = deque(maxlen=LOG_LINES)
_sets_state = {"status": "idle", "media": "sets", "scope": None, "message": "Idle", "processed": 0, "total": 0,
               "current": "", "started_at": None, "finished_at": None, "result": {}, "id": None,
               "art_only": False, "embedded": False}
_sets_log = deque(maxlen=LOG_LINES)
_sets_initialized = False


def _load_initial_sets_state():
    global _sets_initialized
    if _sets_initialized:
        return
    _sets_initialized = True
    try:
        from resonance import db
        row = db.fetchone(
            "SELECT * FROM video_scrape_jobs WHERE media = 'sets' ORDER BY started_at DESC NULLS LAST LIMIT 1",
        )
        from curator import scan_logs
        latest = scan_logs.latest_log("sets")
        if row:
            res = row.get("result") or {}
            if not isinstance(res, dict):
                res = {}
            with _lock:
                _sets_state.update({
                    "status": row.get("status") or "completed",
                    "media": "sets",
                    "scope": row.get("scope"),
                    "message": row.get("message") or ("Scan finished" if row.get("status") == "completed" else "Idle"),
                    "started_at": row.get("started_at").isoformat(timespec="seconds") if row.get("started_at") else None,
                    "finished_at": row.get("finished_at").isoformat(timespec="seconds") if row.get("finished_at") else None,
                    "result": res,
                    "id": str(row.get("id")) if row.get("id") else None,
                })
        if latest and latest.get("text"):
            lines = latest["text"].splitlines()
            with _lock:
                _sets_log.clear()
                _sets_log.extend(lines[-LOG_LINES:])
    except Exception:
        logger.exception("could not load previous sets scan state")


def _sets_snapshot(include_log):
    state_snap = dict(_sets_state)
    state_snap["result"] = dict(_sets_state.get("result") or {})
    if include_log:
        state_snap["log"] = "\n".join(_sets_log)
    return state_snap


def add_listener(callback):
    _listeners.append(callback)


def _notify():
    snapshot = status(include_log=False)
    for callback in list(_listeners):
        try:
            callback(snapshot)
        except Exception:
            logger.exception("scrape listener failed")


def status(include_log=True):
    _load_initial_sets_state()
    with _lock:
        snapshot = dict(_state)
        snapshot["result"] = dict(_state["result"])
        if include_log:
            snapshot["log"] = "\n".join(_log)
        snapshot["sets"] = _sets_snapshot(include_log)
    return snapshot


def running():
    with _lock:
        return _state["status"] == "running"


# Fix Match picks made while another scrape is running wait here and start one after another.
_fix_queue = deque()
_apply_active = False


def queue_fix(media, item_id):
    """Remember a Fix Match scrape to start when the running one finishes. Returns the place in the queue."""
    with _lock:
        if (media, item_id) not in _fix_queue:
            _fix_queue.append((media, item_id))
        place = len(_fix_queue)
    start_next_fix()
    return place


def queued_fixes():
    with _lock:
        return len(_fix_queue)


def start_next_fix():
    with _lock:
        if _apply_active or _state["status"] == "running" or not _fix_queue:
            return False
        media, item_id = _fix_queue.popleft()
    if not start(media, "selected", [item_id], policy="overwrite", label="fix match"):
        with _lock:
            _fix_queue.appendleft((media, item_id))
        return False
    return True


def suspend():
    """Mark the scan's scrape idle so a webhook batch can scrape while the scan is parked."""
    with _lock:
        saved = dict(_state)
        saved["result"] = dict(_state.get("result") or {})
        _state["status"] = "idle"
        _state["embedded"] = False
        _state["message"] = ""
    return saved


def restore(saved):
    """Put the scan's scrape back after the webhook batch has finished."""
    if not saved:
        return
    with _lock:
        _state.update(saved)
        _state["result"] = dict(saved.get("result") or {})
        _state["status"] = "running"
        _state["embedded"] = True


def fill_missing_during_scan(scan_job, ids, season_numbers=None):
    """Metadata and a still for episodes the source lists when a deep scan found no file."""
    cfg = config.current()
    ids = [item for item in (ids or []) if item]
    if not ids:
        return
    if not cfg.get("scan_fill_missing", True):
        scan_job.log("Metadata and artwork during a scan are off in Settings, so missing episodes were left as gaps")
        return
    with _lock:
        if _state["status"] == "running":
            scan_job.log("A scrape is already running, so missing episodes were left for later")
            return
        _state["status"] = "running"
        _state["media"] = "tv"
        _state["embedded"] = True
    try:
        noun = "show" if len(ids) == 1 else "shows"
        scan_job.log(f"Missing episodes: looking up metadata and artwork for {len(ids)} {noun}")
        scan_job.progress(message=f"Missing episodes 0/{len(ids)}", processed=0, total=len(ids), phase="lookup", force=True)
        bridge = _ScanBridge(scan_job, cfg, art_only=False, phase="lookup", label="Missing episodes")
        bridge.missing_only = True
        if season_numbers:
            bridge.only_season_numbers = {int(number) for number in season_numbers}
        bridge.prepare(len(ids))
        _embedded_pass(bridge, ids)
    except ScrapeError as exc:
        scan_job.log(f"Missing episodes stopped: {exc}")
    except Exception as exc:
        logger.exception("missing episode lookup failed")
        scan_job.log(f"Missing episodes stopped: {exc}")
    finally:
        with _lock:
            if _state.get("embedded"):
                _state["status"] = "idle"
                _state["message"] = ""
                _state["embedded"] = False


def fill_during_scan(scan_job, ids, limited=False):
    """Metadata and artwork together for items a scan just decided to refresh.

    One lookup per title writes the text and then the images from that same reply.
    A scrape started on its own is left alone.
    """
    cfg = config.current()
    with _lock:
        if _state["status"] == "running":
            scan_job.log("A scrape is already running, so metadata and artwork were left for later")
            return
        _state["status"] = "running"
        _state["media"] = scan_job.media
        _state["embedded"] = True
    try:
        if not cfg.get("download_artwork", True):
            scan_job.log("Artwork download is off, so this lookup writes metadata only")
        lookup = _limited_art(cfg, scan_job.media) if limited and cfg.get("download_artwork", True) else cfg
        _scan_pass(scan_job, ids, lookup, art_only=False, phase="lookup", label="Metadata and artwork")
    finally:
        with _lock:
            if _state.get("embedded"):
                _state["status"] = "idle"
                _state["message"] = ""
                _state["embedded"] = False


def fill_replaced_artwork(scan_job, movie_ids, episodes):
    """Download artwork that is still missing after a replaced file kept the images it already had.

    episodes is {show id: [episode ids]}. Existing files are left in place.
    """
    cfg = config.current()
    movie_ids = [item for item in (movie_ids or []) if item]
    episodes = {str(show_id): [item for item in ids if item] for show_id, ids in (episodes or {}).items() if show_id}
    episodes = {show_id: ids for show_id, ids in episodes.items() if ids}
    if not movie_ids and not episodes:
        return
    if not cfg.get("download_artwork", True):
        scan_job.log("Artwork download is off, so missing artwork was left")
        return
    with _lock:
        if _state["status"] == "running":
            scan_job.log("A scrape is already running, so missing artwork was left for later")
            return
        _state["status"] = "running"
        _state["media"] = scan_job.media
        _state["embedded"] = True
    try:
        if movie_ids and not scan_job.cancelled:
            scan_job.log(f"Artwork: checking {len(movie_ids)} replaced movie{'s' if len(movie_ids) != 1 else ''}")
            bridge = _ScanBridge(scan_job, cfg, True, "nfo", "Artwork")
            bridge.media = "movies"
            bridge.policy = "missing"
            bridge.prepare(len(movie_ids))
            _embedded_pass(bridge, movie_ids)
        if episodes and not scan_job.cancelled:
            episode_ids = [item for ids in episodes.values() for item in ids]
            scan_job.log(f"Artwork: checking {len(episode_ids)} replaced episode{'s' if len(episode_ids) != 1 else ''}")
            bridge = _ScanBridge(scan_job, cfg, True, "nfo", "Artwork")
            bridge.media = "episodes"
            bridge.policy = "missing"
            shows = _episode_shows(bridge, episode_ids)
            bridge.prepare(len(shows))
            _embedded_pass(bridge, shows)
    except ScrapeError as exc:
        scan_job.log(f"Artwork stopped: {exc}")
    except Exception as exc:
        logger.exception("replaced artwork lookup failed")
        scan_job.log(f"Artwork stopped: {exc}")
    finally:
        with _lock:
            if _state.get("embedded"):
                _state["status"] = "idle"
                _state["message"] = ""
                _state["embedded"] = False


def _limited_art(cfg, media):
    """Poster only, matching the music scan's limited artwork search."""
    narrowed = dict(cfg)

    def posters(kinds):
        return {kind: bool(on) and kind == "poster" for kind, on in (kinds or {}).items()}

    if media == "movies":
        narrowed["movie_art"] = posters(cfg.get("movie_art"))
        narrowed["set_art"] = posters(cfg.get("set_art"))
    else:
        narrowed["tv_art"] = posters(cfg.get("tv_art"))
        narrowed["season_art"] = posters(cfg.get("season_art"))
    return narrowed


class _ScanBridge:
    """Scrape job that reports through the scan already on screen."""

    def __init__(self, scan_job, cfg, art_only, phase, label):
        self.scan = scan_job
        self.cfg = cfg
        self.meta_policy = config.policy_for(cfg, scan_job.media, "metadata")
        self.art_policy = config.policy_for(cfg, scan_job.media, "artwork")
        self.rewrite_nfo = bool(cfg.get("scan_rewrite_nfo"))
        self.art_only = art_only
        self.media = scan_job.media
        self.lang = str(cfg.get("language") or "en").split("-")[0]
        self.phase = phase
        self.label = label
        self.sets_done = set()
        self.only_episode_ids = None
        self.missing_only = False
        self.only_season_numbers = None
        self.scan_trailers = bool(getattr(scan_job, "scan_trailers", False))
        self.groups = None
        self.picks = None
        self.primary = None
        self.meta_primary = {}
        self.art_primary = {}
        self._done = 0
        self._total = 0

    @property
    def policy(self):
        return self.meta_policy

    @policy.setter
    def policy(self, value):
        self.meta_policy = value
        self.art_policy = value

    def prepare(self, total):
        self._total = total
        self.scan.progress(message=f"{self.label} 0/{total}", processed=0, total=total, phase=self.phase, force=True)

    def log(self, line):
        self.scan.log(line)

    def count(self, key, step=1):
        if self.art_only and key == "scraped":
            return
        self.scan.count(key, step)

    def fail(self, title, error):
        self.scan.log(f"Failed: {title}: {error}")
        self.scan.count("scrape_failed")

    def step(self, current=None):
        self._done += 1
        name = f": {current}" if current else ""
        self.scan.progress(
            message=f"{self.label} {self._done}/{self._total}{name}",
            processed=self._done, total=self._total, phase=self.phase,
        )

    def push(self, force=False):
        self.scan.progress(phase=self.phase, force=force)

    @property
    def cancelled(self):
        return self.scan.cancelled


def _scan_pass(scan_job, ids, cfg, art_only, phase, label):
    if scan_job.cancelled:
        return
    if not ids:
        scan_job.log(f"{label}: nothing to do.")
        scan_job.progress(message=f"{label}: nothing to do", phase=phase, force=True)
        return
    bridge = _ScanBridge(scan_job, cfg, art_only, phase, label)
    bridge.hold_unmatched = True
    bridge.prepare(len(ids))
    scan_job.log(f"{label}: {len(ids)} {'shows' if scan_job.media == 'tv' else 'movies'}")
    try:
        _embedded_pass(bridge, ids)
    except ScrapeError as exc:
        scan_job.log(f"{label} stopped: {exc}")
    except Exception as exc:
        logger.exception("scan %s step failed", label.lower())
        scan_job.log(f"{label} stopped: {exc}")


def start(media, scope, ids=None, policy=None, label=None, art_only=False, release_queue=False,
         groups=None, primary=None, fields=None, art=None, art_primary=None, meta_policy=None, art_policy=None,
         rewrite_nfo=None):
    """Returns False when a scrape is already running."""
    if media not in ("movies", "tv", "sets", "episodes", "seasons"):
        raise ValueError(media)
    if scope not in SCOPES:
        scope = "missing"
    with _lock:
        if _state["status"] == "running":
            return False
        _cancel.clear()
        _log.clear()
        _state.update({
            "status": "running", "media": media, "scope": scope, "message": "Starting", "processed": 0,
            "total": 0, "current": "", "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None, "id": None, "art_only": bool(art_only), "embedded": False,
            "result": {"scraped": 0, "skipped": 0, "failed": 0, "art": 0, "nfo": 0, "failures": []},
        })
        if media == "sets":
            _sets_log.clear()
            _sets_state.update(dict(_state))
    thread = threading.Thread(
        target=_run, args=(media, scope, list(ids or []), policy, label, art_only, release_queue, groups, primary,
                           fields, art, art_primary, meta_policy, art_policy, rewrite_nfo),
        name=f"{media}-scrape", daemon=True,
    )
    thread.start()
    return True


def apply_pending(ids=None):
    """Write files for scan matches that were kept in the database. ids limits it to those items."""
    movies, shows = store.pending_match_ids()
    if ids is not None:
        wanted = {str(item) for item in ids}
        movies = [item for item in movies if item in wanted]
        shows = [item for item in shows if item in wanted]
    if not movies and not shows:
        return False
    with _lock:
        if _state["status"] == "running":
            return False
        _cancel.clear()
        _log.clear()
        _state.update({
            "status": "running", "media": "movies" if movies else "tv", "scope": "selected",
            "message": "Apply match", "processed": 0, "total": 0, "current": "",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None, "id": None, "art_only": False, "embedded": False,
            "result": {"scraped": 0, "skipped": 0, "failed": 0, "art": 0, "nfo": 0, "failures": []},
        })
    thread = threading.Thread(target=_apply_pending_run, args=(movies, shows), name="apply-match", daemon=True)
    thread.start()
    return True


def _apply_pending_run(movies, shows):
    global _apply_active
    _apply_active = True
    try:
        _apply_pending_steps(movies, shows)
    finally:
        _apply_active = False
        start_next_fix()


def _apply_pending_steps(movies, shows):
    if movies:
        _run("movies", "selected", movies, "overwrite", "Apply match")
    if not shows or _cancel.is_set():
        return
    if movies:
        with _lock:
            if _state["status"] == "running":
                return
            _state.update({
                "status": "running", "media": "tv", "scope": "selected", "message": "Apply match",
                "processed": 0, "total": 0, "current": "", "finished_at": None,
                "result": {"scraped": 0, "skipped": 0, "failed": 0, "art": 0, "nfo": 0, "failures": []},
            })
    _run("tv", "selected", shows, "overwrite", "Apply match")


def cancel():
    if not running():
        return False
    _cancel.set()
    with _lock:
        _state["message"] = "Stopping"
    _notify()
    return True


def _split_primary(primary, media):
    """A string is the one primary for the whole job. A dict is one primary per dialog block."""
    if isinstance(primary, dict):
        cleaned = {}
        for key, value in primary.items():
            name = str(value or "").strip().lower()
            if name:
                cleaned[str(key)] = name
        main = {"movies": "movie", "tv": "show", "seasons": "season", "episodes": "episode"}.get(media, "movie")
        return cleaned.get(main), cleaned
    return str(primary or "").strip().lower() or None, {}


class _Job:
    def __init__(self, media, cfg, policy, art_only=False, groups=None, primary=None, fields=None, art=None,
                 art_primary=None, meta_policy=None, art_policy=None, rewrite_nfo=None):
        self.media = media
        self.cfg = cfg
        self.meta_policy = config.choose_policy(meta_policy, policy, cfg, media, "metadata")
        self.art_policy = config.choose_policy(art_policy, policy, cfg, media, "artwork")
        self.policy = self.meta_policy
        self.rewrite_nfo = rewrite_nfo if isinstance(rewrite_nfo, bool) else None
        self.art_only = art_only
        self.groups = None if groups is None else {str(item) for item in groups}
        self.primary, self.meta_primary = _split_primary(primary, media)
        self.picks = _parse_picks(fields, art)
        self.art_primary = {str(key): str(value).strip().lower() for key, value in (art_primary or {}).items() if value}
        self.only_episode_ids = None
        self.missing_only = False
        self.only_season_numbers = None
        self.lang = cfg["language"].split("-")[0]
        self.last_push = 0.0
        self.sets_done = set()

    def log(self, line):
        stamp = datetime.now().strftime('%H:%M:%S')
        with _lock:
            _log.append(f"{stamp} {line}")
            if self.media == "sets":
                _sets_log.append(f"{stamp} {line}")

    def count(self, key, step=1):
        with _lock:
            _state["result"][key] = _state["result"].get(key, 0) + step
            if self.media == "sets":
                _sets_state["result"][key] = _sets_state["result"].get(key, 0) + step

    def fail(self, title, error):
        self.log(f"Failed: {title}: {error}")
        with _lock:
            result = _state["result"]
            result["failed"] += 1
            if len(result["failures"]) < LIST_LIMIT:
                result["failures"].append({"title": title, "error": str(error)})
            if self.media == "sets":
                s_res = _sets_state["result"]
                s_res["failed"] += 1
                if len(s_res["failures"]) < LIST_LIMIT:
                    s_res["failures"].append({"title": title, "error": str(error)})

    def step(self, current=None):
        with _lock:
            _state["processed"] += 1
            if current:
                _state["current"] = current
            _state["message"] = f"Scraping {_state['processed']}/{_state['total']}"
            if self.media == "sets":
                _sets_state["processed"] = _state["processed"]
                if current:
                    _sets_state["current"] = current
                _sets_state["message"] = _state["message"]
        self.push()

    def push(self, force=False):
        now = time.monotonic()
        if force or now - self.last_push > 0.5:
            self.last_push = now
            _notify()

    @property
    def cancelled(self):
        return _cancel.is_set()


def _run(media, scope, ids, policy, label, art_only=False, release_queue=False, groups=None, primary=None,
         fields=None, art=None, art_primary=None, meta_policy=None, art_policy=None, rewrite_nfo=None):
    cfg = config.current()
    policy = policy if policy in config.POLICIES else None
    job = _Job(media, cfg, policy, art_only=art_only, groups=groups, primary=primary, fields=fields, art=art,
               art_primary=art_primary, meta_policy=meta_policy, art_policy=art_policy, rewrite_nfo=rewrite_nfo)
    try:
        job_id = store.start_scrape_job(media, label or scope)
        with _lock:
            _state["id"] = job_id
    except Exception:
        logger.exception("could not record the scrape job")
    final, message = "completed", ""
    writes.forget_roots()
    try:
        if media == "episodes":
            items = _episode_shows(job, ids)
        elif media == "seasons":
            items = _season_shows(job, ids)
        else:
            items = {"movies": store.movie_ids, "tv": store.show_ids, "sets": store.set_ids}[media](scope, ids)
        with _lock:
            _state["total"] = len(items)
        if media == "episodes":
            noun = "episodes"
            count = len(job.only_episode_ids or [])
        elif media == "seasons":
            noun = "seasons"
            count = sum(len(numbers) for numbers in (job.only_seasons or {}).values())
        else:
            noun = {"movies": "movies", "tv": "shows", "sets": "movie sets"}[media]
            count = len(items)
        detail = f"{scope}, metadata {job.meta_policy}, artwork {job.art_policy}"
        if job.primary:
            detail += f", primary {job.primary}"
        if job.groups is not None:
            detail += f", {', '.join(sorted(job.groups))}"
        job.log(f"{'Downloading artwork for' if art_only else 'Scraping'} {count} {noun} ({detail})")
        job.push(force=True)
        if items:
            asyncio.run(_main(job, items))
        if job.cancelled:
            final, message = "cancelled", "Scrape stopped. Items already scraped were kept."
    except ScrapeError as exc:
        final, message = "failed", str(exc)
        job.log(message)
    except Exception as exc:
        logger.exception("%s scrape failed", media)
        final, message = "failed", str(exc)
        job.log(f"Scrape failed: {exc}")
    with _lock:
        result = dict(_state["result"])
    if final == "completed":
        message = (f"{result['scraped']} scraped, {result['skipped']} skipped, {result['failed']} failed, "
                   f"{result['art']} images saved, {result['nfo']} .nfo files written")
    job.log(message)
    with _lock:
        _state.update({"status": final, "message": message, "current": "",
                       "finished_at": datetime.now().isoformat(timespec="seconds")})
        job_id = _state["id"]
        lines = list(_log)
        if media == "sets":
            _sets_state.update(dict(_state))
            _sets_log = deque(_log, maxlen=LOG_LINES)
    try:
        store.finish_scrape_job(job_id, final, message, result)
    except Exception:
        logger.exception("could not record the scrape result")
    if media == "sets":
        try:
            from curator.video.scanner import _write_log
            _write_log("sets", lines)
        except Exception:
            logger.exception("could not write sets scan log")
    _notify()
    if release_queue:
        from resonance import scan_queue

        scan_queue.finished()
    start_next_fix()


def refresh_ratings(kind, item_id):
    """Ask TMDB, OMDb and Trakt for a fresh rating and write it onto this item."""
    if kind not in ("movie", "show", "episode"):
        raise ValueError(kind)
    return asyncio.run(_refresh_ratings(kind, item_id))


async def _refresh_ratings(kind, item_id):
    row = await asyncio.to_thread(_rating_row, kind, item_id)
    if not row:
        raise ScrapeError("That item is not in the library any more")
    if row.get("locked"):
        raise ScrapeError("This item is locked. Unlock it to update ratings.")
    cfg = config.current()
    client = Client()
    extra_ids = {}
    try:
        media = "tv" if kind in ("show", "episode") else "movies"
        found = sources(client, cfg, media)
        fresh = {}
        tmdb = found.get("tmdb")
        if tmdb and kind == "movie" and row.get("tmdb_id"):
            base = await tmdb.movie(row["tmdb_id"])
            fresh.update((base or {}).get("ratings") or {})
        elif tmdb and kind == "show" and row.get("tmdb_id"):
            base = await tmdb.tv(row["tmdb_id"])
            fresh.update((base or {}).get("ratings") or {})
        elif tmdb and kind == "episode" and row.get("show_tmdb"):
            episode = await tmdb.episode(row["show_tmdb"], row["season_number"], row["episode_number"])
            fresh.update((episode or {}).get("ratings") or {})
        ids = _ids(row)
        if kind == "episode" and row.get("show_imdb"):
            ids.setdefault("imdb", str(row["show_imdb"]))
        if found.get("omdb") and ids.get("imdb"):
            if kind == "episode":
                omdb = await found["omdb"].episode_ratings(ids["imdb"], row["season_number"], row["episode_number"])
            else:
                omdb = await found["omdb"].ratings(ids["imdb"])
            fresh.update((omdb or {}).get("ratings") or {})
        if found.get("trakt"):
            if kind == "movie":
                payload = await found["trakt"].movie(ids)
            elif kind == "show":
                payload = await found["trakt"].show(ids)
            else:
                payload = await found["trakt"].episode(ids, row["season_number"], row["episode_number"])
            fresh.update((payload or {}).get("ratings") or {})
            extra_ids = (payload or {}).get("ids") or {}
        else:
            extra_ids = {}
        if kind in ("movie", "show"):
            fresh.update(await _page_ratings(found, kind, row.get("title"), row.get("year")))
    finally:
        await client.close()
    if not fresh:
        raise ScrapeError("No ratings came back. The item needs a TMDB id, and OMDb or Trakt when you want those scores.")
    ratings = dict(row.get("ratings") or {})
    ratings.update(fresh)
    value, votes = merge.default_rating(ratings, cfg["default_rating"])
    await asyncio.to_thread(store.save_ratings, kind, item_id, ratings, value, votes)
    if extra_ids:
        await asyncio.to_thread(store.merge_ids, kind, item_id, extra_ids)
    if cfg.get("write_nfo") and cfg.get("write_on_edit", True):
        if kind == "movie":
            await asyncio.to_thread(exports.write_movie, item_id, cfg)
        elif kind == "show":
            await asyncio.to_thread(exports.write_show, item_id, cfg)
        else:
            await asyncio.to_thread(exports.write_show, str(row["show_id"]), cfg, "overwrite", [item_id])
    shown = f"{value}" if value is not None else "saved"
    return {"ok": True, "rating": value, "votes": votes, "message": f"Ratings updated. Score {shown}."}


def _rating_row(kind, item_id):
    if kind == "movie":
        return store.movie_row(item_id)
    if kind == "show":
        show, _seasons, _episodes = store.show_rows(item_id)
        return show
    row = store.db.fetchone(
        """
        SELECT e.*, s.tmdb_id AS show_tmdb, s.imdb_id AS show_imdb, s.tvdb_id AS show_tvdb, s.ids AS show_ids
        FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id WHERE e.id = %s
        """,
        (item_id,),
    )
    return store.db.clean(dict(row)) if row else None


def _score_tasks(tasks, job, found, media, title, year):
    if found.get("rottentomatoes"):
        scraper = found["rottentomatoes"]
        call = scraper.show(title, year) if media == "tv" else scraper.movie(title, year)
        tasks["rottentomatoes"] = _quiet(job, "Rotten Tomatoes", call)
    if found.get("metacritic"):
        scraper = found["metacritic"]
        call = scraper.show(title, year) if media == "tv" else scraper.movie(title, year)
        tasks["metacritic"] = _quiet(job, "Metacritic", call)
    for name, label in (("anilist", "AniList"), ("ofdb", "OFDb")):
        scraper = found.get(name)
        if scraper and title:
            call = scraper.show(title, year) if media == "tv" else scraper.movie(title, year)
            tasks[name] = _quiet(job, label, call)


async def _page_ratings(found, kind, title, year):
    fresh = {}
    media = "tv" if kind == "show" else "movie"
    for name, label in (("rottentomatoes", "Rotten Tomatoes"), ("metacritic", "Metacritic"),
                        ("anilist", "AniList"), ("ofdb", "OFDb")):
        scraper = found.get(name)
        if not scraper or not title:
            continue
        try:
            call = scraper.show(title, year) if media == "tv" else scraper.movie(title, year)
            data = await call
        except ScrapeError as exc:
            logger.info("%s ratings skipped: %s", label, exc)
            continue
        fresh.update((data or {}).get("ratings") or {})
    return fresh


def sources(client, cfg, media):
    chain = cfg["tv_sources"] if media == "tv" else cfg["movie_sources"]
    found = {}
    if "tmdb" in chain and cfg.get("tmdb_key"):
        tmdb = Tmdb(client, cfg["tmdb_key"], cfg["language"], cfg["country"])
        tmdb.art_languages = cfg.get("art_languages") or []
        found["tmdb"] = tmdb
    if cfg.get("tvdb_key") and (media != "tv" or "tvdb" in chain):
        found["tvdb"] = Tvdb(client, cfg["tvdb_key"], cfg["language"])
    if "omdb" in chain and cfg.get("omdb_key"):
        found["omdb"] = Omdb(client, cfg["omdb_key"])
    if "trakt" in chain:
        client_id = trakt_auth.client_id()
        if client_id:
            found["trakt"] = TraktRatings(client, client_id)
    if "fanart" in chain and cfg.get("fanart_key"):
        found["fanart"] = Fanart(client, cfg["fanart_key"])
    if "rottentomatoes" in chain:
        found["rottentomatoes"] = RottenTomatoes(client, cfg.get("crawlbase_token"))
    if "metacritic" in chain:
        found["metacritic"] = Metacritic(client, cfg.get("crawlbase_token"))
    if "anilist" in chain:
        found["anilist"] = AniList(client)
    if "ofdb" in chain:
        found["ofdb"] = Ofdb(client)
    if media == "tv" and "tvmaze" in chain:
        found["tvmaze"] = Tvmaze(client)
    if media in ("movies", "sets") and "tmdb" not in found:
        raise ScrapeError("Movies and movie sets need a TMDB API key. Add one under Settings > General > API credentials.")
    if media == "tv" and "tmdb" not in found and "tvdb" not in found:
        raise ScrapeError("TV needs a TMDB API key (free). Add one under Settings > General > API credentials.")
    return found


def _wait_for_memory(job):
    from resonance.memory import wait as wait_for_memory

    wait_for_memory(job.log, stop=lambda: job.cancelled)


def _library_pause_applies(job):
    """A library scan parks for a webhook. The webhook scan is that import, so it keeps going."""
    scan = getattr(job, "scan", job)
    return not getattr(scan, "during_import", False)


def _embedded_pass(bridge, ids):
    """Run the scan's scrape, parking between movies when imports are due.

    Movies already being looked up finish first. The rest wait until the webhook batch
    has scanned and scraped, then this pass continues. A webhook scan does not park:
    the pause it sees is the one held open until this scan returns.
    """
    from curator.video import scanner

    pending = list(ids)
    while pending:
        if bridge.cancelled:
            return
        deferred = asyncio.run(_main(bridge, pending)) or []
        if not deferred:
            return
        if scanner.pause_requested() and _library_pause_applies(bridge):
            scanner.yield_for_imports()
        pending = deferred


async def _main(job, items):
    from curator.video import scanner

    client = Client()
    deferred = []
    try:
        found = sources(client, job.cfg, "tv" if job.media in ("episodes", "seasons") else job.media)
        gate = asyncio.Semaphore(job.cfg["concurrency"])
        if job.art_only and job.media == "sets":
            raise ScrapeError("Artwork download works on movies and shows")
        worker = {"movies": _movie, "tv": _show, "sets": _set_item, "episodes": _show, "seasons": _show}[job.media]

        async def one(item_id):
            async with gate:
                if scanner.pause_requested() and _library_pause_applies(job):
                    deferred.append(item_id)
                    return
                if job.cancelled:
                    return
                await asyncio.to_thread(_wait_for_memory, job)
                if scanner.pause_requested() and _library_pause_applies(job):
                    deferred.append(item_id)
                    return
                if job.cancelled:
                    return
                with activity.holding() as hold:
                    hold(item_id)
                    title = None
                    try:
                        title = await worker(job, client, found, item_id)
                    except ScrapeError as exc:
                        title = await asyncio.to_thread(store.title_of, _table(job.media), item_id)
                        job.fail(title, exc)
                        await asyncio.to_thread(store.scrape_failed, _table(job.media), item_id, str(exc))
                    except Exception as exc:
                        logger.exception("scrape of %s failed", item_id)
                        title = await asyncio.to_thread(store.title_of, _table(job.media), item_id)
                        job.fail(title, exc)
                    finally:
                        job.step(title)

        await asyncio.gather(*(one(item_id) for item_id in items))
        return deferred
    finally:
        await client.close()


def _table(media):
    return {"movies": "movies", "tv": "tv_shows", "sets": "movie_sets", "episodes": "tv_shows", "seasons": "tv_shows"}[media]


def _episode_shows(job, ids):
    """Show ids for the episodes being scraped, and the episode ids the show pass should keep."""
    from resonance import db

    rows = db.fetchall(
        "SELECT id::text AS id, show_id::text AS show_id FROM tv_episodes WHERE id = ANY(%s::uuid[])",
        (list(ids or []),),
    )
    job.only_episode_ids = {row["id"] for row in rows}
    shows = []
    for row in rows:
        if row["show_id"] not in shows:
            shows.append(row["show_id"])
    return shows


def _season_shows(job, ids):
    """Show ids for the seasons being scraped, and which season numbers each show should keep."""
    from resonance import db

    rows = db.fetchall(
        "SELECT show_id::text AS show_id, season_number FROM tv_seasons WHERE id = ANY(%s::uuid[])",
        (list(ids or []),),
    )
    limits = {}
    shows = []
    for row in rows:
        limits.setdefault(row["show_id"], set()).add(int(row["season_number"]))
        if row["show_id"] not in shows:
            shows.append(row["show_id"])
    job.only_seasons = limits
    return shows


def _has_result(res):
    if not res:
        return False
    if isinstance(res, tuple) and len(res) == 2:
        show_art, season_art = res
        count = len(show_art or []) + (sum(len(v) for v in season_art.values()) if isinstance(season_art, dict) else 0)
        return count > 0
    if isinstance(res, (list, set)):
        return len(res) > 0
    if isinstance(res, dict):
        if "ratings" in res and not res.get("ratings") and not res.get("ids") and not res.get("mpaa"):
            return False
        return bool(res)
    return True


def _result_detail(label, res):
    if not res:
        return ""
    if isinstance(res, tuple) and len(res) == 2:
        show_art, season_art = res
        count = len(show_art or []) + (sum(len(v) for v in season_art.values()) if isinstance(season_art, dict) else 0)
        return f" ({count} image{'s' if count != 1 else ''})"
    if isinstance(res, list) and "fanart" in label.lower():
        return f" ({len(res)} image{'s' if len(res) != 1 else ''})"
    if isinstance(res, (list, dict)) and "episodes" in label.lower():
        count = len(res)
        return f" ({count} episode{'s' if count != 1 else ''})"
    if isinstance(res, dict):
        ratings = res.get("ratings")
        if isinstance(ratings, dict) and ratings:
            names = sorted(ratings.keys())
            return f" ({', '.join(names)})"
    return ""


async def _quiet(job, label, coroutine, timeout=15.0, log_success=True):
    """Secondary sources never fail the item; their errors only reach the log."""
    if coroutine is None:
        if log_success:
            job.log(f"{label}: skipped")
        return None
    try:
        if timeout:
            res = await asyncio.wait_for(coroutine, timeout=timeout)
        else:
            res = await coroutine
    except asyncio.TimeoutError:
        job.log(f"{label}: timed out after {int(timeout)}s")
        return None
    except ScrapeError as exc:
        job.log(f"{label}: {exc}")
        return None
    except Exception as exc:
        logger.exception("%s failed", label)
        job.log(f"{label}: {exc}")
        return None

    if log_success:
        if _has_result(res):
            job.log(f"{label}: succeeded{_result_detail(label, res)}")
        else:
            noun = "artwork" if "fanart" in label.lower() or "art" in label.lower() else "match"
            job.log(f"{label}: no {noun} found")
    return res



def _ids(row):
    ids = {key: str(value) for key, value in (row.get("ids") or {}).items() if value}
    for kind in ("imdb", "tmdb", "tvdb", "trakt"):
        if row.get(f"{kind}_id"):
            ids.setdefault(kind, str(row[f"{kind}_id"]))
    return ids


def _ordered(results, chain):
    order = {name: index for index, name in enumerate(chain)}
    return sorted((item for item in results if item), key=lambda item: order.get(item.get("source"), 99))


def _prefer_season_source(job, merged, results):
    """Season fields follow the season block's provider when it differs from the show's."""
    chosen = (job.meta_primary or {}).get("season")
    if not chosen or chosen == job.primary:
        return merged
    chain = _metadata_chain(job, "tv", lead=chosen, prefer_lead=True)
    seasons = {}
    for result in _ordered(results, chain):
        for number, season in (result.get("seasons") or {}).items():
            target = seasons.setdefault(number, {})
            for key, value in season.items():
                if key == "art" or not value:
                    continue
                if key == "ids" and isinstance(value, dict):
                    bucket = target.setdefault("ids", {})
                    for name, item in value.items():
                        if item and not bucket.get(name):
                            bucket[name] = item
                elif not target.get(key):
                    target[key] = value
    current = merged.get("seasons") or {}
    for number, previous in current.items():
        target = seasons.setdefault(number, {})
        target["art"] = previous.get("art") or []
    if seasons:
        merged["seasons"] = seasons
    return merged


def _season_fields(job, merged, results, season):
    """One season can prefer a provider without changing the other seasons in this scrape."""
    number = season.get("season_number")
    info = dict((merged.get("seasons") or {}).get(number) or {})
    if (getattr(job, "meta_primary", None) or {}).get("season"):
        return info
    lead = _saved_pref(job, "season", season, "meta")
    if not lead:
        return info
    chain = _metadata_chain(job, "tv", lead=lead, prefer_lead=True)
    picked = {}
    for result in _ordered(results, chain):
        data = (result.get("seasons") or {}).get(number) or {}
        for key, value in data.items():
            if key == "art" or not value:
                continue
            if key == "ids" and isinstance(value, dict):
                bucket = picked.setdefault("ids", {})
                for name, item in value.items():
                    if item and not bucket.get(name):
                        bucket[name] = item
            elif not picked.get(key):
                picked[key] = value
    if not picked:
        return info
    picked["art"] = info.get("art") or []
    return picked


_COLUMN_KEYS = {
    "title": {"title", "season_name"},
    "original_title": {"original_title"},
    "english_title": {"english_title"},
    "sort_title": {"sort_title"},
    "year": {"year"},
    "tagline": {"tagline"},
    "outline": {"plot"},
    "plot": {"plot"},
    "runtime_minutes": {"runtime"},
    "premiered": {"premiered", "release_date", "aired"},
    "aired": {"aired", "premiered"},
    "mpaa": {"mpaa", "certification"},
    "certifications": {"certification"},
    "directors": {"director"},
    "writers": {"credits"},
    "producers": {"crew"},
    "actors": {"actors"},
    "guest_stars": {"actors"},
    "genres": {"genres"},
    "studios": {"studio"},
    "countries": {"country"},
    "tags": {"tags"},
    "languages": {"language"},
    "original_language": {"language"},
    "ratings": {"rating"},
    "top250": {"top250"},
    "trailer": {"trailer"},
    "ids": {"ids", "id_tmdb", "id_imdb", "id_tvdb", "id_trakt", "id_tvmaze", "id_wikidata"},
    "imdb_id": {"ids", "id_imdb"},
    "tmdb_id": {"ids", "id_tmdb"},
    "tvdb_id": {"ids", "id_tvdb"},
    "trakt_id": {"ids", "id_trakt"},
    "anilist_id": {"ids"},
    "ofdb_id": {"ids"},
}
_SEASON_ID_FIELDS = {
    "tmdb": "id_tmdb", "imdb": "id_imdb", "tvdb": "id_tvdb", "trakt": "id_trakt",
    "tvmaze": "id_tvmaze", "wikidata": "id_wikidata",
}
_STORY_KEYS = {"title", "season_name", "plot", "year", "premiered", "aired", "release_date", "tagline", "runtime",
               "original_title", "english_title", "sort_title"}


def _saved_fields(job, level):
    """Fields switched on in Settings. None means this level has no saved list."""
    key = {"movie": "movie_fields", "show": "show_fields", "season": "season_fields", "episode": "episode_fields"}.get(level)
    saved = (getattr(job, "cfg", None) or {}).get(key) if key else None
    if not isinstance(saved, list):
        return None
    return set(saved)


def _meta_on(job, level, key):
    """True when this metadata field is part of the scrape. A dialog choice wins over Settings."""
    if getattr(job, "picks", None) is not None:
        return key in (_chosen(job, level) or set())
    saved = _saved_fields(job, level)
    return saved is None or key in saved


def _column_allowed(chosen, column):
    keys = _COLUMN_KEYS.get(column)
    if not keys:
        return True
    if set(chosen or ()) & keys:
        return True
    return str(column).startswith("rating") and "rating" in chosen


def _parse_picks(fields, art):
    """Turn 'show:plot' choices into per-level field and artwork sets. None keeps the older group list."""
    if fields is None and art is None:
        return None
    picks = {}
    for item in fields or []:
        level, _, key = str(item).partition(":")
        if level and key:
            picks.setdefault(level, {"fields": set(), "art": set()})["fields"].add(key)
    for item in art or []:
        level, _, key = str(item).partition(":")
        if level and key:
            picks.setdefault(level, {"fields": set(), "art": set()})["art"].add(key)
    return picks


def _field_on(chosen, column):
    return bool(set(chosen or ()) & (_COLUMN_KEYS.get(column) or set()))


def _chosen(job, level):
    if job.picks is None:
        return None
    return (job.picks.get(level) or {}).get("fields") or set()


def _wants(job, name, level=None):
    """True when this scrape updates that group. No choice list means everything that was queued."""
    if job.picks is not None:
        levels = [level] if level else list(job.picks)
        if name == "artwork":
            return any((job.picks.get(item) or {}).get("art") for item in levels)
        if name == "set":
            return "set" in (_chosen(job, "movie") or set())
        if name == "ratings":
            return any("rating" in (_chosen(job, item) or set()) for item in levels)
        if name == "trailer":
            return any("trailer" in (_chosen(job, item) or set()) for item in levels)
        if name == "story":
            return any(_STORY_KEYS & (_chosen(job, item) or set()) for item in levels)
        return any(_chosen(job, item) for item in levels)
    if name == "set":
        movie = _saved_fields(job, "movie")
        if movie is not None:
            return "set" in movie
    elif level and name in {"ratings", "trailer", "story"} and not (name == "trailer" and level == "season"):
        saved = _saved_fields(job, level)
        if saved is not None:
            if name == "ratings":
                return "rating" in saved
            if name == "trailer":
                return "trailer" in saved
            return bool(_STORY_KEYS & saved)
    return job.groups is None or name in job.groups


def _writes_metadata(job):
    if job.picks is not None:
        return any((item.get("fields") or set()) for item in job.picks.values())
    return job.groups is None or bool(job.groups & _METADATA_GROUPS)


def _fields(job, names, level="movie"):
    names = [field for field in names if field not in RATING_FIELDS]
    if job.picks is not None:
        chosen = _chosen(job, level) or set()
        allowed = {column for column, keys in _COLUMN_KEYS.items() if chosen & keys}
        if "rating" in chosen:
            allowed.update(field for field in names if field.startswith("rating"))
        if level == "show" and "crew" in chosen:
            allowed.add("directors")
        return [field for field in names if field in allowed]
    if job.groups is None:
        names = list(names)
    else:
        allowed = set()
        for group in job.groups:
            allowed.update(_GROUP_FIELDS.get(group) or ())
        names = [field for field in names if field in allowed]
    saved = _saved_fields(job, level)
    if saved is None:
        return names
    if level == "show" and "crew" in saved:
        saved = set(saved) | {"director"}
    return [field for field in names if _column_allowed(saved, field)]


def _saved_pref(job, level, row, kind):
    """A stored provider. Ignored when this scrape already chose one, or when it left the global chain."""
    if kind == "meta":
        if level in {"movie", "show"} and job.primary:
            return None
        if level not in {"movie", "show"} and (getattr(job, "meta_primary", None) or {}).get(level):
            return None
        saved = str((row or {}).get("preferred_source") or "").strip().lower()
        allowed = {"tmdb", "tvdb", "omdb", "trakt"} if level == "movie" else {"tmdb", "tvdb", "omdb", "trakt"}
        chain_name = "movie_sources" if level == "movie" else "tv_sources"
    else:
        if (getattr(job, "art_primary", None) or {}).get(level):
            return None
        saved = str((row or {}).get("preferred_art") or "").strip().lower()
        allowed = {"fanart", "tmdb", "tvdb"}
        chain_name = "art_sources" if level == "movie" else "tv_art_sources"
    if saved not in allowed:
        return None
    chain = list((getattr(job, "cfg", None) or {}).get(chain_name) or [])
    if not chain and chain_name == "tv_art_sources":
        chain = list(job.cfg.get("art_sources") or [])
    if saved not in chain and not (level == "movie" and saved == "tvdb"):
        return None
    return saved


def _art_sources(job, level, row=None):
    key = "tv_art_sources" if level in {"show", "season", "episode"} else "art_sources"
    chain = job.cfg.get(key)
    if chain is None:
        chain = job.cfg.get("art_sources") or []
    chain = list(chain)
    primary = (job.art_primary or {}).get(level) or _saved_pref(job, level, row, "art")
    if primary and primary in chain:
        chain.remove(primary)
        chain.insert(0, primary)
    elif primary == "tvdb" and level == "movie":
        chain.insert(0, primary)
    return chain


def _kinds_for(job, level, kinds):
    if job.picks is None:
        return kinds or {} if _wants(job, "artwork") else {}
    allowed = set((job.picks.get(level) or {}).get("art") or ())
    found = {}
    for key, enabled in (kinds or {}).items():
        if not enabled:
            continue
        if key in allowed:
            found[key] = enabled
    return found


def _named_season(number, title):
    text = str(title or "").strip()
    if not text:
        return ""
    try:
        number = int(number)
    except (TypeError, ValueError):
        number = None
    generic = set()
    if number == 0:
        generic.update({"specials", "season 0", "series 0"})
    elif number is not None:
        generic.update({f"season {number}", f"season {number:02d}", f"series {number}"})
    if text.lower() in generic:
        return ""
    return text


def _season_ids(job, ids):
    found = {str(key): str(value) for key, value in (ids or {}).items() if value}
    chosen = _chosen(job, "season")
    if chosen is None:
        chosen = _saved_fields(job, "season")
    if chosen is None:
        return found
    keep = {kind for kind, field in _SEASON_ID_FIELDS.items() if field in chosen}
    return {kind: value for kind, value in found.items() if kind in keep}


def _metadata_chain(job, media, lead=None, prefer_lead=False):
    """Source order for one scrape. The chosen primary is asked with the rest and wins ties."""
    chain = list(job.cfg["tv_sources"] if media == "tv" else job.cfg["movie_sources"])
    movie_tvdb = media != "tv"
    primary = job.primary if job.primary in chain or (movie_tvdb and job.primary == "tvdb") else None
    chosen = lead if lead in chain or (movie_tvdb and lead == "tvdb") else None
    head = (chosen if prefer_lead else None) or primary or chosen
    if head and head in chain:
        chain.remove(head)
        chain.insert(0, head)
    elif head == "tvdb" and media != "tv":
        chain.insert(0, head)
    return chain


def _rate(job, changes, row, locked, level="movie"):
    if not _wants(job, "ratings", level):
        return changes
    return _with_rating(changes, row, job.cfg, locked)


def _with_rating(changes, row, cfg, locked):
    ratings = changes.get("ratings", row.get("ratings") or {})
    value, votes = merge.default_rating(ratings, cfg["default_rating"])
    if value is None:
        return changes
    current = float(row["rating"]) if row.get("rating") is not None else None
    if "rating" not in locked and current != value:
        changes["rating"] = value
    if "votes" not in locked and votes and row.get("votes") != votes:
        changes["votes"] = votes
    return changes


def _keyart(candidates):
    extra = [{**item, "kind": "keyart"} for item in candidates if item.get("kind") == "poster" and not item.get("lang")]
    return candidates + extra


_EXTRAS = (("extrafanart", "fanart", "fanart"), ("extrathumbs", "landscape", "thumb"))


def _slim_art(ranked):
    slim = []
    for item in ranked or []:
        url = item.get("url")
        if not url:
            continue
        slim.append({
            "source": item.get("source") or "",
            "kind": item.get("kind") or "",
            "url": url,
            "lang": item.get("lang") or "",
            "width": item.get("width") or 0,
        })
        if len(slim) >= 8:
            break
    return slim


_defer_files_var: contextvars.ContextVar[bool] = contextvars.ContextVar("_defer_files_var", default=False)
_deferred_art_var: contextvars.ContextVar[dict] = contextvars.ContextVar("_deferred_art_var", default=None)


def _defer_active(job):
    return _defer_files_var.get() or getattr(job, "defer_files", False)


def _remember_art(job, candidates, kinds, level, row=None):
    bucket = _deferred_art_var.get()
    if bucket is None:
        bucket = {}
        _deferred_art_var.set(bucket)
    job.deferred_art = bucket
    sources = _art_sources(job, level, row)
    for kind, enabled in (kinds or {}).items():
        if not enabled or kind in {"extrafanart", "extrathumbs"}:
            continue
        ranked = merge.rank_art(
            candidates, kind, lang=job.lang, sources=sources,
            min_width=job.cfg["min_width"].get(kind, 0), langs=job.cfg.get("art_languages"),
        )
        if ranked:
            bucket.setdefault(kind, []).extend(_slim_art(ranked))


def _arm_hold(job, row, kind):
    """A scan match for a title with no id stays in the database until Apply match."""
    bare = False
    if getattr(job, "hold_unmatched", False):
        ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
        if kind == "movie":
            bare = not (row.get("tmdb_id") or ids.get("tmdb"))
        else:
            bare = not (row.get("tmdb_id") or ids.get("tmdb") or row.get("tvdb_id") or ids.get("tvdb"))
    _defer_files_var.set(bool(bare))
    _deferred_art_var.set({})
    job.defer_files = bool(bare)
    job.deferred_art = {}


def _settle_hold(job, table, item_id, title, wrote):
    if _defer_active(job):
        art = _deferred_art_var.get()
        if art is None:
            art = getattr(job, "deferred_art", {}) or {}
        store.save_pending_match(table, item_id, art or {})
        _defer_files_var.set(False)
        _deferred_art_var.set({})
        job.defer_files = False
        job.deferred_art = {}
        job.log(f"{title} is waiting for Apply match")
        job.count("pending")
        return
    if wrote:
        store.clear_pending_match(table, item_id)


def _art_policy(job, level):
    """Set images written while scraping a movie follow the Sets artwork policy."""
    if level == "set" and getattr(job, "media", "") != "sets":
        return config.policy_for(job.cfg, "sets", "artwork")
    return getattr(job, "art_policy", None) or job.policy


def _meta_policy(job, level):
    if level == "set" and getattr(job, "media", "") != "sets":
        return config.policy_for(job.cfg, "sets", "metadata")
    return getattr(job, "meta_policy", None) or job.policy


def _nfo_policy(job, level=None):
    """Rewrite replaces an existing .nfo. Off leaves an existing file and still writes one that is missing."""
    flag = getattr(job, "rewrite_nfo", None)
    if flag is True:
        return "overwrite"
    if flag is False:
        return "missing"
    if level == "set":
        return _meta_policy(job, "set")
    return getattr(job, "meta_policy", None) or job.policy


async def _extra_art(job, client, folder, candidates, kinds, level="movie", row=None):
    if _defer_active(job):
        _remember_art(job, candidates, kinds, level, row)
        return
    """Extra backdrops and thumbs go in extrafanart/ and extrathumbs/ inside the movie or show folder."""
    kinds = _kinds_for(job, level, kinds)
    if not kinds or not job.cfg["download_artwork"] or not folder:
        return
    sources = _art_sources(job, level, row)
    for flag, kind, prefix in _EXTRAS:
        if not kinds.get(flag) or job.cancelled:
            continue
        ranked = merge.rank_art(candidates, kind, lang=job.lang, sources=sources,
                                min_width=job.cfg["min_width"].get(kind, 0), langs=job.cfg.get("art_languages"))
        # The main fanart file is separate. Extra fanart and extra thumbs each have their own count.
        limit = job.cfg.get("extrafanart_count") or 10 if flag == "extrafanart" else (job.cfg.get("extra_art_count") or 10)
        saved = await art_fetch.extras(
            client, ranked[1:], os.path.join(folder, flag), prefix, kind, _art_policy(job, level), limit,
        )
        job.count("art", len(saved))


async def _art(job, client, kinds, candidates, existing, base_for, level="movie", row=None):
    """Fetch every enabled kind. Returns the updated kind->path map."""
    if _defer_active(job):
        _remember_art(job, candidates, kinds, level, row)
        return existing
    kinds = _kinds_for(job, level, kinds)
    if not kinds or not job.cfg["download_artwork"]:
        return existing
    sources = _art_sources(job, level, row)
    current = dict(existing or {})
    for kind, enabled in kinds.items():
        if not enabled or job.cancelled or kind in {"extrafanart", "extrathumbs"}:
            continue
        ranked = merge.rank_art(candidates, kind, lang=job.lang, sources=sources,
                                min_width=job.cfg["min_width"].get(kind, 0), langs=job.cfg.get("art_languages"))
        if not ranked:
            continue
        path = await art_fetch.fetch(client, ranked, base_for(kind), kind, current.get(kind), _art_policy(job, level))
        if path:
            current[kind] = path
            job.count("art")
    return current


async def _stacked_discarts(job, client, folder, stem, parts, art, row=None):
    if _defer_active(job):
        return
    """part1 and part2 share one movie. Extra disc images become filename-discart1.png and discart2.png."""
    if not _wants(job, "artwork", "movie") or len(parts or []) < 2 or not stem or not folder:
        return
    if not (job.cfg.get("movie_art") or {}).get("discart"):
        return
    if job.picks is not None and "discart" not in ((job.picks.get("movie") or {}).get("art") or set()):
        return
    ranked = merge.rank_art(art or [], "discart", lang=job.lang, sources=_art_sources(job, "movie", row),
                            min_width=job.cfg["min_width"].get("discart", 0), langs=job.cfg.get("art_languages"))
    if len(ranked) < 2:
        return
    for index, candidate in enumerate(ranked[: len(parts)], start=1):
        base = os.path.join(folder, f"{stem}-discart{index}")
        existing = art_fetch._existing_named(folder, f"{stem}-discart{index}")
        path = await art_fetch.fetch(client, [candidate], base, "discart", existing, job.art_policy, tries=1)
        if path:
            job.count("art")


async def _write_nfo(job, writer, *args):
    if _defer_active(job) or not job.cfg["write_nfo"]:
        return
    try:
        written = await asyncio.to_thread(writer, *args, job.cfg, _nfo_policy(job))
    except Exception as exc:
        job.log(f"Could not write .nfo: {exc}")
        return
    if isinstance(written, list):
        job.count("nfo", len(written))
    elif written:
        job.count("nfo")


# Movies.

async def _scan_trailer(job, kind, item_id):
    """Download this item's YouTube trailer during a scan lookup. Other titles keep going."""
    if _defer_active(job) or not getattr(job, "scan_trailers", False) or job.art_only or job.cancelled or not item_id:
        return
    from curator.video import trailers
    from resonance.errors import AppError

    try:
        path = await asyncio.to_thread(trailers.download, kind, str(item_id), job.cfg, job.log, True)
    except AppError as exc:
        job.log(str(exc))
        job.count("trailer_failed")
        return
    if path:
        job.count("trailers")


async def _tvdb_movie(tvdb, ids, title, year):
    ident = await tvdb.movie_id(ids, title, year)
    if not ident:
        return None
    return await tvdb.movie(ident)


_SOURCE_NAMES = {"trakt": "Trakt", "tvdb": "TheTVDB", "omdb": "OMDb", "tmdb": "TMDB"}


async def _movie(job, client, found, movie_id):
    row = await asyncio.to_thread(store.movie_row, movie_id)
    if not row or row.get("locked") or row.get("status") == "IGNORED":
        job.count("skipped")
        return row["title"] if row else movie_id
    title = f"{row['title']} ({row['year']})" if row.get("year") else row["title"]
    if str(row.get("path") or "").startswith("wanted://"):
        job.log(f"{title} is wanted and has no folder yet")
        job.count("skipped")
        return title
    _arm_hold(job, row, "movie")
    job.log(f"Looking up {title}" if not job.art_only else f"Looking up artwork for {title}")
    tmdb = found["tmdb"]
    language = str(row.get("scrape_language") or "").strip()
    if language:
        tmdb = tmdb.for_language(language)
    ids = _ids(row)
    saved = _saved_pref(job, "movie", row, "meta")
    if saved:
        chain = _metadata_chain(job, "movies", lead=saved, prefer_lead=True)
    else:
        chain = _metadata_chain(job, "movies")
    lead = chain[0] if chain else "tmdb"
    trakt = found.get("trakt") or (TraktRatings(client, trakt_auth.client_id()) if trakt_auth.client_id() else None)
    alt_base, alt_source = None, ""

    async def from_source(name):
        """The movie described by one other provider, in the shape TMDB returns."""
        try:
            if name == "trakt" and trakt and (ids.get("trakt") or ids.get("imdb")):
                return await asyncio.wait_for(trakt.movie_base(ids), timeout=30.0)
            if name == "tvdb" and found.get("tvdb"):
                return await asyncio.wait_for(_tvdb_movie(found["tvdb"], ids, row["title"], row.get("year")), timeout=30.0)
            if name == "omdb" and found.get("omdb") and ids.get("imdb"):
                return await asyncio.wait_for(found["omdb"].movie_base(ids), timeout=30.0)
        except Exception as exc:
            job.log(f"{_SOURCE_NAMES.get(name, name)}: {exc}")
        return None

    # Trakt or TheTVDB chosen as the source: ask it first. TMDB then only fills in what it lacks.
    if lead in ("trakt", "tvdb", "omdb"):
        alt_base = await from_source(lead)
        if alt_base:
            alt_source = lead
            job.log(f"{_SOURCE_NAMES[lead]}: succeeded")
            ids = {**ids, **{k: v for k, v in alt_base["ids"].items() if k != "tmdb"}}
            if alt_base["ids"].get("tmdb") and not ids.get("tmdb"):
                ids["tmdb"] = alt_base["ids"]["tmdb"]
    tmdb_base = None
    try:
        tmdb_id = await asyncio.wait_for(tmdb.movie_id(ids, row["title"], row.get("year")), timeout=20.0)
        tmdb_base = await asyncio.wait_for(tmdb.movie(tmdb_id), timeout=20.0) if tmdb_id else None
        if tmdb_base:
            job.log(f"TMDB: succeeded (id {tmdb_id})")
        elif tmdb_id:
            job.log(f"TMDB: movie details not found for id {tmdb_id}")
        else:
            job.log(f"TMDB: no match found for {row['title']}")
    except asyncio.TimeoutError:
        job.log("TMDB: lookup timed out after 20s")
    except ScrapeError as exc:
        job.log(f"TMDB: {exc}")
    except Exception as exc:
        job.log(f"TMDB: {exc}")
    if not tmdb_base:
        ids.pop("tmdb", None)                  # TMDB does not have it, so that id is not usable
        if alt_base:
            alt_base["ids"].pop("tmdb", None)
            job.log(f"TMDB has no entry for this movie. Using the metadata from {_SOURCE_NAMES[alt_source]}.")
        elif lead == "tmdb":
            # TMDB was asked first and has nothing; another provider can still describe the movie.
            for name in ("trakt", "tvdb", "omdb"):
                alt_base = await from_source(name)
                if alt_base:
                    alt_source = name
                    alt_base["ids"].pop("tmdb", None)
                    ids = {**ids, **alt_base["ids"]}
                    job.log(f"TMDB has no entry for this movie. Using the metadata from {_SOURCE_NAMES[name]}.")
                    break
    base = tmdb_base or alt_base
    if not base:
        raise ScrapeError("No confident TMDB match. Use Fix Match to pick one.")
    main = alt_base if (lead in ("trakt", "tvdb", "omdb") and alt_base) else base
    ids = {**ids, **(alt_base or {}).get("ids", {}), **(tmdb_base or {}).get("ids", {})}
    art_choice = (getattr(job, "art_primary", None) or {}).get("movie") or _saved_pref(job, "movie", row, "art")
    tasks = {}
    if "omdb" in found and alt_source != "omdb":
        if ids.get("imdb"):
            # One request returns the ratings and the English movie fields; TMDB wins where it has a value.
            tasks["omdb"] = _quiet(job, "OMDb", found["omdb"].movie_base(ids))
        else:
            job.log("OMDb: skipped (no IMDb id)")
    if "tvdb" in found and alt_source != "tvdb" and ("tvdb" in chain or art_choice == "tvdb"):
        tasks["tvdb"] = _quiet(job, "TheTVDB", _tvdb_movie(found["tvdb"], ids, row["title"], row.get("year")))
    if "trakt" in found and alt_source != "trakt":
        tasks["trakt"] = _quiet(job, "Trakt", found["trakt"].movie(ids))
    if "fanart" in found:
        if ids.get("tmdb") or ids.get("imdb"):
            tasks["fanart"] = _quiet(job, "Fanart.tv", found["fanart"].movie(ids))
        else:
            job.log("Fanart.tv: skipped (no TMDB or IMDb id)")
    _score_tasks(tasks, job, found, "movie", row["title"], row.get("year"))
    if tmdb_base and tmdb_base.get("set") and tmdb_base["set"].get("tmdb_id"):
        tasks["set"] = _quiet(job, "TMDB collection",
                              tmdb.collection(tmdb_base["set"]["tmdb_id"], images=bool(job.cfg["set_folder"])))
    answers = dict(zip(tasks, await asyncio.gather(*tasks.values())))
    results = [item for item in (tmdb_base, alt_base) if item]
    if answers.get("omdb"):
        results.append(answers["omdb"])
    if answers.get("tvdb"):
        results.append(answers["tvdb"])
    if answers.get("trakt"):
        payload = answers["trakt"] or {}
        results.append({"source": "trakt", "ratings": payload.get("ratings") or {}, "ids": payload.get("ids") or {}})
    for name in ("rottentomatoes", "metacritic", "anilist", "ofdb"):
        if answers.get(name):
            results.append(answers[name])
    if answers.get("fanart"):
        results.append({"source": "fanart", "art": answers["fanart"]})
    merged = merge.combine(_ordered(results, chain))
    locked_tmdb = ((tmdb_base or {}).get("ids") or {}).get("tmdb")
    if locked_tmdb:
        merged.setdefault("ids", {})
        merged["ids"]["tmdb"] = locked_tmdb
    if merged.get("actors") and "actors" not in set(row.get("locked_fields") or []) and _meta_on(job, "movie", "actors") and not _defer_active(job):
        merged["actors"] = await actor_art.store_thumbs(client, row["folder"], merged["actors"])
    if not job.cfg["keywords_as_tags"]:
        merged.pop("tags", None)
    merged["imdb_id"] = merged.get("ids", {}).get("imdb")
    merged["tmdb_id"] = merged.get("ids", {}).get("tmdb")
    for key, column in (("anilist", "anilist_id"), ("ofdb", "ofdb_id"), ("trakt", "trakt_id")):
        if merged.get("ids", {}).get(key):
            merged[column] = merged["ids"][key]
    own = row["path"] == row["folder"]
    parts = row.get("parts") or []
    stem = naming.movie_art_stem(parts)

    def base_for(kind):
        if len(parts) > 1 and stem:
            return os.path.join(row["folder"], f"{stem}-{kind}")
        return os.path.join(row["folder"], kind if own or not stem else f"{stem}-{kind}")

    if job.art_only:
        art = await _art(job, client, job.cfg["movie_art"], _keyart(merged["art"]), row.get("artwork"), base_for, row=row)
        await _stacked_discarts(job, client, row["folder"], stem, parts, merged.get("art"), row)
        await _extra_art(job, client, row["folder"], merged["art"], job.cfg["movie_art"], row=row)
        if art != (row.get("artwork") or {}):
            await asyncio.to_thread(store.set_artwork, "movies", movie_id, art)
        job.count("scraped")
        job.log(f"Artwork for {title}")
        _settle_hold(job, "movies", movie_id, title, True)
        return title
    locked = set(row.get("locked_fields") or [])
    fields = _fields(job, store.MOVIE_FIELDS)
    changes = merge.updates(row, merged, fields, job.policy, locked)
    changes = _rate(job, changes, row, locked)
    if _writes_metadata(job) and (changes or job.groups is None):
        if not await asyncio.to_thread(store.apply_fields, "movies", movie_id, changes, source=main.get("source") or "tmdb"):
            job.count("skipped")
            _settle_hold(job, "movies", movie_id, title, False)
            return title
    collection = answers.get("set") or (tmdb_base or {}).get("set")
    set_id = row.get("set_id")
    if _wants(job, "set") and collection and "set" not in locked and (job.policy == "overwrite" or not set_id):
        set_id = await asyncio.to_thread(store.link_set, movie_id, collection)
    if set_id:
        await _set_sync(job, client, found, str(set_id), collection if collection and "parts" in collection else None)
    art = await _art(job, client, job.cfg["movie_art"], _keyart(merged["art"]), row.get("artwork"), base_for, row=row)
    await _stacked_discarts(job, client, row["folder"], stem, parts, merged.get("art"), row)
    await _extra_art(job, client, row["folder"], merged["art"], job.cfg["movie_art"], row=row)
    if art != (row.get("artwork") or {}):
        await asyncio.to_thread(store.set_artwork, "movies", movie_id, art)
    if _writes_metadata(job):
        await _write_nfo(job, exports.write_movie, movie_id)
    await _scan_trailer(job, "movie", movie_id)
    job.count("scraped")
    job.log(f"Scraped {title}")
    _settle_hold(job, "movies", movie_id, title, True)
    return title


# Movie sets.

async def _set_sync(job, client, found, set_id, collection=None):
    """Collection overview and parts, then artwork and set.nfo in <set folder>/<set name>/.
    Runs once per set in a job."""
    if set_id in job.sets_done:
        return
    job.sets_done.add(set_id)
    row = await asyncio.to_thread(store.set_row, set_id)
    if not row:
        return
    collection_id = row.get("tmdb_collection_id") or (collection or {}).get("tmdb_id")
    want_art = bool(job.cfg["set_folder"])
    if collection_id and "tmdb" in found and (collection is None or (want_art and "art" not in collection)):
        collection = await _quiet(job, "TMDB collection", found["tmdb"].collection(collection_id, images=want_art))
    if collection:
        if _wants(job, "story"):
            await asyncio.to_thread(store.save_set_meta, set_id, collection.get("overview"), collection.get("tmdb_id"))
            row["overview"] = collection.get("overview") or row.get("overview")
            row["tmdb_collection_id"] = row.get("tmdb_collection_id") or collection.get("tmdb_id")
        if collection.get("parts"):
            await asyncio.to_thread(store.save_set_parts, set_id, collection["parts"])
    if want_art and _wants(job, "artwork"):
        await _set_art(job, client, found, row, collection, collection_id)


async def _set_art(job, client, found, row, collection, collection_id):
    set_id = str(row["id"])
    folder = sets.folder_for(job.cfg["set_folder"], row["name"])
    try:
        await asyncio.to_thread(writes.ensure_dir, folder)
    except (AppError, OSError) as exc:
        job.log(f"Set {row['name']}: cannot use {folder}: {exc}")
        await asyncio.to_thread(store.save_set_art, set_id, row.get("artwork") or {}, None, None, str(exc))
        return
    candidates = list((collection or {}).get("art") or [])
    if "fanart" in found and collection_id:
        candidates += await _quiet(job, "Fanart.tv set art", found["fanart"].collection(collection_id)) or []
    candidates = _keyart(candidates)
    existing = {**(row.get("artwork") or {}), **await asyncio.to_thread(sets.local_art, folder)}
    art = await _art(job, client, job.cfg["set_art"], candidates, existing, lambda kind: os.path.join(folder, kind), level="set")
    nfo_path = None
    if job.cfg["write_nfo"] and job.cfg["set_nfo"]:
        target = os.path.join(folder, sets.NFO_NAME)
        try:
            written, _ = await asyncio.to_thread(nfo_write.write, target, nfo_write.set_xml(row),
                                                 policy=_nfo_policy(job, "set"), backup=job.cfg["nfo_backup"])
            nfo_path = target
            if written:
                job.count("nfo")
                stamped = dict(row)
                stamped["nfo_path"] = target
                await asyncio.to_thread(store._stamp_nfo, "movie_sets", set_id, stamped)
        except (AppError, OSError) as exc:
            job.log(f"Set {row['name']}: could not write {sets.NFO_NAME}: {exc}")
    await asyncio.to_thread(store.save_set_art, set_id, art, folder, nfo_path)
    job.log(f"Set {row['name']}: {len(art)} images in {folder}")


async def _set_item(job, client, found, set_id):
    name = await asyncio.to_thread(store.title_of, "movie_sets", set_id)
    await _set_sync(job, client, found, set_id)
    job.count("scraped")
    return name


# TV.

async def _show(job, client, found, show_id):
    show, seasons, episodes = await asyncio.to_thread(store.show_rows, show_id)
    if not show or show.get("locked") or show.get("status") == "IGNORED":
        job.count("skipped")
        return show["title"] if show else show_id
    only = job.only_episode_ids
    if only:
        episodes = [item for item in episodes if str(item["id"]) in only]
        if not episodes:
            job.count("skipped")
            return show["title"]
        kept = {item["season_number"] for item in episodes}
        seasons = [item for item in seasons if item["season_number"] in kept]
    limits = (getattr(job, "only_seasons", None) or {}).get(str(show["id"]))
    if limits:
        seasons = [item for item in seasons if int(item["season_number"]) in limits]
        episodes = [item for item in episodes if int(item["season_number"]) in limits]
        if not seasons:
            job.count("skipped")
            return show["title"]
    title = f"{show['title']} ({show['year']})" if show.get("year") else show["title"]
    if str(show.get("path") or "").startswith("wanted://"):
        job.log(f"{title} is wanted and has no folder yet")
        job.count("skipped")
        return title
    _arm_hold(job, show, "show")
    job.log(f"Looking up {title}" if not job.art_only else f"Looking up artwork for {title}")
    order = show.get("episode_order") or job.cfg["episode_order"]
    tmdb, tvdb = found.get("tmdb"), found.get("tvdb")
    language = str(show.get("scrape_language") or "").strip()
    if language:
        if tmdb:
            tmdb = tmdb.for_language(language)
        if tvdb:
            tvdb = tvdb.for_language(language)
    ids = _ids(show)
    base_tmdb = base_tvdb = None
    if tmdb:
        try:
            tmdb_id = await asyncio.wait_for(tmdb.tv_id(ids, show["title"], show.get("year")), timeout=20.0)
            base_tmdb = await asyncio.wait_for(tmdb.tv(tmdb_id), timeout=20.0) if tmdb_id else None
            if base_tmdb:
                job.log(f"TMDB: succeeded (id {tmdb_id})")
                ids = {**base_tmdb["ids"], **ids} if job.policy != "overwrite" else {**ids, **base_tmdb["ids"]}
            elif tmdb_id:
                job.log(f"TMDB: show details not found for id {tmdb_id}")
            else:
                job.log("TMDB: no match found")
        except asyncio.TimeoutError:
            job.log("TMDB: lookup timed out after 20s")
        except ScrapeError as exc:
            job.log(f"TMDB: {exc}")
        except Exception as exc:
            job.log(f"TMDB: {exc}")
    if tvdb:
        try:
            tvdb_id = await asyncio.wait_for(tvdb.tv_id(ids, show["title"], show.get("year")), timeout=20.0)
            base_tvdb = await asyncio.wait_for(tvdb.series(tvdb_id), timeout=20.0) if tvdb_id else None
            if base_tvdb:
                job.log(f"TVDB: succeeded (id {tvdb_id})")
                ids = {**ids, **{key: value for key, value in base_tvdb["ids"].items() if key not in ids}}
            elif tvdb_id:
                job.log(f"TVDB: series details not found for id {tvdb_id}")
            else:
                job.log("TVDB: no match found")
        except asyncio.TimeoutError:
            job.log("TVDB: lookup timed out after 20s")
        except ScrapeError as exc:
            job.log(f"TVDB: {exc}")
        except Exception as exc:
            job.log(f"TVDB: {exc}")
    base_trakt = None
    if not base_tmdb and not base_tvdb:
        trakt = found.get("trakt") or (TraktRatings(client, trakt_auth.client_id()) if trakt_auth.client_id() else None)
        if trakt and (ids.get("trakt") or ids.get("imdb")):
            try:
                base_trakt = await asyncio.wait_for(trakt.show_base(ids), timeout=30.0)
            except Exception as exc:
                job.log(f"Trakt: {exc}")
        if not base_trakt:
            raise ScrapeError("No confident match on TMDB or TVDB. Use Fix Match to pick one.")
        job.log("TMDB and TVDB have no entry for this show. Using the show metadata from Trakt "
                "(seasons and episodes keep what is already stored).")
        ids = {**ids, **{k: v for k, v in base_trakt["ids"].items() if k != "tmdb"}}
    saved_meta = _saved_pref(job, "show", show, "meta")
    if job.primary in ("tmdb", "tvdb"):
        preferred = job.primary
    elif saved_meta in ("tmdb", "tvdb"):
        preferred = saved_meta
    else:
        preferred = job.cfg["tv_primary"]
    primary = "tvdb" if base_tvdb and preferred == "tvdb" else "tmdb"
    if not base_tmdb:
        primary = "tvdb"
    tasks = {}
    if "omdb" in found:
        if ids.get("imdb"):
            tasks["omdb"] = _quiet(job, "OMDb", found["omdb"].ratings(ids["imdb"]))
        else:
            job.log("OMDb: skipped (no IMDb id)")
    if "trakt" in found and not base_trakt:
        tasks["trakt"] = _quiet(job, "Trakt", found["trakt"].show_details(ids))
    if "fanart" in found:
        if ids.get("tvdb"):
            tasks["fanart"] = _quiet(job, "Fanart.tv", found["fanart"].tv(ids))
        else:
            job.log("Fanart.tv: skipped (no TVDB id)")
    _score_tasks(tasks, job, found, "tv", show["title"], show.get("year"))
    numbers = sorted({season["season_number"] for season in seasons})
    if base_tmdb:
        for number in numbers:
            if order == "aired":
                tasks[f"season{number}"] = _quiet(job, f"TMDB season {number}", tmdb.season(base_tmdb["ids"]["tmdb"], number), log_success=False)
            else:
                tasks[f"seasonart{number}"] = _quiet(
                    job, f"TMDB season {number} posters", tmdb.season_images(base_tmdb["ids"]["tmdb"], number), log_success=False
                )
    if base_tmdb and order != "aired" and primary == "tmdb":
        tasks["groups"] = _quiet(job, f"TMDB {order} order", tmdb.episode_group(base_tmdb["ids"]["tmdb"], order), log_success=False)
    if base_tvdb and (primary == "tvdb" or not base_tmdb or order != "aired"):
        tasks["episodes"] = _quiet(job, "TVDB episodes", tvdb.episodes(base_tvdb["ids"]["tvdb"], order))
    if "tvmaze" in found:
        tasks["tvmaze"] = _quiet(job, "TVMaze", found["tvmaze"].show(ids, show["title"], show.get("year")))
    answers = dict(zip(tasks, await asyncio.gather(*tasks.values())))
    if getattr(job, "missing_only", False):
        if job.only_season_numbers:
            seasons = [item for item in seasons if int(item["season_number"]) in job.only_season_numbers]
        await _fill_missing_episodes(job, client, show, seasons, episodes, answers, order, primary)
        job.count("scraped")
        _settle_hold(job, "tv_shows", show_id, title, False)
        return title
    if order != "aired" and not answers.get("groups") and not answers.get("episodes"):
        job.log(f"{title}: TMDB has no {order} episode group for this show and no TheTVDB key is set, "
                "so episode details were skipped. Use aired order or add a TheTVDB key.")
    if job.primary:
        chain = _metadata_chain(job, "tv", lead=primary)
    elif saved_meta:
        chain = _metadata_chain(job, "tv", lead=saved_meta, prefer_lead=True)
    else:
        chain = _metadata_chain(job, "tv", lead=primary)
    results = [base_tmdb, base_tvdb, base_trakt]
    if answers.get("omdb"):
        results.append(dict(answers["omdb"]))
    if answers.get("trakt"):
        results.append({**(answers["trakt"] or {}), "source": "trakt"})
    for name in ("rottentomatoes", "metacritic", "anilist", "ofdb"):
        if answers.get(name):
            results.append(answers[name])
    fanart_seasons = {}
    if answers.get("fanart"):
        fanart_show, fanart_seasons = answers["fanart"]
        results.append({"source": "fanart", "art": fanart_show})
    if answers.get("tvmaze"):
        results.append(answers["tvmaze"])
        answers["tvmaze_episodes"] = answers["tvmaze"].get("episodes") or {}
    merged = _prefer_season_source(job, merge.combine(_ordered(results, chain)), results)
    merged["ids"] = {**merged.get("ids", {}), **ids}
    for kind in ("imdb", "tmdb", "tvdb", "anilist", "ofdb", "trakt"):
        merged[f"{kind}_id"] = merged["ids"].get(kind)
    if not job.cfg["keywords_as_tags"]:
        merged.pop("tags", None)
    for number, art in fanart_seasons.items():
        merged["seasons"].setdefault(number, {"art": []})["art"].extend(art)
    for number in numbers:
        season_info = answers.get(f"season{number}") or answers.get(f"seasonart{number}")
        if season_info:
            target = merged["seasons"].setdefault(number, {"art": []})
            target["art"].extend(season_info.get("art") or [])
            for key in ("title", "plot", "premiered", "trailer", "sort_title", "episode_count", "episode_numbers"):
                if season_info.get(key) and not target.get(key):
                    target[key] = season_info[key]
            if season_info.get("ids"):
                bucket = target.setdefault("ids", {})
                for name, value in season_info["ids"].items():
                    if value and not bucket.get(name):
                        bucket[name] = value
    if job.only_episode_ids:
        await _episodes(job, client, show, episodes, answers, order, primary)
        if not job.art_only and job.cfg["write_nfo"] and _writes_metadata(job) and not _defer_active(job):
            written = await asyncio.to_thread(
                exports.write_show, show_id, job.cfg, _nfo_policy(job),
                [str(item["id"]) for item in episodes], True,
            )
            if written:
                job.count("nfo", len(written))
        names = ", ".join(
            f"S{int(item['season_number']):02d}E{int(item['episode_number']):02d}" for item in episodes
        )
        job.count("scraped")
        job.log(f"Scraped {title}: {names}")
        _settle_hold(job, "tv_shows", show_id, title, True)
        return title
    if job.art_only:
        folder = show["path"]
        art = await _art(job, client, job.cfg["tv_art"], merged.get("art") or [], show.get("artwork"),
                         lambda kind: os.path.join(folder, kind), level="show", row=show)
        await _extra_art(job, client, folder, merged.get("art") or [], job.cfg["tv_art"], level="show", row=show)
        if art != (show.get("artwork") or {}):
            await asyncio.to_thread(store.set_artwork, "tv_shows", show_id, art)
        for season in seasons:
            if season.get("locked") or season.get("status") == "IGNORED":
                continue
            with activity.holding() as hold:
                hold(season["id"], show_id)
                number = season["season_number"]
                info = _season_fields(job, merged, results, season)
                label = "specials" if number == 0 else f"{number:02d}"
                season_art = await _art(job, client, job.cfg["season_art"], info.get("art") or [], season.get("artwork"),
                                        lambda kind, label=label: os.path.join(folder, f"season{label}-{kind}"),
                                        level="season", row=season)
                if season_art != (season.get("artwork") or {}):
                    await asyncio.to_thread(store.set_artwork, "tv_seasons", season["id"], season_art)
        await _episodes(job, client, show, episodes, answers, order, primary)
        await _fill_missing_episodes(job, client, show, seasons, episodes, answers, order, primary)
        job.count("scraped")
        job.log(f"Artwork for {title}")
        _settle_hold(job, "tv_shows", show_id, title, True)
        return title
    folder = show["path"]
    if not getattr(job, "only_seasons", None):
        if merged.get("actors") and "actors" not in set(show.get("locked_fields") or []) and _meta_on(job, "show", "actors") and not _defer_active(job):
            merged["actors"] = await actor_art.store_thumbs(client, show["path"], merged["actors"])
        locked = set(show.get("locked_fields") or [])
        fields = _fields(job, store.SHOW_FIELDS, "show")
        changes = merge.updates(show, merged, fields, job.policy, locked)
        changes = _rate(job, changes, show, locked, "show")
        if job.picks is None:
            write_show = _writes_metadata(job) and (changes or job.groups is None)
        else:
            write_show = bool(changes) and bool(_chosen(job, "show"))
        if write_show:
            if not await asyncio.to_thread(store.apply_fields, "tv_shows", show_id, changes, source="trakt" if base_trakt else primary):
                job.count("skipped")
                _settle_hold(job, "tv_shows", show_id, title, False)
                return title
        art = await _art(job, client, job.cfg["tv_art"], merged["art"], show.get("artwork"),
                         lambda kind: os.path.join(folder, kind), level="show", row=show)
        await _extra_art(job, client, folder, merged["art"], job.cfg["tv_art"], level="show", row=show)
        if art != (show.get("artwork") or {}):
            await asyncio.to_thread(store.set_artwork, "tv_shows", show_id, art)
    for season in seasons:
        if season.get("locked") or season.get("status") == "IGNORED":
            continue
        with activity.holding() as hold:
            hold(season["id"], show_id)
            number = season["season_number"]
            info = _season_fields(job, merged, results, season)
            chosen = _chosen(job, "season")
            if chosen is None:
                saved = _saved_fields(job, "season")
                if saved is not None:
                    chosen = set(saved)
                    if job.groups is None or "trailer" in (job.groups or ()):
                        chosen.add("trailer")
            if chosen is None:
                story_keys = ("title", "plot", "premiered") if _wants(job, "story", "season") else ()
            else:
                story_keys = tuple(key for key in ("title", "plot", "premiered", "sort_title") if _field_on(chosen, key))
            trailer_keys = ("trailer",) if (chosen is None and _wants(job, "trailer", "season")) or (chosen is not None and "trailer" in chosen) else ()
            locked = set(season.get("locked_fields") or [])
            meta = {key: info[key] for key in story_keys + trailer_keys
                    if key not in locked and info.get(key) and (job.policy == "overwrite" or not season.get(key))}
            premiered = meta.get("premiered") or season.get("premiered") or ""
            want_year = "year" not in locked and (chosen is None or "year" in chosen)
            if want_year and premiered and str(premiered)[:4].isdigit() and (job.policy == "overwrite" or not season.get("year")):
                meta["year"] = int(str(premiered)[:4])
            ids = _season_ids(job, info.get("ids"))
            if ids and (job.policy == "overwrite" or not (season.get("ids") or {})):
                meta["ids"] = ids
            if info.get("episode_count"):
                meta["tmdb_episode_count"] = info["episode_count"]
            if info.get("episode_numbers"):
                meta["tmdb_episode_numbers"] = info["episode_numbers"]
            if meta:
                await asyncio.to_thread(store.save_season_meta, season["id"], meta)
            if (chosen is None or "season_name" in chosen) and "season_name" not in set(season.get("locked_fields") or []):
                name = _named_season(number, info.get("title") or meta.get("title") or season.get("title"))
                if name:
                    await asyncio.to_thread(store.merge_season_name, show_id, number, name)
            await _scan_trailer(job, "season", season.get("id"))
            label = "specials" if number == 0 else f"{number:02d}"
            season_art = await _art(job, client, job.cfg["season_art"], info.get("art") or [], season.get("artwork"),
                                    lambda kind, label=label: os.path.join(folder, f"season{label}-{kind}"),
                                    level="season", row=season)
            if season_art != (season.get("artwork") or {}):
                await asyncio.to_thread(store.set_artwork, "tv_seasons", season["id"], season_art)
    await _episodes(job, client, show, episodes, answers, order, primary)
    await _fill_missing_episodes(job, client, show, seasons, episodes, answers, order, primary)
    if getattr(job, "only_seasons", None):
        if not job.art_only and job.cfg["write_nfo"] and _writes_metadata(job) and not _defer_active(job):
            for season in seasons:
                path = await asyncio.to_thread(exports.write_season, season["id"], job.cfg, _nfo_policy(job))
                if path:
                    job.count("nfo")
            written = await asyncio.to_thread(
                exports.write_show, show_id, job.cfg, _nfo_policy(job),
                [str(item["id"]) for item in episodes], True,
            )
            if written:
                job.count("nfo", len(written))
        names = ", ".join(f"season {int(item['season_number'])}" if int(item["season_number"]) else "specials" for item in seasons)
        await _scan_trailer(job, "show", show_id)
        job.count("scraped")
        job.log(f"Scraped {title}: {names}")
        _settle_hold(job, "tv_shows", show_id, title, True)
        return title
    if _writes_metadata(job):
        await _write_nfo(job, exports.write_show, show_id)
    await _scan_trailer(job, "show", show_id)
    job.count("scraped")
    job.log(f"Scraped {title}")
    _settle_hold(job, "tv_shows", show_id, title, True)
    return title


async def _episodes(job, client, show, episodes, answers, order, primary):
    thumbs = {"thumb": job.cfg["episode_thumbs"]}
    total = len(episodes)
    for index, episode in enumerate(episodes, start=1):
        if index == 1 or index == total or index % 25 == 0:
            job.log(f"{show.get('title') or 'Show'}: episode {index}/{total}")
        if job.cancelled:
            return
        if episode.get("locked") or episode.get("status") == "IGNORED":
            continue
        with activity.holding() as hold:
            hold(episode.get("id"), show.get("id"), episode.get("season_id"))
            await _scrape_one_episode(job, client, show, episode, episodes, answers, order, primary, thumbs)
    await asyncio.to_thread(_retire_shared_thumbs, episodes)


def _retire_shared_thumbs(episodes):
    """Drop <video>-thumb once every episode in that file has its own <video>-SxxEyy-thumb."""
    groups = {}
    for episode in episodes or []:
        path = episode.get("path") or ""
        if path:
            groups.setdefault(path, []).append(episode)
    for path, group in groups.items():
        if len(group) < 2:
            continue
        folder = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        marks = [
            f"{stem}-{naming.episode_mark(item.get('season_number'), item.get('episode_number'))}-thumb"
            for item in group
        ]
        if not all(art_fetch._existing_named(folder, mark) for mark in marks):
            continue
        shared = art_fetch._existing_named(folder, f"{stem}-thumb")
        if not shared:
            continue
        try:
            os.remove(shared)
        except OSError:
            pass


async def _episode_certificate(job, client, show, episode):
    """OMDb's Rated line for one episode. A whole-show scrape leaves this to the show rating."""
    if job.media != "episodes" or not job.cfg.get("omdb_key"):
        return None
    imdb = (show.get("ids") or {}).get("imdb") or show.get("imdb_id")
    if not imdb:
        return None
    data = await _quiet(
        job, "OMDb",
        Omdb(client, job.cfg["omdb_key"]).episode_ratings(imdb, episode.get("season_number"), episode.get("episode_number")),
        log_success=False,
    )
    if not data:
        return None
    certificate = data.get("mpaa") or data.get("mpaa_fallback")
    if not certificate:
        return None
    return {"source": "omdb", "mpaa": certificate, "ratings": data.get("ratings") or {}}


async def _episode_language(job, client, show, episode):
    """One episode can use a different scrape language than the show."""
    override = str(episode.get("scrape_language") or "").strip()
    if not override:
        return None
    show_lang = str(show.get("scrape_language") or "").strip() or job.cfg["language"]
    if override == show_lang:
        return None
    tmdb_id = (show.get("ids") or {}).get("tmdb") or show.get("tmdb_id")
    if not tmdb_id or not job.cfg.get("tmdb_key"):
        return None
    local = Tmdb(client, job.cfg["tmdb_key"], override, job.cfg["country"])
    return await _quiet(
        job, "TMDB",
        local.episode(tmdb_id, episode.get("season_number"), episode.get("episode_number")),
        log_success=False,
    )


async def _scrape_one_episode(job, client, show, episode, episodes, answers, order, primary, thumbs):
    tvdb_episodes = answers.get("episodes") or {}
    key = (episode["season_number"], episode["episode_number"])
    if order == "aired":
        from_tmdb = ((answers.get(f"season{key[0]}") or {}).get("episodes") or {}).get(key[1])
    else:
        from_tmdb = (answers.get("groups") or {}).get(key)
    from_tvdb = tvdb_episodes.get(key)
    episode_lead = (job.meta_primary or {}).get("episode") or _saved_pref(job, "episode", episode, "meta")
    rank = episode_lead if episode_lead in ("tmdb", "tvdb") else primary
    ranked = [from_tvdb, from_tmdb] if rank == "tvdb" else [from_tmdb, from_tvdb]
    found = [item for item in ranked if item]
    extra = await _episode_certificate(job, client, show, episode)
    own_language = await _episode_language(job, client, show, episode)
    if own_language:
        found.insert(0, own_language)
    if extra:
        if episode_lead == "omdb" or job.primary == "omdb":
            found.insert(0, extra)
        else:
            found.append(extra)
    from_tvmaze = (answers.get("tvmaze_episodes") or {}).get(key)
    if from_tvmaze:
        found.append(from_tvmaze)
    if not found:
        return False
    merged = merge.combine(found)
    if merged.get("guest_stars") and "guest_stars" not in set(episode.get("locked_fields") or []) and _meta_on(job, "episode", "actors") and not _defer_active(job):
        merged["guest_stars"] = await actor_art.store_thumbs(client, show["path"], merged["guest_stars"])
    locked = set(episode.get("locked_fields") or [])
    fields = _fields(job, store.EPISODE_FIELDS, "episode")
    changes = merge.updates(episode, merged, fields, job.policy, locked)
    changes = _rate(job, changes, episode, locked, "episode")
    if changes and not job.art_only and _writes_metadata(job):
        await asyncio.to_thread(store.apply_fields, "tv_episodes", episode["id"], changes)
    folder, thumb_stem, multi = _episode_thumb_target(show, episode, episodes)
    if not folder:
        return
    thumb = os.path.join(folder, thumb_stem)
    artwork = dict(episode.get("artwork") or {})
    if multi:
        specific = art_fetch._existing_named(folder, thumb_stem)
        shared = str(artwork.get("thumb") or "")
        if specific:
            artwork["thumb"] = specific
        elif os.path.splitext(os.path.basename(shared))[0].lower() != thumb_stem.lower():
            artwork.pop("thumb", None)
    art = await _art(job, client, thumbs, merged.get("art") or [], artwork, lambda kind: thumb, level="episode", row=episode)
    if multi and not art.get("thumb"):
        previous = (episode.get("artwork") or {}).get("thumb")
        if previous:
            art["thumb"] = previous
    if art != (episode.get("artwork") or {}):
        await asyncio.to_thread(store.set_artwork, "tv_episodes", episode["id"], art)
    return True


def _episode_thumb_target(show, episode, episodes):
    """Where an episode still is saved. A missing episode uses the season folder and an SxxEyy name."""
    if episode.get("missing") or str(episode.get("path") or "").startswith("missing://"):
        folder = episode.get("season_path") if episode.get("season_path") and os.path.isdir(str(episode.get("season_path"))) else ""
        if not folder and show.get("path") and os.path.isdir(str(show.get("path"))):
            folder = show["path"]
        mark = naming.episode_mark(episode.get("season_number"), episode.get("episode_number"))
        return folder or "", f"{mark}-thumb", False
    folder = os.path.dirname(episode["path"])
    stem = os.path.splitext(os.path.basename(episode["path"]))[0]
    siblings = [item for item in episodes if item.get("path") == episode.get("path")]
    multi = len(siblings) > 1
    mark = naming.episode_mark(episode["season_number"], episode["episode_number"]) if multi else ""
    thumb_stem = f"{stem}-{mark}-thumb" if multi else f"{stem}-thumb"
    return folder, thumb_stem, multi


def _listed_numbers(answers, season_number):
    numbers = set()
    season = answers.get(f"season{season_number}") or {}
    for number in (season.get("episodes") or {}):
        try:
            numbers.add(int(number))
        except (TypeError, ValueError):
            continue
    for key in answers.get("episodes") or {}:
        if isinstance(key, tuple) and len(key) == 2 and int(key[0]) == int(season_number):
            numbers.add(int(key[1]))
    for key in answers.get("groups") or {}:
        if isinstance(key, tuple) and len(key) == 2 and int(key[0]) == int(season_number):
            numbers.add(int(key[1]))
    for key in answers.get("tvmaze_episodes") or {}:
        if isinstance(key, tuple) and len(key) == 2 and int(key[0]) == int(season_number):
            numbers.add(int(key[1]))
    return numbers


async def _fill_missing_episodes(job, client, show, seasons, episodes, answers, order, primary):
    """Keep a row, metadata and still for every listed episode that has no video file."""
    if job.only_episode_ids or str(show.get("path") or "").startswith("wanted://"):
        return
    thumbs = {"thumb": job.cfg["episode_thumbs"]}
    known = {}
    for item in episodes:
        try:
            known[(int(item["season_number"]), int(item["episode_number"]))] = item
        except (TypeError, ValueError):
            continue
    made = listed = 0
    for season in seasons:
        if season.get("locked") or season.get("status") == "IGNORED":
            continue
        for number in sorted(_listed_numbers(answers, season["season_number"])):
            listed += 1
            code = naming.episode_mark(season["season_number"], number)
            existing = known.get((int(season["season_number"]), int(number)))
            if existing and not existing.get("missing") and not str(existing.get("path") or "").startswith("missing://"):
                continue
            if existing:
                row = existing
                row["season_path"] = season.get("path")
            else:
                path = f"missing://{show['id']}/{code}"
                try:
                    episode_id, _inserted = await asyncio.to_thread(store.save_episode, {
                        "show_id": show["id"], "season_id": season["id"],
                        "season_number": season["season_number"], "episode_number": number,
                        "path": path, "missing": True,
                    })
                except Exception as exc:
                    job.log(f"{show.get('title')}: could not record missing {code}: {exc}")
                    continue
                row = {
                    "id": episode_id, "show_id": show["id"], "season_id": season["id"],
                    "season_number": season["season_number"], "episode_number": number,
                    "path": path, "missing": True,
                    "season_path": season.get("path"), "artwork": {}, "locked_fields": [],
                }
            try:
                saved = await _scrape_one_episode(job, client, show, row, [row], answers, order, primary, thumbs)
            except Exception as exc:
                job.log(f"{show.get('title')}: {code} metadata was not saved: {exc}")
                continue
            if not saved:
                job.log(f"{show.get('title')}: {code} is listed, but the source had no episode details")
                continue
            made += 1
            job.log(f"{show.get('title')}: {code} is missing, metadata saved")
    title = show.get("title") or "Show"
    if made:
        job.log(f"{title}: {made} missing episode{'s' if made != 1 else ''} recorded")
    elif listed:
        job.log(f"{title}: every listed episode has a file")
    else:
        job.log(f"{title}: the source listing had no episode numbers, so missing episodes were not added")
