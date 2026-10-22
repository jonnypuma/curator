"""Scheduler for curator-side periodic tasks: player update and clean schedules."""
import datetime
import logging
import threading
import time

logger = logging.getLogger(__name__)
_started = False


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="curator-schedule", daemon=True).start()


def _loop():
    last_fired: dict = {}
    last_checked_utc = None
    while True:
        try:
            from resonance import cron
            from resonance.settings import load as load_settings

            cfg = load_settings()
            schedules = cfg.get("player_clean_schedules") or []
            if schedules:
                tz = cron.get_timezone()
                now = datetime.datetime.now(tz)
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                current_minute = (now.year, now.month, now.day, now.hour, now.minute)
                current_keys: set = set()
                for item in schedules:
                    expr = str(item.get("cron") or "")
                    player = str(item.get("player") or "kodi")
                    media = str(item.get("media") or "video")
                    kind = str(item.get("kind") or "clean")
                    sched_key = f"{player}:{kind}:{media}:{expr}"
                    current_keys.add(sched_key)
                    if last_fired.get(sched_key) == current_minute:
                        continue
                    matched = cron.matches_cron(now, expr)
                    if not matched and last_checked_utc is not None:
                        gap_seconds = (now_utc - last_checked_utc).total_seconds()
                        if 60 <= gap_seconds <= 7200:
                            chk = last_checked_utc + datetime.timedelta(minutes=1)
                            while chk < now_utc:
                                if cron.matches_cron(chk.astimezone(tz), expr):
                                    matched = True
                                    break
                                chk += datetime.timedelta(minutes=1)
                    if not matched:
                        continue
                    last_fired[sched_key] = current_minute
                    logger.info(
                        "Triggering scheduled %s %s %s for %s",
                        player,
                        media,
                        kind,
                        expr,
                    )
                    _fire_schedule(player, media, kind)
                last_checked_utc = now_utc
                last_fired = {k: v for k, v in last_fired.items() if k in current_keys}
        except Exception:
            logger.exception("curator schedule check failed")
        time.sleep(15)


def _fire_schedule(player: str, media: str, kind: str = "clean") -> None:
    """Run one saved player schedule.

    A clean removes entries whose files are gone: Kodi has VideoLibrary.Clean /
    AudioLibrary.Clean and Plex has Empty Trash on a section. Emby and Jellyfin have no
    separate clean, so a clean asked of them runs as an update, which is what drops their
    missing items. An update is an ordinary library scan for every player.
    """
    from resonance.settings import PLAYER_CLEAN_SUPPORT

    try:
        from curator import automation
        from curator.library_queue import PLAYERS, enabled_players, enqueue, queue_for

        _, cfg = automation.current()
        if player not in PLAYERS or player not in enabled_players(cfg):
            logger.warning("Scheduled %s skipped: %s not enabled", kind, player)
            return

        wants_clean = kind == "clean" and player in PLAYER_CLEAN_SUPPORT
        label = "clean" if wants_clean else "update"
        note = f"Scheduled {media} library {label}"

        if wants_clean and player == "kodi":
            stored = "music" if media == "music" else "video"
            enqueue("kodi", stored, False, [], False, note, clean_only=True)
            return
        if wants_clean and player == "plex":
            from curator import notify

            logger.info("%s", notify.clean_plex(media))
            return

        # Update, and the fallback for a clean on a player without one: a full library scan,
        # which is also how Emby and Jellyfin drop entries that no longer exist on disk.
        if player == "kodi":
            stored = "music" if media == "music" else "video"
            enqueue("kodi", stored, True, [], False, note)
            return
        from curator import folders as folder_mod

        media_key = "music" if media == "music" else "movies"
        roots = folder_mod.mounted(media_key)
        if roots:
            queue_for([player], media_key, roots, True, note, cfg)
    except Exception as exc:
        logger.error("Scheduled %s for %s/%s failed: %s", kind, player, media, exc)
