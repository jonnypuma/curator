"""One library-update worker per player.

The webhook queue scans Curator, then hands the folders here. Kodi, Emby,
Jellyfin, Plex, and Navidrome each run on their own thread, so a scan that hangs in one
does not hold the others or the ARR searches. Waiting rows for the same player
and media type collapse into one job.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
import logging
import threading
import uuid

from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

PLAYERS = ("kodi", "emby", "jellyfin", "plex", "navidrome")
_LABELS = {"kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex", "navidrome": "Navidrome"}
_MEDIA = {"movies": "Movies", "tv": "TV", "music": "Music", "video": "Video", "library": "Library"}

class _Quiet(Exception):
    """A finished job that has nothing worth a row in Recent library updates."""


class Cancelled(Exception):
    """A library job was removed while its player was still being watched."""


_stop = threading.Event()
_wake = {player: threading.Event() for player in PLAYERS}
_abort = {player: threading.Event() for player in PLAYERS}
_clean_due = {player: False for player in PLAYERS}
_clean_tries = {player: 0 for player in PLAYERS}
_bound = threading.local()
_queued_for = threading.local()
_threads = {}
_trigger = contextvars.ContextVar("library_trigger", default="")
TRIGGERS_KEPT = 6
RESTARTED = "Curator restarted while this update was running"


@contextmanager
def triggered_by(text):
    """Name what asks for the library updates queued inside this block, such as "Radarr webhook"."""
    token = _trigger.set(str(text or "").strip())
    try:
        yield
    finally:
        _trigger.reset(token)


def _trigger_for(message):
    """The trigger of a new request: the named one, else its message when that says who asked (a schedule, a button,
    Retry). A message that only lists titles ("Updated: Heat") names no trigger."""
    named = _trigger.get()
    if named:
        return named
    text = str(message or "").strip()
    if not text or text.lower().startswith(("updated", "removed", "added")):
        return ""
    return text


def merged_triggers(*groups):
    """Every trigger once, oldest first, at most TRIGGERS_KEPT (the rest become "and N more")."""
    found = []
    for group in groups:
        for text in ([group] if isinstance(group, str) else list(group or [])):
            text = str(text or "").strip()
            if text and text not in found and not text.startswith("and ") :
                found.append(text)
    if len(found) > TRIGGERS_KEPT:
        return found[:TRIGGERS_KEPT] + [f"and {len(found) - TRIGGERS_KEPT} more"]
    return found


def trigger_text(payload):
    """'Radarr webhook; Scheduled video library update', or '' when nothing was recorded."""
    return "; ".join(str(text) for text in ((payload or {}).get("triggers") or []) if str(text or "").strip())


def current_trigger():
    """The trigger of the library job running on this thread, for the alerts a player writes while it works."""
    return getattr(_bound, "trigger", "")


def owes_library_clean(player, payload):
    """A delete marks a Kodi video clean. It runs once, after the whole queue has finished."""
    payload = payload or {}
    if player != "kodi" or payload.get("clean_only"):
        return False
    return bool(payload.get("clean"))


def ready_for_clean(library_left, ingest_left):
    """True only when no library update and no video webhook is still waiting."""
    return int(library_left or 0) == 0 and int(ingest_left or 0) == 0


def bind(player):
    """Remember which player's worker is running on this thread."""
    _bound.player = player


def aborted():
    """True when the library job on this thread was cancelled."""
    player = getattr(_bound, "player", "")
    event = _abort.get(player)
    return bool(event and event.is_set())


def mappings_for(player, cfg):
    if player == "kodi":
        return [{"local": row.get("local") or "", "remote": row.get("kodi") or ""} for row in cfg.get("kodi_paths") or []]
    return list(cfg.get(f"{player}_paths") or [])


def scope_for(player, folders, cfg):
    """True when this player should scan its whole library for the media type."""
    from curator.notify import _mapped_paths

    folders = [folder for folder in folders or [] if str(folder or "").strip()]
    mappings = [row for row in mappings_for(player, cfg) if row.get("local") and row.get("remote")]
    if not folders or not mappings:
        return True, []
    mapped = _mapped_paths(folders, mappings)
    if not mapped:
        return True, []
    return False, mapped


