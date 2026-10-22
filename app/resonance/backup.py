import datetime
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from resonance.errors import AppError

logger = logging.getLogger(__name__)
_started = False
_running = threading.Lock()
_status_guard = threading.Lock()
_status = {"status": "idle", "message": "", "kind": "backup"}


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="backup-schedule", daemon=True).start()


def status():
    with _status_guard:
        return dict(_status)


def restoring():
    """True while a restore or a music import is replacing database rows."""
    with _status_guard:
        return _status.get("status") == "running" and _status.get("kind") in {"restore", "import"}


def _set_status(state, message):
    with _status_guard:
        if state in {"running", "waiting"} and _status.get("status") not in {"running", "waiting"}:
            _status["kind"] = "backup"
        _status["status"] = state
        _status["message"] = message


def _loop():
    last_run_minute = None
    last_checked_utc = None
    while True:
        try:
            from resonance import cron
            from resonance.settings import load as load_settings

            cfg = load_settings()
            if cfg.get("backup_enabled"):
                view = cron.as_schedule(cfg, "backup")
                tz = cron.get_timezone()
                now = datetime.datetime.now(tz)
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                current_minute = (now.year, now.month, now.day, now.hour, now.minute)
                cron_expr = cron.get_effective_cron(view)
                if current_minute != last_run_minute:
                    matched = cron.matches_cron(now, cron_expr)
                    if not matched and last_checked_utc is not None:
                        gap_seconds = (now_utc - last_checked_utc).total_seconds()
                        if 60 <= gap_seconds <= 7200:
                            chk = last_checked_utc + datetime.timedelta(minutes=1)
                            while chk < now_utc:
                                if cron.matches_cron(chk.astimezone(tz), cron_expr):
                                    matched = True
                                    break
                                chk += datetime.timedelta(minutes=1)
                    if matched:
                        last_run_minute = current_minute
                        logger.info("Scheduled database backup is due: %s (%s)", cron_expr, cron.describe_cron(cron_expr))
                        try:
                            path = start_dump(wait=True, keep=cfg.get("backup_keep") or 14)
                            logger.info("Database backup written to %s", path)
                        except AppError as exc:
                            logger.info("scheduled backup did not start: %s", exc)
                last_checked_utc = now_utc
        except Exception:
            logger.exception("scheduled backup failed")
        time.sleep(15)


def request_manual():
    from resonance import jobs
    from resonance.settings import load as load_settings

    current = status()
    if current["status"] in {"running", "waiting"} or _running.locked():
        raise AppError("A backup is already running", 409)
    if jobs.locked():
        raise AppError("A scan is running. Backup now is available when the scan finishes.", 409)
    keep = load_settings().get("backup_keep") or 14

    def work():
        try:
            start_dump(wait=False, keep=keep)
        except AppError as exc:
            logger.info("manual backup did not start: %s", exc)
            if status()["status"] == "running":
                _set_status("idle", "")
        except Exception:
            logger.exception("manual backup failed")

    _set_status("running", "Writing database dump")
    threading.Thread(target=work, name="manual-backup", daemon=True).start()
    return status()


def _take_library_lock(wait):
    from resonance import jobs

    if jobs.try_lock():
        return True
    if not wait:
        return False
    _set_status("waiting", "Waiting for the scan to finish")
    logger.info("Backup is waiting for the scan to finish")
    jobs.acquire()
    return True


def _tell(event, title, message, level):
    try:
        from curator import outbound

        outbound.send(event, title, message, level)
    except Exception:
        logger.exception("could not send the backup notification")


def start_dump(wait, keep):
    """Dump the database. A scheduled dump waits until the scan lock is free."""
    if not _running.acquire(blocking=False):
        raise AppError("A backup is already running", 409)
    held = False
    try:
        held = _take_library_lock(wait)
        if not held:
            raise AppError("A scan is running. Backup now is available when the scan finishes.", 409)
        try:
            _set_status("running", "Writing database dump")
            path = run_backup(keep)
            _set_status("completed", f"Dump written to {os.path.basename(path)}")
            _tell("backup_completed", "Database backup finished", f"Dump written to {os.path.basename(path)}", "success")
            return path
        except Exception as exc:
            _set_status("failed", str(exc)[:400])
            _tell("backup_failed", "Database backup failed", str(exc)[:400], "error")
            raise
        finally:
            if held:
                from resonance import jobs

                jobs.release_lock()
    finally:
        _running.release()


