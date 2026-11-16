"""One set of rules for translating paths between Curator and the apps around it.

Every app keeps its own path rows (Kodi, Emby, Jellyfin and Plex under Integrations, Radarr, Sonarr, Bazarr and Lidarr
under path mappings). Only the rules that apply a row are shared:

- The longest matching root wins, so a nested row beats its parent.
- A root matches the whole path or a path below it, never a name that only starts the same (/tv does not match /tv2).
- A root with a drive letter or a UNC share (C:\\Media, \\\\nas\\tv) is matched without regard to letter case.
- Backslashes are read as slashes. A target root written with backslashes only (a Windows server) gets backslashes.
- Trailing slashes on a root do not matter.
"""
from __future__ import annotations

PLAYER_SCHEMES = ("nfs://", "smb://", "dav://", "davs://", "ftp://", "ftps://", "http://", "https://", "upnp://",
                  "special://")


def clean(value):
    """Slashes only, no trailing slash (a lone "/" stays)."""
    text = str(value or "").strip().replace("\\", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    return text


def _folds_case(root):
    return (len(root) > 1 and root[1] == ":") or root.startswith("//")


def _windows_target(root):
    text = str(root or "").strip()
    return "\\" in text and "/" not in text


def _under(path, root):
    """The rest of path below root ("" for root itself), or None when path is not inside root."""
    if _folds_case(root):
        path_key, root_key = path.lower(), root.lower()
    else:
        path_key, root_key = path, root
    if path_key == root_key:
        return ""
    if root_key == "/":
        return path if path_key.startswith("/") else None
    if path_key.startswith(root_key + "/"):
        return path[len(root):]
    return None


def translate(path, pairs):
    """Apply (from root, to root) pairs to one path. Returns the translated path, or None when no root matches."""
    text = clean(path)
    if not text:
        return None
    ranked = []
    for source, target in pairs or []:
        source_root, target_text = clean(source), str(target or "").strip()
        if source_root and target_text:
            ranked.append((source_root, target_text))
    ranked.sort(key=lambda pair: len(pair[0]), reverse=True)
    for source_root, target_text in ranked:
        rest = _under(text, source_root)
        if rest is None:
            continue
        if _windows_target(target_text):
            return target_text.rstrip("\\") + rest.replace("/", "\\")
        return clean(target_text) + rest if clean(target_text) != "/" else (rest or "/")
    return None


def _player_root(row):
    return (row or {}).get("remote") or (row or {}).get("kodi") or ""


def to_player(path, rows):
    """A local path as a player sees it, using that player's rows ({"local", "remote"} or {"local", "kodi"}).

    A path that already has a player address (nfs://, smb://...) is returned as it is. None when nothing maps it."""
    text = str(path or "").strip()
    if not text:
        return None
    if text.startswith(PLAYER_SCHEMES):
        return text
    return translate(text, [((row or {}).get("local"), _player_root(row)) for row in rows or []])


def to_players(paths, rows):
    """Player paths for several local paths, without repeats. None when any of them has no row (scan everything)."""
    if not paths:
        return None
    found = []
    for path in paths:
        if not str(path or "").strip():
            continue
        mapped = to_player(path, rows)
        if mapped is None:
            return None
        if mapped not in found:
            found.append(mapped)
    return found


def from_player(path, rows):
    """The local path for a path a player reported. None when nothing maps it."""
    return translate(path, [(_player_root(row), (row or {}).get("local")) for row in rows or []])


def from_source(path, rows, source):
    """A path reported by Radarr, Sonarr, Bazarr or Lidarr as the container sees it, or None when nothing maps it.

    Rows ({"remote", "local", "source"}) for that app and rows for "any" app both count. On an equal length the
    app's own row wins over an "any" row."""
    chosen = [row for row in rows or [] if (row or {}).get("source", "any") in ("any", source)]
    chosen.sort(key=lambda row: row.get("source") != "any", reverse=True)
    pairs = [(row.get("remote"), row.get("local")) for row in chosen]
    # translate() ranks by length only and keeps the first of equal lengths, so the app's rows go first.
    return translate(path, pairs)
