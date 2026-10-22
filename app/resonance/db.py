import logging
import os
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote_plus
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

pool = None
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def database_url():
    explicit = os_environ_url()
    if explicit:
        return explicit
    user = quote_plus(os_environ("POSTGRES_USER", "resonance"))
    password = quote_plus(os_environ("POSTGRES_PASSWORD", "resonance"))
    host = os_environ("POSTGRES_HOST", "postgres")
    port = os_environ("POSTGRES_PORT", "5432")
    name = quote_plus(os_environ("POSTGRES_DB", "resonance"))
    return f"postgresql://{user}:{password}@{host}:{port}/{name}?connect_timeout=5"


def os_environ(key, default):
    import os

    return os.environ.get(key, default)


def os_environ_url():
    import os

    return os.environ.get("DATABASE_URL", "").strip()


def init_db():
    global pool
    url = database_url()
    last = None
    for attempt in range(60):
        try:
            with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
                conn.execute("SELECT 1")
                close_leftover_sessions(conn)
            break
        except Exception as exc:
            last = exc
            logger.warning("database not ready (%s/60): %s", attempt + 1, exc)
            try:
                from curator.boot_status import advance

                advance(0.08 + (attempt + 1) / 60 * 0.34)
            except Exception:
                pass
            time.sleep(1)
    else:
        raise RuntimeError(f"database not ready: {last}")
    try:
        from curator.boot_status import advance

        advance(0.46)
    except Exception:
        pass
    migrate()
    # Auto-size: probe_workers + scrape/ingest concurrency + headroom for UI/background tasks.
    # CMM_PROBE_WORKERS defaults to 8 (max 20); we add 6 extra for scraping and UI threads, minimum 16.
    _probe_workers = max(1, min(20, int(os.environ.get("CMM_PROBE_WORKERS", "8").strip() or "8")))
    _pool_size = max(16, _probe_workers + 6)
    pool = ConnectionPool(
        url,
        min_size=2,
        max_size=_pool_size,
        timeout=30,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=True,
    )
    with pool.connection() as conn:
        conn.execute("SELECT 1")
        conn.commit()
    try:
        from curator.boot_status import advance

        advance(0.58)
    except Exception:
        pass
    _interrupt_restarted_jobs()


def split_sql(script):
    statements = []
    buf = []
    dollar = False
    for line in script.splitlines():
        stripped = line.strip()
        if not dollar and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if line.count("$$") % 2 == 1:
            dollar = not dollar
        if not dollar and line.rstrip().endswith(";"):
            statement = "\n".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def close_leftover_sessions(conn, wait_for_maintenance=False):
    """End client sessions left by a previous process.

    Catalogue maintenance keeps its lock until that statement finishes. Terminating
    it makes Postgres log a fatal administrator shutdown for a query that was
    going to commit on its own. Startup leaves it running. A schema change waits
    for it, because those statements need the same locks.
    """
    rows = conn.execute(
        """
        SELECT pid, state, query
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
        """
    ).fetchall()
    if not rows:
        return 0
    rehome = [row for row in rows if _rehome_statement(row["query"])]
    others = [row for row in rows if row not in rehome]
    for row in others:
        conn.execute("SELECT pg_terminate_backend(%s)", (row["pid"],))
        logger.warning(
            "closed leftover database session %s state=%s query=%s",
            row["pid"],
            row["state"] or "",
            " ".join((row["query"] or "").split())[:160],
        )
    if rehome and wait_for_maintenance:
        logger.info("waiting for catalogue maintenance to finish before schema changes")
    pending = [row["pid"] for row in others]
    if wait_for_maintenance:
        pending.extend(row["pid"] for row in rehome)
    if not pending:
        return len(rows)
    other_pids = {row["pid"] for row in others}
    for _ in range(480 if rehome and wait_for_maintenance else 40):
        still = conn.execute(
            """
            SELECT pid, query
            FROM pg_stat_activity
            WHERE pid = ANY(%s)
            """,
            (pending,),
        ).fetchall()
        if not still:
            return len(rows)
        pending = [row["pid"] for row in still if row["pid"] in other_pids or (wait_for_maintenance and _rehome_statement(row["query"]))]
        if not pending:
            return len(rows)
        time.sleep(0.25)
    logger.warning("leftover database sessions still open after waiting")
    return len(rows)


def catalogue_maintenance_running(conn):
    rows = conn.execute(
        """
        SELECT query
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
        """
    ).fetchall()
    return any(_rehome_statement(row["query"]) for row in rows)


def _rehome_statement(query):
    """True for the album rehome, including the prefix Postgres keeps in pg_stat_activity.

    That view stores about 1024 characters. The UPDATE sits past that, so a restart
    used to treat the still-running rehome as an ordinary leftover session and cancel it.
    """
    text = " ".join((query or "").split()).lower()
    if "curator-album-rehome" in text or "curator-original-year" in text:
        return True
    if "update albums" in text and "musicbrainz_albumartistid" in text:
        return True
    return "with tagged" in text and "musicbrainz_albumartistid" in text and "album_choice" in text


CURRENT_SCHEMA_VERSION = 1


_schema_checksum_cache: str | None = None

def schema_checksum():
    global _schema_checksum_cache
    if _schema_checksum_cache is None:
        import hashlib
        _schema_checksum_cache = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    return _schema_checksum_cache