def default_dir():
    return os.environ.get("BACKUP_DIR", "/backups")


def backup_dir():
    from resonance import settings

    return settings.load().get("backup_folder") or default_dir()


def check_folder(path):
    from resonance.errors import AppError
    from resonance.paths import assert_library_path

    real = assert_library_path(path, "backup")
    if not os.access(real, os.W_OK):
        raise AppError(f"{path} is read-only in this container. Pick a folder on a mount marked rw.", 400)
    return real


def _pg_conn_info():
    from urllib.parse import unquote, urlsplit

    from resonance import db

    url = db.database_url()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "postgres"
        port = str(parsed.port or 5432)
        user = unquote(parsed.username or "resonance")
        password = unquote(parsed.password or "resonance")
        dbname = (parsed.path or "/resonance").lstrip("/") or "resonance"
        return host, port, user, password, dbname
    except Exception:
        return (
            os.environ.get("POSTGRES_HOST", "postgres"),
            str(os.environ.get("POSTGRES_PORT", "5432")),
            os.environ.get("POSTGRES_USER", "resonance"),
            os.environ.get("POSTGRES_PASSWORD", "resonance"),
            os.environ.get("POSTGRES_DB", "resonance"),
        )


def _pg_env():
    env = os.environ.copy()
    _host, _port, _user, password, _dbname = _pg_conn_info()
    env["PGPASSWORD"] = password
    return env


def _pg_args():
    host, port, user, _password, dbname = _pg_conn_info()
    return ["-h", host, "-p", port, "-U", user, "-d", dbname]


SNAPSHOT_PREFIX = "before-bulk-"
SNAPSHOT_KEEP = 2
SNAPSHOT_MIN_ITEMS = 5


def snapshot_before(reason, count):
    """Dump the database before a large write, when Settings asks for it. Never raises.

    Only the newest SNAPSHOT_KEEP of these files are kept. A failed dump is logged and the write goes on:
    a missing safety copy should not stop the work the user asked for.
    """
    try:
        from resonance import settings

        if not settings.load().get("backup_snapshot_before_bulk") or int(count or 0) < SNAPSHOT_MIN_ITEMS:
            return None
        directory = backup_dir()
        os.makedirs(directory, exist_ok=True)
        target = _dump(os.path.join(directory, f"{SNAPSHOT_PREFIX}{_stamp()}{DUMP_SUFFIX}"))
        old = sorted(Path(directory).glob(f"{SNAPSHOT_PREFIX}*{DUMP_SUFFIX}"))
        for path in old[: max(0, len(old) - SNAPSHOT_KEEP)]:
            try:
                path.unlink()
            except OSError:
                logger.warning("could not remove old snapshot %s", path)
        logger.info("Database snapshot %s written before %s", os.path.basename(target), reason)
        return target
    except Exception:
        logger.exception("could not write the snapshot before %s", reason)
        return None


def _stamp():
    from resonance import cron

    return datetime.datetime.now(cron.get_timezone()).strftime("%Y%m%d-%H%M%S")