def full_scan_reason(player, folders, cfg):
    """Why this update cannot scan only the changed folders. Empty when every folder maps."""
    from curator.automation import clean_path

    clean = [clean_path(folder) for folder in folders or [] if str(folder or "").strip()]
    mappings = [row for row in mappings_for(player, cfg) if str(row.get("local") or "").strip() and str(row.get("remote") or "").strip()]
    if not clean:
        return "no folder was included"
    if not mappings:
        return "no path mappings are saved"
    ranked = sorted(mappings, key=lambda row: len(clean_path(row.get("local") or "")), reverse=True)
    missing = []
    for folder in clean:
        matched = False
        for row in ranked:
            local = clean_path(row.get("local") or "")
            if folder == local or (local and folder.startswith(local + "/")):
                matched = True
                break
        if not matched and folder not in missing:
            missing.append(folder)
    if not missing:
        return ""
    shown = ", ".join(missing[:4])
    extra = len(missing) - 4
    if extra > 0:
        shown += f" and {extra} more"
    if len(missing) == 1:
        return f"{shown} is not mapped"
    return f"{shown} are not mapped"


def merge_key(player, media, full):
    """Kodi has one video library, so a full movie scan and a full TV scan are the same job."""
    if player == "kodi" and full and media in {"movies", "tv", "video"}:
        return f"{player}\nvideo\nfull"
    return f"{player}\n{media}\n{'full' if full else 'folders'}"


def same_library_job(player, media, full, other_media, other_full):
    """True when a new request should fold into a job that is still queued."""
    video = {"movies", "tv", "video", "library"}
    if player == "kodi" and media in video and other_media in video and (full or other_full):
        return True
    if player in {"emby", "jellyfin"} and (full or other_full):
        if media == "music" or other_media == "music":
            return media == other_media
        return True
    return media == other_media


def folded(player, media, full, paths, other=None, clean=False, items=(), reason="", quality=None):
    """The payload after one more request joins a queued job. A full scan drops folder paths and item names."""
    other = other or {}
    become_full = bool(full or other.get("full"))
    if player == "kodi" and become_full and media in {"movies", "tv", "video"}:
        stored = "video"
    elif player in {"emby", "jellyfin"} and become_full and media == "music":
        stored = "music"
    elif player in {"emby", "jellyfin"} and become_full:
        stored = "library"
    elif not become_full:
        stored = other.get("media") or media
    else:
        stored = other.get("media") or media
    found = []
    labels = []
    if not become_full:
        for path in list(other.get("paths") or []) + list(paths or []):
            if path not in found:
                found.append(path)
        for label in list(other.get("items") or []) + list(items or []):
            text = str(label or "").strip()
            if text and text not in labels:
                labels.append(text)
    known = {**(other.get("quality") or {}), **(quality or {})}
    return {
        "media": stored,
        "full": become_full,
        "paths": found,
        "items": labels,
        "quality": {label: known[label] for label in labels if known.get(label)},
        "clean": bool(clean or other.get("clean")),
        "message": other.get("message") or "",
        "reason": _kept_reason(become_full, full, reason, other),
        "merge": merge_key(player, stored, become_full),
    }


def _kept_reason(become_full, full, reason, other):
    """The full-scan explanation that should stay on a folded job."""
    if not become_full:
        return ""
    other = other or {}
    if full and reason:
        return reason
    if other.get("full") and other.get("reason"):
        return other.get("reason") or ""
    return reason or other.get("reason") or ""


def enabled_players(cfg):
    """Players that are switched on and have an address and a key."""
    from curator import notify

    players = []
    if notify._library_target(cfg):
        players.append("kodi")
    players.extend(name.lower() for name, _call in notify._ready_servers(cfg))
    from resonance.webhooks import navidrome_ready

    if navidrome_ready(cfg):
        players.append("navidrome")
    return players


def pick_players(requested, ready):
    """Chosen players split into ones that can be queued and ones that cannot."""
    allowed = set(ready or [])
    chosen, skipped, seen = [], [], set()
    for name in requested or []:
        key = str(name or "").strip().lower()
        if key not in PLAYERS or key in seen:
            continue
        seen.add(key)
        (chosen if key in allowed else skipped).append(key)
    return chosen, skipped


def _side_on(cfg, player, media):
    """True when this player's video or music switch allows the update."""
    cfg = cfg or {}
    music = media == "music"
    if cfg.get(f"{player}_on", True) is False:
        return False
    if player == "navidrome":
        return music and cfg.get("webhook_navidrome_enabled", True) is not False
    if player == "kodi":
        key, legacy = ("kodi_music_enabled", "kodi_library_enabled") if music else ("kodi_video_enabled", "kodi_library_enabled")
    else:
        key, legacy = (f"{player}_music_enabled", f"{player}_enabled") if music else (f"{player}_video_enabled", f"{player}_enabled")
    if key in cfg:
        return bool(cfg.get(key))
    return cfg.get(legacy, True) is not False


