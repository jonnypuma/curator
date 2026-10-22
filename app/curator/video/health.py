"""Warnings about a video file that was read successfully but looks wrong.

These come from facts already stored by the probe, so nothing is read from disk here. A probe that failed is
reported by its own pill and is not repeated. Each warning is a code and a short label.
"""
from __future__ import annotations

UNKNOWN_LANGS = {"", "und", "unk", "unknown", "zxx", "mis", "mul"}
DISC_CONTAINERS = {"iso", "vob", "bdmv", "disc"}


def unknown_language(lang):
    """True when a track has no language, or one that says nothing (und, zxx, mul and so on)."""
    return str(lang or "").strip().lower() in UNKNOWN_LANGS


LABELS = {
    "no_size": "Empty file",
    "no_video": "No video stream",
    "no_audio": "No audio",
    "audio_lang": "Unknown audio language",
    "short": "Shorter than expected",
}


def warnings(row, audio_tracks, duration=None, runtime_minutes=None):
    """Codes for the problems found in one probed file. An unprobed or failed probe has none."""
    if not row or row.get("probe_error") or not row.get("probed_at"):
        return []
    if str(row.get("container") or "").lower() in DISC_CONTAINERS:
        return []
    found = []
    size = row.get("size_bytes")
    if size is not None and int(size) == 0:
        found.append("no_size")
        return found
    if not row.get("video_codec"):
        found.append("no_video")
    tracks = audio_tracks or []
    if not tracks:
        found.append("no_audio")
    elif all(str(track.get("lang") or "").lower() in UNKNOWN_LANGS for track in tracks):
        found.append("audio_lang")
    try:
        seconds = float(duration or 0)
        expected = float(runtime_minutes or 0) * 60
    except (TypeError, ValueError):
        seconds = expected = 0
    # Half the listed runtime is far enough off to be a cut or damaged file, and not a stacked part or a recut.
    if seconds and expected >= 20 * 60 and seconds < expected * 0.5 and not row.get("parts"):
        found.append("short")
    return found
