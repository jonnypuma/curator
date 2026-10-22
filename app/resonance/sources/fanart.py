from resonance import settings
from resonance.sources.client import get_json


def music(mbid):
    key = (settings.load().get("fanart_key") or "").strip()
    if not key or not mbid:
        return None
    data = get_json(f"https://webservice.fanart.tv/v3/music/{mbid}", {"api_key": key})
    if not isinstance(data, dict) or data.get("status") == "error":
        return None
    return data


def configured():
    return bool((settings.load().get("fanart_key") or "").strip())


def _sorted(items):
    rows = list(items or [])
    rows.sort(key=lambda item: int(item.get("likes") or 0), reverse=True)
    return rows
