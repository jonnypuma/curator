"""A local copy of IMDb's free datasets, used for ratings, episode ids and basic title facts.

IMDb publishes a few tab separated files for personal and non-commercial use at datasets.imdbws.com. This module
fetches three of them (title.ratings, title.episode and title.basics), builds one SQLite index from them and answers
lookups from that index, so a scrape needs no web request for what these files hold.

How it stays within IMDb's terms:

* It does nothing unless the person turns it on in Settings. Each install downloads straight from
  datasets.imdbws.com for its own user. The files are never bundled in the image or the repository, and nothing
  here serves them to anyone.
* The request sends a common browser user agent (`default_user_agent`). A person can enter any name in Settings, for
  example the one their own agreement with IMDb asks for, and that is sent instead.
* A downloaded file is deleted as soon as the index is built. Files the person put in `<data>/imdb` themselves are
  read but never changed or deleted.
* The index is refreshed on an interval (30 days by default), not on every scan.

The index lives in the cache folder, so deleting that folder only costs a new build. A build goes to a side file and
replaces the old index in one step, so a failed or interrupted build leaves the old data as it was.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import requests

from resonance import paths
from resonance.errors import AppError

logger = logging.getLogger(__name__)

BASE_URL = "https://datasets.imdbws.com/"
TERMS_URL = "https://developer.imdb.com/non-commercial-datasets"
LICENSE_URL = "https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX"
PROJECT_URL = "https://github.com/jonnypuma/curator"

RATINGS = "title.ratings.tsv.gz"
EPISODES = "title.episode.tsv.gz"
BASICS = "title.basics.tsv.gz"
FILES = (RATINGS, EPISODES, BASICS)
# Several times the real sizes, so a wrong answer from the server cannot fill the disk.
MAX_BYTES = {RATINGS: 100 * 2**20, EPISODES: 400 * 2**20, BASICS: 1200 * 2**20}

SCHEMA = 1
# A file smaller than this is not a dataset, so a copy the person placed in the data folder is ignored.
MIN_BYTES = 1024
DEFAULT_DAYS = 30
MIN_DAYS, MAX_DAYS = 7, 365
# After a failed refresh nothing is tried again by itself for a day. "Refresh now" still works.
RETRY_AFTER_FAILURE = 24 * 3600
POLL_SECONDS = 15 * 60
STEPS = 7

# The kinds of title kept from title.basics. Episodes are left out: their ids come from title.episode.
KIND_CODES = {"movie": 1, "tvMovie": 2, "tvSeries": 3, "tvMiniSeries": 4, "tvSpecial": 5, "video": 6}
KIND_NAMES = {code: name for name, code in KIND_CODES.items()}

_lock = threading.Lock()
_wake = threading.Event()
_forced = False
_local = threading.local()
_progress = {"message": "", "done": 0}

TABLES = """
CREATE TABLE ratings (t INTEGER PRIMARY KEY, r INTEGER NOT NULL, v INTEGER NOT NULL);
CREATE TABLE episodes (
    parent INTEGER NOT NULL, season INTEGER NOT NULL, number INTEGER NOT NULL, t INTEGER NOT NULL,
    PRIMARY KEY (parent, season, number)
) WITHOUT ROWID;
CREATE TABLE titles (
    t INTEGER PRIMARY KEY, kind INTEGER NOT NULL, title TEXT, original TEXT,
    year INTEGER, ended INTEGER, runtime INTEGER, genres TEXT
);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


# --- where things live -----------------------------------------------------------------------------------------

def work_dir():
    return os.path.join(paths.cache_dir(), "imdb")


def index_path():
    return os.path.join(work_dir(), "imdb.sqlite")


def dropin_dir():
    """Datasets the person downloaded themselves. Read when fresh enough; never changed or deleted."""
    return os.path.join(paths.data_dir(), "imdb")


def _state_path():
    return os.path.join(work_dir(), "state.json")


# A common desktop browser name. Settings can replace it with anything.
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def default_user_agent():
    return BROWSER_USER_AGENT


def user_agent():
    """What requests to IMDb call themselves: the name saved in Settings, else the default naming Curator."""
    try:
        from curator.video import config

        custom = str(config.current().get("imdb_user_agent") or "").strip()
    except Exception:
        custom = ""
    return custom or default_user_agent()


def clamp_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(MIN_DAYS, min(MAX_DAYS, days))


# --- remembered outcome of the last attempt ----------------------------------------------------------------

