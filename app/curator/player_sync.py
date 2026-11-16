"""Watched-state sync between the library and Kodi, Jellyfin, Emby and Plex.

Each player's movies, episodes, music videos and (when switched on) music tracks are matched to the library by file
path (through the player's path rows under Integrations). The merge works like the Trakt sync: the higher play count and
the later last-played time win, so nothing is lost by accident. A resume point that one side has and the other does not
is copied over; when both have one, the player's wins on pull and Curator's on push.

Unwatching is opt-in. Curator remembers what both sides agreed on at the last sync (player_sync_state). With it on, a
count that fell on one side while the other stayed where it was is an unwatch, and it spreads; if both changed, the
higher count still wins.

Jellyfin and Emby can sync several users. The users listed share one watched state, like a household.

Pull writes the library (and the .nfo of changed items, unless locked). Push writes each player:
- Kodi: VideoLibrary.SetMovieDetails / SetEpisodeDetails (playcount, lastplayed, resume).
- Jellyfin and Emby: the user's item data (PlayCount, LastPlayedDate, Played, PlaybackPositionTicks).
- Plex: scrobble marks an unwatched item watched; progress sets the resume point. Plex cannot set a play count.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

import requests

from curator import automation, path_map
from resonance import db, history
from resonance.errors import AppError

logger = logging.getLogger(__name__)

PLAYERS = ("kodi", "jellyfin", "emby", "plex")
NAMES = {"kodi": "Kodi", "jellyfin": "Jellyfin", "emby": "Emby", "plex": "Plex"}
MODES = ("both", "pull", "push")
TICKS = 10_000_000
TIMEOUT = 60

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "started_at": None, "finished_at": None, "result": {}}
_log = deque(maxlen=500)
_timer = {"started": False}


def status():
    with _lock:
        snapshot = dict(_state)
        snapshot["result"] = dict(_state["result"])
        snapshot["log"] = "\n".join(_log)
    return snapshot


def _say(line):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        _state["message"] = line


# Times: the library keeps Kodi's "YYYY-MM-DD HH:MM:SS" in local time.

def _from_iso(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00")[:32])
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _from_epoch(value):
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S") if value else None
    except (TypeError, ValueError, OSError):
        return None


def _to_iso(value):
    try:
        moment = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return moment.astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _later(first, second):
    values = [value for value in (first, second) if value]
    return max(values) if values else None


def merge(local, remote, mode):
    """The state both sides should have after the sync, from {"plays", "last", "resume", "total"} dicts."""
    plays = max(int(local.get("plays") or 0), int(remote.get("plays") or 0))
    last = _later(local.get("last"), remote.get("last"))
    local_resume, remote_resume = float(local.get("resume") or 0), float(remote.get("resume") or 0)
    if local_resume and remote_resume:
        prefer_remote = mode == "pull" or (mode == "both" and (remote.get("last") or "") >= (local.get("last") or ""))
        resume, total = (remote_resume, remote.get("total")) if prefer_remote else (local_resume, local.get("total"))
    elif remote_resume:
        resume, total = remote_resume, remote.get("total")
    else:
        resume, total = local_resume, local.get("total")
    return {"plays": plays, "last": last, "resume": resume or 0.0, "total": float(total or 0) or 0.0}


def _differs(state, wanted):
    return (int(state.get("plays") or 0) != wanted["plays"] or (state.get("last") or None) != (wanted["last"] or None)
            or abs(float(state.get("resume") or 0) - wanted["resume"]) > 5)


# The library

def _library(music=False):
    """{local file key: row} for movies, episodes and music videos, and with music=True the music tracks."""
    from curator.video import store

    rows = {}
    for row in db.fetchall(
        "SELECT m.id::text AS id, f.path AS file_path, m.parts, m.playcount, m.last_played, m.resume_position, "
        "m.resume_total, m.locked FROM movies m LEFT JOIN video_files f ON f.id = m.file_id "
        "WHERE NOT COALESCE(m.wanted, FALSE)"
    ):
        for path in store.movie_file_paths(row):      # movies.path is the folder; every file of a stack is this movie
            rows[_key(path)] = {**dict(row), "path": path, "table": "movies"}
    for row in db.fetchall(
        "SELECT id::text AS id, show_id::text AS show_id, path, playcount, last_played, resume_position, resume_total, "
        "locked FROM tv_episodes WHERE NOT missing AND COALESCE(path, '') <> '' AND path NOT LIKE '%%://%%'"
    ):
        rows[_key(row["path"])] = {**dict(row), "table": "tv_episodes"}
    for row in db.fetchall(
        "SELECT id::text AS id, path, playcount, last_played, resume_position, resume_total, locked FROM music_videos"
    ):
        rows[_key(row["path"])] = {**dict(row), "table": "music_videos"}
    if music:
        for row in db.fetchall(
            "SELECT id::text AS id, file_path AS path, playcount, last_played FROM tracks WHERE COALESCE(file_path, '') <> ''"
        ):
            rows[_key(row["path"])] = {**dict(row), "table": "tracks"}
    return rows


def _key(path):
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def _local_state(row):
    return {"plays": int(row.get("playcount") or 0), "last": row.get("last_played"),
            "resume": float(row.get("resume_position") or 0), "total": float(row.get("resume_total") or 0)}


# Players: each reader returns [(local path, state, handle)]; each writer takes (handle, wanted state).

def _cfg():
    _auto, cfg = automation.current()
    return cfg


def ready_players(cfg=None):
    cfg = cfg or _cfg()
    found = []
    if cfg.get("kodi_library_host") and cfg.get("kodi_video_enabled", True):
        found.append("kodi")
    for name in ("jellyfin", "emby", "plex"):
        if cfg.get(f"{name}_on", True) is not False and cfg.get(f"{name}_url") and cfg.get(f"{name}_token"):
            found.append(name)
    return found


def _mappings(player, cfg):
    from curator.library_queue import mappings_for

    return mappings_for(player, cfg)


def _local(remote, rows):
    return path_map.from_player(remote, rows) or ""


_KODI_SETTERS = {"movieid": "VideoLibrary.SetMovieDetails", "episodeid": "VideoLibrary.SetEpisodeDetails",
                 "musicvideoid": "VideoLibrary.SetMusicVideoDetails", "songid": "AudioLibrary.SetSongDetails"}


class Kodi:
    def __init__(self, cfg):
        from curator import notify

        self.call = notify.kodi_call
        self.target = (cfg["kodi_library_host"], cfg.get("kodi_library_user"), cfg.get("kodi_library_password"))
        self.rows = _mappings("kodi", cfg)

    def read(self, music=False):
        found = []
        props = ["file", "playcount", "lastplayed", "resume"]
        for method, key, id_key in (("VideoLibrary.GetMovies", "movies", "movieid"),
                                    ("VideoLibrary.GetEpisodes", "episodes", "episodeid"),
                                    ("VideoLibrary.GetMusicVideos", "musicvideos", "musicvideoid")):
            result = self.call(*self.target, method, {"properties": props}, timeout=TIMEOUT) or {}
            for row in result.get(key) or []:
                files = [row.get("file") or ""]
                if files[0].startswith("stack://"):
                    files = [part.strip() for part in files[0][8:].split(" , ")]
                local = next((path for path in (_local(item, self.rows) for item in files) if path), "")
                if not local:
                    continue
                resume = row.get("resume") or {}
                state = {"plays": int(row.get("playcount") or 0), "last": row.get("lastplayed") or None,
                         "resume": float(resume.get("position") or 0), "total": float(resume.get("total") or 0)}
                found.append((local, state, (method, id_key, int(row[id_key]))))
        if music:
            result = self.call(*self.target, "AudioLibrary.GetSongs", {"properties": ["file", "playcount", "lastplayed"]},
                               timeout=TIMEOUT) or {}
            for row in result.get("songs") or []:
                local = _local(row.get("file") or "", self.rows)
                if local:
                    state = {"plays": int(row.get("playcount") or 0), "last": row.get("lastplayed") or None,
                             "resume": 0.0, "total": 0.0}
                    found.append((local, state, ("AudioLibrary.GetSongs", "songid", int(row["songid"]))))
        return found

    def write(self, handle, wanted):
        method, id_key, item_id = handle
        setter = _KODI_SETTERS[id_key]
        params = {id_key: item_id, "playcount": wanted["plays"], "lastplayed": wanted["last"] or ""}
        if id_key != "songid":
            params["resume"] = {"position": wanted["resume"], "total": wanted["total"] or 0}
        self.call(*self.target, setter, params, timeout=TIMEOUT)


class MediaServer:
    """Jellyfin and Emby share the item data API."""

    def __init__(self, player, cfg, user_id=None):
        from curator import notify

        self.player = player
        self.url = notify._base(cfg[f"{player}_url"])
        self.headers = {**notify._auth_headers(player, cfg[f"{player}_token"]), "Accept": "application/json"}
        self.rows = _mappings(player, cfg)
        from curator.video import config

        self.wanted_user = str(config.current().get(f"watch_sync_user_{player}") or "").strip().split(",")[0].strip().lower()
        if self.wanted_user == "*":
            self.wanted_user = ""
        self.user = user_id or self._user()

    def users(self):
        """Every user of the server: [{"Id", "Name", "Policy"}]."""
        return [user for user in (self._get("/Users") or []) if isinstance(user, dict) and user.get("Id")]

    def _get(self, path, params=None):
        response = requests.get(f"{self.url}{path}", params=params, headers=self.headers, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise RuntimeError(f"{NAMES[self.player]} answered HTTP {response.status_code} for {path}")
        return response.json() if response.content else {}

    def _user(self):
        users = self._get("/Users") or []
        if self.wanted_user:
            for user in users:
                if str(user.get("Name") or "").lower() == self.wanted_user:
                    return user["Id"]
            raise RuntimeError(f"{NAMES[self.player]} has no user named {self.wanted_user}")
        admins = [user for user in users if (user.get("Policy") or {}).get("IsAdministrator")]
        chosen = (admins or users or [None])[0]
        if not chosen:
            raise RuntimeError(f"{NAMES[self.player]} listed no users")
        return chosen["Id"]

    def read(self, music=False):
        kinds = "Movie,Episode,MusicVideo" + (",Audio" if music else "")
        params = {"Recursive": "true", "IncludeItemTypes": kinds, "Fields": "Path,MediaSources", "EnableUserData": "true"}
        data = self._get(f"/Users/{self.user}/Items", params)
        found = []
        for item in data.get("Items") or []:
            local = _local(item.get("Path") or "", self.rows)
            if not local:
                continue
            user = item.get("UserData") or {}
            total = float(item.get("RunTimeTicks") or 0) / TICKS
            state = {"plays": int(user.get("PlayCount") or (1 if user.get("Played") else 0)),
                     "last": _from_iso(user.get("LastPlayedDate")),
                     "resume": float(user.get("PlaybackPositionTicks") or 0) / TICKS, "total": total}
            found.append((local, state, item["Id"]))
        return found

    def write(self, handle, wanted):
        body = {"PlayCount": wanted["plays"], "Played": wanted["plays"] > 0,
                "PlaybackPositionTicks": int(wanted["resume"] * TICKS)}
        if wanted["last"]:
            body["LastPlayedDate"] = _to_iso(wanted["last"])
        response = requests.post(f"{self.url}/Users/{self.user}/Items/{handle}/UserData", json=body,
                                 headers=self.headers, timeout=TIMEOUT)
        if response.status_code == 404:
            response = requests.post(f"{self.url}/UserItems/{handle}/UserData", params={"userId": self.user},
                                     json=body, headers=self.headers, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise RuntimeError(f"{NAMES[self.player]} answered HTTP {response.status_code}")


class Plex:
    def __init__(self, cfg):
        from curator import notify

        self.notify = notify
        self.url = notify._base(cfg["plex_url"])
        self.token = cfg["plex_token"]
        self.rows = list(cfg.get("plex_paths") or [])
        self.cfg = cfg

    def read(self, music=False):
        found = []
        sections = self.notify._plex_sections(self.cfg)
        kinds = {"movie": 1, "show": 4, **({"artist": 10} if music else {})}     # Plex type 10 is a music track
        wanted = sorted({(str(row.get("key")), kinds[row["type"]]) for row in sections or []
                         if isinstance(row, dict) and row.get("key") and row.get("type") in kinds})
        for section, kind in wanted:
            try:
                rows = self.notify._plex_json(self.url, self.token, f"/library/sections/{section}/all", {"type": kind})
            except RuntimeError:
                continue
            for row in rows:
                files = [file for file, _key, _show in self.notify.plex_files([row])]
                local = next((path for path in (_local(item, self.rows) for item in files) if path), "")
                if not local:
                    continue
                state = {"plays": int(row.get("viewCount") or 0), "last": _from_epoch(row.get("lastViewedAt")),
                         "resume": float(row.get("viewOffset") or 0) / 1000,
                         "total": float(row.get("duration") or 0) / 1000}
                found.append((local, state, (str(row.get("ratingKey")), state)))
        return found

    def write(self, handle, wanted):
        rating_key, before = handle
        params = {"X-Plex-Token": self.token, "key": rating_key, "identifier": "com.plexapp.plugins.library"}
        if wanted["plays"] > int(before.get("plays") or 0) and not int(before.get("plays") or 0):
            requests.get(f"{self.url}/:/scrobble", params=params, timeout=TIMEOUT)
        elif not wanted["plays"] and int(before.get("plays") or 0):
            requests.get(f"{self.url}/:/unscrobble", params=params, timeout=TIMEOUT)
        if wanted["resume"] and abs(wanted["resume"] - float(before.get("resume") or 0)) > 5:
            requests.get(f"{self.url}/:/progress", params={**params, "time": int(wanted["resume"] * 1000),
                                                           "state": "stopped"}, timeout=TIMEOUT)


def _client(player, cfg):
    if player == "kodi":
        return Kodi(cfg)
    if player == "plex":
        return Plex(cfg)
    return MediaServer(player, cfg)


# Sync

def decide(mine, theirs, base, mode, propagate):
    """The state both sides should have. base is what they agreed on at the last sync (None: never synced).

    With propagate on, a count that fell on one side while the other stayed at the baseline is an unwatch and wins.
    Anything else merges upward, so a change on both sides never loses a watch."""
    if propagate and base is not None:
        was = int(base.get("plays") or 0)
        mine_plays, their_plays = int(mine.get("plays") or 0), int(theirs.get("plays") or 0)
        if their_plays < was and mine_plays == was and mode in ("both", "pull"):
            source = theirs
        elif mine_plays < was and their_plays == was and mode in ("both", "push"):
            source = mine
        else:
            return merge(mine, theirs, mode)
        plays = int(source.get("plays") or 0)
        return {"plays": plays, "last": source.get("last") if plays else None,
                "resume": float(source.get("resume") or 0) if plays else 0.0, "total": float(source.get("total") or 0)}
    return merge(mine, theirs, mode)


def plan_full(library, remote, mode, previous=None, propagate=False):
    """(library updates, player writes, agreed) for one player or user.

    library: {key: row}; remote: [(local, state, handle)]; previous: {key: {"plays", "last"}} from the last sync.
    agreed is [(key, wanted)] for every matched item: what to remember as the state both sides now share."""
    previous = previous or {}
    updates, writes, agreed = {}, [], []
    for local, state, handle in remote:
        key = _key(local)
        row = library.get(key)
        if not row:
            continue
        mine = _local_state(row)
        wanted = decide(mine, state, previous.get(key), mode, propagate)
        if mode in ("both", "pull") and _differs(mine, wanted):
            updates[row["id"]] = (row["table"], row["id"], wanted)
        if mode in ("both", "push") and _differs(state, wanted):
            writes.append((handle, wanted, row))
        agreed.append((key, wanted))
    return list(updates.values()), writes, agreed


def plan(library, remote, mode):
    """(library updates, player writes) for one player. library: {key: row}; remote: [(local, state, handle)]."""
    updates, writes, _agreed = plan_full(library, remote, mode)
    return updates, writes


def _apply(updates):
    with db.transaction() as conn:
        for table, row_id, wanted in updates:
            if table == "tracks":        # a track has a play count and a last played time, no resume point
                conn.execute("UPDATE tracks SET playcount = %s, last_played = %s WHERE id = %s",
                             (wanted["plays"], wanted["last"], row_id))
                continue
            conn.execute(
                f"UPDATE {table} SET playcount = %s, last_played = %s, resume_position = %s, resume_total = %s, "
                "updated_at = NOW() WHERE id = %s",
                (wanted["plays"], wanted["last"], wanted["resume"] or None, wanted["total"] or None, row_id),
            )


def _previous(ident):
    """{key: {"plays", "last"}} that this player (or player user) and the library agreed on at the last sync."""
    rows = db.fetchall("SELECT path_key, plays, last_played FROM player_sync_state WHERE player = %s", (ident,))
    return {row["path_key"]: {"plays": int(row["plays"] or 0), "last": row["last_played"]} for row in rows}


def _remember(ident, agreed):
    """Keep the state both sides now share, for the next sync to tell an unwatch from a change on the other side."""
    for start in range(0, len(agreed), 5000):
        chunk = agreed[start:start + 5000]
        db.execute(
            """
            INSERT INTO player_sync_state (player, path_key, plays, last_played)
            SELECT %s, t.k, t.p, t.l FROM unnest(%s::text[], %s::int[], %s::text[]) AS t(k, p, l)
            ON CONFLICT (player, path_key) DO UPDATE SET plays = EXCLUDED.plays, last_played = EXCLUDED.last_played
            """,
            (ident, [key for key, _w in chunk], [int(w["plays"]) for _k, w in chunk], [w["last"] for _k, w in chunk]),
        )


def _remotes(player, cfg):
    """[(ident, label, client)] for a player: one for Kodi and Plex, one per chosen user for Jellyfin and Emby.

    Users are listed in the setting by name, comma between, or * for everyone; empty means the first administrator."""
    name = NAMES[player]
    if player not in ("jellyfin", "emby"):
        return [(player, name, _client(player, cfg))]
    from curator.video import config

    wanted = [item.strip() for item in str(config.current().get(f"watch_sync_user_{player}") or "").replace(";", ",").split(",") if item.strip()]
    base = MediaServer(player, cfg)
    if len(wanted) <= 1 and "*" not in wanted:
        return [(player, name, base)]
    users = base.users()
    chosen = users if "*" in wanted else []
    for item in ([] if "*" in wanted else wanted):
        match = next((user for user in users if str(user.get("Name") or "").lower() == item.lower()), None)
        if not match:
            raise RuntimeError(f"{name} has no user named {item}")
        chosen.append(match)
    return [(f"{player}:{user['Name']}", f"{name} ({user['Name']})", MediaServer(player, cfg, user_id=user["Id"])) for user in chosen]


def sync(mode="both", players=None):
    from curator.video import config

    if mode not in MODES:
        raise AppError(f"Unknown sync mode {mode}", 400)
    cfg = _cfg()
    chosen = [player for player in (players or _chosen_players()) if player in ready_players(cfg)]
    if not chosen:
        raise AppError("No player is ready. Set up Kodi, Jellyfin, Emby or Plex under Integrations and tick it here.", 400)
    video = config.current()
    music, unwatch = bool(video.get("watch_sync_music")), bool(video.get("watch_sync_unwatch"))
    result = {"pulled": 0, "pushed": 0, "players": {}, "nfo": 0}
    changed = []
    for player in chosen:
        try:
            remotes = _remotes(player, cfg)
        except (RuntimeError, requests.RequestException, AppError) as exc:
            result["players"][player] = {"error": str(exc)}
            _say(f"{NAMES[player]}: {exc}")
            continue
        for ident, name, client in remotes:
            try:
                _say(f"Reading watched state from {name}")
                library = _library(music)
                updates, writes, agreed = plan_full(library, client.read(music=music), mode, _previous(ident), unwatch)
                if updates:
                    _apply(updates)
                    changed += updates
                failed, failed_keys = 0, set()
                for handle, wanted, row in writes:
                    try:
                        client.write(handle, wanted)
                    except (RuntimeError, requests.RequestException) as exc:
                        failed += 1
                        failed_keys.add(_key(row.get("path")))
                        if failed <= 3:
                            _say(f"{name}: {exc}")
                _remember(ident, [(key, wanted) for key, wanted in agreed if key not in failed_keys])
                pushed = len(writes) - failed
                result["pulled"] += len(updates)
                result["pushed"] += pushed
                result["players"][ident] = {"pulled": len(updates), "pushed": pushed, "failed": failed}
                _say(f"{name}: {len(updates)} updated in the library, {pushed} updated in {name}")
            except (RuntimeError, requests.RequestException, AppError) as exc:
                result["players"][ident] = {"error": str(exc)}
                _say(f"{name}: {exc}")
    if changed:
        from curator import trakt_sync

        result["nfo"] = trakt_sync._write_nfos([(table, row_id, w["plays"], w["last"]) for table, row_id, w in changed
                                                if table in ("movies", "tv_episodes")])
    return result


def _chosen_players():
    from curator.video import config

    chosen = config.current().get("watch_sync_players") or []
    return [player for player in chosen if player in PLAYERS]


def start(mode="both"):
    with _lock:
        if _state["status"] == "running":
            return False
        _log.clear()
        _state.update({"status": "running", "message": "Starting", "result": {},
                       "started_at": datetime.now().astimezone().isoformat(timespec="seconds"), "finished_at": None})
    threading.Thread(target=_run, args=(mode,), name="player-sync", daemon=True).start()
    return True


def _run(mode):
    try:
        result = sync(mode)
        message = f"Done: {result['pulled']} updated in the library, {result['pushed']} updated in the players"
        final = "done"
    except AppError as exc:
        result, message, final = {}, str(exc), "failed"
    except Exception as exc:
        logger.exception("player watched sync failed")
        result, message, final = {}, str(exc), "failed"
    _say(message)
    history.record("synced", "Player watched sync", "", "", message)
    with _lock:
        _state.update({"status": final, "message": message, "result": result,
                       "finished_at": datetime.now().astimezone().isoformat(timespec="seconds")})


def start_timer():
    if _timer["started"]:
        return
    _timer["started"] = True
    threading.Thread(target=_timer_loop, name="player-sync-timer", daemon=True).start()


def _timer_loop():
    from curator.video import config

    while True:
        hours = int(config.current().get("watch_sync_hours") or 0)
        time.sleep(max(1, hours or 1) * 3600)
        if hours and _chosen_players():
            try:
                start(config.current().get("watch_sync_mode") or "both")
            except Exception:
                logger.exception("scheduled player watched sync failed")


# Kodi item refresh: a refresh re-reads the .nfo and can drop the resume point. Put the watched state back.

def kodi_state(call, target, method, key, id_key, name):
    """{file: (playcount, lastplayed, resume)} for the Kodi rows with this file name."""
    found = call(*target, method, {"filter": {"field": "filename", "operator": "is", "value": name},
                                   "properties": ["file", "playcount", "lastplayed", "resume"]}) or {}
    return found.get(key) or []


def restore_after_refresh(call, target, saved, attempts=6, wait=5):
    """saved: [(method, key, id_key, name, remote file, state)]. Re-finds each item (a refresh gives it a new id) and
    writes the old play count, last played and resume point back when the refresh lost them. Returns how many."""
    from curator.notify import kodi_match

    left = list(saved)
    restored = 0
    for _attempt in range(attempts):
        if not left:
            break
        time.sleep(wait)
        pending = []
        for method, key, id_key, name, remote, before in left:
            row = kodi_match(kodi_state(call, target, method, key, id_key, name), remote)
            if not row:
                pending.append((method, key, id_key, name, remote, before))
                continue
            resume = row.get("resume") or {}
            now = {"plays": int(row.get("playcount") or 0), "last": row.get("lastplayed") or None,
                   "resume": float(resume.get("position") or 0), "total": float(resume.get("total") or 0)}
            wanted = merge(now, before, "both")
            if _differs(now, wanted):
                setter = _KODI_SETTERS[id_key]
                call(*target, setter, {id_key: int(row[id_key]), "playcount": wanted["plays"],
                                       "lastplayed": wanted["last"] or "",
                                       "resume": {"position": wanted["resume"], "total": wanted["total"] or 0}})
                restored += 1
        left = pending
    return restored


def test_player(player):
    """Read one player the way a sync does and say what matched. Writes nothing."""
    cfg = _cfg()
    if player not in PLAYERS:
        raise AppError("Unknown player", 400)
    if player not in ready_players(cfg):
        return {"player": player, "ok": None, "message": f"{NAMES[player]} is not set up under Integrations"}
    try:
        found = _client(player, cfg).read()
        library = _library()
        matched = sum(1 for local, _state, _handle in found if _key(local) in library)
        watched = sum(1 for _local, state, _handle in found if state.get("plays"))
        hint = "" if matched else " Check this player's path rows under Integrations."
        return {"player": player, "ok": bool(matched), "message":
                f"{NAMES[player]} listed {len(found)} items with a mapped path, {matched} match the library, {watched} are watched.{hint}"}
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as exc:
        return {"player": player, "ok": False, "message": f"{NAMES[player]}: {exc}"}