def _hosted_medias(player, medias, cfg):
    """Drop a media type when Emby, Jellyfin, or Plex has no library for it."""
    if player not in {"emby", "jellyfin", "plex"}:
        return list(medias)
    from curator import notify

    kinds = notify.hosted_kinds(player, cfg)
    if kinds is None:
        return list(medias)
    return [item for item in medias if item in kinds]


def queue_for(players, media, folders=(), clean=False, message="", cfg=None, items=(), quality=None):
    """Queue one library update per player. Returns how many jobs were queued."""
    if cfg is None:
        from curator import automation
        _, cfg = automation.current()
    queued = 0
    medias = ["movies", "tv"] if media in {"video", ""} else [media]
    for player in players:
        if player == "navidrome" and "music" not in medias:
            continue
        if not any(_side_on(cfg, player, item) for item in medias):
            continue
        medias_for_player = _hosted_medias(player, medias, cfg)
        if not medias_for_player:
            continue
        full, paths = scope_for(player, folders, cfg)
        reason = full_scan_reason(player, folders, cfg) if full else ""
        if player == "kodi" and full and (media in {"video", ""} or set(medias_for_player) >= {"movies", "tv"}):
            enqueue(player, "video", True, [], clean, message, items=items, reason=reason, quality=quality)
            queued += 1
            continue
        if player in {"emby", "jellyfin"} and full and medias_for_player == ["music"]:
            enqueue(player, "music", True, [], clean, message, items=items, reason=reason, quality=quality)
            queued += 1
            continue
        if player in {"emby", "jellyfin"} and full:
            enqueue(player, "library", True, [], clean, message, items=items, reason=reason, quality=quality)
            queued += 1
            continue
        if media in {"video", ""} and not full:
            enqueue(player, "video", False, paths, clean, message, items=items, quality=quality)
            queued += 1
            continue
        for item in medias_for_player:
            enqueue(player, item, full, paths, clean, message, items=items, reason=reason, quality=quality)
            queued += 1
    return queued


def request_clean(message=""):
    """Ask Kodi for one video library clean, with no scan, after Curator removed or replaced files.

    Kodi keeps the entry of a file that is gone until it is cleaned. Several requests fold into one waiting job. Nothing is
    queued when the clean is switched off or Kodi is not set up. Never raises: a missing clean must not fail the delete."""
    try:
        from curator import automation, notify

        _, cfg = automation.current()
        if not cfg.get("kodi_clean") or not notify._library_target(cfg) or not _side_on(cfg, "kodi", "movies"):
            return None
        return enqueue("kodi", "video", False, [], False, message or "Clean after removed files", clean_only=True)
    except Exception:
        logger.exception("could not queue the Kodi library clean")
        return None


def handoff(media, folders=(), clean=False, message="", items=(), quality=None):
    """Queue one library update per enabled player. Returns how many jobs were queued."""
    from curator import automation

    _, cfg = automation.current()
    return queue_for(enabled_players(cfg), media, folders, clean, message, cfg, items, quality)


def retry_target(source, message, path=""):
    """Player, full-library flag, and paths for a failed history row. None when it cannot be tried again."""
    player = str(source or "kodi").strip().lower()
    if player not in PLAYERS:
        return None
    stored = str(path or "").strip()
    if stored:
        return player, False, [stored if stored.endswith("/") else f"{stored}/"]
    text = str(message or "")
    where = ""
    for marker in (" library scan failed for ", " did not report a scan for "):
        if marker in text:
            where = text.split(marker, 1)[1]
            break
    if where:
        for sep in (". Kodi at ", ". Emby at ", ". Jellyfin at ", ". Plex at ", ". The rest", ". It stays"):
            if sep in where:
                where = where.split(sep, 1)[0]
                break
        else:
            where = where.split(". ", 1)[0]
        where = where.strip()
        if not where or where == "the full library":
            return player, True, []
        return player, False, [where if where.endswith("/") else f"{where}/"]
    lowered = text.lower()
    if "library refresh failed" in lowered or "library update failed" in lowered:
        return player, True, []
    return None


