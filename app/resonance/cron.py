import datetime
import logging
import os
import zoneinfo

logger = logging.getLogger(__name__)

DAYS_MAP = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
    "SUNDAY": 0,
    "MONDAY": 1,
    "TUESDAY": 2,
    "WEDNESDAY": 3,
    "THURSDAY": 4,
    "FRIDAY": 5,
    "SATURDAY": 6,
}

WEEKDAY_NAMES = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
]

MONTHS_MAP = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

PRESETS = [
    {"id": "every_15m", "group": "Often", "name": "Every 15 minutes", "cron": "*/15 * * * *", "description": "Every 15 minutes"},
    {"id": "every_30m", "group": "Often", "name": "Every 30 minutes", "cron": "*/30 * * * *", "description": "Every 30 minutes"},
    {"id": "hourly", "group": "Often", "name": "Every hour", "cron": "0 * * * *", "description": "At minute 0 of every hour"},
    {"id": "every_2h", "group": "Often", "name": "Every 2 hours", "cron": "0 */2 * * *", "description": "Every 2 hours at minute 0"},
    {"id": "every_3h", "group": "Often", "name": "Every 3 hours", "cron": "0 */3 * * *", "description": "Every 3 hours at minute 0"},
    {"id": "every_4h", "group": "Often", "name": "Every 4 hours", "cron": "0 */4 * * *", "description": "Every 4 hours at minute 0"},
    {"id": "every_6h", "group": "Often", "name": "Every 6 hours", "cron": "0 */6 * * *", "description": "Every 6 hours at minute 0"},
    {"id": "every_12h", "group": "Often", "name": "Every 12 hours", "cron": "0 */12 * * *", "description": "Every 12 hours at minute 0"},
    {"id": "twice_daily", "group": "Every day", "name": "Twice a day (midnight and noon)", "cron": "0 0,12 * * *", "description": "Twice a day, at midnight and noon"},
    {"id": "daily_midnight", "group": "Every day", "name": "Daily at midnight (00:00)", "cron": "0 0 * * *", "description": "Every day at midnight"},
    {"id": "daily_0200", "group": "Every day", "name": "Daily at 02:00", "cron": "0 2 * * *", "description": "Every day at 02:00"},
    {"id": "daily_0300", "group": "Every day", "name": "Daily at 03:00", "cron": "0 3 * * *", "description": "Every day at 03:00"},
    {"id": "daily_0400", "group": "Every day", "name": "Daily at 04:00", "cron": "0 4 * * *", "description": "Every day at 04:00"},
    {"id": "daily_0600", "group": "Every day", "name": "Daily at 06:00", "cron": "0 6 * * *", "description": "Every day at 06:00"},
    {"id": "daily_noon", "group": "Every day", "name": "Daily at noon (12:00)", "cron": "0 12 * * *", "description": "Every day at noon"},
    {"id": "weekdays_midnight", "group": "Weekdays and weekends", "name": "Weekdays (Mon–Fri) at midnight", "cron": "0 0 * * 1-5", "description": "Monday through Friday at midnight"},
    {"id": "weekdays_0300", "group": "Weekdays and weekends", "name": "Weekdays (Mon–Fri) at 03:00", "cron": "0 3 * * 1-5", "description": "Monday through Friday at 03:00"},
    {"id": "weekends_midnight", "group": "Weekdays and weekends", "name": "Weekends (Sat–Sun) at midnight", "cron": "0 0 * * 6,0", "description": "Saturday and Sunday at midnight"},
    {"id": "weekends_0300", "group": "Weekdays and weekends", "name": "Weekends (Sat–Sun) at 03:00", "cron": "0 3 * * 6,0", "description": "Saturday and Sunday at 03:00"},
    {"id": "weekly_sun_midnight", "group": "Every week", "name": "Weekly on Sunday at midnight", "cron": "0 0 * * 0", "description": "Every Sunday at midnight"},
    {"id": "weekly_sun_0200", "group": "Every week", "name": "Weekly on Sunday at 02:00", "cron": "0 2 * * 0", "description": "Every Sunday at 02:00"},
    {"id": "weekly_sun_0300", "group": "Every week", "name": "Weekly on Sunday at 03:00", "cron": "0 3 * * 0", "description": "Every Sunday at 03:00"},
    {"id": "weekly_mon_midnight", "group": "Every week", "name": "Weekly on Monday at midnight", "cron": "0 0 * * 1", "description": "Every Monday at midnight"},
    {"id": "weekly_mon_0300", "group": "Every week", "name": "Weekly on Monday at 03:00", "cron": "0 3 * * 1", "description": "Every Monday at 03:00"},
    {"id": "weekly_wed_0300", "group": "Every week", "name": "Weekly on Wednesday at 03:00", "cron": "0 3 * * 3", "description": "Every Wednesday at 03:00"},
    {"id": "weekly_fri_0300", "group": "Every week", "name": "Weekly on Friday at 03:00", "cron": "0 3 * * 5", "description": "Every Friday at 03:00"},
    {"id": "weekly_sat_midnight", "group": "Every week", "name": "Weekly on Saturday at midnight", "cron": "0 0 * * 6", "description": "Every Saturday at midnight"},
    {"id": "monthly_1st_midnight", "group": "Every month", "name": "Monthly on the 1st at midnight", "cron": "0 0 1 * *", "description": "1st day of every month at midnight"},
    {"id": "monthly_1st_0300", "group": "Every month", "name": "Monthly on the 1st at 03:00", "cron": "0 3 1 * *", "description": "1st day of every month at 03:00"},
    {"id": "monthly_1st_0400", "group": "Every month", "name": "Monthly on the 1st at 04:00", "cron": "0 4 1 * *", "description": "1st day of every month at 04:00"},
    {"id": "monthly_15th_midnight", "group": "Every month", "name": "Monthly on the 15th at midnight", "cron": "0 0 15 * *", "description": "15th day of every month at midnight"},
    {"id": "monthly_15th_0300", "group": "Every month", "name": "Monthly on the 15th at 03:00", "cron": "0 3 15 * *", "description": "15th day of every month at 03:00"},
]