def _dump(target):
    command = ["pg_dump", *_pg_args(), "-Fc", "--no-owner", "--no-acl", "-f", target]
    try:
        result = subprocess.run(command, env=_pg_env(), capture_output=True, text=True, timeout=3600, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("pg_dump is not installed in this image") from exc
    except subprocess.TimeoutExpired as exc:
        try:
            os.remove(target)
        except OSError:
            pass
        raise RuntimeError("pg_dump timed out after 1 hour") from exc
    if result.returncode != 0:
        try:
            os.remove(target)
        except OSError:
            pass
        detail = (result.stderr or result.stdout or "pg_dump failed").strip()
        raise RuntimeError(detail[-400:])
    return target


def run_backup(keep=14):
    """Write a custom-format pg_dump into the backups directory and prune older dumps."""
    directory = backup_dir()
    os.makedirs(directory, exist_ok=True)
    target = _dump(os.path.join(directory, f"curator-{_stamp()}.dump"))
    prune(directory, keep)
    return target


# Restore

RESTORE_WORD = "RESTORE"
DUMP_SUFFIX = ".dump"


def import_dir():
    """Folder watched for a Resonance dump dropped next to docker-compose. Mounted at /import."""
    folder = os.environ.get("CMM_IMPORT_DIR", "/import")
    return folder if folder and os.path.isdir(folder) else None


def _folders():
    found = []
    for folder in (backup_dir(), default_dir(), import_dir()):
        if folder and folder not in found and os.path.isdir(folder):
            found.append(folder)
    return found


def list_dumps():
    """Dump files in the backup folders, newest first."""
    items = []
    for folder in _folders():
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if not name.endswith(DUMP_SUFFIX) or not os.path.isfile(path):
                continue
            stat = os.stat(path)
            items.append({
                "name": name, "folder": folder, "size": stat.st_size,
                "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "safety": name.startswith(("before-restore-", "before-import-", SNAPSHOT_PREFIX)),
            })
    items.sort(key=lambda item: item["modified"], reverse=True)
    return items


def _resolve(name, folder=None):
    name = os.path.basename(str(name or ""))
    if not name.endswith(DUMP_SUFFIX):
        raise AppError("Pick a .dump file from the list", 400)
    for candidate in _folders():
        if folder and os.path.normpath(folder) != os.path.normpath(candidate):
            continue
        path = os.path.join(candidate, name)
        if os.path.isfile(path):
            return path
    raise AppError(f"{name} is not in the backup folder", 404)


def _busy_reason():
    from resonance import jobs

    if _running.locked() or status()["status"] in {"running", "waiting"}:
        return "A backup or restore is already running"
    if jobs.locked():
        return "A music scan is running"
    try:
        from curator import ingest
        from curator.video import files, scanner, scrape

        if scanner.running() or scrape.running() or files.running():
            return "A movie or TV scan, scrape or file job is running"
        if ingest.queue_running():
            return "The webhook queue is processing"
    except ImportError:
        pass
    return None


IMPORT_WORD = "IMPORT"
# Library rows copied from an old Resonance dump. Job history stays in Curator.
MUSIC_TABLES = (
    "artists", "albums", "tracks", "artwork_pool", "expected_tracks",
    "loaded_matches", "artwork_undo", "dismissed_duplicates",
)


def request_music_import(name, confirm, folder=None):
    """Replace artists, albums and tracks from a Resonance dump. Movies and TV stay."""
    if confirm != IMPORT_WORD:
        raise AppError(f"Type {IMPORT_WORD} to confirm", 400)
    path = _resolve(name, folder)
    reason = _busy_reason()
    if reason:
        raise AppError(f"{reason}. Import when it has finished.", 409)
    _set_status("running", f"Importing music from {os.path.basename(path)}")
    with _status_guard:
        _status["kind"] = "import"
    threading.Thread(target=_import_worker, args=(path,), name="music-import", daemon=True).start()
    return status()


def _import_worker(path):
    from resonance import jobs

    if not _running.acquire(blocking=False):
        _set_status("failed", "A backup is already running")
        return
    held = jobs.try_lock()
    try:
        if not held:
            _set_status("failed", "A music scan started. Import when it has finished.")
            return
        message = import_music_file(path)
        _set_status("completed", message)
    except Exception as exc:
        logger.exception("music import failed")
        _set_status("failed", str(exc)[:600])
    finally:
        if held:
            jobs.release_lock()
        _running.release()


def import_music_file(path):
    """Load path into a side database and copy its music tables over the live ones.

    The current database is dumped first. If the copy fails, that dump is put back.
    """
    directory = backup_dir()
    os.makedirs(directory, exist_ok=True)
    _set_status("running", "Saving the current database first")
    safety = _dump(os.path.join(directory, f"before-import-{_stamp()}{DUMP_SUFFIX}"))
    side = "curator_music_import"
    try:
        _set_status("running", f"Reading {os.path.basename(path)}")
        _load_side_database(side, path)
        _set_status("running", "Copying artists, albums and tracks")
        counts = _copy_music(side)
    except Exception as exc:
        logger.error("music import of %s failed: %s", path, exc)
        _drop_database(side)
        raise RuntimeError(f"The music import failed ({exc}). The existing database was left unchanged.") from exc
    _drop_database(side)
    _after_restore()
    return (f"Imported {counts.get('artists', 0)} artists, {counts.get('albums', 0)} albums and "
            f"{counts.get('tracks', 0)} tracks from {os.path.basename(path)}. Movies and TV were left as they were. "
            f"The previous database was saved as {os.path.basename(safety)}.")


def shared_columns(dest_columns, source_columns):
    """Columns that exist on both sides, in the live table's order."""
    source = set(source_columns)
    return [column for column in dest_columns if column in source]


def _database_url(name):
    from urllib.parse import urlsplit, urlunsplit

    from resonance import db

    parts = urlsplit(db.database_url())
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, ""))


