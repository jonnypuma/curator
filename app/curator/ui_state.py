"""Layout choices the browser keeps (columns, column order and widths, pane widths, sort, theme).

They used to live only in the browser's own storage, so a different address, another browser or
cleared site data reset them. The browser now mirrors them here, in the config folder, which is the
same place that survives a rebuild of the container.
"""
import json
import os
import tempfile
import threading

from resonance.paths import config_dir

# Only these browser-storage keys are accepted, and each value is the JSON text the page wrote.
KEYS = frozenset({
    "resonance.columns", "resonance.columnWidths", "resonance.panes", "resonance.librarySort",
    "resonance.density", "resonance.theme", "resonance.reviewCollapsed", "resonance.bioCollapsed",
    "curator.movieColumns", "curator.tvColumns", "curator.movieWidths", "curator.tvWidths",
    "curator.movieSort", "curator.tvSort", "curator.setSort", "curator.videoLeft", "curator.videoRight",
})
MAX_VALUE = 100_000
_lock = threading.Lock()


def _path():
    return os.path.join(config_dir(), "ui_state.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if key in KEYS and isinstance(value, str)}


def update(values):
    """Merge {key: text or None}. Unknown keys and oversized values are ignored; None removes a key."""
    if not isinstance(values, dict):
        return load()
    with _lock:
        state = load()
        for key, value in values.items():
            if key not in KEYS:
                continue
            if value is None:
                state.pop(key, None)
            elif isinstance(value, str) and len(value) <= MAX_VALUE:
                state[key] = value
        directory = config_dir()
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ui_state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=1, sort_keys=True)
            os.replace(tmp, _path())
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return state
