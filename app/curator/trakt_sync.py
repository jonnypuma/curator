"""Watched-state sync between the library and the signed-in Trakt account.

Pull copies Trakt's play counts and last-watched times into the library; push adds items watched
in the library but not on Trakt to the Trakt history. Both keep the higher play count and the
later time, so running both is a two-way merge that never unwatches anything. Changed items get
their .nfo rewritten (<playcount>, <lastplayed>) unless they are locked.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from curator import trakt
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

MODES = ("both", "pull", "push")
BATCH = 100
LOG_LINES = 500

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "started_at": None, "finished_at": None, "result": {}}
_log = deque(maxlen=LOG_LINES)
_timer = {"started": False}


def status():
    with _lock:
        snapshot = dict(_state)
        snapshot["result"] = dict(_state["result"])
        snapshot["log"] = "\n".join(_log)
    return snapshot


def running():
    with _lock:
        return _state["status"] == "running"


def _say(line):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        _state["message"] = line


# Time formats: Trakt sends ISO 8601 in UTC, Kodi stores "YYYY-MM-DD HH:MM:SS" in local time.

def kodi_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def trakt_time(value):
    if not value:
        return "released"
    try:
        moment = datetime.strptime(str(value).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            moment = datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")
        except ValueError:
            return "released"
    return moment.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def later(first, second):
    """The later of two Kodi time strings (they sort as text)."""
    values = [value for value in (first, second) if value]
    return max(values) if values else None


def merge(local_plays, local_last, remote_plays, remote_last):
    """(plays, last_played) after a two-way merge."""
    return max(int(local_plays or 0), int(remote_plays or 0)), later(local_last, remote_last)


# Trakt API

def _headers():
    token = trakt.access_token()
    if not token:
        raise AppError("Connect Curator to Trakt first (Settings, Integrations, Trakt)", 400)
    cid = trakt.client_id()
    return {"Authorization": f"Bearer {token}", "trakt-api-key": cid, "trakt-api-version": "2",
            "Content-Type": "application/json", "User-Agent": "Curator"}


def _call(method, path, body=None):
    for attempt in range(4):
        try:
            response = httpx.request(method, f"{trakt.API_HOST}{path}", json=body, headers=_headers(), timeout=60)
        except httpx.HTTPError as exc:
            raise AppError(f"Trakt could not be reached: {exc}", 502) from exc
        if response.status_code == 429 and attempt < 3:
            time.sleep(min(float(response.headers.get("Retry-After") or 2), 30))
            continue
        if response.status_code >= 400:
            raise AppError(f"Trakt answered {response.status_code} for {path}", 502)
        return response.json() if response.content else {}
    raise AppError("Trakt kept asking Curator to slow down", 502)


def _key(ids, *names):
    return [(name, str(ids.get(name))) for name in names if ids.get(name)]


# Local rows

def _movies():
    return db.fetchall("SELECT id, title, year, tmdb_id, imdb_id, ids, playcount, last_played, locked FROM movies")


def _shows():
    return db.fetchall("SELECT id, title, tmdb_id, tvdb_id, imdb_id, ids FROM tv_shows")


def _episodes():
    return db.fetchall("SELECT id, show_id, season_number, episode_number, playcount, last_played, locked "
                       "FROM tv_episodes")


def _ids(row):
    ids = {key: str(value) for key, value in (row.get("ids") or {}).items() if value}
    for key in ("tmdb", "tvdb", "imdb"):
        if row.get(f"{key}_id") and not ids.get(key):
            ids[key] = str(row[f"{key}_id"])
    return ids


def _index(rows, names):
    found = {}
    for row in rows:
        ids = _ids(row)
        for pair in _key(ids, *names):
            found.setdefault(pair, row)
    return found


def _find(index, ids, names):
    for pair in _key(ids, *names):
        if pair in index:
            return index[pair]
    return None


# Sync

def plan(movies, shows, episodes, remote_movies, remote_shows, mode):
    """Work out what changes. Returns (local updates, history to push).

    Local updates are (table, id, plays, last_played). The push body follows Trakt's /sync/history.
    """
    updates, push_movies, push_shows = [], [], {}
    movie_index = _index(movies, ("tmdb", "imdb"))
    show_index = _index(shows, ("tmdb", "tvdb", "imdb"))
    remote_movie_state, remote_episode_state = {}, {}
    for item in remote_movies:
        row = _find(movie_index, (item.get("movie") or {}).get("ids") or {}, ("tmdb", "imdb"))
        if row:
            remote_movie_state[str(row["id"])] = (int(item.get("plays") or 0), kodi_time(item.get("last_watched_at")))
    for item in remote_shows:
        show = _find(show_index, (item.get("show") or {}).get("ids") or {}, ("tmdb", "tvdb", "imdb"))
        if not show:
            continue
        for season in item.get("seasons") or []:
            for episode in season.get("episodes") or []:
                key = (str(show["id"]), int(season.get("number") or 0), int(episode.get("number") or 0))
                remote_episode_state[key] = (int(episode.get("plays") or 0), kodi_time(episode.get("last_watched_at")))
    for row in movies:
        remote = remote_movie_state.get(str(row["id"]), (0, None))
        local = (int(row.get("playcount") or 0), row.get("last_played"))
        if mode in ("both", "pull") and remote[0]:
            plays, last = merge(local[0], local[1], remote[0], remote[1])
            if (plays, last) != local:
                updates.append(("movies", str(row["id"]), plays, last))
        if mode in ("both", "push") and local[0] and not remote[0]:
            ids = dict(_key(_ids(row), "tmdb", "imdb"))
            if ids:
                push_movies.append({"ids": ids, "watched_at": trakt_time(local[1])})
    shows_by_id = {str(show["id"]): show for show in shows}
    for row in episodes:
        key = (str(row["show_id"]), int(row["season_number"]), int(row["episode_number"]))
        remote = remote_episode_state.get(key, (0, None))
        local = (int(row.get("playcount") or 0), row.get("last_played"))
        if mode in ("both", "pull") and remote[0]:
            plays, last = merge(local[0], local[1], remote[0], remote[1])
            if (plays, last) != local:
                updates.append(("tv_episodes", str(row["id"]), plays, last))
        if mode in ("both", "push") and local[0] and not remote[0]:
            show = shows_by_id.get(key[0])
            ids = dict(_key(_ids(show or {}), "tmdb", "tvdb", "imdb"))
            if not ids:
                continue
            entry = push_shows.setdefault(key[0], {"ids": ids, "seasons": {}})
            entry["seasons"].setdefault(key[1], []).append({"number": key[2], "watched_at": trakt_time(local[1])})
    shows_body = [{"ids": entry["ids"], "seasons": [{"number": number, "episodes": items}
                                                    for number, items in sorted(entry["seasons"].items())]}
                  for entry in push_shows.values()]
    return updates, {"movies": push_movies, "shows": shows_body}


def _apply_updates(updates):
    with db.transaction() as conn:
        for table, row_id, plays, last in updates:
            conn.execute(f"UPDATE {table} SET playcount = %s, last_played = %s, updated_at = NOW() WHERE id = %s",
                         (plays, last, row_id))


def _write_nfos(updates):
    from curator.video import config, exports

    cfg = config.current()
    if not cfg["write_nfo"]:
        return 0
    written = 0
    movie_ids = [row_id for table, row_id, _p, _l in updates if table == "movies"]
    episode_ids = [row_id for table, row_id, _p, _l in updates if table == "tv_episodes"]
    if movie_ids:
        for row in db.fetchall("SELECT id FROM movies WHERE id = ANY(%s::uuid[]) AND NOT locked", (movie_ids,)):
            try:
                written += 1 if exports.write_movie(str(row["id"]), cfg) else 0
            except (OSError, AppError) as exc:
                _say(f"Could not write the .nfo of a movie: {exc}")
    if episode_ids:
        shows = {}
        for row in db.fetchall("SELECT id, show_id FROM tv_episodes WHERE id = ANY(%s::uuid[]) AND NOT locked",
                               (episode_ids,)):
            shows.setdefault(str(row["show_id"]), []).append(str(row["id"]))
        for show_id, ids in shows.items():
            try:
                written += len(exports.write_show(show_id, cfg, episode_ids=ids))
            except (OSError, AppError) as exc:
                _say(f"Could not write episode .nfo files: {exc}")
    return written


def _push(body):
    added = {"movies": 0, "episodes": 0}
    for start in range(0, len(body["movies"]), BATCH):
        reply = _call("POST", "/sync/history", {"movies": body["movies"][start:start + BATCH]})
        added["movies"] += int(((reply or {}).get("added") or {}).get("movies") or 0)
    for start in range(0, len(body["shows"]), BATCH):
        reply = _call("POST", "/sync/history", {"shows": body["shows"][start:start + BATCH]})
        added["episodes"] += int(((reply or {}).get("added") or {}).get("episodes") or 0)
    return added


def sync(mode="both"):
    """Run one sync in the calling thread. Returns the result counts."""
    if mode not in MODES:
        raise AppError(f"Unknown sync mode {mode}", 400)
    _say("Reading watched movies and shows from Trakt")
    remote_movies = _call("GET", "/sync/watched/movies") or []
    remote_shows = _call("GET", "/sync/watched/shows") or []
    updates, push = plan(_movies(), _shows(), _episodes(), remote_movies, remote_shows, mode)
    result = {"pulled": len(updates), "pushed_movies": 0, "pushed_episodes": 0, "nfo": 0}
    if updates:
        _say(f"Updating {len(updates)} watched item(s) in the library")
        _apply_updates(updates)
        result["nfo"] = _write_nfos(updates)
    if push["movies"] or push["shows"]:
        episodes = sum(len(season["episodes"]) for show in push["shows"] for season in show["seasons"])
        _say(f"Adding {len(push['movies'])} movie(s) and {episodes} episode(s) to the Trakt history")
        added = _push(push)
        result["pushed_movies"], result["pushed_episodes"] = added["movies"], added["episodes"]
    trakt.mark_synced()
    return result


def start(mode="both"):
    """Start a sync in a thread. Returns False when one is already running."""
    if mode not in MODES:
        raise AppError(f"Unknown sync mode {mode}", 400)
    if not trakt.access_token():
        raise AppError("Connect Curator to Trakt first", 400)
    from resonance import backup

    if backup.restoring():
        raise AppError("Wait for the database restore to finish", 409)
    with _lock:
        if _state["status"] == "running":
            return False
        _log.clear()
        _state.update({"status": "running", "message": "Starting", "result": {},
                       "started_at": datetime.now().isoformat(timespec="seconds"), "finished_at": None})
    threading.Thread(target=_run, args=(mode,), name="trakt-sync", daemon=True).start()
    return True


def _run(mode):
    try:
        result = sync(mode)
        message = (f"Done: {result['pulled']} updated from Trakt, {result['pushed_movies']} movie(s) and "
                   f"{result['pushed_episodes']} episode(s) added to Trakt, {result['nfo']} .nfo file(s) written")
        final = "done"
    except AppError as exc:
        result, message, final = {}, str(exc), "failed"
    except Exception as exc:
        logger.exception("Trakt sync failed")
        result, message, final = {}, str(exc), "failed"
    _say(message)
    with _lock:
        _state.update({"status": final, "message": message, "result": result,
                       "finished_at": datetime.now().isoformat(timespec="seconds")})


def start_timer():
    """Sync on the interval set in Settings (hours, 0 = off)."""
    if _timer["started"]:
        return
    _timer["started"] = True
    threading.Thread(target=_timer_loop, name="trakt-sync-timer", daemon=True).start()


def _timer_loop():
    while True:
        time.sleep(300)
        try:
            from resonance import backup
            from curator.video import config

            cfg = config.current()
            hours = cfg.get("trakt_sync_hours") or 0
            if not hours or not trakt.access_token() or backup.restoring():
                continue
            if time.time() - trakt.last_synced() >= hours * 3600:
                start(cfg.get("trakt_sync_mode") or "both")
        except Exception:
            logger.exception("scheduled Trakt sync failed")