def _recall():
    try:
        with open(_state_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(**changes):
    data = {**_recall(), **changes}
    try:
        os.makedirs(work_dir(), exist_ok=True)
        with open(_state_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError:
        logger.debug("could not write the IMDb data state", exc_info=True)


def _drop(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# --- reading the index -------------------------------------------------------------------------------------

def _db():
    """A read-only connection for this thread. It reopens by itself when the index has been replaced."""
    path = index_path()
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "key", None) == key:
        return conn
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        _local.conn = None
    try:
        conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=5)
        row = conn.execute("SELECT v FROM meta WHERE k = 'schema'").fetchone()
        if not row or str(row[0]) != str(SCHEMA):
            conn.close()
            return None
    except sqlite3.Error:
        return None
    _local.conn, _local.key = conn, key
    return conn


def ready():
    """True when an index of the right version is on disk."""
    return _db() is not None


def _number(imdb_id):
    text = str(imdb_id or "").strip().lower()
    if text.startswith("tt"):
        text = text[2:]
    return int(text) if text.isascii() and text.isdigit() and text else None


def _imdb(number):
    return "tt%07d" % number


def _meta(conn=None):
    conn = conn or _db()
    if conn is None:
        return {}
    try:
        return {key: value for key, value in conn.execute("SELECT k, v FROM meta")}
    except sqlite3.Error:
        return {}


def rating(imdb_id):
    """{"value": 8.7, "votes": 2100000, "max": 10} for a title IMDb rates, else None."""
    number, conn = _number(imdb_id), _db()
    if number is None or conn is None:
        return None
    try:
        row = conn.execute("SELECT r, v FROM ratings WHERE t = ?", (number,)).fetchone()
    except sqlite3.Error:
        return None
    return {"value": row[0] / 10, "votes": row[1], "max": 10} if row else None


def episode(show_imdb, season, number):
    """The IMDb id of one episode of a show and, when it has one, its rating: {"imdb": "tt...", "rating": {...}}."""
    parent, conn = _number(show_imdb), _db()
    if parent is None or conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT t FROM episodes WHERE parent = ? AND season = ? AND number = ?", (parent, int(season), int(number))
        ).fetchone()
    except (sqlite3.Error, TypeError, ValueError):
        return None
    if not row:
        return None
    return {"imdb": _imdb(row[0]), "rating": rating(_imdb(row[0]))}


def title(imdb_id):
    """Basic facts for a movie or a show: title, original_title, year, runtime, genres and kind. None if unknown."""
    number, conn = _number(imdb_id), _db()
    if number is None or conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT kind, title, original, year, ended, runtime, genres FROM titles WHERE t = ?", (number,)
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    kind, name, original, year, ended, runtime, genres = row
    found = {
        "kind": KIND_NAMES.get(kind, ""),
        "title": name,
        "original_title": original or name,
        "year": year,
        "end_year": ended,
        "runtime": runtime,
        "genres": [g for g in (genres or "").split(",") if g],
    }
    return {key: value for key, value in found.items() if value not in (None, "", [])}


# --- reading the files -------------------------------------------------------------------------------------

def _layout_error(name):
    return AppError(f"IMDb changed the layout of {name}; the local copy was left as it was", 502)


def _columns(header, wanted, name):
    names = header.rstrip("\r\n").split("\t")
    try:
        return [names.index(column) for column in wanted]
    except ValueError:
        raise _layout_error(name) from None


def _id(text):
    if len(text) > 2 and text.startswith("tt") and text[2:].isascii() and text[2:].isdigit():
        return int(text[2:])
    return None


def _count(text):
    """A whole number, or None for IMDb's \\N."""
    return int(text) if text.isascii() and text.isdigit() else None


def _text(text):
    return None if text in ("", "\\N") else text