def _load_side_database(name, path):
    _drop_database(name)
    import psycopg
    from psycopg import sql

    from resonance import db

    with psycopg.connect(db.database_url(), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    args = _pg_args()
    args[args.index("-d") + 1] = name
    command = ["pg_restore", *args, "--no-owner", "--no-acl", path]
    try:
        result = subprocess.run(command, env=_pg_env(), capture_output=True, text=True, timeout=3600, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("pg_restore is not installed in this image") from exc
    problems = restore_errors(result.stderr)
    if result.returncode != 0 and problems:
        raise RuntimeError(problems[-1][-400:])


def _drop_database(name):
    import psycopg
    from psycopg import sql

    from resonance import db

    with psycopg.connect(db.database_url(), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def _table_columns(conn, table):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [row["column_name"] for row in rows]


def _copy_music(side):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    from resonance import db

    source = psycopg.connect(_database_url(side), row_factory=dict_row)
    dest = psycopg.connect(db.database_url(), row_factory=dict_row)
    try:
        if not _table_columns(source, "artists"):
            raise RuntimeError("That dump has no artists table. Export the Resonance database as a .dump file.")
        planned = []
        for table in MUSIC_TABLES:
            columns = shared_columns(_table_columns(dest, table), _table_columns(source, table))
            if columns:
                planned.append((table, columns))
        with dest.transaction():
            dest.execute("SET session_replication_role = replica")
            dest.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(table) for table, _columns in planned)))
            for table, columns in planned:
                listed = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
                outgoing = sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(listed, sql.Identifier(table))
                incoming = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), listed)
                with source.cursor() as read_from, dest.cursor() as write_to:
                    with read_from.copy(outgoing) as copy_out, write_to.copy(incoming) as copy_in:
                        for chunk in copy_out:
                            copy_in.write(chunk)
            dest.execute("SET session_replication_role = DEFAULT")
            counts = {}
            for table, _columns in planned:
                counts[table] = dest.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"]
            return counts
    finally:
        source.close()
        dest.close()


def request_restore(name, confirm, folder=None):
    """Replace the whole database with a dump. Runs in a thread; status() reports progress."""
    if confirm != RESTORE_WORD:
        raise AppError(f"Type {RESTORE_WORD} to confirm", 400)
    path = _resolve(name, folder)
    reason = _busy_reason()
    if reason:
        raise AppError(f"{reason}. Restore when it has finished.", 409)
    _set_status("running", f"Restoring {os.path.basename(path)}")
    with _status_guard:
        _status["kind"] = "restore"
    threading.Thread(target=_restore_worker, args=(path,), name="restore", daemon=True).start()
    return status()


