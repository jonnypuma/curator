import contextvars
import os

from psycopg.types.json import Json

from resonance import db, tags
from resonance.errors import AppError
from resonance.paths import assert_library_writable, inside, music_roots

_batch = contextvars.ContextVar("undo_batch", default=None)
_owned = contextvars.ContextVar("undo_owned", default=False)
_hold = contextvars.ContextVar("undo_hold", default=0)


def bind(batch_id):
    return _batch.set(str(batch_id)), _owned.set(False)


def reset(tokens):
    batch_token, owned_token = tokens
    _batch.reset(batch_token)
    _owned.reset(owned_token)


def snapshot_tags(track_id, path, previous):
    if not path or not os.path.isfile(path):
        return
    batch_id = _ensure("Tag edit")
    _mtime_ns, file_size = _stat(path)
    db.execute(
        """
        INSERT INTO tag_snapshots (batch_id, track_id, file_path, tags, mtime_ns, file_size)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (batch_id, track_id, path, Json(previous or {}), _mtime_ns, file_size),
    )


def snapshot_path(kind, row_id, path):
    if not path or not row_id:
        return
    batch_id = _ensure("Rename")
    db.execute(
        """
        INSERT INTO tag_snapshots (batch_id, track_id, file_path, tags, mtime_ns, file_size)
        VALUES (%s, NULL, %s, %s, 0, 0)
        """,
        (batch_id, path, Json({"_index": kind, "id": str(row_id)})),
    )


def snapshot_move(source, dest):
    if not dest or not os.path.exists(dest):
        return
    batch_id = _ensure("Rename")
    mtime_ns, file_size = _stat(dest)
    db.execute(
        """
        INSERT INTO file_moves (batch_id, source_path, dest_path, mtime_ns, file_size)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (batch_id, source, dest, mtime_ns, file_size),
    )


def hold():
    _hold.set(_hold.get() + 1)


def release():
    _hold.set(max(0, _hold.get() - 1))
    if _hold.get() == 0:
        finish()


def finish():
    if _hold.get() or not _owned.get():
        return
    batch_id = _batch.get()
    if batch_id:
        db.execute(
            """
            UPDATE batch_jobs
            SET status = 'completed', message = 'Recorded for undo', finished_at = NOW()
            WHERE id = %s AND status = 'running'
            """,
            (batch_id,),
        )
    _batch.set(None)
    _owned.set(False)