def is_schema_up_to_date(conn):
    try:
        present = conn.execute("SELECT to_regclass('public.schema_version') AS rel").fetchone()
        if not present or not present.get("rel"):
            return False
        row = conn.execute(
            """
            SELECT version, checksum
            FROM schema_version
            ORDER BY version DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return False
        return (
            row.get("version") == CURRENT_SCHEMA_VERSION
            and row.get("checksum") == schema_checksum()
        )
    except Exception:
        return False


def record_schema_version(conn):
    conn.execute(
        """
        INSERT INTO schema_version (version, checksum, applied_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (version) DO UPDATE
            SET checksum = EXCLUDED.checksum,
                applied_at = NOW()
        """,
        (CURRENT_SCHEMA_VERSION, schema_checksum()),
    )


def migrate(force=False):
    url = database_url()
    last = None
    checksum = schema_checksum()
    for attempt in range(5):
        with psycopg.connect(url, row_factory=dict_row, autocommit=True) as conn:
            if not force and is_schema_up_to_date(conn):
                logger.info("schema version %s up to date (hash %s), skipping migration", CURRENT_SCHEMA_VERSION, checksum[:10])
                return
            close_leftover_sessions(conn, wait_for_maintenance=True)
            conn.execute("SET lock_timeout = '10s'")
            try:
                script = SCHEMA_PATH.read_text(encoding="utf-8")
                statements = split_sql(script)
                # Run the whole schema in one transaction: eliminates 800+ individual
                # round-trips on a fresh database and makes the migration atomic.
                with conn.transaction():
                    for statement in statements:
                        conn.execute(statement)
                    _allow_shared_release_ids(conn)
                    record_schema_version(conn)
                logger.info("schema ready (version %s, hash %s)", CURRENT_SCHEMA_VERSION, checksum[:10])
                return
            except psycopg.errors.LockNotAvailable as exc:
                last = exc
                logger.warning("schema lock busy (%s/5): %s", attempt + 1, exc)
        time.sleep(1)
    raise RuntimeError(f"schema lock stayed busy: {last}")


def _interrupt_restarted_jobs():
    for table in ("scan_jobs", "batch_jobs", "work_jobs"):
        waiting = "('running', 'queued')" if table == "work_jobs" else "('running')"
        execute(
            f"""
            UPDATE {table}
            SET status = 'interrupted',
                message = 'Interrupted by restart',
                finished_at = NOW()
            WHERE status IN {waiting}
            """
        )


def maintain_catalog():
    """Fill original years and rehome tagged albums after the server is listening."""
    try:
        with psycopg.connect(database_url(), autocommit=True, row_factory=dict_row) as conn:
            if catalogue_maintenance_running(conn):
                logger.info("catalogue maintenance already running from the previous start")
                return
            from resonance.library import rehome_tagged_artists
            from resonance.upgrade import store_original_years

            store_original_years(conn)
            rehome_tagged_artists(conn)
        from resonance.upgrade import clear_orphan_flags

        clear_orphan_flags()
        logger.info("catalogue maintenance finished")
    except Exception:
        logger.exception("catalogue maintenance failed")


def allow_shared_release_ids():
    """Let two albums store the same MusicBrainz release. Those copies are duplicates."""
    with psycopg.connect(database_url(), autocommit=True, row_factory=dict_row) as conn:
        return _allow_shared_release_ids(conn)


def _allow_shared_release_ids(conn):
    from psycopg import sql

    constraints = conn.execute(
        """
        SELECT n.nspname AS schema_name, c.conname AS name
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relname = 'albums'
          AND c.contype = 'u'
          AND pg_get_constraintdef(c.oid) ILIKE '%musicbrainz_release_id%'
        """
    ).fetchall()
    for row in constraints:
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT {}").format(
                sql.Identifier(row["schema_name"]),
                sql.Identifier("albums"),
                sql.Identifier(row["name"]),
            )
        )
    indexes = conn.execute(
        """
        SELECT n.nspname AS schema_name, ic.relname AS name
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_class tc ON tc.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = ic.relnamespace
        WHERE tc.relname = 'albums'
          AND i.indisunique
          AND NOT i.indisprimary
          AND pg_get_indexdef(i.indexrelid) ILIKE '%musicbrainz_release_id%'
        """
    ).fetchall()
    for row in indexes:
        conn.execute(
            sql.SQL("DROP INDEX IF EXISTS {}.{}").format(
                sql.Identifier(row["schema_name"]),
                sql.Identifier(row["name"]),
            )
        )
    dropped = [row["name"] for row in constraints] + [row["name"] for row in indexes]
    if dropped:
        logger.info("album release ids may be shared; dropped %s", ", ".join(dropped))
    else:
        logger.info("album release ids may already be shared")
    return dropped


@contextmanager
def transaction():
    with pool.connection() as conn:
        with conn.transaction():
            yield conn


def execute(sql, params=()):
    with pool.connection() as conn:
        conn.execute(sql, params)
        conn.commit()


def fetchone(sql, params=()):
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def fetchall(sql, params=()):
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def text_array(values):
    parts = []
    for value in values or []:
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{text}"')
    return "{" + ",".join(parts) + "}"


def artist_mbid_blocked(mbid, name, current_id=None, conn=None):
    """True when a differently named artist already holds this MusicBrainz artist id.

    The same band listed once per library path shares the id, so a holder with the same name
    (ignoring capital letters) does not block it.
    """
    sql = "SELECT id, name FROM artists WHERE musicbrainz_artist_id = %s"
    rows = conn.execute(sql, (mbid,)).fetchall() if conn is not None else fetchall(sql, (mbid,))
    wanted = str(name or "").casefold()
    return any(
        str(row["id"]) != str(current_id) and str(row["name"] or "").casefold() != wanted
        for row in rows
    )


def uuid_array(values):
    parts = [str(UUID(str(value))) for value in values or []]
    return "{" + ",".join(parts) + "}"


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        integral = value.to_integral_value()
        return int(value) if value == integral else float(value)
    return value