PRESETS_BY_ID = {preset["id"]: preset for preset in PRESETS}
PRESETS_BY_CRON = {preset["cron"]: preset for preset in PRESETS}


def get_timezone():
    """Resolve the local timezone configured in CMM_TIMEZONE (or TZ) or system fallback.

    CMM_TIMEZONE takes precedence over TZ so the app TZ setting and the cron TZ agree.
    zoneinfo handles DST transitions correctly, including the spring-forward gap and the
    fall-back fold; naive datetimes are never used for scheduling.
    """
    for env_var in ("CMM_TIMEZONE", "TZ"):
        tz_name = os.environ.get(env_var, "").strip()
        if tz_name:
            try:
                return zoneinfo.ZoneInfo(tz_name)
            except Exception:
                logger.warning("Invalid timezone %r in %s, falling back", tz_name, env_var)
    try:
        return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc
    except Exception:
        return datetime.timezone.utc


def ordinal(n):
    """Format ordinal number (1st, 2nd, 3rd, 4th, etc.)."""
    n_int = int(n)
    if 11 <= (n_int % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n_int % 10, "th")
    return f"{n_int}{suffix}"


def parse_cron_part(part, min_val, max_val, names=None):
    """Parse one field of a crontab expression into a set of allowed integer values."""
    allowed = set()
    for sub in part.split(","):
        sub = sub.strip()
        if not sub:
            continue
        step = 1
        has_step = "/" in sub
        if has_step:
            sub, step_s = sub.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError("Invalid cron step value")
        if sub in ("*", ""):
            start, end = min_val, max_val
        elif "-" in sub:
            s_str, e_str = sub.split("-", 1)
            start = names[s_str.upper()] if names and s_str.upper() in names else int(s_str)
            end = names[e_str.upper()] if names and e_str.upper() in names else int(e_str)
        else:
            val = names[sub.upper()] if names and sub.upper() in names else int(sub)
            if has_step:
                start = val
                end = max_val
            else:
                start = end = val
        if min_val == 0:
            if start == 7:
                start = 0
            if end == 7 and start == 0:
                end = 6
            elif end == 7:
                end = 0
        if start > end:
            allowed.update(range(start, max_val + 1, step))
            allowed.update(range(min_val, end + 1, step))
        else:
            allowed.update(range(start, end + 1, step))
    res = {v for v in allowed if min_val <= v <= max_val or (min_val == 0 and v == 7)}
    if min_val == 0 and 7 in res:
        res.add(0)
        res.discard(7)
    return res