def _restore_worker(path):
    from resonance import jobs

    if not _running.acquire(blocking=False):
        _set_status("failed", "A backup is already running")
        return
    held = jobs.try_lock()
    try:
        if not held:
            _set_status("failed", "A music scan started. Restore when it has finished.")
            return
        message = restore_file(path)
        _set_status("completed", message)
    except Exception as exc:
        logger.exception("restore failed")
        _set_status("failed", str(exc)[:600])
    finally:
        if held:
            jobs.release_lock()
        _running.release()


def restore_file(path):
    """Dump the current database to a safety file, then replace it with path.

    The current database is dropped first so tables that are not in the dump do not linger. When
    the restore fails, the safety dump is put back.
    """
    directory = backup_dir()
    os.makedirs(directory, exist_ok=True)
    _set_status("running", "Saving the current database first")
    safety = _dump(os.path.join(directory, f"before-restore-{_stamp()}{DUMP_SUFFIX}"))
    try:
        _set_status("running", f"Restoring {os.path.basename(path)}")
        _replace_database(path)
    except Exception as exc:
        logger.error("restore of %s failed: %s", path, exc)
        try:
            _replace_database(safety)
        except Exception as again:
            raise RuntimeError(f"The restore failed ({exc}) and putting back {os.path.basename(safety)} failed too "
                               f"({again}). Restore that file by hand with pg_restore.") from again
        finally:
            _after_restore()
        raise RuntimeError(f"The restore failed and the previous database was put back: {exc}") from exc
    _after_restore()
    return f"Restored {os.path.basename(path)}. The previous database was saved as {os.path.basename(safety)}."


def _replace_database(path):
    import psycopg
    from psycopg.rows import dict_row

    from resonance import db

    with psycopg.connect(db.database_url(), autocommit=True, row_factory=dict_row) as conn:
        db.close_leftover_sessions(conn, wait_for_maintenance=True)
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    command = ["pg_restore", *_pg_args(), "--no-owner", "--no-acl", path]
    try:
        result = subprocess.run(command, env=_pg_env(), capture_output=True, text=True, timeout=3600, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("pg_restore is not installed in this image") from exc
    problems = restore_errors(result.stderr)
    if result.returncode != 0 and problems:
        raise RuntimeError(problems[-1][-400:])


def restore_errors(stderr):
    """pg_restore error lines that matter. The public schema already existing is expected."""
    lines = [line.strip() for line in (stderr or "").splitlines()]
    errors = []
    for index, line in enumerate(lines):
        if "error:" not in line or "errors ignored on restore" in line:
            continue
        context = " ".join(lines[index:index + 3])
        if 'schema "public" already exists' in context or "must be owner of" in context:
            continue
        # A dump from a newer PostgreSQL sets parameters this server does not have.
        # pg_restore keeps going after that SET fails.
        if "unrecognized configuration parameter" in context:
            continue
        errors.append(line)
    return errors


def _after_restore():
    """Bring the restored schema up to date and drop pooled connections that were closed."""
    from resonance import db

    db.migrate()
    if db.pool is not None:
        db.pool.check()
    db._interrupt_restarted_jobs()
    try:
        from curator.video import store

        store.interrupt_running()
    except Exception:
        logger.exception("could not reset video jobs after the restore")


def prune(directory, keep):
    """Keep the newest dump files. Names sort by the timestamp they contain."""
    try:
        keep_count = max(1, min(int(keep), 100))
    except (TypeError, ValueError):
        keep_count = 14
    # Dumps made before the rename are called resonance-*. Both kinds are pruned, oldest timestamp first.
    paths = sorted(
        [*Path(directory).glob("curator-*.dump"), *Path(directory).glob("resonance-*.dump")],
        key=lambda item: item.name.split("-", 1)[1],
    )
    for path in paths[: max(0, len(paths) - keep_count)]:
        try:
            path.unlink()
        except OSError:
            logger.warning("could not remove old backup %s", path)
