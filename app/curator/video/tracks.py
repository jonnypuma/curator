"""Set the default audio or embedded subtitle track inside an MKV.

mkvpropedit changes the container flag in place. MP4 and other containers are left
alone, because those flags need a remux.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from resonance.errors import AppError

_KINDS = {"audio": ("a", "audio"), "subtitle": ("s", "subtitle")}


def edit_args(kind, index, count):
    """mkvpropedit --edit arguments that leave one track of this type as the default."""
    letter = _KINDS[kind][0]
    args = []
    for number in range(1, count + 1):
        args.extend(["--edit", f"track:{letter}{number}", "--set", f"flag-default={1 if number == index + 1 else 0}"])
    return args


def apply(path, kind, index, tracks):
    """Mark one embedded track as the default and clear the flag on the others."""
    if kind not in _KINDS:
        raise AppError("Choose an audio or subtitle track", 400)
    label = _KINDS[kind][1]
    count = len(tracks or [])
    if index < 0 or index >= count:
        raise AppError(f"That {label} track is not in this file", 400)
    if os.path.splitext(path or "")[1].lower() != ".mkv":
        raise AppError("Default tracks can be set on MKV files. Other containers need a remux.", 400)
    from curator.video import writes

    writes.check(path)
    binary = shutil.which("mkvpropedit")
    if not binary:
        raise AppError("mkvpropedit is not installed in the container", 500)
    command = [binary, path, *edit_args(kind, index, count)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AppError("mkvpropedit did not finish", 504) from None
    if result.returncode > 1:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise AppError(detail[-1] if detail else "mkvpropedit could not set the default track", 502)
    return True


def language_args(kind, index, lang):
    """mkvpropedit --edit arguments that give one track a language, in both fields Matroska keeps it in."""
    from curator.video.languages import _LANG_ALIASES, _LANG_LABELS, normalize_lang

    code = normalize_lang(lang)
    if not code or code == "und" or code not in _LANG_LABELS:
        raise AppError("Choose a language", 400)
    short = next((key for key, value in _LANG_ALIASES.items() if value == code and len(key) == 2 and key.isalpha()), code)
    letter = _KINDS[kind][0]
    return code, ["--edit", f"track:{letter}{index + 1}", "--set", f"language={code}", "--set", f"language-ietf={short}"]


def set_language(path, kind, index, tracks, lang):
    """Write the language of one embedded track inside an MKV. Other containers need a remux."""
    if kind not in _KINDS:
        raise AppError("Choose an audio or subtitle track", 400)
    count = len(tracks or [])
    if index < 0 or index >= count:
        raise AppError(f"That {_KINDS[kind][1]} track is not in this file", 400)
    if os.path.splitext(path or "")[1].lower() != ".mkv":
        raise AppError("The language can be changed on MKV files. Other containers need a remux.", 400)
    code, edit = language_args(kind, index, lang)
    from curator.video import writes

    writes.check(path)
    binary = shutil.which("mkvpropedit")
    if not binary:
        raise AppError("mkvpropedit is not installed in the container", 500)
    try:
        result = subprocess.run([binary, path, *edit], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AppError("mkvpropedit did not finish", 504) from None
    if result.returncode > 1:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise AppError(detail[-1] if detail else "mkvpropedit could not set the language", 502)
    return code
