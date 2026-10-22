"""The "Synced" status of an external subtitle: the user pressed Sync OK for it.

The mark is stored with the subtitle's modification time and only counts while the file still has
it, so editing, re-syncing, reverting or replacing the file removes the status by itself.
"""
import os

from resonance import db


def _target(folder, name):
    """The file the sync window opens for this row. A VobSub .sub row stands for its .idx."""
    if name.lower().endswith(".sub"):
        for other in (name[:-4] + ".idx", name[:-4] + ".IDX"):
            if os.path.isfile(os.path.join(folder, other)):
                return os.path.join(folder, other)
    return os.path.join(folder, name)


def mark(sub_path):
    real = os.path.realpath(sub_path)
    mtime = os.stat(real).st_mtime
    db.execute(
        """
        INSERT INTO subtitle_sync_marks (path, mtime, synced_at) VALUES (%s, %s, NOW())
        ON CONFLICT (path) DO UPDATE SET mtime = EXCLUDED.mtime, synced_at = NOW()
        """,
        (real, mtime),
    )
    return {"path": real}


def status(path):
    """The synced timestamp (string) of one sidecar file, or None when it is not marked or has
    changed since it was marked. Used for lyrics (.lrc), which have no row list to annotate."""
    real = os.path.realpath(path)
    try:
        row = db.fetchone("SELECT mtime, synced_at FROM subtitle_sync_marks WHERE path = %s", (real,))
        current = os.stat(real).st_mtime
    except Exception:
        return None
    if row and abs(current - float(row["mtime"])) < 1.0:
        return str(row["synced_at"])[:16]
    return None


def annotate(file):
    """Set `synced` (a timestamp string) on each external subtitle of a video_files dict."""
    tracks = (file or {}).get("external_subtitles") or []
    video = (file or {}).get("path") or ""
    if not tracks or not video:
        return file
    folder = os.path.dirname(video)
    targets = {}
    for track in tracks:
        name = str(track.get("file") or "")
        if name:
            targets[name] = os.path.realpath(_target(folder, name))
    try:
        rows = db.fetchall("SELECT path, mtime, synced_at FROM subtitle_sync_marks WHERE path = ANY(%s)",
                           (list(set(targets.values())),))
    except Exception:
        return file
    marks = {row["path"]: row for row in rows}
    for track in tracks:
        row = marks.get(targets.get(str(track.get("file") or "")))
        try:
            current = os.stat(targets[track["file"]]).st_mtime if row else None
        except (OSError, KeyError):
            current = None
        if row and current is not None and abs(current - float(row["mtime"])) < 1.0:
            track["synced"] = str(row["synced_at"])[:16]
        else:
            track.pop("synced", None)
    return file