def _lines(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield handle.readline()
        yield from handle


def _ratings_rows(path):
    lines = _lines(path)
    at = _columns(next(lines), ("tconst", "averageRating", "numVotes"), RATINGS)
    for line in lines:
        parts = line.rstrip("\r\n").split("\t")
        try:
            number = _id(parts[at[0]])
            average, votes = round(float(parts[at[1]]) * 10), int(parts[at[2]])
        except (ValueError, IndexError):
            continue
        if number is not None:
            yield (number, average, votes)


def _episode_rows(path):
    lines = _lines(path)
    at = _columns(next(lines), ("tconst", "parentTconst", "seasonNumber", "episodeNumber"), EPISODES)
    for line in lines:
        parts = line.rstrip("\r\n").split("\t")
        try:
            number, parent = _id(parts[at[0]]), _id(parts[at[1]])
            season, episode_number = _count(parts[at[2]]), _count(parts[at[3]])
        except IndexError:
            continue
        if None not in (number, parent, season, episode_number):
            yield (parent, season, episode_number, number)


def _title_rows(path):
    lines = _lines(path)
    at = _columns(
        next(lines),
        ("tconst", "titleType", "primaryTitle", "originalTitle", "startYear", "endYear", "runtimeMinutes", "genres"),
        BASICS,
    )
    if at[:2] != [0, 1]:
        raise _layout_error(BASICS)
    for line in lines:
        head = line.split("\t", 2)
        if len(head) < 3 or head[1] not in KIND_CODES:
            continue
        parts = line.rstrip("\r\n").split("\t")
        try:
            number = _id(parts[0])
            name, original = _text(parts[at[2]]), _text(parts[at[3]])
            year, ended, runtime = _count(parts[at[4]]), _count(parts[at[5]]), _count(parts[at[6]])
            genres = _text(parts[at[7]])
        except IndexError:
            continue
        if number is not None and name:
            yield (number, KIND_CODES[head[1]], name, None if original == name else original, year, ended, runtime, genres)


def _insert(conn, sql, rows, batch=50_000):
    total, chunk = 0, []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= batch:
            conn.executemany(sql, chunk)
            total += len(chunk)
            chunk = []
    if chunk:
        conn.executemany(sql, chunk)
        total += len(chunk)
    return total


# --- downloading -------------------------------------------------------------------------------------------

def _stamp(headers):
    """What identifies one published version of a file. Empty when the server gives nothing to compare."""
    etag, modified = headers.get("ETag") or "", headers.get("Last-Modified") or ""
    return f"{etag}|{modified}|{headers.get('Content-Length') or ''}" if (etag or modified) else ""


def _remote_stamps():
    """The version marks of the three files, from HEAD requests. Empty if IMDb could not be asked or gave none."""
    found = {}
    for name in FILES:
        try:
            response = requests.head(
                BASE_URL + name, timeout=15, allow_redirects=True, headers={"User-Agent": user_agent()}
            )
        except requests.RequestException:
            return {}
        stamp = _stamp(response.headers) if response.status_code == 200 else ""
        if not stamp:
            return {}
        found[name] = stamp
    return found


def _fetch(name, report):
    """Download one file into the work folder. Returns (path, stamp)."""
    target = os.path.join(work_dir(), name)
    part = target + ".part"
    cap = MAX_BYTES[name]
    try:
        with requests.get(
            BASE_URL + name,
            stream=True,
            timeout=(10, 60),
            headers={"User-Agent": user_agent(), "Accept-Encoding": "identity"},
        ) as response:
            if response.status_code != 200:
                raise AppError(f"IMDb answered {response.status_code} for {name}", 502)
            expected = int(response.headers.get("Content-Length") or 0)
            if expected > cap:
                raise AppError(f"{name} is far larger than expected; nothing was downloaded", 502)
            written = 0
            with open(part, "wb") as out:
                for chunk in response.iter_content(1 << 20):
                    written += len(chunk)
                    if written > cap:
                        raise AppError(f"{name} is far larger than expected; the download was stopped", 502)
                    out.write(chunk)
                    report(f"Downloading {name} ({written // 2**20} MB)")
            stamp = _stamp(response.headers)
        if expected and written != expected:
            raise AppError(f"The download of {name} was cut short", 502)
        os.replace(part, target)
        return target, stamp
    except requests.RequestException as exc:
        raise AppError(f"Could not download {name} from IMDb ({exc.__class__.__name__})", 502) from None
    except OSError as exc:
        raise AppError(f"Could not save {name} in the cache folder ({exc.strerror or exc.__class__.__name__})", 500) from None
    finally:
        _drop(part)


def _fresh_dropins(days):
    """Files the person placed in the data folder that are newer than the refresh interval: {name: path}."""
    found, limit = {}, time.time() - days * 86400
    for name in FILES:
        path = os.path.join(dropin_dir(), name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if stat.st_size >= MIN_BYTES and stat.st_mtime >= limit:
            found[name] = path
    return found


# --- building ----------------------------------------------------------------------------------------------

def _build(sources, target, report):
    _drop(target)
    conn = sqlite3.connect(target)
    try:
        conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-200000;" + TABLES)
        counts = {}
        report("Indexing ratings", 1)
        counts["ratings"] = _insert(conn, "INSERT OR REPLACE INTO ratings VALUES (?, ?, ?)", _ratings_rows(sources[RATINGS]))
        report("Indexing episodes", 2)
        counts["episodes"] = _insert(conn, "INSERT OR IGNORE INTO episodes VALUES (?, ?, ?, ?)", _episode_rows(sources[EPISODES]))
        report("Indexing titles", 3)
        counts["titles"] = _insert(conn, "INSERT OR REPLACE INTO titles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", _title_rows(sources[BASICS]))
        conn.commit()
        return counts
    finally:
        conn.close()


def _write_meta(path, **values):
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)", [(key, str(value)) for key, value in values.items()]
        )
        conn.commit()
    finally:
        conn.close()


