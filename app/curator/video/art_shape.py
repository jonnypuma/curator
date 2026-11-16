"""Is a picture the right shape for its artwork type? A fanart saved as a poster is wide where a poster is tall.

Each type has a range of width / height it may have. The ranges are wide on purpose: they tell a poster from a
fanart or a banner, not a 2:3 poster from a 27:40 one. Clear logos, clear art and character art come in every shape,
so they are never judged.
"""
from __future__ import annotations

# width / height: the lowest and highest a picture of this type may have.
_RANGES = {
    "poster": (0.55, 0.85),          # 2:3 posters (0.667) and Fanart.tv's 1000×1426 (0.701)
    "keyart": (0.55, 0.85),
    "fanart": (1.40, 2.40),          # 16:9 (1.78), and the wider 1.85 and 2.0 backdrops some sites have
    "landscape": (1.40, 2.40),
    "thumb": (1.20, 2.50),           # episode stills and frames: 16:9 mostly, 4:3 older shows, 2.39 scope
    "extrafanart": (1.40, 2.40),
    "extrathumbs": (1.40, 2.40),
    "banner": (3.50, 7.50),          # 1000×185 (5.4) and TheTVDB's 758×140
    "discart": (0.85, 1.18),
    "squareart": (0.85, 1.18),
}
LABELS = {
    "poster": "tall (about 2:3)", "keyart": "tall (about 2:3)", "fanart": "wide (about 16:9)",
    "landscape": "wide (about 16:9)", "thumb": "wide (about 16:9)", "extrafanart": "wide (about 16:9)",
    "extrathumbs": "wide (about 16:9)", "banner": "a long strip (about 5:1)", "discart": "square",
    "squareart": "square",
}


def judged(kind):
    """True for the types whose shape is checked."""
    return str(kind or "") in _RANGES


def wrong(kind, size):
    """True when the size (width, height) is known and does not fit this type. Unknown size or type: False."""
    limits = _RANGES.get(str(kind or ""))
    try:
        width, height = int(size[0] or 0), int(size[1] or 0)
    except (TypeError, ValueError, IndexError):
        return False
    if not limits or width <= 0 or height <= 0:
        return False
    ratio = width / height
    return not (limits[0] <= ratio <= limits[1])


def wrong_item(kind, item):
    """For a candidate: True when its listed width and height do not fit the type."""
    item = item or {}
    return wrong(kind, (item.get("width"), item.get("height")))


def describe(kind, size):
    """'1920×1080, a fanart should be wide (about 16:9)' style note for a log line."""
    try:
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError, IndexError):
        return ""
    return f"{width}×{height}, a {kind} should be {LABELS.get(kind, 'another shape')}"