def retry_logged(source, message, path=""):
    """Queue the same library update again. Returns a short label, or None when it cannot."""
    found = retry_target(source, message, path)
    if not found:
        return None
    player, full, paths = found
    if player == "plex" and full:
        enqueue(player, "movies", True, [], False, "Retry button in Recent updates")
        enqueue(player, "tv", True, [], False, "Retry button in Recent updates")
        return "Plex movies and TV"
    if player == "kodi":
        if "music" in (message or "").lower() or (path and "/music" in path.lower().replace("\\", "/")):
            media = "music"
        else:
            media = "video"
    elif full and player in {"emby", "jellyfin"}:
        media = "library"
    else:
        media = "video"
    enqueue(player, media, full, paths, False, "Retry button in Recent updates")
    if full:
        return f"{_LABELS.get(player, player)} · Full scan"
    return paths[0] if paths else _LABELS.get(player, player)


def enqueue(player, media, full, paths=(), clean=False, message="", clean_only=False, items=(), reason="", quality=None):
    """Add or fold one library job. paths are already in that player's path layout."""
    if player not in PLAYERS or media not in {"movies", "tv", "music", "video", "library"}:
        return None
    _queued_for.player = player
    from resonance import db

    rows = db.fetchall(
        """
        SELECT id::text AS id, payload FROM work_queue
        WHERE lane = 'library' AND status = 'queued' AND kind = %s
        ORDER BY created_at ASC
        """,
        (player,),
    )
    rows = [row for row in rows if not (row.get("payload") or {}).get("refresh")]
    matches = [
        row for row in rows
        if bool((row.get("payload") or {}).get("clean_only")) == bool(clean_only)
        and same_library_job(player, media, full, (row.get("payload") or {}).get("media") or "", bool((row.get("payload") or {}).get("full")))
    ]
    if clean_only:
        matches = [row for row in rows if (row.get("payload") or {}).get("clean_only") and (row.get("payload") or {}).get("media") == media]
    if matches:
        payload = {}
        for row in matches:
            payload = folded(player, (row.get("payload") or {}).get("media") or media, bool((row.get("payload") or {}).get("full")), (row.get("payload") or {}).get("paths") or [], payload, bool((row.get("payload") or {}).get("clean")), (row.get("payload") or {}).get("items") or [], (row.get("payload") or {}).get("reason") or "", (row.get("payload") or {}).get("quality"))
        payload = folded(player, media, full, paths, payload, clean, items, reason, quality)
        payload["clean_only"] = bool(clean_only)
        payload["journeys"] = _journeys(*[(row.get("payload") or {}).get("journeys") for row in matches])
        payload["triggers"] = merged_triggers(*[(row.get("payload") or {}).get("triggers") for row in matches], _trigger_for(message))
        if message and not payload.get("message"):
            payload["message"] = message
        keep = matches[0]["id"]
        extras = [row["id"] for row in matches[1:]]
        if extras:
            db.execute("DELETE FROM work_queue WHERE id = ANY(%s::uuid[])", (extras,))
        db.execute(
            "UPDATE work_queue SET payload = %s, title = %s, source = %s WHERE id = %s",
            (Jsonb(payload), _title(player, payload["media"], payload["full"], payload["paths"], payload.get("clean_only"), payload.get("items")), payload["media"], keep),
        )
        _wake[player].set()
        return keep
    payload = folded(player, media, full, paths, clean=clean, items=items, reason=reason, quality=quality)
    payload["message"] = message or ""
    payload["clean_only"] = bool(clean_only)
    payload["journeys"] = _journeys()
    payload["triggers"] = merged_triggers(_trigger_for(message))
    row_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO work_queue (id, lane, kind, title, source, priority, status, payload)
        VALUES (%s, 'library', %s, %s, %s, 10, 'queued', %s)
        """,
        (row_id, player, _title(player, payload["media"], payload["full"], payload["paths"], clean_only, payload.get("items")), payload["media"], Jsonb(payload)),
    )
    _wake[player].set()
    return row_id


def _journeys(*earlier):
    """The webhook journeys a library job carries: the ones it already had and the ones bound to this thread.

    Each journey bound now gets this player's library stage, waiting."""
    from curator import journey

    now = journey.current()
    if now:
        player = getattr(_queued_for, "player", "")
        journey.stage(now, f"library:{player}" if player else "library", "waiting", "Queued for the player")
    found = []
    for item in [*[value for group in earlier for value in (group or [])], *now]:
        if item and item not in found:
            found.append(item)
    return found