def parse_cron(expr):
    """
    Parse a standard 5-field cron expression.
    Returns (mins, hours, doms, months, dows, dom_is_star, dow_is_star) or None if invalid.
    """
    if not isinstance(expr, str):
        return None
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    try:
        mins = parse_cron_part(parts[0], 0, 59)
        hours = parse_cron_part(parts[1], 0, 23)
        doms = parse_cron_part(parts[2], 1, 31)
        months = parse_cron_part(parts[3], 1, 12, MONTHS_MAP)
        dows = parse_cron_part(parts[4], 0, 6, DAYS_MAP)
        if not (mins and hours and doms and months and dows):
            return None
        if parts[2] != "*":
            month_max = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
            if not any(any(d <= month_max[m] for d in doms) for m in months):
                return None
        return (mins, hours, doms, months, dows, parts[2] == "*", parts[4] == "*")
    except Exception:
        return None


def validate_cron(expr):
    """Return True if expr is a valid 5-part cron expression."""
    return parse_cron(expr) is not None


def matches_cron(dt, cron_expr):
    """Check if the given datetime dt matches cron_expr."""
    parsed = parse_cron(cron_expr)
    if not parsed:
        return False
    mins, hours, doms, months, dows, dom_is_star, dow_is_star = parsed
    if dt.minute not in mins:
        return False
    if dt.hour not in hours:
        return False
    if dt.month not in months:
        return False
    cron_dow = (dt.weekday() + 1) % 7
    if dom_is_star and dow_is_star:
        return True
    if not dom_is_star and not dow_is_star:
        return (dt.day in doms) or (cron_dow in dows)
    if not dom_is_star:
        return dt.day in doms
    return cron_dow in dows


def next_cron_run(cron_expr, now=None, tz=None):
    """
    Compute the next matching datetime (in timezone tz or now's timezone) after `now`.
    Returns None if the cron expression is invalid.
    """
    parsed = parse_cron(cron_expr)
    if not parsed:
        return None
    mins, hours, doms, months, dows, dom_is_star, dow_is_star = parsed
    if tz is None:
        tz = get_timezone()
    if now is None:
        now = datetime.datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    cur = (now + datetime.timedelta(minutes=1)).replace(second=0, microsecond=0)
    # Search up to 5 years into the future
    for _ in range(525600 * 5):
        if cur.month not in months:
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1, day=1, hour=0, minute=0)
            else:
                cur = cur.replace(month=cur.month + 1, day=1, hour=0, minute=0)
            continue

        cron_dow = (cur.weekday() + 1) % 7
        day_match = (
            True
            if (dom_is_star and dow_is_star)
            else ((cur.day in doms) or (cron_dow in dows))
            if (not dom_is_star and not dow_is_star)
            else (cur.day in doms)
            if not dom_is_star
            else (cron_dow in dows)
        )
        if not day_match:
            cur = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0)
            continue

        if cur.hour not in hours:
            cur = (cur + datetime.timedelta(hours=1)).replace(minute=0)
            continue

        if cur.minute in mins:
            return cur

        cur += datetime.timedelta(minutes=1)
    return None


def parse_time_parts(time_str):
    """Parse 'HH:MM' into (hour, minute). Defaults to (3, 0)."""
    text = str(time_str or "").strip()
    if ":" in text:
        parts = text.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            return max(0, min(h, 23)), max(0, min(m, 59))
        except (ValueError, IndexError):
            pass
    return 3, 0


