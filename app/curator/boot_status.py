"""How far container startup has got, for the loading screen."""
from __future__ import annotations

import threading

_lock = threading.Lock()
_state = {"ready": False, "progress": 0.04, "error": ""}


def advance(progress):
    """Move the bar forward. A later smaller value does not pull it back."""
    value = max(0.0, min(float(progress), 0.8))
    with _lock:
        if _state["ready"]:
            return
        if value > _state["progress"]:
            _state["progress"] = value


def mark_ready():
    with _lock:
        _state["ready"] = True
        _state["error"] = ""
        _state["progress"] = max(_state["progress"], 0.8)


def fail(message):
    with _lock:
        _state["ready"] = False
        _state["error"] = str(message or "Curator could not start.")


def snapshot():
    with _lock:
        return dict(_state)
