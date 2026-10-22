"""How long a queue row has been in the running state."""
from datetime import datetime, timezone


def seconds_since(value):
    moment = _moment(value)
    if moment is None:
        return None
    delta = (datetime.now(timezone.utc) - moment).total_seconds()
    return max(0, int(delta))


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