def _say(report):
    def send(message, done=None):
        _progress["message"] = message
        if done is not None:
            _progress["done"] = done
        report(message, _progress["done"])

    return send


def refresh(days=DEFAULT_DAYS, report=None):
    """Bring the index up to date. Raises AppError with a plain message when it cannot. Returns a result dict."""
    if not _lock.acquire(blocking=False):
        raise AppError("The IMDb data is already being updated", 409)
    try:
        _progress.update(message="Starting", done=0)
        send = _say(report or (lambda message, done: None))
        try:
            return _refresh(clamp_days(days), send)
        except AppError as exc:
            _remember(attempt=time.time(), error=str(exc))
            raise
        except Exception as exc:
            logger.exception("the IMDb data could not be built")
            message = f"The IMDb data could not be built ({exc.__class__.__name__})"
            _remember(attempt=time.time(), error=message)
            raise AppError(message, 500) from None
    finally:
        _progress.update(message="", done=0)
        _lock.release()


def _refresh(days, send):
    folder = work_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise AppError(f"Cannot use the cache folder ({exc.strerror or exc.__class__.__name__})", 500) from None
    for stale in os.listdir(folder):
        if stale.endswith((".part", ".new")):
            _drop(os.path.join(folder, stale))
    _remember(attempt=time.time())

    sources = dict(_fresh_dropins(days))
    downloaded = []
    stamps = {}
    if len(sources) < len(FILES):
        send("Checking what IMDb has published", 0)
        wanted = _remote_stamps()
        previous = _meta()
        if wanted and not sources and previous.get("stamps") == json.dumps(wanted, sort_keys=True):
            _write_meta(index_path(), checked_at=int(time.time()))
            _remember(error="")
            return {"changed": False, "message": "IMDb has not published newer files; the local copy is current"}
        free = shutil.disk_usage(folder).free
        if free < 3 * 2**29:
            raise AppError("There is less than 1.5 GB free in the cache folder, which a download and the index need", 507)
        for name in FILES:
            if name in sources:
                continue
            path, stamp = _fetch(name, lambda message: send(message))
            sources[name] = path
            downloaded.append(path)
            stamps[name] = stamp or (wanted or {}).get(name, "")
    for name, path in sources.items():
        if name not in stamps:
            stat = os.stat(path)
            stamps[name] = f"data|{int(stat.st_mtime)}|{stat.st_size}"

    target = index_path() + ".new"
    try:
        counts = _build(sources, target, send)
        send("Finishing", 4)
        used_data_folder = any(path.startswith(dropin_dir()) for path in sources.values())
        now = int(time.time())
        _write_meta(
            target,
            schema=SCHEMA,
            built_at=now,
            checked_at=now,
            source="data folder" if used_data_folder and not downloaded else ("download" if not used_data_folder else "mixed"),
            stamps=json.dumps(stamps, sort_keys=True) if len(downloaded) == len(FILES) else "",
            counts=json.dumps(counts),
        )
        os.replace(target, index_path())
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise AppError(f"The IMDb files could not be read ({exc.__class__.__name__}); the old copy was kept", 500) from None
    finally:
        _drop(target)
        for path in downloaded:
            _drop(path)
    _remember(error="", attempt=time.time())
    return {"changed": True, "counts": counts, "message": "IMDb data updated"}


# --- what the scrapes use -----------------------------------------------------------------------------------

def usable(cfg):
    """Lookups happen only when the switch is on and an index has been built."""
    return bool((cfg or {}).get("imdb_data")) and ready()