def refresh_plan(player, media, items, cfg):
    """Whether this player takes a refresh of these items, and why not. Returns (ok, reason)."""
    if player == "navidrome":
        return False, ""                      # every music scan already sends Navidrome a scan
    art_only = bool(items) and all(item.get("kind") in ("set", "album", "artist") for item in items)
    if art_only and player != "kodi":
        return False, ""                      # only Kodi takes the artwork of a set, an album or an artist by itself
    if player == "kodi" and media == "music" and not art_only:
        return False, ""                      # every music scan already sends Kodi a music library scan
    if not _side_on(cfg, player, media):
        return False, ""
    if not _hosted_medias(player, [media], cfg):
        return False, ""
    if player in {"emby", "jellyfin", "plex"}:
        full, _paths = scope_for(player, [item.get("folder") for item in items], cfg)
        if full:
            label = _LABELS.get(player, player)
            return False, f"{label} was left out: {full_scan_reason(player, [item.get('folder') for item in items], cfg) or 'a folder has no path row'}"
    return True, ""


def _merge_refresh(kept, item):
    full = (not kept.get("art") or kept.get("full")) or (not item.get("art") or item.get("full"))
    if item.get("art"):
        kept["art"] = {**(kept.get("art") or {}), **item["art"]}
    if kept.get("art") and full:
        kept["full"] = True


def art_players(media, cfg=None):
    """The players an artwork refresh of this media can go to: switched on, with an address, and on for this media.
    [{"id", "label"}] in the order of Settings, for the per-player boxes."""
    if cfg is None:
        from curator import automation

        _, cfg = automation.current()
    return [{"id": player, "label": _LABELS.get(player, player)} for player in enabled_players(cfg)
            if player != "navidrome" and _side_on(cfg, player, media)]


def queue_refresh(media, items, cfg=None, players=None):
    """Queue a refresh of changed items on each player. Returns (players queued, reasons for players left out).

    One waiting refresh job per player and media type; a second one adds its items to it."""
    from resonance import db

    if cfg is None:
        from curator import automation

        _, cfg = automation.current()
    queued, skipped = [], []
    chosen = None if players is None else {str(name).lower() for name in players}
    for player in enabled_players(cfg):
        if chosen is not None and player not in chosen:
            continue                      # its box was left unticked
        ok, reason = refresh_plan(player, media, items, cfg)
        if not ok:
            if reason:
                skipped.append(reason)
            continue
        rows = db.fetchall(
            """
            SELECT id::text AS id, payload FROM work_queue
            WHERE lane = 'library' AND status = 'queued' AND kind = %s
            ORDER BY created_at ASC
            """,
            (player,),
        )
        mine = next((row for row in rows if (row.get("payload") or {}).get("refresh") and (row.get("payload") or {}).get("media") == media), None)
        merged = [dict(item) for item in ((mine or {}).get("payload") or {}).get("refresh") or []]
        seen = {(item.get("kind"), item.get("path") or item.get("folder")): item for item in merged}
        for item in items:
            key = (item.get("kind"), item.get("path") or item.get("folder"))
            if key not in seen:
                seen[key] = dict(item)
                merged.append(seen[key])
                continue
            # The same item twice: an artwork-only refresh (art) and a full one combine into a full refresh that also
            # shows the new pictures.
            _merge_refresh(seen[key], item)
        labels = [item.get("label") or "" for item in merged if item.get("label")]
        payload = {"media": media, "full": False, "paths": [], "items": labels, "refresh": merged, "clean": False,
                   "clean_only": False, "message": "Updated during a scan", "reason": "", "merge": f"{player}\n{media}\nrefresh"}
        title = _refresh_title(player, media, labels)
        if mine:
            db.execute("UPDATE work_queue SET payload = %s, title = %s WHERE id = %s", (Jsonb(payload), title, mine["id"]))
        else:
            db.execute(
                """
                INSERT INTO work_queue (id, lane, kind, title, source, priority, status, payload)
                VALUES (%s, 'library', %s, %s, %s, 10, 'queued', %s)
                """,
                (str(uuid.uuid4()), player, title, media, Jsonb(payload)),
            )
        _wake[player].set()
        queued.append(_LABELS.get(player, player))
    return queued, skipped


def _refresh_title(player, media, labels):
    head = f"{_LABELS.get(player, player)} · {_MEDIA.get(media, media)} · Refresh"
    if not labels:
        return head
    shown = ", ".join(labels[:4])
    extra = len(labels) - 4
    return f"{head} · {shown}" + (f" and {extra} more" if extra > 0 else "")


def history_title(row):
    """The movie or show names for the history. A single folder name fills in when no title was stored."""
    payload = (row or {}).get("payload") or {}
    labels = [str(item).strip() for item in (payload.get("items") or []) if str(item or "").strip()]
    if labels:
        shown = ", ".join(labels[:8])
        extra = len(labels) - 8
        return shown + (f" and {extra} more" if extra > 0 else "")
    paths = payload.get("paths") or []
    if len(paths) == 1:
        return str(paths[0]).rstrip("/\\").split("/")[-1].split("\\")[-1]
    return (row or {}).get("title") or ""


