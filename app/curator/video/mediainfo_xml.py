"""Sidecar written beside a video so a moved or renamed folder can skip a new probe.

The file is ``<video stem>.cmm_mediainfo.xml``. Identity is the file name and size, not the
absolute path, so the sidecar stays valid after the folder moves.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from curator.video import store, writes

SUFFIX = ".cmm_mediainfo.xml"
# Set CMM_WRITE_SIDECARS=0 to disable writing sidecar .cmm_mediainfo.xml files entirely.
_WRITE_SIDECARS = os.environ.get("CMM_WRITE_SIDECARS", "1").lower() not in ("0", "false", "no")
_BOOLS = {"is_hybrid", "is_3d"}
_INTS = {"duration_seconds", "width", "height", "bit_depth", "chapters"}
_FLOATS = {"bitrate_mbps", "video_bitrate_mbps", "fps"}
_LISTS = {"audio_tracks", "subtitle_tracks", "external_subtitles"}


def path_for(video_path):
    folder, name = os.path.split(video_path)
    stem = os.path.splitext(name)[0]
    return os.path.join(folder, stem + SUFFIX)


def write(video_path, summary, size):
    if not summary or summary.get("probe_error"):
        return None
    root = ET.Element("mediainfo", {"version": "1"})
    file_node = ET.SubElement(root, "file")
    ET.SubElement(file_node, "name").text = os.path.basename(video_path)
    ET.SubElement(file_node, "size").text = str(int(size or 0))
    for column in store.PROBE_COLUMNS:
        if column in _LISTS or column == "probe_error":
            continue
        value = summary.get(column)
        if value in (None, ""):
            continue
        ET.SubElement(file_node, column).text = "true" if value is True else "false" if value is False else str(value)
    for kind in ("audio_tracks", "subtitle_tracks", "external_subtitles"):
        parent = ET.SubElement(root, kind)
        for track in summary.get(kind) or []:
            if not isinstance(track, dict):
                continue
            node = ET.SubElement(parent, "track")
            for key, value in track.items():
                if value in (None, "", [], {}):
                    continue
                if isinstance(value, (list, tuple)):
                    ET.SubElement(node, key).text = ",".join(str(item) for item in value)
                elif isinstance(value, bool):
                    ET.SubElement(node, key).text = "true" if value else "false"
                else:
                    ET.SubElement(node, key).text = str(value)
    ET.indent(root, space="  ")
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    if not _WRITE_SIDECARS:
        return None
    target = path_for(video_path)
    # Only write if the content actually changed (avoids touching mtime on every scan).
    try:
        existing = open(target, "r", encoding="utf-8").read()
    except OSError:
        existing = None
    if existing != text:
        writes.atomic_write(target, text.encode("utf-8"))
    return target


def read_matching(video_path, size):
    """Probe summary when the sidecar names this file and records the same size."""
    target = path_for(video_path)
    try:
        tree = ET.parse(target)
    except (OSError, ET.ParseError):
        return None
    root = tree.getroot()
    file_node = root.find("file")
    if file_node is None:
        return None
    name = (file_node.findtext("name") or "").strip()
    if name and name != os.path.basename(video_path):
        return None
    try:
        recorded = int((file_node.findtext("size") or "0").strip())
    except ValueError:
        return None
    if recorded != int(size or 0) or not recorded:
        return None
    summary = {}
    for column in store.PROBE_COLUMNS:
        if column in _LISTS:
            continue
        text = file_node.findtext(column)
        if text is None or text == "":
            continue
        summary[column] = _coerce(column, text)
    for kind in ("audio_tracks", "subtitle_tracks", "external_subtitles"):
        tracks = []
        parent = root.find(kind)
        for node in parent.findall("track") if parent is not None else []:
            track = {}
            for child in list(node):
                track[child.tag] = _track_value(child.tag, child.text or "")
            if track:
                tracks.append(track)
        if tracks or kind == "external_subtitles":
            summary[kind] = tracks
    summary.setdefault("external_subtitles", [])
    return summary


def _coerce(column, text):
    if column in _BOOLS:
        return text.strip().lower() in {"1", "true", "yes"}
    if column in _INTS:
        try:
            return int(float(text))
        except ValueError:
            return None
    if column in _FLOATS:
        try:
            return float(text)
        except ValueError:
            return None
    return text


def _track_value(key, text):
    if key == "flags":
        return [part for part in text.split(",") if part]
    if key == "default":
        return text.strip().lower() in {"1", "true", "yes"}
    if key in {"bitrate_kbps", "channels_count", "stream"}:
        try:
            return int(float(text))
        except ValueError:
            return text
    return text