def as_schedule(cfg, prefix="schedule"):
    """Map backup_* (or schedule_*) keys onto the schedule_* names the cron helpers read."""
    if prefix == "schedule":
        return cfg
    return {
        "schedule_enabled": cfg.get(f"{prefix}_enabled"),
        "schedule_mode": cfg.get(f"{prefix}_mode"),
        "schedule_preset": cfg.get(f"{prefix}_preset"),
        "schedule_time": cfg.get(f"{prefix}_time"),
        "schedule_weekday": cfg.get(f"{prefix}_weekday"),
        "schedule_day": cfg.get(f"{prefix}_day"),
        "schedule_cron": cfg.get(f"{prefix}_cron"),
    }


def get_effective_cron(cfg):
    """
    Determine the effective 5-part cron expression from a configuration dictionary.
    Supports modes: preset, daily, weekly, monthly, custom.
    """
    mode = str(cfg.get("schedule_mode") or "").strip().lower()
    time_str = cfg.get("schedule_time", "03:00")
    h, m = parse_time_parts(time_str)

    if mode == "daily":
        return f"{m} {h} * * *"

    if mode == "weekly":
        try:
            raw_dow = cfg.get("schedule_weekday", 0)
            if isinstance(raw_dow, str) and raw_dow.upper() in DAYS_MAP:
                dow = DAYS_MAP[raw_dow.upper()]
            else:
                dow = int(raw_dow) % 7
        except (ValueError, TypeError):
            dow = 0
        return f"{m} {h} * * {dow}"

    if mode == "monthly":
        try:
            day = max(1, min(int(cfg.get("schedule_day", 1)), 31))
        except (ValueError, TypeError):
            day = 1
        return f"{m} {h} {day} * *"

    if mode == "custom":
        return str(cfg.get("schedule_cron") or "").strip() or "0 3 * * *"

    # Default: preset mode or legacy fallback
    preset_id = str(cfg.get("schedule_preset") or "").strip()
    if preset_id in PRESETS_BY_ID:
        return PRESETS_BY_ID[preset_id]["cron"]

    # Legacy interval fallback: "nightly" -> daily 03:00, "weekly" -> weekly Sunday 03:00
    legacy = str(cfg.get("schedule_interval") or "").strip().lower()
    if legacy == "nightly":
        return "0 3 * * *"
    if legacy == "weekly":
        return "0 3 * * 0"

    return "0 3 * * *"


def describe_cron(expr):
    """Return a clean human-readable description for a 5-part cron expression."""
    clean_expr = " ".join(str(expr or "").strip().split())
    if clean_expr in PRESETS_BY_CRON:
        return PRESETS_BY_CRON[clean_expr]["description"]

    parts = clean_expr.split()
    if len(parts) != 5:
        return "Invalid schedule"

    m_str, h_str, dom_str, mon_str, dow_str = parts

    # Hourly / interval
    if dom_str == "*" and mon_str == "*" and dow_str == "*":
        if h_str == "*":
            if m_str == "*":
                return "Every minute"
            if m_str.startswith("*/"):
                return f"Every {m_str[2:]} minutes"
            return f"Hourly at minute {m_str}"
        if h_str.startswith("*/"):
            return f"Every {h_str[2:]} hours at minute {m_str}"
        if h_str.isdigit() and m_str.isdigit():
            hour = int(h_str)
            minute = int(m_str)
            if hour == 0 and minute == 0:
                return "Daily at midnight"
            return f"Daily at {hour:02d}:{minute:02d}"

    # Weekly
    if dom_str == "*" and mon_str == "*":
        dow_clean = dow_str.upper()
        if dow_clean in ("1-5", "MON-FRI"):
            if h_str.isdigit() and m_str.isdigit():
                return f"Monday through Friday at {int(h_str):02d}:{int(m_str):02d}"
            return "Monday through Friday"
        if dow_clean in ("6,0", "0,6", "SAT,SUN", "SUN,SAT"):
            if h_str.isdigit() and m_str.isdigit():
                return f"Saturday and Sunday at {int(h_str):02d}:{int(m_str):02d}"
            return "Saturday and Sunday"
        if dow_str.isdigit() or dow_clean in DAYS_MAP:
            val = DAYS_MAP[dow_clean] if dow_clean in DAYS_MAP else int(dow_str) % 7
            day_name = WEEKDAY_NAMES[val]
            if h_str.isdigit() and m_str.isdigit():
                return f"Every {day_name} at {int(h_str):02d}:{int(m_str):02d}"
            return f"Every {day_name}"

    # Monthly
    if dom_str.isdigit() and mon_str == "*" and dow_str == "*":
        day = int(dom_str)
        if h_str.isdigit() and m_str.isdigit():
            return f"Monthly on the {ordinal(day)} at {int(h_str):02d}:{int(m_str):02d}"
        return f"Monthly on the {ordinal(day)}"

    return f"Custom crontab ({clean_expr})"