def history_quality(row):
    """Badge facts for the named items, in the order the history title lists them."""
    from curator.queue_quality import pick

    payload = (row or {}).get("payload") or {}
    return pick(payload.get("quality"), payload.get("items"))


def history_path(row):
    """The folder under the title when the update was one folder."""
    paths = ((row or {}).get("payload") or {}).get("paths") or []
    if len(paths) == 1:
        return str(paths[0])
    return ""


def _title(player, media, full, paths, clean_only=False, items=()):
    name = _LABELS.get(player, player)
    head = name if media == "library" else f"{name} · {_MEDIA.get(media, media)}"
    if clean_only:
        return f"{head} · Clean"
    if full:
        return f"{head} · Full scan"
    labels = [str(item).strip() for item in items or [] if str(item or "").strip()]
    if labels:
        shown = ", ".join(labels[:4])
        extra = len(labels) - 4
        if extra > 0:
            shown += f" and {extra} more"
        return f"{head} · {shown}"
    count = len(paths or [])
    return f"{head} · {count} folder{'s' if count != 1 else ''}"


def snapshot():
    from resonance import db

    if db.pool is None:
        return []
    rows = db.fetchall(
        """
        SELECT id::text AS id, kind, title, source, status, payload, started_at,
               GREATEST(0, EXTRACT(EPOCH FROM (LOCALTIMESTAMP - started_at)))::int AS running_for
        FROM work_queue
        WHERE lane = 'library' AND status IN ('queued', 'running')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at ASC
        """
    )
    return [_public(row) for row in rows]


def _public(row):
    payload = row.get("payload") or {}
    player = row.get("kind") or ""
    media = row.get("source") or payload.get("media") or ""
    full = bool(payload.get("full"))
    paths = payload.get("paths") or []
    items = [str(item).strip() for item in (payload.get("items") or []) if str(item or "").strip()]
    return {
        "id": str(row["id"]),
        "title": _refresh_title(player, media, items) if payload.get("refresh") else _title(player, media, full, paths, payload.get("clean_only"), items),
        "player": player,
        "where": _LABELS.get(player, player),
        "source": player,
        "media": "All" if media == "library" else _MEDIA.get(media, media),
        "items": items,
        "quality": history_quality(row),
        "scope": _scope_label(payload, full, paths),
        "trigger": trigger_text(payload),
        "status": row.get("status") or "queued",
        "running_seconds": _running_seconds(row),
        "progress": _progress(player, media, row.get("status")),
    }


def _progress(player, media, status):
    """Which folder Kodi is on, for the running Kodi row; None for the other players and for waiting rows."""
    if player != "kodi" or status != "running":
        return None
    try:
        from curator import notify

        return notify.kodi_progress("music" if str(media or "").lower() == "music" else "video")
    except Exception:
        return None


def _running_seconds(row):
    if (row.get("status") or "") != "running":
        return None
    from curator.queue_time import elapsed

    return elapsed(row)


def _scope_label(payload, full, paths):
    if payload.get("clean_only"):
        return "Clean"
    if payload.get("refresh"):
        count = len(payload.get("refresh") or [])
        return f"Refresh {count} item{'s' if count != 1 else ''}"
    if full:
        reason = str(payload.get("reason") or "").strip()
        if reason:
            return f"Full scan · {reason}"
        return "Full scan"
    count = len(paths or [])
    return f"{count} folder{'s' if count != 1 else ''}"


def drop(item_id):
    from resonance import db

    rows = db.fetchall(
        "DELETE FROM work_queue WHERE id = %s AND lane = 'library' AND status = 'queued' RETURNING id",
        (str(item_id),),
    )
    return bool(rows)


def cancel(item_id):
    """Remove a waiting or running library job. A running job stops waiting for its player."""
    from resonance import db

    row = db.fetchone(
        """
        SELECT id::text AS id, kind, status
        FROM work_queue
        WHERE id = %s AND lane = 'library' AND status IN ('queued', 'running')
        """,
        (str(item_id),),
    )
    if not row:
        return None
    if row.get("status") == "running":
        event = _abort.get(row.get("kind") or "")
        if event:
            event.set()
    db.execute("DELETE FROM work_queue WHERE id = %s AND lane = 'library'", (str(item_id),))
    return row.get("status") or "queued"


def clear_waiting():
    from resonance import db

    rows = db.fetchall(
        "DELETE FROM work_queue WHERE lane = 'library' AND status = 'queued' RETURNING id"
    )
    return len(rows)


