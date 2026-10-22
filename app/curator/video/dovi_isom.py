"""Dolby Vision config boxes in MP4 and MOV. Ported from video-analyzer.

Profile 20 (MV-HEVC stereo) is stored in a dvwC box. The RPU often looks like Profile 5,
so the box wins.
"""
from __future__ import annotations

import os

_DOVI_CONFIG_BOXES = {b"dvcC", b"dvvC", b"dvwC"}
_ISOM_CONTAINER_BOXES = {
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stsd",
    b"udta", b"meta", b"iprp", b"ipco", b"moof", b"traf",
    b"vexu", b"eyes",
}
ISOM_EXTENSIONS = {".mp4", ".mov", ".m4v", ".cmfv", ".qt"}


def _decode_dovi_config_payload(payload):
    """Decode a dvcC, dvvC, or dvwC payload into profile and compatibility id."""
    if len(payload) < 4:
        return None
    packed = (payload[2] << 8) | payload[3]
    profile = (packed >> 9) & 0x7F
    level = (packed >> 3) & 0x3F
    compat = None
    if len(payload) >= 5:
        compat = (payload[4] >> 4) & 0x0F
    return {
        "dovi_profile": str(profile),
        "dovi_level": str(level),
        "bl_compatibility_id": str(compat) if compat is not None else None,
    }


def _scan_buffer_for_dovi_config(buf):
    for box in _DOVI_CONFIG_BOXES:
        idx = buf.find(box)
        if idx < 4:
            continue
        size_off = idx - 4
        nsize = int.from_bytes(buf[size_off:size_off + 4], "big")
        if 8 <= nsize <= 64 and size_off + nsize <= len(buf):
            payload = buf[idx + 4:size_off + nsize]
        else:
            payload = buf[idx + 4:idx + 4 + 24]
        decoded = _decode_dovi_config_payload(payload)
        if decoded:
            decoded["box_type"] = box.decode("ascii", errors="replace")
            return decoded
    return None


def parse_isom_dovi_config(path):
    """The first Dolby Vision config box in an MP4 or MOV, without reading the whole file."""
    try:
        file_size = os.path.getsize(path)
    except OSError:
        return None
    if file_size < 16:
        return None

    found = None
    is_stereo = False

    def walk(handle, end, depth=0):
        nonlocal found, is_stereo
        if depth > 24:
            return
        while handle.tell() + 8 <= end:
            start = handle.tell()
            header = handle.read(8)
            if len(header) < 8:
                break
            size = int.from_bytes(header[:4], "big")
            kind = header[4:8]
            header_len = 8
            if size == 1:
                large = handle.read(8)
                if len(large) < 8:
                    break
                size = int.from_bytes(large, "big")
                header_len = 16
            elif size == 0:
                size = end - start
            if size < header_len or start + size > end:
                break
            payload_start = start + header_len
            payload_end = start + size
            payload_size = payload_end - payload_start

            if kind in _DOVI_CONFIG_BOXES and found is None and payload_size >= 4:
                payload = handle.read(min(payload_size, 32))
                decoded = _decode_dovi_config_payload(payload)
                if decoded:
                    found = decoded
                    found["box_type"] = kind.decode("ascii", errors="replace")
            elif kind in (b"vexu", b"eyes"):
                is_stereo = True
                if kind == b"vexu" and payload_size > 0:
                    handle.seek(payload_start)
                    walk(handle, payload_end, depth + 1)
            elif kind in _ISOM_CONTAINER_BOXES and payload_size > 0:
                handle.seek(payload_start)
                if kind == b"stsd" and payload_size >= 8:
                    handle.read(8)
                elif kind == b"meta" and payload_size >= 4:
                    handle.read(4)
                walk(handle, payload_end, depth + 1)
            elif found is None and 16 < payload_size < 8192 and kind not in (b"mdat", b"free", b"skip", b"wide"):
                handle.seek(payload_start)
                peek = handle.read(payload_size)
                if b"vexu" in peek or b"eyes" in peek:
                    is_stereo = True
                decoded = _scan_buffer_for_dovi_config(peek)
                if decoded:
                    found = decoded

            handle.seek(payload_end)
            if found is not None and is_stereo:
                return

    try:
        with open(path, "rb") as handle:
            walk(handle, file_size, 0)
    except OSError:
        return None

    if found is None and not is_stereo:
        return None
    if found is None:
        return {"is_stereo": True}
    found["is_stereo"] = is_stereo or found.get("dovi_profile") == "20"
    return found