def title_result(cfg, imdb_id):
    """What the index knows about a movie or show, shaped like a scraper's answer.

    It is added after the other sources, so it only fills what they left empty: the IMDb score when OMDb gave none,
    and a missing title, year, runtime or genre list."""
    if not imdb_id or not usable(cfg):
        return None
    facts, score = title(imdb_id), rating(imdb_id)
    result = {"source": "imdb_data"}
    if facts:
        result.update(
            title=facts.get("title"),
            original_title=facts.get("original_title"),
            year=facts.get("year"),
            runtime_minutes=facts.get("runtime"),
            genres=facts.get("genres") or [],
        )
    if score:
        result["ratings"] = {"imdb": score}
    return result if len(result) > 1 else None


def episode_result(cfg, show_imdb, season, number):
    """An episode's own IMDb id and score, found by the show's IMDb id and the episode's place in it."""
    if not show_imdb or season is None or number is None or not usable(cfg):
        return None
    found = episode(show_imdb, season, number)
    if not found:
        return None
    result = {"source": "imdb_data", "ids": {"imdb": found["imdb"]}}
    if found.get("rating"):
        result["ratings"] = {"imdb": found["rating"]}
    return result


# --- when to refresh ---------------------------------------------------------------------------------------

def age_seconds():
    meta = _meta()
    marker = max(int(meta.get("built_at") or 0), int(meta.get("checked_at") or 0))
    return time.time() - marker if marker else None


def due(days=DEFAULT_DAYS):
    """True when there is no index yet or it is older than the interval, unless a recent attempt failed."""
    state = _recall()
    if state.get("error") and time.time() - float(state.get("attempt") or 0) < RETRY_AFTER_FAILURE:
        return False
    age = age_seconds()
    return age is None or age >= clamp_days(days) * 86400


def status(days=DEFAULT_DAYS):
    meta = _meta()
    state = _recall()
    age = age_seconds()
    try:
        size = os.path.getsize(index_path())
    except OSError:
        size = 0
    try:
        counts = json.loads(meta.get("counts") or "{}")
    except ValueError:
        counts = {}
    return {
        "ready": bool(meta),
        "running": _lock.locked(),
        "queued": _forced,
        "step": _progress["message"],
        "built_at": int(meta.get("built_at") or 0),
        "checked_at": int(meta.get("checked_at") or 0),
        "age_days": None if age is None else int(age // 86400),
        "next_in_days": None if age is None else max(0, clamp_days(days) - int(age // 86400)),
        "source": meta.get("source", ""),
        "counts": counts,
        "size": size,
        "error": state.get("error") or "",
        "data_folder": dropin_dir(),
        "data_folder_files": sorted(_fresh_dropins(clamp_days(days))),
    }


def remove():
    """Delete the index and anything left from a download. Files in the data folder are not touched."""
    if _lock.locked():
        raise AppError("The IMDb data is being updated; try again when it has finished", 409)
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        _local.conn = None
    folder = work_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    removed = 0
    for name in names:
        if name == "state.json" or name.startswith("imdb.sqlite") or name.endswith((".part", ".new", ".tsv.gz")):
            _drop(os.path.join(folder, name))
            removed += 1
    return removed


def request(force=False):
    """Ask the background thread to look now instead of at its next round. `force` skips the interval check."""
    global _forced
    if force:
        _forced = True
    _wake.set()


def refresh_if_due(force=False):
    """The background job: refresh when the switch is on and the data is missing or older than the interval.

    The switch is read from the saved settings each time, so nothing is downloaded while it is off, even when
    `force` is set."""
    from curator.video import config

    cfg = config.current()
    if not cfg.get("imdb_data") or _lock.locked():
        return False
    if not force and not due(cfg.get("imdb_refresh_days")):
        return False
    run(cfg.get("imdb_refresh_days"))
    return True


def run(days=DEFAULT_DAYS):
    """A refresh shown in the Jobs panel. Raises AppError when it fails, after recording the failure."""
    from curator.video import work_track

    job = work_track.Tracked("imdb_data", "Updating IMDb data", STEPS)
    try:
        result = refresh(days, lambda message, done: job.update(done, message))
    except AppError as exc:
        job.finish("failed", str(exc), 0)
        raise
    job.finish("completed", result["message"], STEPS)
    return result


def _loop():
    global _forced
    _wake.wait(120)
    while True:
        _wake.clear()
        forced, _forced = _forced, False
        try:
            refresh_if_due(forced)
        except AppError as exc:
            logger.warning("IMDb data: %s", exc)
        except Exception:
            logger.exception("the IMDb data check failed")
        _wake.wait(POLL_SECONDS)


def start():
    threading.Thread(target=_loop, name="imdb-data", daemon=True).start()