def start():
    """Move leftover Kodi rows off the ARR lane, then start one worker per player."""
    from resonance import db

    db.execute(
        """
        UPDATE work_queue
        SET lane = 'library', payload = payload || '{"legacy": true}'::jsonb
        WHERE lane = 'arr' AND kind = 'kodi'
        """
    )
    # An update that was running when Curator stopped runs again. It says so, or the repeat looks like a new request.
    db.execute(
        """
        UPDATE work_queue
        SET status = 'queued', started_at = NULL,
            payload = CASE WHEN COALESCE(payload->'triggers', '[]'::jsonb) @> %s THEN payload
                           ELSE jsonb_set(payload, '{triggers}', COALESCE(payload->'triggers', '[]'::jsonb) || %s) END
        WHERE lane = 'library' AND status = 'running'
        """,
        (Jsonb([RESTARTED]), Jsonb([RESTARTED])),
    )
    _stop.clear()
    for player in PLAYERS:
        thread = _threads.get(player)
        if thread and thread.is_alive():
            _wake[player].set()
            continue
        thread = threading.Thread(target=_worker, args=(player,), name=f"library-{player}", daemon=True)
        _threads[player] = thread
        thread.start()


def stop():
    _stop.set()
    for event in _wake.values():
        event.set()


def _announce_failure(player):
    label = {"kodi": "Kodi", "emby": "Emby", "jellyfin": "Jellyfin", "plex": "Plex", "navidrome": "Navidrome"}.get(player, player)
    try:
        from curator import notify

        notify.announce("failed", f"{label} library update failed.")
    except Exception:
        logger.exception("could not show the library failure")


def _worker(player):
    """One player's queue. A database error (a dropped connection, Postgres restarting) is logged and the loop goes on
    after a pause: before, it ended the thread, and that player got no more library updates until Curator restarted."""
    while not _stop.is_set():
        try:
            _worker_step(player)
        except Exception:
            logger.exception("library queue for %s hit an error; trying again in 10 seconds", player)
            _stop.wait(10)


def _worker_step(player):
    """Claim and run one job, or wait a moment for one."""
    _abort[player].clear()
    row = _claim(player)
    if not row and _clean_due[player]:
        if updates_finished(player):
            _run_deferred_clean(player)
        else:
            _wake[player].wait(5)
            _wake[player].clear()
        return
    if not row:
        _wake[player].wait(5)
        _wake[player].clear()
        return
    _finish_row(player, row)


def _finish_row(player, row):
    if owes_library_clean(player, row.get("payload")):
        _clean_due[player] = True
    bind(player)
    _bound.trigger = trigger_text(row.get("payload"))
    failed = None
    stopped = False
    detail = ""
    from curator import journey

    trips = (row.get("payload") or {}).get("journeys") or []
    journey.stage(trips, f"library:{player}", "running", "The player is updating its library")
    try:
        detail = _execute(player, row) or ""
    except Cancelled:
        stopped = True
        detail = "Cancelled"
    except Exception as exc:
        failed = exc
        logger.exception("%s library update failed: %s", player, row.get("title"))
        from resonance.connections import note

        note(player, str(exc))
        _announce_failure(player)
    else:
        from resonance.connections import clear

        clear(player)
    finally:
        try:
            from curator import work_log

            text = str(failed) if failed else detail
            quiet = bool((row.get("payload") or {}).get("refresh")) and not failed and not stopped and not text
            if quiet:
                # An artwork refresh that found nothing to do on the player (the item is not there yet) leaves no row.
                journey.stage(trips, f"library:{player}", "skipped", "Nothing to refresh on the player yet")
                raise _Quiet()
            if not failed and not stopped and not text:
                label = {"kodi": "Kodi", "jellyfin": "Jellyfin", "emby": "Emby", "plex": "Plex", "navidrome": "Navidrome"}.get(player, str(player or "").title())
                payload = row.get("payload") or {}
                paths = payload.get("paths") or payload.get("folders") or []
                full = bool(payload.get("full"))
                media = payload.get("media") or row.get("source") or "video"
                noun = "music" if media == "music" else "video"
                if paths and not full:
                    count = len(paths)
                    text = f"{label} updated {count} folder{'s' if count != 1 else ''}."
                else:
                    text = f"{label} finished scanning the {noun} library."
            reason = str((row.get("payload") or {}).get("reason") or "").strip()
            if reason and reason not in text:
                text = f"{text} Full scan because {reason}.".strip()
            asked = trigger_text(row.get("payload"))
            if asked:
                text = f"{text} Triggered by: {asked}.".strip()
            _bound.trigger = ""
            work_log.note(
                "library",
                player,
                row.get("source") or "",
                history_title(row),
                history_path(row),
                "error" if failed else "cleared" if stopped else "done",
                text,
                quality=history_quality(row),
            )
            journey.stage(trips, f"library:{player}", "failed" if failed else "skipped" if stopped else "done", text)
        except _Quiet:
            pass
        except Exception:
            logger.exception("could not record the library update")
        try:
            from resonance import db

            db.execute("DELETE FROM work_queue WHERE id = %s", (row["id"],))
        except Exception:
            logger.exception("could not remove the finished library update")
        _wake[player].set()


