"""Movie sets and tagged saved filters as collections in Jellyfin, Emby and Plex.

Kodi reads sets from the .nfo files. The other players get collections pushed here:
- every movie set with two or more movies in the library becomes a collection of those movies;
- every saved movie or TV filter with a tag becomes a collection of the movies or shows that carry that tag.

Items are matched by file path (movies) or folder (shows) through each player's path rows. Curator remembers the
collections it made (player_collections) and keeps their members exactly in step; a collection of the same name that
already exists is taken over. Collections Curator never made or took over are not touched, and a collection whose
set or filter is gone is emptied of the items Curator put in, not deleted.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime

import requests

from curator import automation, path_map
from resonance import db
from resonance.errors import AppError

logger = logging.getLogger(__name__)

PLAYERS = ("jellyfin", "emby", "plex")
NAMES = {"jellyfin": "Jellyfin", "emby": "Emby", "plex": "Plex"}
TIMEOUT = 60

_lock = threading.Lock()
_state = {"status": "idle", "message": "", "result": {}}
_log = deque(maxlen=300)


def status():
    with _lock:
        return {**_state, "log": "\n".join(_log)}


def _say(line):
    with _lock:
        _log.append(f"{datetime.now().strftime('%H:%M:%S')} {line}")
        _state["message"] = line


def _key(path):
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def wanted_collections(sets=True, tags=True):
    """{name: {"movies": {local file paths}, "shows": {local folders}}} from the library."""
    from curator.video import store

    found = {}
    if sets:
        in_set = {}
        for row in db.fetchall(
            """
            SELECT s.name, m.id::text AS movie_id, f.path AS file_path, m.parts
            FROM movie_sets s JOIN movies m ON m.set_id = s.id LEFT JOIN video_files f ON f.id = m.file_id
            WHERE NOT COALESCE(m.wanted, FALSE)
            """
        ):
            entry = found.setdefault(row["name"], {"movies": set(), "shows": set()})
            entry["movies"].update(store.movie_file_paths(row))
            in_set.setdefault(row["name"], set()).add(row.get("movie_id") or row["file_path"])
        found = {name: members for name, members in found.items() if len(in_set[name]) >= 2}
    if tags:
        for row in db.fetchall("SELECT media, tag FROM saved_filters WHERE media IN ('movies', 'tv') AND COALESCE(tag, '') <> ''"):
            entry = found.setdefault(row["tag"], {"movies": set(), "shows": set()})
            if row["media"] == "movies":
                rows = db.fetchall(
                    "SELECT f.path AS file_path, m.parts FROM movies m LEFT JOIN video_files f ON f.id = m.file_id "
                    "WHERE lower(%s) = ANY (SELECT lower(t) FROM unnest(m.tags) t)", (row["tag"],))
                for item in rows:
                    entry["movies"].update(store.movie_file_paths(item))
            else:
                rows = db.fetchall("SELECT path FROM tv_shows WHERE lower(%s) = ANY (SELECT lower(t) FROM unnest(tags) t)",
                                   (row["tag"],))
                entry["shows"].update(item["path"] for item in rows if item.get("path"))
    return {name: members for name, members in found.items() if members["movies"] or members["shows"]}


def _remembered(player):
    rows = db.fetchall("SELECT name, remote_id FROM player_collections WHERE player = %s", (player,))
    return {row["name"]: row["remote_id"] for row in rows}


def _remember(player, name, remote_id):
    db.execute(
        """
        INSERT INTO player_collections (player, name, remote_id) VALUES (%s, %s, %s)
        ON CONFLICT (player, name) DO UPDATE SET remote_id = EXCLUDED.remote_id
        """,
        (player, name, str(remote_id or "")),
    )


def _forget(player, name):
    db.execute("DELETE FROM player_collections WHERE player = %s AND name = %s", (player, name))


class MediaServer:
    def __init__(self, player, cfg):
        from curator import notify
        from curator.library_queue import mappings_for
        from curator.player_sync import MediaServer as Reader

        self.player = player
        self.url = notify._base(cfg[f"{player}_url"])
        self.headers = {**notify._auth_headers(player, cfg[f"{player}_token"]), "Accept": "application/json"}
        self.rows = mappings_for(player, cfg)
        self.user = Reader(player, cfg).user

    def _call(self, method, path, params=None):
        response = requests.request(method, f"{self.url}{path}", params=params, headers=self.headers, timeout=TIMEOUT)
        if response.status_code >= 400:
            raise RuntimeError(f"{NAMES[self.player]} answered HTTP {response.status_code} for {path}")
        return response.json() if response.content and "json" in response.headers.get("Content-Type", "") else {}

    def items(self):
        """{local path key: player id} for movies (file) and shows (folder)."""
        data = self._call("GET", f"/Users/{self.user}/Items",
                          {"Recursive": "true", "IncludeItemTypes": "Movie,Series", "Fields": "Path"})
        found = {}
        for item in data.get("Items") or []:
            local = path_map.from_player(item.get("Path") or "", self.rows)
            if local:
                found[_key(local)] = item["Id"]
        return found

    def collections(self):
        data = self._call("GET", f"/Users/{self.user}/Items", {"Recursive": "true", "IncludeItemTypes": "BoxSet"})
        return {item.get("Name"): item["Id"] for item in data.get("Items") or []}

    def members(self, collection_id):
        data = self._call("GET", f"/Users/{self.user}/Items", {"ParentId": collection_id})
        return {item["Id"] for item in data.get("Items") or []}

    def create(self, name, ids):
        reply = self._call("POST", "/Collections", {"Name": name, "Ids": ",".join(ids)})
        return reply.get("Id") or self.collections().get(name)

    def add(self, collection_id, ids):
        for start in range(0, len(ids), 100):
            self._call("POST", f"/Collections/{collection_id}/Items", {"Ids": ",".join(ids[start:start + 100])})

    def remove(self, collection_id, ids):
        for start in range(0, len(ids), 100):
            self._call("DELETE", f"/Collections/{collection_id}/Items", {"Ids": ",".join(ids[start:start + 100])})


class Plex:
    """Plex collections are tags on the items, set per library section."""

    def __init__(self, cfg):
        from curator import notify

        self.notify = notify
        self.cfg = cfg
        self.url = notify._base(cfg["plex_url"])
        self.token = cfg["plex_token"]
        self.rows = list(cfg.get("plex_paths") or [])
        self.where = {}   # rating key -> (section, type)
        self.tags = {}    # rating key -> {collection names}

    def items(self):
        found = {}
        for section in self.notify._plex_sections(self.cfg):
            if section.get("type") not in ("movie", "show"):
                continue
            key = str(section.get("key"))
            kind = 1 if section["type"] == "movie" else 2
            rows = self.notify._plex_json(self.url, self.token, f"/library/sections/{key}/all", {"type": kind})
            for row in rows:
                rating = str(row.get("ratingKey") or "")
                self.where[rating] = (key, kind)
                self.tags[rating] = {tag.get("tag") for tag in row.get("Collection") or [] if tag.get("tag")}
                paths = [file for file, _rating, _show in self.notify.plex_files([row])] if kind == 1 else \
                    [location.get("path") for location in row.get("Location") or [] if location.get("path")]
                for remote in paths:
                    local = path_map.from_player(remote, self.rows)
                    if local:
                        found[_key(local)] = rating
        return found

    def collections(self):
        names = set()
        for tags in self.tags.values():
            names |= tags
        return {name: name for name in names}

    def members(self, collection_id):
        return {rating for rating, tags in self.tags.items() if collection_id in tags}

    def _tag(self, ids, name, add):
        for rating in ids:
            section, kind = self.where.get(rating, (None, None))
            if not section:
                continue
            field = "collection[0].tag.tag" if add else "collection[].tag.tag-"
            response = requests.put(f"{self.url}/library/sections/{section}/all",
                                    params={"X-Plex-Token": self.token, "type": kind, "id": rating, field: name,
                                            "collection.locked": 1}, timeout=TIMEOUT)
            if response.status_code >= 400:
                raise RuntimeError(f"Plex answered HTTP {response.status_code}")

    def create(self, name, ids):
        self._tag(ids, name, True)
        return name

    def add(self, collection_id, ids):
        self._tag(ids, collection_id, True)

    def remove(self, collection_id, ids):
        self._tag(ids, collection_id, False)


def _client(player, cfg):
    return Plex(cfg) if player == "plex" else MediaServer(player, cfg)


def plan(wanted, items, existing, remembered):
    """[(name, collection id or None, ids to add, ids to remove)] for one player."""
    steps = []
    for name, members in sorted(wanted.items()):
        ids = sorted({items[_key(path)] for path in members["movies"] | members["shows"] if _key(path) in items})
        if not ids:
            continue
        steps.append((name, existing.get(name) or remembered.get(name), ids))
    return steps


def push(players=None):
    from curator.video import config

    _auto, cfg = automation.current()
    video = config.current()
    chosen = [player for player in (players or video.get("collections_players") or []) if player in PLAYERS]
    if not chosen:
        raise AppError("Tick Jellyfin, Emby or Plex under Collections first", 400)
    wanted = wanted_collections(video.get("collections_sets", True), video.get("collections_tags", True))
    result = {}
    for player in chosen:
        name = NAMES[player]
        if not (cfg.get(f"{player}_url") and cfg.get(f"{player}_token")):
            result[player] = {"error": f"{name} is not set up under Integrations"}
            continue
        try:
            _say(f"Reading {name}")
            client = _client(player, cfg)
            items = client.items()
            existing = client.collections()
            remembered = _remembered(player)
            made = changed = 0
            for title, collection_id, ids in plan(wanted, items, existing, remembered):
                if not collection_id:
                    collection_id = client.create(title, ids)
                    made += 1
                else:
                    have = client.members(collection_id)
                    missing = [item for item in ids if item not in have]
                    extra = sorted(have - set(ids)) if title in remembered else []
                    if missing:
                        client.add(collection_id, missing)
                    if extra:
                        client.remove(collection_id, extra)
                    changed += 1 if missing or extra else 0
                _remember(player, title, collection_id)
            for title, collection_id in remembered.items():
                if title not in wanted and collection_id:
                    have = client.members(collection_id)
                    if have:
                        client.remove(collection_id, sorted(have))
                    _forget(player, title)
            result[player] = {"created": made, "updated": changed}
            _say(f"{name}: {made} collections created, {changed} updated")
        except (RuntimeError, requests.RequestException) as exc:
            result[player] = {"error": str(exc)}
            _say(f"{name}: {exc}")
    return result


def start():
    with _lock:
        if _state["status"] == "running":
            return False
        _log.clear()
        _state.update({"status": "running", "message": "Starting", "result": {}})
    threading.Thread(target=_run, name="collections", daemon=True).start()
    return True


def _run():
    try:
        result = push()
        final, message = "done", "Collections are up to date"
    except AppError as exc:
        result, final, message = {}, "failed", str(exc)
    except Exception as exc:
        logger.exception("collection push failed")
        result, final, message = {}, "failed", str(exc)
    _say(message)
    with _lock:
        _state.update({"status": final, "message": message, "result": result})