def schedule_summary(cfg):
    """
    Compile complete schedule status and next run for settings API responses.
    """
    enabled = bool(cfg.get("schedule_enabled"))
    tz = get_timezone()
    mode = str(cfg.get("schedule_mode") or "").strip().lower()
    custom = str(cfg.get("schedule_cron") or "").strip()
    if mode == "custom" and not validate_cron(custom):
        return {
            "enabled": enabled,
            "effective_cron": custom,
            "description": "Invalid crontab",
            "is_valid": False,
            "next_run": None,
            "next_run_display": "",
            "timezone": str(getattr(tz, "key", str(tz))),
        }
    cron_expr = get_effective_cron(cfg)
    is_valid = validate_cron(cron_expr)
    now = datetime.datetime.now(tz)
    next_run_dt = next_cron_run(cron_expr, now=now, tz=tz) if is_valid else None

    next_run_iso = next_run_dt.isoformat() if next_run_dt else None
    next_run_display = ""
    if next_run_dt:
        diff = next_run_dt - now
        total_seconds = int(diff.total_seconds())
        if total_seconds < 60:
            rel = "in less than a minute"
        elif total_seconds < 3600:
            rel = f"in {total_seconds // 60}m"
        elif total_seconds < 86400:
            h = total_seconds // 3600
            m = (total_seconds % 3600) // 60
            rel = f"in {h}h {m}m"
        else:
            days = total_seconds // 86400
            h = (total_seconds % 86400) // 3600
            rel = f"in {days}d {h}h"
        next_run_display = f"{next_run_dt.strftime('%A, %b %d at %H:%M')} ({rel})"

    return {
        "enabled": enabled,
        "effective_cron": cron_expr,
        "description": describe_cron(cron_expr),
        "is_valid": is_valid,
        "next_run": next_run_iso,
        "next_run_display": next_run_display,
        "timezone": str(getattr(tz, "key", str(tz))),
    }


SCAN_MODE_LABELS = {
    "incremental": "Incremental deep scan",
    "full": "Full scan",
    "deep": "Deep scan",
}


def saved_schedule_summary(item, enabled=False):
    """Status line for one saved scan schedule."""
    entry = item if isinstance(item, dict) else {}
    mode = str(entry.get("scan_mode") or "").strip().lower()
    if mode not in SCAN_MODE_LABELS:
        mode = "incremental"
    summary = schedule_summary(
        {
            "schedule_enabled": bool(enabled),
            "schedule_mode": "custom",
            "schedule_cron": entry.get("cron") or "",
        }
    )
    summary["scan_mode"] = mode
    summary["scan_label"] = SCAN_MODE_LABELS[mode]
    media = str(entry.get("media") or "music")
    summary["media"] = media if media in {"music", "movies", "tv", "sets"} else "music"
    summary["media_label"] = {"music": "Music", "movies": "Movies", "tv": "TV shows", "sets": "Movie sets"}.get(summary["media"], "Music")
    return summary