def updates_finished(player):
    """True when this player has no library job left and no video webhook is still coming."""
    from resonance import db

    library = db.fetchone(
        """
        SELECT count(*)::int AS n FROM work_queue
        WHERE lane = 'library' AND kind = %s AND status IN ('queued', 'running')
        """,
        (player,),
    )
    ingest = db.fetchone(
        """
        SELECT count(*)::int AS n FROM ingest_queue
        WHERE status IN ('queued', 'running') AND media IN ('movies', 'tv')
        """
    )
    return ready_for_clean((library or {}).get("n"), (ingest or {}).get("n"))


def _run_deferred_clean(player):
    """One video-library clean, after every queued update has already been sent."""
    if player != "kodi" or not updates_finished(player):
        return
    from curator import notify

    failed = None
    try:
        outcome = notify.clean_after_queue()
        if outcome is False:
            return
        if outcome is None:
            # Kodi refused the clean, or it could not be reached (the activity log has why). Try once more before giving up.
            if _clean_tries.get(player, 0) < 1:
                _clean_tries[player] = _clean_tries.get(player, 0) + 1
                _wake[player].wait(30)
                _wake[player].clear()
                return
            failed = RuntimeError("Kodi did not accept the library clean, even after a second try. See the activity log.")
    except Cancelled:
        logger.info("%s library clean was cancelled", player)
        return
    except Exception as exc:
        failed = exc
        logger.exception("%s library clean failed", player)
    _clean_tries[player] = 0
    _clean_due[player] = False
    try:
        from curator import work_log

        work_log.note(
            "library",
            player,
            "Clean",
            "Kodi · Video · Clean",
            "",
            "error" if failed else "done",
            str(failed) if failed else "Kodi finished cleaning the video library.",
        )
    except Exception:
        logger.exception("could not record deferred Kodi clean in work_log")


def _claim(player):
    from resonance import db

    return db.fetchone(
        """
        WITH picked AS (
            SELECT id FROM work_queue
            WHERE lane = 'library' AND kind = %s AND status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE work_queue SET status = 'running', started_at = LOCALTIMESTAMP
        FROM picked
        WHERE work_queue.id = picked.id
        RETURNING work_queue.id::text AS id, work_queue.kind, work_queue.title,
                  work_queue.source, work_queue.payload
        """,
        (player,),
    )


def _execute(player, row):
    from curator import notify

    payload = row.get("payload") or {}
    if payload.get("clean_only"):
        kind = "music" if (payload.get("media") or "") == "music" else "video"
        notify.clean_kodi(kind)
        return f"Kodi finished cleaning the {kind} library."
    names = payload.get("items") or []
    if payload.get("refresh"):
        return notify.refresh_items(player, payload.get("media") or row.get("source") or "", payload["refresh"])
    if payload.get("full") and not payload.get("legacy") and RESTARTED in (payload.get("triggers") or []):
        # The player kept scanning while Curator was down. Sending the same full scan again would only repeat it, so
        # wait for the one in progress (the jobs behind it must not start early) and call this job done.
        media = payload.get("media") or row.get("source") or "video"
        if notify.full_scan_running(player, media):
            label = _LABELS.get(player, player)
            noun = "" if media == "library" else "music " if media == "music" else "video "
            text = f"{label} was still running this {noun}library scan when Curator came back, so it was not sent again."
            if player == "kodi":
                notify._activity(f"{text}{notify._asked_by()}", "noted", "", "the full library")
            notify.wait_full_scan(player, media)
            return text
    if payload.get("legacy"):
        return notify.run_kodi(payload.get("media") or "video", payload.get("folders") or [], False, payload.get("message"), names)
    return notify.run_library(
        player,
        payload.get("media") or row.get("source") or "video",
        bool(payload.get("full")),
        payload.get("paths") or [],
        False,
        names,
    )