def rollback_last():
    row = db.fetchone(
        """
        SELECT id, message FROM batch_jobs
        WHERE status = 'completed' AND COALESCE(rolled_back, FALSE) = FALSE
          AND (
            EXISTS (SELECT 1 FROM tag_snapshots WHERE batch_id = batch_jobs.id)
            OR EXISTS (SELECT 1 FROM file_moves WHERE batch_id = batch_jobs.id)
          )
        ORDER BY finished_at DESC NULLS LAST, started_at DESC
        LIMIT 1
        """
    )
    if not row:
        raise AppError("There is no batch to roll back")
    batch_id = row["id"]
    moves = db.fetchall(
        "SELECT * FROM file_moves WHERE batch_id = %s ORDER BY created_at DESC",
        (batch_id,),
    )
    snapshots = db.fetchall(
        "SELECT * FROM tag_snapshots WHERE batch_id = %s ORDER BY created_at",
        (batch_id,),
    )
    source_to_dest = {item["source_path"]: item["dest_path"] for item in moves}
    moved_dests = set(source_to_dest.values())
    located = []
    index_snaps = []
    for snap in snapshots:
        payload = snap["tags"] or {}
        if isinstance(payload, dict) and payload.get("_index"):
            index_snaps.append((snap, payload))
            continue
        path = snap["file_path"]
        if not os.path.isfile(path):
            path = source_to_dest.get(snap["file_path"], "")
        if not path or not os.path.isfile(path):
            raise AppError("Rollback stopped because a file from that batch is missing")
        if path not in moved_dests and not _same_stat(path, snap):
            raise AppError("Rollback stopped because a file changed after that batch")
        located.append(snap)
    for move in moves:
        if not os.path.exists(move["dest_path"]):
            raise AppError("Rollback stopped because a renamed file is missing")
        if not _same_stat(move["dest_path"], move):
            raise AppError("Rollback stopped because a renamed file changed after that batch")
        assert_library_writable(move["dest_path"])
        if os.path.exists(move["source_path"]) and not _same_file(move["source_path"], move["dest_path"]):
            raise AppError("Rollback stopped because the original path is already in use")
        root = _root(move["dest_path"])
        if not root or not inside(root, move["source_path"]):
            raise AppError("Rollback stopped because the original path leaves the music folder")
    for move in moves:
        os.makedirs(os.path.dirname(move["source_path"]), exist_ok=True)
        os.replace(move["dest_path"], move["source_path"])
        db.execute(
            "UPDATE tracks SET file_path = %s WHERE file_path = %s",
            (move["source_path"], move["dest_path"]),
        )
    from resonance.completeness import columns_from_tags

    for index, snap in enumerate(located):
        if snap.get("track_id"):
            db.execute(
                "UPDATE tracks SET track_number = %s WHERE id = %s",
                (50000 + index + 1, snap["track_id"]),
            )
    for snap in located:
        target = snap["file_path"]
        tags.write_easy(target, snap["tags"] or {})
        if snap.get("track_id"):
            columns = columns_from_tags(snap["tags"] or {})
            db.execute(
                """
                UPDATE tracks SET
                    title = %s,
                    artist_name = %s,
                    album_name = %s,
                    genre = %s,
                    year = %s,
                    track_number = %s,
                    disc_number = %s,
                    musicbrainz_track_id = %s,
                    musicbrainz_release_group_id = %s,
                    tags = %s
                WHERE id = %s
                """,
                (
                    columns["title"],
                    columns["artist_name"],
                    columns["album_name"],
                    columns["genre"],
                    columns["year"],
                    columns["track_number"],
                    columns["disc_number"],
                    columns["musicbrainz_track_id"],
                    columns["musicbrainz_release_group_id"],
                    Json(columns["tags"]),
                    snap["track_id"],
                ),
            )
    for snap, payload in index_snaps:
        kind = payload.get("_index")
        row_id = payload.get("id")
        if kind == "album":
            db.execute("UPDATE albums SET path = %s WHERE id = %s", (snap["file_path"], row_id))
        elif kind == "artist":
            db.execute("UPDATE artists SET path = %s WHERE id = %s", (snap["file_path"], row_id))
        elif kind == "artwork":
            db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (snap["file_path"], row_id))
    db.execute(
        "UPDATE batch_jobs SET rolled_back = TRUE, message = %s WHERE id = %s",
        (f"Rolled back {row.get('message') or 'batch'}", batch_id),
    )
    return {"batch_id": str(batch_id), "moves": len(moves), "tags": len(snapshots)}


def _ensure(message):
    current = _batch.get()
    if current:
        return current
    row = db.fetchone(
        """
        INSERT INTO batch_jobs (status, message, processed, total, log, started_at)
        VALUES ('running', %s, 0, 1, '', NOW())
        RETURNING id
        """,
        (message,),
    )
    _batch.set(str(row["id"]))
    _owned.set(True)
    return str(row["id"])


def _stat(path):
    stat = os.stat(path)
    modified = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    return int(modified), int(stat.st_size)


def _same_stat(path, row):
    try:
        mtime_ns, file_size = _stat(path)
    except OSError:
        return False
    return mtime_ns == row.get("mtime_ns") and file_size == row.get("file_size")


def _same_file(left, right):
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _locate(path, translated):
    if path and os.path.isfile(path):
        return path
    seen = set()
    current = path
    while current in translated and current not in seen:
        seen.add(current)
        current = translated[current]
        if os.path.isfile(current):
            return current
    return path if path and os.path.isfile(path) else ""


def _root(path):
    real = os.path.realpath(path)
    matches = [os.path.realpath(root) for root in music_roots() if inside(root, real)]
    if not matches:
        return ""
    return max(matches, key=len)
