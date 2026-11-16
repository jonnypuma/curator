"""How long a queue row has been in the running state."""
from datetime import datetime, timezone


def seconds_since(value):
    moment = _moment(value)
    if moment is None:
        return None
    delta = (datetime.now(timezone.utc) - moment).total_seconds()
    return max(0, int(delta))


def elapsed(row):
    """Seconds a database row has been running. The database measures it, because started_at is a timestamp in the
    database's own time zone and reading it here as UTC made the timer start from zero on every refresh."""
    value = row.get("running_for")
    if value is not None:
        return max(0, int(value))
    return seconds_since(row.get("started_at"))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
