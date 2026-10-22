import logging
import os
import re
import time
from collections import Counter
from datetime import datetime

from psycopg.types.json import Json

from resonance import completeness, db, tags
from resonance.errors import AppError
from resonance.fields import (
    album_title_without_disc,
    clean_text,
    leading_int,
    opt_uuid_loose,
    release_type,
    genre_name,
    year_from,
)
from resonance.paths import choose_roots, config_dir, like_prefix, music_roots, path_kind
from resonance.settings import apply_steps, load as load_settings

logger = logging.getLogger(__name__)


def normalize_scan_mode(mode):
    text = str(mode or "").strip().lower()
    if text in {"full", "deep"}:
        return text
    return "incremental"


def _shared_release_conflict(exc):
    text = f"{exc}".lower()
    if "musicbrainz_release_id" in text and "duplicate key" in text:
        return True
    diag = getattr(exc, "diag", None)
    if diag is None:
        return False
    detail = " ".join(
        str(getattr(diag, name, "") or "")
        for name in ("constraint_name", "message_detail", "message_primary")
    ).lower()
    return "musicbrainz_release_id" in detail and "duplicate" in detail


def _checkpoint():
    from resonance.jobs import checkpoint

    checkpoint()


def _album_targets(albums, roots):
    from resonance.paths import inside

    chosen = []
    seen = set()
    for item in albums or []:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip()
        if not os.path.isdir(raw):
            continue
        real = os.path.realpath(raw)
        if not any(inside(root, real) or _same_path(root, real) for root in roots):
            continue
        key = os.path.normcase(real)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(real)
    return chosen


def _artist_folder(album_path):
    from resonance.paths import inside

    root = _release_root(album_path)
    parent = os.path.dirname(album_path.rstrip(os.sep))
    if root and parent and not _same_path(parent, root) and (inside(root, parent) or _same_path(root, parent)):
        return parent
    if root and path_kind(root) == "artist":
        return os.path.realpath(root)
    return album_path


def _ids_for_paths(paths):
    wanted = list(dict.fromkeys(path for path in paths if path))
    if not wanted:
        return []
    rows = db.fetchall("SELECT id FROM albums WHERE path = ANY(%s)", (wanted,))
    return [row["id"] for row in rows]


def _scan_selected_albums(progress, targets, roots, settings, mode, force):
    """Index the chosen album folders and leave every other album in place."""
    file_index = _load_scan_index() if mode == "incremental" else None
    errors = 0
    changed_files = 0
    unchanged_files = 0
    skipped_albums = 0
    lookup_ids = []
    seen = []
    artists = []
    progress.update(0, len(targets), "Scanning selected albums", "delta")
    for index, album_path in enumerate(targets, start=1):
        _checkpoint()
        artist_path = _artist_folder(album_path)
        name = os.path.basename(album_path.rstrip(os.sep))
        progress.update(index - 1, len(targets), f"Scanning {name}", "delta")
        artist_id, album_paths, album_errors, stats, album_failures = _scan_artist(
            artist_path, settings, mode, progress, only_album=album_path, file_index=file_index
        )
        errors += album_errors
        changed_files += stats["changed"]
        unchanged_files += stats["unchanged"]
        skipped_albums += int(stats.get("skipped_albums") or 0)
        lookup_ids.extend(stats.get("lookup_ids") or [])
        seen.extend(album_paths or [album_path])
        if artist_id and artist_path not in artists:
            artists.append(artist_path)
        for failure in album_failures:
            progress.issue(f"Failed: {failure['path']}: {failure['error']}")
        progress.update(index, len(targets), f"Scanning {name}", "delta")
    selected_ids = _ids_for_paths(seen)
    scope_ids = selected_ids if mode in {"full", "deep"} else lookup_ids
    looked_up_labels = _rematch(progress, roots, scope_ids, mode=mode, force=force)
    _fill_stored_mb_metadata(progress, roots, mode, scope_ids)
    if mode in {"full", "deep"} and artists:
        _sidecar_summary(progress, artists)
        _refresh_discographies(progress, artists)
    if load_settings().get("fill_missing_during_scan", True) is not False:
        _fill_missing_metadata(progress, roots, scope_ids, skipped_albums if mode == "incremental" else None)
        _fill_missing_artwork(progress, roots, scope_ids, skipped_albums if mode == "incremental" else None)
    _nfos_from_scan(progress, roots, mode, None if mode == "deep" else scope_ids)
    message = f"Indexed {len(seen)} albums"
    if mode in {"incremental", "full"}:
        message += f", {unchanged_files} unchanged, {changed_files} changed/new, {len(looked_up_labels)} albums looked up"
    if mode == "incremental":
        message += f", {skipped_albums} albums left unchanged"
    if errors:
        message += f", {errors} errors"
    progress.log(message, phase="artwork", message=message)
    try:
        from resonance import webhooks

        webhooks.fire("scan")
    except Exception:
        logger.info("music library update after scan failed", exc_info=True)
    return message

AUDIO_EXTS = {
    ".mp3",
    ".flac",
    ".m4a",
    ".mp4",
    ".ogg",
    ".opus",
    ".wma",
    ".aac",
    ".wav",
    ".aiff",
    ".aif",
}
DISC_RE = re.compile(r"(?:cd|disc|disk)\s*0*(\d+)", re.IGNORECASE)
DISC_ONLY = re.compile(r"^(?:cd|disc|disk)\s*0*\d+$", re.IGNORECASE)
SIDECAR_DIRS = {"extrafanart", "artwork", "art", "scans", "extras"}
SKIP_DIRS = {"lost+found", "@eadir", ".trash", "extrafanart", "artwork", "art", "scans", "_archive"}
# Album / wrapper / disc / files. One level misses a release folder inside the album folder.
AUDIO_NEST_DEPTH = 3


def scan(job_id, force=False, mode="incremental", roots=None, verbose=False, albums=None):
    from resonance.settings import verbose_enabled

    mode = normalize_scan_mode(mode)
    if verbose_enabled():
        verbose = True
    from curator.folders import excluded_real

    skip = excluded_real()
    mounted_roots = music_roots()
    configured = [path for path in mounted_roots if path not in skip]
    # Configured paths that cannot be read right now. music_roots() has already dropped
    # them, so without this they would look like paths the user removed and _prune would
    # delete everything indexed under them.
    from resonance.paths import protected_prefixes, unscannable_library_paths

    offline_roots = unscannable_library_paths("music")
    if not configured:
        if mounted_roots:
            raise AppError("Every music folder is excluded from scans. Turn Exclude off under Settings, General.", 400)
        raise AppError("No music paths are mounted. Add a library path in Settings.", 400)
    if roots:
        kept = []
        for item in roots:
            real = os.path.realpath(item) if item and os.path.exists(item) else os.path.normpath(item or "")
            if real and real not in skip:
                kept.append(item)
        roots = kept
    roots = choose_roots(roots, configured) if roots else list(configured)
    targets = _album_targets(albums, roots) if albums else []
    if albums and not targets:
        raise AppError("None of the selected albums are inside a music library path.", 400)
    from resonance.db import allow_shared_release_ids

    allow_shared_release_ids()
    settings = load_settings()
    progress = _Progress(job_id, verbose=verbose)
    progress.paced = True
    from resonance import scan_pace

    scan_pace.begin("music", "directory")
    logger.info("scan starting: mode=%s verbose=%s", mode, bool(verbose))
    progress.log("Directory walk started", phase="directory", message="Walking music folders")
    for missing in offline_roots:
        progress.issue(
            f"Cannot be read: {missing} is skipped and nothing indexed under it will be "
            f"removed. Take the path out in Settings and scan again to remove its items."
        )
    if verbose:
        progress.log("Verbose log is on. Each album is written here and to the container log.")
    artist_dirs = []
    loose = 0
    readable = []
    seen_artists = []
    seen_albums = []
    errors = 0
    changed_files = 0
    unchanged_files = 0
    lookup_ids = []
    skipped_albums = 0
    looked_up_labels = []
    empty_folders = []
    failures = []
    try:
        if targets:
            return _scan_selected_albums(progress, targets, roots, settings, mode, force)
        for root in roots:
            if not os.path.isdir(root):
                failures.append({"path": root, "error": "path is missing"})
                progress.issue(f"Failed: {root}: path is missing")
                continue
            readable.append(root)
            try:
                folders, skipped = _artist_folders(root, path_kind(root))
            except OSError as exc:
                failures.append({"path": root, "error": str(exc)})
                progress.issue(f"Failed: {root}: {exc}")
                raise AppError(f"Cannot read {root}: {exc}", 400) from exc
            artist_dirs.extend(folders)
            loose += skipped
        progress.log(f"Found {len(artist_dirs)} artist folders in {len(readable)} mounted paths")
        if not readable:
            raise AppError("No music paths are mounted. Add a library path in Settings.", 400)
        if not artist_dirs and not force and _count_under(readable):
            raise AppError(
                "Music folders have no artist directories; refusing to clear the library index. Run a deep scan with force if this is intentional.",
                409,
            )
        progress.update(0, len(artist_dirs), "Comparing modification times", "delta")
        file_index = _load_scan_index() if mode == "incremental" else None

        # SPEED 6: run per-artist local metadata scans in parallel threads.
        # Network look-ups (MusicBrainz etc.) happen later and still run serially
        # to respect rate limits; this only parallelises the local disk + DB work.
        import concurrent.futures as _cf
        _artist_workers = max(1, min(4, int(os.environ.get("CMM_ARTIST_WORKERS", "4").strip() or "4")))

        _cancelled = False

        def _scan_one_artist(args):
            index, artist_path = args
            from resonance.jobs import ScanCancelled
            name = os.path.basename(artist_path)
            try:
                found_empty = _empty_folders(artist_path, progress, index - 1, len(artist_dirs))
                artist_id, album_paths, album_errors, stats, album_failures = _scan_artist(
                    artist_path, settings, mode, progress, file_index=file_index
                )
                return {
                    "artist_path": artist_path,
                    "found_empty": found_empty,
                    "artist_id": artist_id,
                    "album_paths": album_paths,
                    "album_errors": album_errors,
                    "stats": stats,
                    "album_failures": album_failures,
                    "name": name,
                    "index": index,
                    "exc": None,
                }
            except ScanCancelled:
                return {"cancelled": True}
            except Exception as exc:
                logger.exception("artist scan failed: %s", artist_path)
                return {
                    "artist_path": artist_path,
                    "exc": exc,
                    "name": name,
                    "index": index,
                }

        with _cf.ThreadPoolExecutor(max_workers=_artist_workers, thread_name_prefix="artist-scan") as _pool:
            for result in _pool.map(_scan_one_artist, enumerate(artist_dirs, start=1)):
                _checkpoint()
                if result.get("cancelled"):
                    progress.log(
                        "Scan cancelled. Indexed music stays. Missing folders were not removed.",
                        message="Scan cancelled",
                    )
                    return "Scan cancelled"
                index = result["index"]
                name = result["name"]
                artist_path = result["artist_path"]
                progress.update(index - 1, len(artist_dirs), f"Scanning {name}", "delta")
                if result.get("exc") is not None:
                    errors += 1
                    failures.append({"path": artist_path, "error": str(result["exc"])})
                    progress.issue(f"Failed: {artist_path}: {result['exc']}")
                else:
                    found_empty = result["found_empty"]
                    empty_folders.extend(found_empty)
                    if found_empty:
                        progress.parked.extend(f"Empty folder: {folder}" for folder in found_empty)
                        progress.log(f"{name}: {len(found_empty)} empty folders")
                    artist_id = result["artist_id"]
                    album_paths = result["album_paths"]
                    album_errors = result["album_errors"]
                    stats = result["stats"]
                    album_failures = result["album_failures"]
                    errors += album_errors
                    changed_files += stats["changed"]
                    unchanged_files += stats["unchanged"]
                    lookup_ids.extend(stats.get("lookup_ids") or [])
                    skipped_albums += int(stats.get("skipped_albums") or 0)
                    for failure in album_failures:
                        failures.append(failure)
                        progress.issue(f"Failed: {failure['path']}: {failure['error']}")
                    if artist_id:
                        seen_artists.append(artist_path)
                        seen_albums.extend(album_paths)
                        progress.log(
                            f"{name}: {len(album_paths)} albums, {stats['unchanged']} unchanged, {stats['changed']} changed/new"
                        )
                progress.update(index, len(artist_dirs), f"Scanning {name}", "delta")
        if mode == "incremental":
            progress.log(
                f"Incremental: {len(lookup_ids)} albums to check. {skipped_albums} albums were left unchanged.",
                message=_with_skip(f"{len(lookup_ids)} to check", skipped_albums),
            )
        try:
            _checkpoint()
        except Exception as exc:
            from resonance.jobs import ScanCancelled

            if isinstance(exc, ScanCancelled):
                progress.log(
                    "Scan cancelled. Indexed music stays. Missing folders were not removed.",
                    message="Scan cancelled",
                )
                return "Scan cancelled"
            raise
        progress.log(
            "Removing folders that are no longer in the library.",
            message="Removing missing folders",
        )
        failed_paths = [f["path"] for f in failures if f.get("path")]
        # A root that read as online but yielded nothing is almost always a mount that came
        # back empty, so pruning it would wipe every album under it. Keep it out of the
        # per-root prune and leave its rows alone; removing the path in Settings is what
        # removes its items.
        # Measure every root first, so the mount each one sits on can be judged as a whole.
        from resonance.paths import mount_for
        from resonance.settings import prune_safety_on

        safety = prune_safety_on()
        measured = []
        for root in readable:
            prefix = root.rstrip("/") + "/"
            seen_here = sum(1 for path in seen_albums if str(path or "").startswith(prefix) or path == root)
            measured.append((root, seen_here, _known_album_count(root)))

        # A mount can hold several library paths, of more than one media type, so a mount that
        # came back half-populated has to be judged across all of its paths at once: each path
        # on its own could stay under the per-root limit while the mount loses a great deal.
        mounts = {}
        for root, seen_here, known_here in measured:
            agg = mounts.setdefault(mount_for(root), {"known": 0, "remove": 0, "roots": []})
            agg["known"] += known_here
            agg["remove"] += max(0, known_here - seen_here)
            agg["roots"].append(root)
        blocked = set()
        for mount, agg in mounts.items():
            if safety and mount and agg["known"] > 10 and agg["remove"] > agg["known"] * 0.20:
                blocked.add(mount)
                progress.issue(
                    f"Prune safety: the mount {mount} would lose {agg['remove']}/{agg['known']} "
                    f"albums ({100 * agg['remove'] // agg['known']}%) across "
                    f"{len(agg['roots'])} library path(s), so none of them were pruned. Run a "
                    f"full scan if this is expected."
                )

        fruitful = []
        for root, seen_here, known_here in measured:
            if mount_for(root) in blocked:
                continue
            if not seen_here:
                progress.issue(
                    f"Empty: {root} is readable but no album was found in it, so nothing "
                    f"indexed under it was removed. Take the path out in Settings and scan "
                    f"again if its items should go."
                )
                continue
            # Per-path limit, for a single library path losing a lot on its own.
            to_remove = max(0, known_here - seen_here)
            if safety and known_here > 10 and to_remove > known_here * 0.20:
                progress.issue(
                    f"Prune safety: would remove {to_remove}/{known_here} albums from {root} "
                    f"({100 * to_remove // known_here}%) - skipping. Run a full scan if this "
                    f"is expected."
                )
                continue
            fruitful.append(root)
        # An offline root counts as part of the library for the outside-library removal, so
        # its rows survive. `fruitful` drives the per-root prune, so nothing is pruned
        # against a walk that never happened or came back empty.
        skipped_roots = [root for root in readable if root not in fruitful]
        # The keep-list for the outside-library removal. `configured` has the excluded folders
        # stripped out, so they have to go back in here: Exclude means "skip it on scans",
        # not "remove what is indexed in it". Same for offline and came-back-empty roots.
        keep_roots = (
            configured
            + protected_prefixes(sorted(skip))
            + protected_prefixes(offline_roots)
            + protected_prefixes(skipped_roots)
        )
        # Paths the user explicitly removed in Settings. Only what sits under one of these
        # is deleted, and never a row that still belongs to a configured path, so a removed
        # path cannot take its neighbours on the same mount with it.
        from resonance.settings import take_path_removals

        removed_paths = take_path_removals("music")
        _prune(
            seen_artists,
            seen_albums,
            fruitful,
            keep_roots,
            failed_paths=failed_paths,
            removed_paths=removed_paths,
            held_roots=skipped_roots,
        )
        for gone in removed_paths:
            progress.log(
                f"Removed items from the database, indexed under {gone}, which is no longer "
                f"a library path. No files were touched."
            )
        gone_rows, gone_samples = _purge_unmounted(
            protected_prefixes(keep_roots), seen_albums, seen_artists,
            [root for root in readable if path_kind(root) != "artist"],
        )
        if gone_rows:
            progress.log(
                f"Removed {gone_rows} items from the database that sat outside every music library "
                f"path. No files were touched. For example: {'; '.join(gone_samples)}"
            )
        try:
            totals = db.fetchone("SELECT (SELECT count(*) FROM artists) AS artists, (SELECT count(*) FROM albums) AS albums")
            parts = [f"{root}: {_known_album_count(root)} albums" for root in readable]
            progress.log(
                f"Library now holds {totals['albums']} albums by {totals['artists']} artists ("
                + ", ".join(parts) + ")."
            )
        except Exception:
            logger.exception("library totals after the prune could not be read")
        if failed_paths:
            progress.log(f"Preserved {len(failed_paths)} folders with scan errors from deletion.")
        progress.log(f"Removed folders that are no longer under {', '.join(readable)}")
        looked_up = lookup_ids
        looked_up_labels = []
        retried_shared_release = False
        while True:
            try:
                if mode == "deep":
                    looked_up_labels = _rematch(progress, roots, mode="deep", force=force)
                elif mode == "full":
                    from resonance.library import store_missing_release_fields

                    store_missing_release_fields()
                    looked_up = _merge_ids(lookup_ids, _missing_album_ids(roots))
                    looked_up_labels = _rematch(progress, roots, looked_up, mode="full", force=force)
                else:
                    looked_up_labels = _rematch(progress, roots, lookup_ids, mode="incremental", force=force)
                break
            except Exception as exc:
                from resonance.jobs import ScanCancelled

                if isinstance(exc, ScanCancelled):
                    progress.log(
                        "Scan cancelled during MusicBrainz lookup. The file index was kept.",
                        message="Scan cancelled",
                    )
                    return "Scan cancelled"
                if _shared_release_conflict(exc) and not retried_shared_release:
                    from resonance.db import allow_shared_release_ids

                    dropped = allow_shared_release_ids()
                    retried_shared_release = True
                    logger.warning(
                        "scan: shared MusicBrainz release kept on both albums (%s); dropped %s",
                        exc,
                        ", ".join(dropped) or "nothing",
                    )
                    progress.log(
                        "Two albums share a MusicBrainz release. Both copies are kept so they can be marked as duplicates."
                    )
                    continue
                if _shared_release_conflict(exc):
                    logger.exception("scan continued after a shared MusicBrainz release id")
                    progress.issue(
                        "A MusicBrainz release id is already stored on another album. Both copies are kept. "
                        + str(exc)
                    )
                    break
                raise
        _sidecar_summary(progress, roots)
        _fill_stored_mb_metadata(progress, roots, mode, lookup_ids if mode == "incremental" else None)
        if mode == "incremental":
            _refresh_discographies(progress, roots, lookup_ids)
        else:
            _refresh_discographies(progress, roots)
        fill_missing = load_settings().get("fill_missing_during_scan", True) is not False
        if fill_missing:
            changed_ids = lookup_ids if mode == "incremental" else None
            left_alone = skipped_albums if mode == "incremental" else None
            _fill_missing_metadata(progress, roots, changed_ids, left_alone)
            _fill_missing_artwork(progress, roots, changed_ids, left_alone)
        from resonance.library import store_missing_countries
        from resonance.upgrade import refresh_stored

        progress.log("Filling blank release countries from tags already stored", message="Recording release countries")
        store_missing_countries()
        progress.log("Recording duplicates, upgrade copies, and original years", message="Recording catalogue notes")
        refresh_stored()
        _nfos_from_scan(progress, roots, mode, looked_up if mode != "deep" else None)
        message = f"Indexed {len(seen_albums)} albums"
        if mode in {"incremental", "full"}:
            message += (
                f", {unchanged_files} unchanged, {changed_files} changed/new, "
                f"{len(looked_up_labels)} albums looked up"
            )
        if mode == "incremental":
            message += f", {skipped_albums} albums left unchanged"
        if errors:
            message += f", {errors} errors"
        if empty_folders:
            message += f", {len(empty_folders)} empty folders"
        if loose:
            message += f", skipped {loose} loose files"
        if not artist_dirs:
            message = "No artist folders found"
        progress.log(message, phase="artwork" if fill_missing else "sidecars", message=message)
        try:
            from resonance import webhooks

            webhooks.fire("scan")
            progress.log("Music library update queued.", message="Music library update queued")
        except Exception:
            logger.info("music library update after scan failed", exc_info=True)
            progress.log("Music library update was not queued.")
        return message
    finally:
        _save_scan_issues(
            progress,
            {
                "albums": len(seen_albums),
                "artists": len(seen_artists),
                "changed": changed_files,
                "unchanged": unchanged_files,
                "errors": errors,
                "empty_folders": empty_folders,
                "failures": failures,
                "lookups": looked_up_labels,
                "loose": loose,
                "albums_scanned": progress.album_count,
            },
        )


class _Progress:
    def __init__(self, job_id, verbose=False):
        self.job_id = job_id
        self.verbose = bool(verbose)
        self.lines = []
        self.issues = []
        self.parked = []
        self.album_count = 0
        self.library_counts = {}
        self._flushed = 0.0
        self.paced = False

    def stored_log(self):
        # Keep the live box on recent lines. Replaying the oldest empty folders
        # pinned the bottom of the log and made every status read carry that text.
        head = self.lines[-200:]
        shown = set(head)
        omitted = sum(1 for line in self.issues if line not in shown)
        if omitted:
            head = list(head) + [
                (
                    f"{omitted} earlier failures and empty folders are hidden so this log can keep moving. "
                    "The full list is written to a timestamped log in config/logs when the scan finishes."
                )
            ]
        return "\n".join(head)

    def update(self, processed, total, message, phase):
        if self.paced:
            from resonance import scan_pace

            scan_pace.note(phase, processed, total)
        db.execute(
            """
            UPDATE scan_jobs
            SET processed = %s, total = %s, message = %s, phase = %s, log = %s
            WHERE id = %s
            """,
            (processed, total, message, phase, self.stored_log(), self.job_id),
        )
        self._flushed = time.monotonic()

    def log(self, line, phase=None, message=None):
        if self.verbose:
            logger.info("scan: %s", line)
        self.lines.append(line)
        if self.paced and phase:
            from resonance import scan_pace

            scan_pace.note(phase)
        if phase or message:
            db.execute(
                """
                UPDATE scan_jobs
                SET phase = COALESCE(%s, phase), message = COALESCE(%s, message), log = %s
                WHERE id = %s
                """,
                (phase, message, self.stored_log(), self.job_id),
            )
        else:
            db.execute(
                "UPDATE scan_jobs SET log = %s WHERE id = %s",
                (self.stored_log(), self.job_id),
            )
        self._flushed = time.monotonic()

    def detail(self, line):
        if self.verbose:
            logger.info("scan: %s", line)
        self.lines.append(line)
        self._touch()

    def issue(self, line):
        logger.warning("scan: %s", line)
        self.issues.append(line)
        self.lines.append(line)
        self._touch()

    def _touch(self):
        now = time.monotonic()
        if now - self._flushed < 1:
            return
        db.execute(
            "UPDATE scan_jobs SET log = %s WHERE id = %s",
            (self.stored_log(), self.job_id),
        )
        self._flushed = now

    def note_album(self):
        self.album_count += 1
        if self.album_count % 50:
            return
        self._publish_result({"albums_scanned": self.album_count})

    def note_library(self, kind):
        """Ask the open library tree to reload after every 50 metadata or artwork lookups."""
        count = self.library_counts.get(kind, 0) + 1
        self.library_counts[kind] = count
        if count % 50:
            return
        key = "metadata_lookups" if kind == "metadata" else "artwork_lookups"
        self._publish_result({key: count})

    def _publish_result(self, patch):
        try:
            db.execute(
                """
                UPDATE scan_jobs
                SET result = COALESCE(result, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (Json(patch), self.job_id),
            )
        except Exception:
            logger.exception("could not publish scan progress")


def _same_path(left, right):
    if not left or not right:
        return False
    left_real = os.path.realpath(left) if os.path.exists(left) else os.path.normpath(left)
    right_real = os.path.realpath(right) if os.path.exists(right) else os.path.normpath(right)
    return os.path.normcase(left_real) == os.path.normcase(right_real)


def _release_root(path):
    from resonance.paths import inside

    matches = []
    for root in music_roots():
        if root and (inside(root, path) or _same_path(root, path)):
            matches.append(root)
    if not matches:
        return None
    return max(matches, key=lambda item: len(os.path.normpath(item)))


def scan_release(job_id, album_path, artist_path=None):
    """Incrementally index one imported album. Other artists and albums stay untouched."""
    from resonance.db import allow_shared_release_ids
    from resonance.paths import inside
    from resonance.settings import verbose_enabled

    allow_shared_release_ids()
    if not album_path or not os.path.isdir(album_path):
        raise AppError(f"Album folder is not available: {album_path}", 404)
    album_path = os.path.realpath(album_path)
    root = _release_root(album_path)
    if not root:
        raise AppError(f"Album folder is outside the music library: {album_path}", 400)
    if not (
        artist_path
        and os.path.isdir(artist_path)
        and (inside(artist_path, album_path) or _same_path(artist_path, album_path))
        and (inside(root, artist_path) or _same_path(root, artist_path))
    ):
        parent = os.path.dirname(album_path.rstrip(os.sep))
        if parent and inside(root, parent) and not _same_path(parent, root):
            artist_path = parent
        elif path_kind(root) == "artist":
            artist_path = os.path.realpath(root)
        else:
            artist_path = album_path
    else:
        artist_path = os.path.realpath(artist_path)
    settings = load_settings()
    progress = _Progress(job_id, verbose=verbose_enabled())
    artist_name = os.path.basename(str(artist_path).rstrip(os.sep))
    album_name = os.path.basename(album_path.rstrip(os.sep))
    label = album_name if _same_path(artist_path, album_path) else f"{artist_name} — {album_name}"
    logger.info("lidarr scan starting: %s", label)
    progress.log(f"Lidarr import: {label}", phase="directory", message=f"Lidarr: {label}")
    errors = 0
    failures = []
    changed = 0
    unchanged = 0
    lookup_ids = []
    looked_up_labels = []
    artist_id = None
    try:
        artist_id, _album_paths, errors, stats, failures = _scan_artist(
            artist_path, settings, "incremental", progress, only_album=album_path
        )
        for failure in failures:
            progress.issue(f"Failed: {failure['path']}: {failure['error']}")
        changed = stats["changed"]
        unchanged = stats["unchanged"]
        lookup_ids = stats.get("lookup_ids") or []
        if not artist_id:
            message = f"Lidarr found no album at {album_name}"
            progress.log(message, message=message)
            return message
        looked_up_labels = _rematch(progress, [root], lookup_ids, mode="incremental")
        _fill_stored_mb_metadata(progress, [root], "incremental", lookup_ids)
        fill_missing = settings.get("fill_missing_during_scan", True) is not False
        if fill_missing:
            skipped = int(stats.get("skipped_albums") or 0)
            _fill_missing_metadata(progress, [root], lookup_ids, skipped)
            _fill_missing_artwork(progress, [root], lookup_ids, skipped)
        from resonance.library import store_missing_countries
        from resonance.upgrade import refresh_stored

        progress.log("Filling blank release countries from tags already stored", message="Recording release countries")
        store_missing_countries()
        progress.log("Recording duplicates, upgrade copies, and original years", message="Recording catalogue notes")
        refresh_stored()
        _nfos_from_scan(progress, [root], "incremental", lookup_ids)
        fingerprinted = 0
        lyrics_written = 0
        try:
            fingerprinted = _fingerprint_release(progress, artist_id, album_path)
        except Exception as exc:
            progress.log(f"Fingerprint failed: {exc}", message="Fingerprint failed")
        try:
            lyrics_written = _lyrics_release(progress, artist_id, album_path)
        except Exception as exc:
            progress.log(f"Lyrics lookup failed: {exc}", message="Lyrics lookup failed")
        message = f"Lidarr indexed {label}, {unchanged} unchanged, {changed} changed/new"
        if looked_up_labels:
            message += f", {len(looked_up_labels)} looked up"
        message += f", fingerprinted {fingerprinted} tracks, lyrics written for {lyrics_written} tracks"
        if errors:
            message += f", {errors} errors"
        progress.log(message, phase="artwork" if fill_missing else "sidecars", message=message)
        return message
    finally:
        _save_scan_issues(
            progress,
            {
                "albums": 1 if artist_id else 0,
                "artists": 1 if artist_id else 0,
                "changed": changed,
                "unchanged": unchanged,
                "errors": errors,
                "empty_folders": [],
                "failures": failures,
                "lookups": looked_up_labels,
                "loose": 0,
                "albums_scanned": progress.album_count,
            },
        )


def _release_album(artist_id, album_path):
    from resonance.library import same_directory

    rows = db.fetchall(
        """
        SELECT id, title, path, match_tier, musicbrainz_release_id
        FROM albums
        WHERE artist_id = %s
        """,
        (artist_id,),
    )
    for row in rows:
        if same_directory(row.get("path"), album_path):
            return row
    return None


def _fingerprint_release(progress, artist_id, album_path):
    """Store AcoustID fingerprints for one imported album when it is still unmatched."""
    from resonance.settings import load as load_settings
    from resonance.sources import fingerprint

    if not str(load_settings().get("acoustid_key") or "").strip():
        progress.log("Fingerprint skipped. No AcoustID key is set.", message="Fingerprint skipped")
        return 0
    album = _release_album(artist_id, album_path)
    if not album:
        return 0
    if album.get("match_tier") != "unmatched" and album.get("musicbrainz_release_id"):
        progress.log("Fingerprint skipped. The album is already matched.", message="Fingerprint skipped")
        return 0
    tracks = db.fetchall("SELECT file_path FROM tracks WHERE album_id = %s", (album["id"],))
    paths = [track["file_path"] for track in tracks if track.get("file_path")]
    if not paths:
        return 0
    title = album.get("title") or "album"
    progress.log(f"Fingerprinting {title}", message=f"Fingerprinting {title}")
    result = fingerprint.fingerprint_tracks(paths, limit=None)
    checked = 0
    for item in result.get("files") or []:
        db.execute(
            """
            UPDATE tracks
            SET fingerprint_hash = COALESCE(%s, fingerprint_hash),
                acoustid_recording_id = COALESCE(%s, acoustid_recording_id),
                acoustid_score = COALESCE(%s, acoustid_score)
            WHERE file_path = %s
            """,
            (item.get("fingerprint_hash"), item.get("recording_id"), item.get("score"), item.get("path")),
        )
        checked += 1
    progress.log(f"Fingerprinted {checked} tracks", message=f"Fingerprinted {checked} tracks")
    return checked


def _lyrics_release(progress, artist_id, album_path):
    """Fetch lyrics for tracks on the imported album that do not have them yet."""
    from resonance import lyrics

    album = _release_album(artist_id, album_path)
    if not album:
        return 0
    title = album.get("title") or "album"
    progress.log(f"Fetching missing lyrics for {title}", message=f"Fetching lyrics for {title}")
    result = lyrics.fetch_album(album["id"], only_missing=True)
    written = int(result.get("written") or 0)
    progress.log(f"Lyrics written for {written} tracks", message=f"Lyrics written for {written} tracks")
    return written


class _ScanIndex:
    def __init__(self):
        self.artists = {}
        self.albums = set()
        self.files = {}


def _load_scan_index():
    """Album file modification times already stored, used to skip unchanged albums."""
    index = _ScanIndex()
    for row in db.fetchall("SELECT id, path, folder_aliases FROM artists"):
        index.artists[row["path"]] = row["id"]
        for alias in row.get("folder_aliases") or []:
            if alias:
                index.artists[alias] = row["id"]
    for row in db.fetchall("SELECT path FROM albums"):
        index.albums.add(row["path"])
        index.files.setdefault(row["path"], {})
    for row in db.fetchall(
        """
        SELECT t.file_path, t.mtime_ns, t.file_size, a.path AS album_path
        FROM tracks t
        JOIN albums a ON a.id = t.album_id
        """
    ):
        bucket = index.files.setdefault(row["album_path"], {})
        bucket[row["file_path"]] = (int(row["mtime_ns"] or 0), int(row["file_size"] or 0))
    return index


def _album_unchanged(album_path, index):
    if album_path not in index.albums:
        return False
    current = _audio_stamp_map(album_path)
    known = index.files.get(album_path) or {}
    if set(current) != set(known):
        return False
    return all(known.get(path) == stamp for path, stamp in current.items())


def _audio_stamp_map(album_path):
    found = {}
    _fill_stamps(album_path, found, AUDIO_NEST_DEPTH)
    return found


def _fill_stamps(directory, found, depth):
    for path in _audio_files(directory):
        found[path] = _mtime_size(path)
    if depth <= 0:
        return
    try:
        children = os.listdir(directory)
    except OSError:
        return
    for name in children:
        if name.startswith(".") or name.lower() in SIDECAR_DIRS:
            continue
        path = os.path.join(directory, name)
        if os.path.isdir(path) and (_audio_files(path) or _contains_audio(path, depth - 1)):
            _fill_stamps(path, found, depth - 1)


def _mtime_size(path):
    stat = os.stat(path)
    modified = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    return int(modified), int(stat.st_size)


def _same_mtime(row, stamp):
    return (int(row.get("mtime_ns") or 0), int(row.get("file_size") or 0)) == (int(stamp[0]), int(stamp[1]))


def _scan_artist(artist_path, settings, mode, progress=None, only_album=None, file_index=None):
    albums = _album_directories(artist_path)
    loose_audio = _audio_files(artist_path)
    if loose_audio and not albums:
        albums = [artist_path]
    if only_album:
        wanted = os.path.realpath(only_album) if os.path.exists(only_album) else os.path.normpath(only_album)
        picked = [path for path in albums if _same_path(path, wanted)]
        if not picked and os.path.isdir(wanted):
            picked = [wanted]
        albums = picked
    skipped = []
    if mode == "incremental" and file_index is not None and not only_album:
        pending = []
        for album_path in albums:
            if _album_unchanged(album_path, file_index):
                skipped.append(album_path)
            else:
                pending.append(album_path)
        albums = pending
        if not albums and skipped:
            unchanged = sum(len(file_index.files.get(path) or {}) for path in skipped)
            artist_id = file_index.artists.get(artist_path) or True
            if file_index.artists.get(artist_path):
                _refresh_artist_name(artist_path)
            return artist_id, list(skipped), 0, {
                "changed": 0,
                "unchanged": unchanged,
                "lookup_ids": [],
                "skipped_albums": len(skipped),
            }, []
    flags = _artist_sidecars(artist_path, settings)
    stats = {"changed": 0, "unchanged": 0, "lookup_ids": [], "skipped_albums": len(skipped)}
    if not albums and not flags["has_nfo"] and not flags["has_artwork"]:
        return None, [], 0, stats, []
    with db.transaction() as conn:
        artist_id = _upsert_artist(conn, artist_path, flags, [])
    album_paths = []
    genres = []
    errors = 0
    failures = []
    for album_path in albums:
        _checkpoint()
        try:
            found, album_stats = _scan_album(
                artist_id,
                artist_path,
                album_path,
                settings,
                mode,
                reread=mode == "incremental",
            )
            genres.extend(found)
            album_paths.append(album_path)
            stats["changed"] += album_stats["changed"]
            stats["unchanged"] += album_stats["unchanged"]
            if album_stats.get("lookup") and album_stats.get("album_id"):
                stats["lookup_ids"].append(album_stats["album_id"])
            if album_stats.get("reclaimed_from") and progress is not None:
                progress.log(
                    "Replaced folder: kept "
                    f"{os.path.basename(album_path.rstrip(os.sep))} from {album_stats['reclaimed_from']}"
                )
            if progress is not None:
                progress.note_album()
                if progress.verbose:
                    progress.detail(
                        f"{os.path.basename(artist_path.rstrip(os.sep))} / {os.path.basename(album_path.rstrip(os.sep))}: "
                        f"{album_stats['unchanged']} unchanged, {album_stats['changed']} changed/new"
                    )
        except Exception as exc:
            from resonance.jobs import ScanCancelled

            if isinstance(exc, ScanCancelled):
                raise
            errors += 1
            logger.exception("album scan failed: %s", album_path)
            failures.append({"path": album_path, "error": str(exc)})
    stats["unchanged"] += sum(len(file_index.files.get(path) or {}) for path in skipped) if file_index else 0
    album_paths = skipped + album_paths
    if genres and not only_album and not skipped:
        db.execute(
            """
            UPDATE artists
            SET genres = %s::text[], genres_from_tags = TRUE, updated_at = NOW()
            WHERE id = %s
              AND COALESCE(genres_custom, FALSE) = FALSE
              AND COALESCE(genres_from_tags, TRUE) = TRUE
            """,
            (db.text_array(sorted(set(genres))), artist_id),
        )
    _remember_artist_website(artist_id, artist_path, skipped + albums)
    _record_local_artwork(None, artist_id, artist_path, artist=True)
    _restore_selected_artist_art(artist_id)
    # SPEED 8: only refresh artist name when something actually changed
    if stats["changed"] > 0 or not skipped:
        _refresh_artist_name(artist_path)
    return artist_id, album_paths, errors, stats, failures


def _scan_album(artist_id, artist_path, album_path, settings, mode, reread=False):
    folder_name = os.path.basename(album_path.rstrip(os.sep))
    if os.path.realpath(album_path) == os.path.realpath(artist_path):
        folder_name = os.path.basename(artist_path.rstrip(os.sep)) if _grouped_discs(album_path) else "Loose tracks"
    collected = _collect_tracks(album_path, "deep" if reread else mode)
    changed = sum(1 for item in collected if not item.get("unchanged"))
    unchanged = len(collected) - changed
    _assign_numbers(collected)
    tag_albums = []
    tag_years = []
    tag_groups = []
    genres = []
    for item in collected:
        if item["album_name"]:
            item["album_name"] = album_title_without_disc(item["album_name"])
            tag_albums.append(item["album_name"])
        if item["year"]:
            tag_years.append(item["year"])
        if item["musicbrainz_release_group_id"]:
            tag_groups.append(item["musicbrainz_release_group_id"])
        if item["genre"]:
            genres.extend(_split_genres(item["genre"]))
    title = _majority(tag_albums) or _clean_folder(folder_name) or folder_name
    year = _majority(tag_years) or year_from(folder_name)
    guessed_type = _guess_type(folder_name)
    guessed_edition = _guess_edition(folder_name)
    flags = _album_sidecars(album_path, settings)
    with db.transaction() as conn:
        existing = conn.execute("SELECT * FROM albums WHERE path = %s", (album_path,)).fetchone()
        reclaimed_from = None
        if not existing:
            reclaimed_from, existing = _reclaim_replaced_album(
                conn, album_path, artist_id, collected, title, year
            )
            if reclaimed_from and existing:
                _carry_replaced_artist(conn, artist_id, existing["artist_id"])
        edition = guessed_edition
        album_type = guessed_type
        from resonance.library import release_artist_mbid

        tagged_mbid = release_artist_mbid(collected)
        if tagged_mbid:
            owner = conn.execute(
                "SELECT id, path FROM artists WHERE musicbrainz_artist_id = %s",
                (tagged_mbid,),
            ).fetchone()
            # The same band in the folder of another library path stays its own artist: each
            # mount lists its own copy, and Duplicate marks them. Only an album filed under
            # a differently named folder follows the tag.
            same_band_elsewhere = bool(
                owner
                and owner.get("path")
                and os.path.basename(str(owner["path"]).rstrip("/\\")).casefold()
                == os.path.basename(str(artist_path).rstrip("/\\")).casefold()
            )
            if owner and not same_band_elsewhere:
                artist_id = owner["id"]
        review = None
        release_id = None
        release_group = _majority(tag_groups)
        if existing:
            if existing["status"] != "NEW":
                if existing["edition"]:
                    edition = existing["edition"]
                if existing["type"] and existing["type"] != "unknown":
                    album_type = existing["type"]
            review = existing["review"]
            release_id = existing["musicbrainz_release_id"]
            if not release_group:
                release_group = existing["musicbrainz_release_group_id"]
            if existing["release_year"] and not year:
                year = existing["release_year"]
        tagged_release = _tagged_release_id(collected)
        if not release_id and tagged_release:
            release_id = tagged_release
        album_id = _upsert_album(
            conn,
            existing,
            artist_id,
            album_path,
            title,
            year,
            album_type,
            edition,
            flags,
            release_group,
            release_id,
            review,
        )
        seen = [item["file_path"] for item in collected]
        if seen:
            conn.execute(
                "DELETE FROM tracks WHERE album_id = %s AND NOT (file_path = ANY(%s::text[]))",
                (album_id, db.text_array(seen)),
            )
        else:
            conn.execute("DELETE FROM tracks WHERE album_id = %s", (album_id,))
        for item in collected:
            _upsert_track(conn, album_id, item, release_group)
        stats = conn.execute(
            """
            SELECT COUNT(*)::int AS total_tracks,
                   COALESCE(MAX(disc_number), 1)::int AS total_discs,
                   COALESCE(SUM(duration_seconds), 0)::int AS duration_seconds
            FROM tracks WHERE album_id = %s
            """,
            (album_id,),
        ).fetchone()
        from resonance.paths import path_role
        from resonance.quality import album_score

        conn.execute(
            """
            UPDATE albums
            SET total_tracks = %s, total_discs = %s, duration_seconds = %s,
                path_role = %s, quality_rank = %s, cue_image = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                stats["total_tracks"],
                stats["total_discs"],
                stats["duration_seconds"],
                path_role(album_path),
                album_score(collected),
                _is_cue_image(album_path),
                album_id,
            ),
        )
    _record_local_artwork(album_id, None, album_path, artist=False)
    _restore_selected_cover(album_id)
    completeness.recompute_album(album_id)
    from resonance.library import refresh_match_tier

    refresh_match_tier(album_id)
    held = existing and (existing.get("status") == "IGNORED" or existing.get("locked"))
    if not held and artist_id:
        owner = db.fetchone("SELECT status, locked FROM artists WHERE id = %s", (artist_id,))
        held = bool(owner and (owner.get("status") == "IGNORED" or owner.get("locked")))
    return genres, {
        "changed": changed,
        "unchanged": unchanged,
        "lookup": _album_needs_lookup(existing, changed) and not held,
        "album_id": str(album_id),
        "reclaimed_from": reclaimed_from,
    }


def _album_needs_lookup(existing, changed):
    return existing is None or changed > 0


def _tagged_release_id(items):
    """MusicBrainz release id agreed by the files in this folder."""
    from resonance.fields import opt_uuid_loose

    votes = []
    for item in items or []:
        raw = item.get("raw") or {}
        found = opt_uuid_loose(raw.get("musicbrainz_albumid"))
        if found:
            votes.append(found)
    return _majority(votes)


def _reclaim_replaced_album(conn, album_path, artist_id, collected, title, year):
    """Point one vanished album row at this folder.

    A MusicBrainz release id wins when the files have one. Otherwise the title,
    year, and track count are used, including when the files have no tags.
    A second copy whose folder is still on disk is left alone. Two vanished
    rows that fit equally well are left alone.
    """
    release_id = _tagged_release_id(collected)
    if release_id:
        rows = conn.execute(
            """
            SELECT * FROM albums
            WHERE musicbrainz_release_id = %s AND path <> %s
            """,
            (release_id, album_path),
        ).fetchall()
        gone = [row for row in rows if _folder_replaced(row["path"])]
        if len(gone) == 1:
            return _retarget_album(conn, album_path, gone[0])
        return None, None
    wanted = _album_identity(title)
    if len(wanted) < 2:
        return None, None
    rows = conn.execute(
        """
        SELECT * FROM albums
        WHERE artist_id = %s AND path <> %s
        """,
        (artist_id, album_path),
    ).fetchall()
    chosen = _choose_replaced(rows, wanted, year, collected)
    if chosen:
        return _retarget_album(conn, album_path, chosen)
    artist = conn.execute("SELECT name FROM artists WHERE id = %s", (artist_id,)).fetchone()
    name = (artist or {}).get("name") or ""
    if not name:
        return None, None
    rows = conn.execute(
        """
        SELECT albums.*, artists.path AS artist_path
        FROM albums
        JOIN artists ON artists.id = albums.artist_id
        WHERE albums.artist_id <> %s
          AND lower(artists.name) = lower(%s)
          AND albums.path <> %s
        """,
        (artist_id, name, album_path),
    ).fetchall()
    rows = [row for row in rows if _folder_replaced(row.get("artist_path"))]
    chosen = _choose_replaced(rows, wanted, year, collected)
    if not chosen:
        return None, None
    return _retarget_album(conn, album_path, chosen)


def _retarget_album(conn, album_path, old):
    conn.execute("UPDATE albums SET path = %s, updated_at = NOW() WHERE id = %s", (album_path, old["id"]))
    row = conn.execute("SELECT * FROM albums WHERE id = %s", (old["id"],)).fetchone()
    return old["path"], row


def _album_identity(text):
    """Folder and tag titles compared without a leading year or a trailing (year)."""
    value = str(text or "")
    value = re.sub(r"^\d{4}\s*[-–—]\s*", "", value)
    value = re.sub(r"\s*\(\d{4}\)\s*$", "", value)
    value = re.sub(r"\s+", " ", value).strip().casefold()
    return value


def _choose_replaced(rows, wanted, year, collected):
    """The one vanished row that matches this folder. None when the choice is ambiguous."""
    track_count = len(collected or [])
    barcode = _tagged_text(collected, "barcode")
    catalog = _tagged_text(collected, "catalognumber")
    wanted_year = _year_number(year)
    matched = []
    for row in rows or []:
        if not _folder_replaced(row.get("path")):
            continue
        if _album_identity(row.get("title")) != wanted:
            continue
        stored_year = _year_number(row.get("release_year"))
        if wanted_year and stored_year and wanted_year != stored_year:
            continue
        stored_tracks = int(row.get("total_tracks") or 0)
        if track_count and stored_tracks and track_count != stored_tracks:
            continue
        stored_barcode = str(row.get("barcode") or "").strip()
        if barcode and stored_barcode and barcode != stored_barcode:
            continue
        stored_catalog = str(row.get("catalog") or "").strip()
        if catalog and stored_catalog and catalog.casefold() != stored_catalog.casefold():
            continue
        matched.append(row)
    if len(matched) != 1:
        return None
    return matched[0]


def _tagged_text(items, key):
    votes = []
    for item in items or []:
        raw = item.get("raw") or {}
        text = str(raw.get(key) or "").strip()
        if text:
            votes.append(text)
    return _majority(votes)


def _year_number(value):
    try:
        number = int(str(value).strip()[:4])
    except (TypeError, ValueError):
        return None
    if number < 1000:
        return None
    return number


def _carry_replaced_artist(conn, new_artist_id, old_artist_id):
    """Copy a vanished artist's blank text onto the artist that now holds the album."""
    if not new_artist_id or not old_artist_id or str(new_artist_id) == str(old_artist_id):
        return
    old = conn.execute("SELECT * FROM artists WHERE id = %s", (old_artist_id,)).fetchone()
    new = conn.execute("SELECT * FROM artists WHERE id = %s", (new_artist_id,)).fetchone()
    if not old or not new or not _folder_replaced(old["path"]):
        return
    sets = []
    params = []
    for key in (
        "biography",
        "style",
        "mood",
        "website",
        "discogs_url",
        "wikipedia_url",
        "formed",
        "origin",
        "years_active",
        "instruments",
        "disambiguation",
    ):
        if str(new.get(key) or "").strip() or not str(old.get(key) or "").strip():
            continue
        sets.append(f"{key} = %s")
        params.append(old[key])
    if not new.get("name_custom") and old.get("name") and old["name"] != new.get("name"):
        sets.append("name = %s")
        params.append(old["name"])
        if old.get("name_custom"):
            sets.append("name_custom = TRUE")
    if not sets:
        return
    params.append(new_artist_id)
    conn.execute(
        f"UPDATE artists SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
        tuple(params),
    )


def _folder_replaced(path):
    """True when this album folder is gone and its library root is still mounted."""
    from resonance.paths import inside, music_roots

    if not path or os.path.isdir(path):
        return False
    homes = [root for root in music_roots() if inside(root, path)]
    if not homes:
        return True
    home = max(homes, key=len)
    return os.path.isdir(home)


def _refresh_artist_name(artist_path):
    """Use the album-artist tag when the user has not saved a name of their own."""
    db.execute(
        """
        UPDATE artists AS ar
        SET name = LEFT(picked.name, 255), updated_at = NOW()
        FROM (
            SELECT name
            FROM (
                SELECT albumartist AS name,
                       ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, albumartist) AS rank
                FROM (
                    SELECT MODE() WITHIN GROUP (ORDER BY BTRIM(tracks.tags->>'albumartist')) AS albumartist
                    FROM tracks
                    JOIN albums ON albums.id = tracks.album_id
                    JOIN artists ON artists.id = albums.artist_id
                    WHERE artists.path = %s
                      AND NULLIF(BTRIM(tracks.tags->>'albumartist'), '') IS NOT NULL
                    GROUP BY albums.id
                ) per_album
                WHERE albumartist IS NOT NULL
                GROUP BY albumartist
            ) ranked
            WHERE rank = 1
        ) picked
        WHERE ar.path = %s
          AND COALESCE(ar.name_custom, FALSE) = FALSE
          AND ar.name IS DISTINCT FROM LEFT(picked.name, 255)
        """,
        (artist_path, artist_path),
    )


def _upsert_artist(conn, path, flags, genres):
    name = clean_text(os.path.basename(path), 255) or "Unknown Artist"
    mbid = _artist_mbid_from_nfo(path) or _mbid_near(path)
    existing = conn.execute("SELECT * FROM artists WHERE path = %s", (path,)).fetchone()
    if not existing:
        linked = conn.execute(
            "SELECT id FROM artists WHERE %s = ANY(folder_aliases) LIMIT 1",
            (path,),
        ).fetchone()
        if linked:
            return linked["id"]
    if not opt_uuid_loose(mbid) or (
        mbid and db.artist_mbid_blocked(mbid, name, existing["id"] if existing else None, conn)
    ):
        mbid = existing["musicbrainz_artist_id"] if existing else None
    if existing:
        conn.execute(
            """
            UPDATE artists SET
                has_nfo = %s,
                has_artwork = %s,
                artwork_width = %s,
                artwork_height = %s,
                musicbrainz_artist_id = COALESCE(%s, musicbrainz_artist_id),
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                flags["has_nfo"],
                flags["has_artwork"],
                flags["width"],
                flags["height"],
                mbid,
                existing["id"],
            ),
        )
        return existing["id"]
    row = conn.execute(
        """
        INSERT INTO artists (
            name, path, status, has_nfo, has_artwork, artwork_width, artwork_height,
            musicbrainz_artist_id, genres
        )
        VALUES (%s, %s, 'NEW', %s, %s, %s, %s, %s, %s::text[])
        RETURNING id
        """,
        (
            name,
            path,
            flags["has_nfo"],
            flags["has_artwork"],
            flags["width"],
            flags["height"],
            mbid,
            db.text_array(genres),
        ),
    ).fetchone()
    return row["id"]


def _scan_title(existing, title):
    """A title the user typed stays in place. A scan only fills the rest."""
    if existing and existing.get("title_custom") and str(existing.get("title") or "").strip():
        return str(existing["title"])
    return title


def _upsert_album(
    conn,
    existing,
    artist_id,
    path,
    title,
    year,
    album_type,
    edition,
    flags,
    release_group,
    release_id,
    review,
):
    title = clean_text(title, 255) or "Unknown Album"
    title = _scan_title(existing, title)
    edition = clean_text(edition, 100)
    album_type = release_type(album_type)
    if existing:
        conn.execute(
            """
            UPDATE albums SET
                artist_id = %s,
                title = %s,
                release_year = %s,
                type = %s::release_type,
                edition = %s,
                has_nfo = %s,
                has_artwork = %s,
                artwork_width = %s,
                artwork_height = %s,
                musicbrainz_release_group_id = COALESCE(%s, musicbrainz_release_group_id),
                musicbrainz_release_id = COALESCE(%s, musicbrainz_release_id),
                review = COALESCE(review, %s),
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                artist_id,
                title,
                year,
                album_type,
                edition,
                flags["has_nfo"],
                flags["has_artwork"],
                flags["width"],
                flags["height"],
                release_group,
                release_id,
                review,
                existing["id"],
            ),
        )
        return existing["id"]
    row = conn.execute(
        """
        INSERT INTO albums (
            artist_id, title, path, status, release_year, type, edition, has_nfo, has_artwork,
            artwork_width, artwork_height, musicbrainz_release_group_id, musicbrainz_release_id, review
        )
        VALUES (
            %s, %s, %s, 'NEW', %s, %s::release_type, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            artist_id,
            title,
            path,
            year,
            album_type,
            edition,
            flags["has_nfo"],
            flags["has_artwork"],
            flags["width"],
            flags["height"],
            release_group,
            release_id,
            review,
        ),
    ).fetchone()
    return row["id"]


def _upsert_track(conn, album_id, item, release_group):
    if item.get("unchanged"):
        conn.execute(
            "UPDATE tracks SET album_id = %s WHERE file_path = %s AND album_id <> %s",
            (album_id, item["file_path"], album_id),
        )
        return
    raw = item["raw"] or {}
    if item.get("_instrumental"):
        raw = dict(raw)
        raw["_instrumental"] = True
    group = item["musicbrainz_release_group_id"] or release_group
    existing = conn.execute("SELECT id FROM tracks WHERE file_path = %s", (item["file_path"],)).fetchone()
    params = (
        album_id,
        item["title"],
        item["artist_name"],
        item["album_name"],
        item["genre"],
        item["year"],
        item["disc_number"],
        item["track_number"],
        item["duration_seconds"],
        item["file_format"],
        item["sample_rate"],
        item["bit_depth"],
        item.get("bitrate"),
        item["lyrics_type"],
        item["musicbrainz_track_id"],
        group,
        Json(raw),
        item.get("mtime_ns"),
        item.get("file_size"),
        item["file_path"],
    )
    if existing:
        conn.execute(
            """
            UPDATE tracks SET
                album_id = %s,
                title = %s,
                artist_name = %s,
                album_name = %s,
                genre = %s,
                year = %s,
                disc_number = %s,
                track_number = %s,
                duration_seconds = %s,
                file_format = %s,
                sample_rate = %s,
                bit_depth = %s,
                bitrate = %s,
                lyrics_type = %s,
                musicbrainz_track_id = %s,
                musicbrainz_release_group_id = %s,
                tags = %s,
                mtime_ns = %s,
                file_size = %s
            WHERE file_path = %s
            """,
            params,
        )
        return
    conn.execute(
        """
        INSERT INTO tracks (
            album_id, title, artist_name, album_name, genre, year, disc_number, track_number,
            duration_seconds, file_format, sample_rate, bit_depth, bitrate, lyrics_type,
            musicbrainz_track_id, musicbrainz_release_group_id, tags, mtime_ns, file_size, file_path
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        params,
    )


def _count_under(roots):
    if not roots:
        return 0
    clauses = " OR ".join(["path LIKE %s ESCAPE '\\'"] * len(roots))
    row = db.fetchone(
        f"SELECT COUNT(*)::int AS count FROM albums WHERE {clauses}",
        tuple(like_prefix(root) for root in roots),
    )
    return int(row["count"]) if row else 0


def _remember_paths(conn, table, paths):
    conn.execute(f"CREATE TEMP TABLE {table} (path text PRIMARY KEY) ON COMMIT DROP")
    pending = []
    for path in paths or []:
        pending.append(path)
        if len(pending) >= 500:
            conn.execute(
                f"INSERT INTO {table} (path) SELECT DISTINCT unnest(%s::text[]) ON CONFLICT DO NOTHING",
                (db.text_array(pending),),
            )
            pending = []
    if pending:
        conn.execute(
            f"INSERT INTO {table} (path) SELECT DISTINCT unnest(%s::text[]) ON CONFLICT DO NOTHING",
            (db.text_array(pending),),
        )


def _known_album_count(root):
    """Albums currently indexed under this root."""
    try:
        row = db.fetchone(
            "SELECT count(*) AS total FROM albums WHERE path = %s OR path LIKE %s ESCAPE '\\'",
            (root, like_prefix(root)),
        )
    except Exception:
        logger.debug("album count unavailable for %s", root, exc_info=True)
        return 0
    return int((row or {}).get("total") or 0)


def _prune(artist_paths, album_paths, roots, configured=None, failed_paths=None, removed_paths=None, held_roots=None):
    """Drop indexed folders that the walk did not see.

    The seen paths go into temporary tables. One giant path array made this
    step sit still after the directory walk on a large library.
    """
    from psycopg.errors import LockNotAvailable

    configured = configured or roots
    failed_paths = [p for p in (failed_paths or []) if p]
    last = None
    for attempt in range(4):
        try:
            with db.transaction() as conn:
                conn.execute("SET LOCAL lock_timeout = '30s'")
                _remember_paths(conn, "scan_seen_albums", album_paths)
                _remember_paths(conn, "scan_seen_artists", artist_paths)
                if failed_paths:
                    _remember_paths(conn, "scan_failed_paths", failed_paths)
                for root in roots:
                    prefix = like_prefix(root)
                    if failed_paths:
                        conn.execute(
                            """
                            DELETE FROM albums
                            WHERE path LIKE %s ESCAPE '\\'
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_seen_albums seen WHERE seen.path = albums.path
                              )
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_failed_paths failed
                                  WHERE albums.path = failed.path
                                     OR albums.path LIKE (failed.path || '/%%')
                                     OR albums.path LIKE (failed.path || '\\%%')
                              )
                            """,
                            (prefix,),
                        )
                        conn.execute(
                            """
                            DELETE FROM artists
                            WHERE path LIKE %s ESCAPE '\\'
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_seen_artists seen WHERE seen.path = artists.path
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM unnest(COALESCE(artists.folder_aliases, ARRAY[]::text[])) AS alias(path)
                                  JOIN scan_seen_artists seen ON seen.path = alias.path
                              )
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_failed_paths failed
                                  WHERE artists.path = failed.path
                                     OR artists.path LIKE (failed.path || '/%%')
                                     OR artists.path LIKE (failed.path || '\\%%')
                              )
                            """,
                            (prefix,),
                        )
                    else:
                        conn.execute(
                            """
                            DELETE FROM albums
                            WHERE path LIKE %s ESCAPE '\\'
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_seen_albums seen WHERE seen.path = albums.path
                              )
                            """,
                            (prefix,),
                        )
                        conn.execute(
                            """
                            DELETE FROM artists
                            WHERE path LIKE %s ESCAPE '\\'
                              AND NOT EXISTS (
                                  SELECT 1 FROM scan_seen_artists seen WHERE seen.path = artists.path
                              )
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM unnest(COALESCE(artists.folder_aliases, ARRAY[]::text[])) AS alias(path)
                                  JOIN scan_seen_artists seen ON seen.path = alias.path
                              )
                            """,
                            (prefix,),
                        )
                # Prune safety: a root that was left alone keeps its missing albums, marked, so
                # they can be filtered and removed by hand. Albums the walk did see are cleared.
                for root in held_roots or []:
                    conn.execute(
                        """
                        UPDATE albums
                        SET prune_held = NOT EXISTS (
                            SELECT 1 FROM scan_seen_albums seen WHERE seen.path = albums.path
                        )
                        WHERE path LIKE %s ESCAPE '\\'
                        """,
                        (like_prefix(root),),
                    )
                for root in roots:
                    conn.execute(
                        "UPDATE albums SET prune_held = FALSE WHERE prune_held AND path LIKE %s ESCAPE '\\'",
                        (like_prefix(root),),
                    )
                # Only paths the user took out of Settings are cleared, and each removal is
                # fenced by "not under any path that is still configured" so it never reaches a
                # sibling path on the same mount. A path that merely stopped being configured
                # (offline mount, Exclude, a hand-edited config) is left alone. Rows only: no
                # file is touched.
                if configured and removed_paths:
                    outside, params = _outside_library(configured)
                    for gone in removed_paths:
                        fence = list(params)
                        fence.extend([gone, like_prefix(gone)])
                        for table in ("albums", "artists"):
                            conn.execute(
                                f"""
                                DELETE FROM {table}
                                WHERE {outside}
                                  AND (path = %s OR path LIKE %s ESCAPE '\\')
                                """,
                                fence,
                            )
            return
        except LockNotAvailable as exc:
            last = exc
            logger.warning("folder cleanup waited on a database lock (%s/4)", attempt + 1)
            time.sleep(2)
    raise last


def _empty_folders(artist_path, progress=None, processed=None, total=None):
    """Directories with no audio: empty album folders, or the artist folder itself.

    A folder full of empty directories used to write one status line each and ignore Cancel
    until the list finished. The live log gets one count. The paths stay for the saved log.
    """
    empty = []
    try:
        names = sorted(os.listdir(artist_path), key=str.lower)
    except OSError as exc:
        logger.warning("scan: cannot list %s: %s", artist_path, exc)
        return empty
    label = os.path.basename(artist_path)
    saw_audio = False
    for index, name in enumerate(names, start=1):
        if index % 25 == 0:
            _checkpoint()
            if progress is not None and processed is not None:
                progress.update(processed, total or 0, f"Checking {label} ({index}/{len(names)} folders)", "delta")
        if name.startswith(".") or name.lower() in SKIP_DIRS:
            continue
        path = os.path.join(artist_path, name)
        if not os.path.isdir(path):
            continue
        if _contains_audio(path):
            saw_audio = True
            continue
        empty.append(path)
    if not saw_audio and not _audio_files(artist_path) and not empty:
        empty.append(artist_path)
    return empty


def _save_scan_issues(progress, result):
    summary = progress.lines[-1] if progress.lines else ""
    failures = list(result.get("failures") or [])
    empty_folders = list(result.get("empty_folders") or [])
    payload = dict(result)
    payload["summary"] = summary
    payload["failure_count"] = len(failures)
    payload["empty_count"] = len(empty_folders)
    lookups = list(result.get("lookups") or [])
    payload["failures"] = failures[:200]
    payload["empty_folders"] = empty_folders[:200]
    payload["lookup_count"] = len(lookups)
    payload["lookups"] = lookups[:200]
    try:
        db.execute(
            "UPDATE scan_jobs SET result = COALESCE(result, '{}'::jsonb) || %s::jsonb, log = %s WHERE id = %s",
            (Json(payload), progress.stored_log(), progress.job_id),
        )
    except Exception:
        logger.exception("could not store scan results")
    _write_scan_log(progress, summary)


def _write_scan_log(progress, summary):
    directory = os.path.join(config_dir(), "logs")
    try:
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        path = os.path.join(directory, f"{stamp}_music_scan.log")
        suffix = 2
        while os.path.exists(path):
            path = os.path.join(directory, f"{stamp}-{suffix}_music_scan.log")
            suffix += 1
        body = list(progress.lines)
        if summary and (not body or body[-1] != summary):
            body.append(summary)
        seen = set(body)
        for line in list(progress.issues) + list(getattr(progress, "parked", [])):
            if line not in seen:
                body.append(line)
                seen.add(line)
        header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"# {header}\n")
            for line in body:
                handle.write(line + "\n")
        _prune_scan_logs(directory, _scan_log_keep())
    except OSError:
        logger.warning("could not write scan log", exc_info=True)


def _scan_log_keep():
    try:
        keep = int(load_settings().get("scan_log_keep") or 30)
    except (TypeError, ValueError):
        keep = 30
    return max(1, min(keep, 100))


def _prune_scan_logs(directory, keep):
    """Keep the newest timestamped scan logs. Names sort by the time they contain."""
    try:
        keep_count = max(1, min(int(keep), 100))
    except (TypeError, ValueError):
        keep_count = 30
    pattern = re.compile(
        r"^(?:\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?_(?:music_scan|scan)(?:-\d+)?|(?:scan|music-scan)-\d{4}-\d{2}-\d{2}-\d{6}(?:-\d+)?)\.log$"
    )
    names = [
        name
        for name in os.listdir(directory)
        if pattern.fullmatch(name)
    ]
    stamp_re = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})")
    names.sort(key=lambda name: (stamp_re.search(name).group(1) if stamp_re.search(name) else "", name))
    for name in names[: max(0, len(names) - keep_count)]:
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            logger.warning("could not remove old scan log %s", name)


def _artist_folders(root, kind="artists"):
    """Return artist directories under a music path, and a count of loose audio files."""
    if not os.path.isdir(root):
        return [], 0
    if kind == "artist":
        return [root], 0
    found = []
    loose = 0
    entries = sorted(os.listdir(root), key=str.lower)
    for name in entries:
        _checkpoint()
        if name.startswith(".") or name.lower() in SKIP_DIRS:
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path):
            found.append(path)
        elif _is_audio(name):
            loose += 1
    return found, loose


def _purge_unmounted(configured, seen_albums=(), seen_artists=(), folder_roots=()):
    """Remove albums and artists that sit outside every music library path.

    The prune safety limits guard a library path that is mounted and came back short. A path
    that is no longer a music path has nothing to protect, so its rows are stale (a changed
    volume, a removed mount), whether or not the folder still exists on another mount. Offline and excluded library paths are in
    `configured`, so they are never touched. Rows only: no file is touched. Returns how many
    albums and artists were removed.
    """
    if not configured:
        return 0, []
    outside, params = _outside_library(configured)
    removed = 0
    samples = []
    seen = {"albums": set(seen_albums or ()), "artists": set(seen_artists or ())}
    for table in ("albums", "artists"):
        rows = db.fetchall(f"SELECT id, path FROM {table} WHERE {outside}", params)
        # Whatever this scan walked is in the library by definition, wherever the row says it is.
        rows = [row for row in rows if row.get("path") and row["path"] not in seen[table]]
        gone = [row["id"] for row in rows]
        if table == "artists":
            # An artist folder that is gone but still has albums elsewhere keeps its row.
            if gone:
                kept = {str(row["artist_id"]) for row in db.fetchall(
                    "SELECT DISTINCT artist_id FROM albums WHERE artist_id = ANY(%s::uuid[])", (db.uuid_array(gone),))}
                gone = [item for item in gone if str(item) not in kept]
                rows = [row for row in rows if row["id"] in gone]
        if gone:
            samples.extend(f"{table[:-1]}: {row['path']}" for row in rows[:3])
            db.execute(f"DELETE FROM {table} WHERE id = ANY(%s::uuid[])", (db.uuid_array(gone),))
            removed += len(gone)
    # An artist row sitting on a library path that holds many artists is left over from when that
    # folder was scanned as part of a bigger path (the folder itself became an "artist"). Only an
    # empty one goes; a row with albums is re-parented by the scan.
    roots = [str(root).rstrip("/") for root in folder_roots or () if root]
    if roots:
        rows = db.fetchall(
            "SELECT id, path FROM artists WHERE rtrim(path, '/') = ANY(%s) AND NOT EXISTS "
            "(SELECT 1 FROM albums WHERE albums.artist_id = artists.id)",
            (roots,),
        )
        rows = [row for row in rows if row["path"] not in seen["artists"]]
        if rows:
            db.execute("DELETE FROM artists WHERE id = ANY(%s::uuid[])", (db.uuid_array([row["id"] for row in rows]),))
            removed += len(rows)
            samples.extend(f"artist: {row['path']}" for row in rows[:3])
    return removed, samples


def _outside_library(configured):
    clauses = []
    params = []
    for root in configured:
        clauses.append("(path LIKE %s ESCAPE '\\' OR path = %s)")
        params.extend([like_prefix(root), root])
    return " AND ".join(f"NOT {clause}" for clause in clauses), params


def _grouped_discs(path):
    albums = []
    try:
        names = os.listdir(path)
    except OSError:
        return False
    for name in names:
        if name.startswith(".") or name.lower() in SKIP_DIRS:
            continue
        child = os.path.join(path, name)
        if os.path.isdir(child) and _contains_audio(child):
            albums.append(name)
    return len(albums) >= 2 and all(DISC_ONLY.match(name) for name in albums)


def _album_directories(artist_path):
    albums = []
    try:
        # SPEED 7: single scandir pass - avoids separate stat/isdir calls per entry
        entries = sorted(os.scandir(artist_path), key=lambda e: e.name.lower())
    except OSError:
        return albums
    for index, entry in enumerate(entries, start=1):
        if index % 25 == 0:
            _checkpoint()
        if entry.name.startswith(".") or entry.name.lower() in SKIP_DIRS:
            continue
        try:
            if not entry.is_dir(follow_symlinks=True):
                continue
        except OSError:
            continue
        if _contains_audio(entry.path):
            albums.append(entry.path)
    if len(albums) >= 2 and all(DISC_ONLY.match(os.path.basename(path)) for path in albums):
        return [artist_path]
    return albums


def _contains_audio(path, depth=AUDIO_NEST_DEPTH):
    if _audio_files(path):
        return True
    if depth <= 0:
        return False
    try:
        children = os.listdir(path)
    except OSError:
        return False
    for name in children:
        if name.startswith(".") or name.lower() in SIDECAR_DIRS:
            continue
        child = os.path.join(path, name)
        if os.path.isdir(child) and _contains_audio(child, depth - 1):
            return True
    return False


def _collect_tracks(album_path, mode):
    return _collect_nested(album_path, None, mode, AUDIO_NEST_DEPTH)


def _collect_nested(directory, disc_hint, mode, depth):
    items = list(_tracks_from_files(directory, disc_hint, mode))
    if depth <= 0:
        return items
    try:
        children = sorted(os.listdir(directory), key=_natural)
    except OSError:
        return items
    next_disc = 1 + max([item["disc_number"] for item in items] or [0])
    for name in children:
        if name.startswith(".") or name.lower() in SIDECAR_DIRS:
            continue
        path = os.path.join(directory, name)
        if not os.path.isdir(path):
            continue
        match = DISC_RE.search(name)
        if match:
            nested = _collect_nested(path, int(match.group(1)), mode, depth - 1)
        elif _audio_files(path):
            nested = _collect_nested(path, next_disc, mode, depth - 1)
        elif _contains_audio(path, depth - 1):
            nested = _collect_nested(path, disc_hint, mode, depth - 1)
        else:
            continue
        if not nested:
            continue
        items.extend(nested)
        next_disc = 1 + max(item["disc_number"] for item in items)
    return items


def _tracks_from_files(directory, disc_hint, mode):
    items = []
    for index, path in enumerate(_audio_files(directory), start=1):
        _checkpoint()
        stamp = _file_stamp(path)
        if mode != "deep":
            existing = db.fetchone("SELECT * FROM tracks WHERE file_path = %s", (path,))
            if existing and _same_mtime(existing, stamp):
                items.append(_item_from_row(existing, stamp))
                continue
        item = _read_track(path, disc_hint, index)
        item["mtime_ns"], item["file_size"] = stamp
        item["unchanged"] = False
        items.append(item)
    return items


def _file_stamp(path):
    stat = os.stat(path)
    modified = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    return int(modified), int(stat.st_size)


def _item_from_row(row, stamp):
    raw = row.get("tags") or {}
    return {
        "file_path": row["file_path"],
        "title": row["title"],
        "artist_name": row["artist_name"],
        "album_name": row["album_name"],
        "genre": row["genre"],
        "year": row["year"],
        "disc_number": row["disc_number"],
        "track_number": row["track_number"],
        "duration_seconds": row["duration_seconds"],
        "file_format": row["file_format"],
        "sample_rate": row["sample_rate"],
        "bit_depth": row["bit_depth"],
        "bitrate": row.get("bitrate"),
        "lyrics_type": row["lyrics_type"],
        "musicbrainz_track_id": row["musicbrainz_track_id"],
        "musicbrainz_release_group_id": row["musicbrainz_release_group_id"],
        "raw": raw,
        "mtime_ns": stamp[0],
        "file_size": stamp[1],
        "unchanged": True,
    }


def _audio_files(directory):
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return found
    for name in names:
        if name.startswith("."):
            continue
        if _is_audio(name):
            found.append(os.path.join(directory, name))
    images = _cue_image_names(directory)
    others = [path for path in found if os.path.basename(path) not in images]
    if images and others:
        found = others
    return sorted(found, key=lambda item: _natural(os.path.basename(item)))


def _cue_image_names(directory):
    names = set()
    try:
        entries = os.listdir(directory)
    except OSError:
        return names
    for name in entries:
        if not name.lower().endswith(".cue"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    text = line.strip()
                    if text.upper().startswith("FILE "):
                        quoted = text.split('"')
                        if len(quoted) >= 2:
                            names.add(os.path.basename(quoted[1]))
        except OSError:
            continue
    return names


def _is_cue_image(album_path):
    try:
        entries = os.listdir(album_path)
    except OSError:
        return False
    cues = [name for name in entries if name.lower().endswith(".cue")]
    direct = []
    for name in entries:
        path = os.path.join(album_path, name)
        if os.path.isfile(path) and _is_audio(name):
            direct.append(name)
    if len(cues) != 1 or len(direct) != 1:
        return False
    if not direct[0].lower().endswith((".flac", ".wav")):
        return False
    for name in entries:
        child = os.path.join(album_path, name)
        if os.path.isdir(child) and name.lower() not in SIDECAR_DIRS and _audio_files(child):
            return False
    return True


def _read_track(path, disc_hint, index):
    raw, info = tags.read_easy(path)
    tech = tags.technical(info)
    filename = os.path.splitext(os.path.basename(path))[0]
    file_disc, file_track, file_title = _parse_filename(filename)
    title = clean_text(raw.get("title"), 255) or clean_text(file_title, 255) or filename[:255]
    disc = leading_int(raw.get("discnumber"), None) or disc_hint or file_disc or 1
    number = leading_int(raw.get("tracknumber"), None) or file_track or index
    columns = completeness.columns_from_tags(raw)
    lyrics = _lyrics_type(path)
    return {
        "file_path": path,
        "title": title,
        "artist_name": columns["artist_name"],
        "album_name": columns["album_name"],
        "genre": columns["genre"],
        "year": columns["year"],
        "disc_number": disc,
        "track_number": number,
        "duration_seconds": tech["duration_seconds"],
        "file_format": os.path.splitext(path)[1].lstrip(".").lower()[:10] or "bin",
        "sample_rate": tech["sample_rate"],
        "bit_depth": tech["bit_depth"],
        "bitrate": tech.get("bitrate"),
        "lyrics_type": lyrics,
        "musicbrainz_track_id": columns["musicbrainz_track_id"],
        "musicbrainz_release_group_id": columns["musicbrainz_release_group_id"],
        "raw": raw,
    }


def _assign_numbers(items):
    used = set()
    for item in items:
        disc = item["disc_number"] or 1
        number = item["track_number"] or 1
        while (disc, number) in used:
            number += 1
        used.add((disc, number))
        item["disc_number"] = disc
        item["track_number"] = number


def _artist_sidecars(path, settings):
    nfo_names = ["artist.nfo", "folder.nfo"] if settings["nfo_profile"] == "kodi" else ["folder.nfo", "artist.nfo"]
    has_nfo = any(os.path.isfile(os.path.join(path, name)) for name in nfo_names)
    art = os.path.join(path, "folder.jpg")
    width, height = _image_size(art)
    return {"has_nfo": has_nfo, "has_artwork": width is not None, "width": width, "height": height}


def _album_sidecars(path, settings):
    names = ["album.nfo", "folder.nfo"] if settings["nfo_profile"] == "kodi" else ["folder.nfo", "album.nfo"]
    has_nfo = any(os.path.isfile(os.path.join(path, name)) for name in names)
    art = os.path.join(path, "folder.jpg")
    width, height = _image_size(art)
    return {"has_nfo": has_nfo, "has_artwork": width is not None, "width": width, "height": height}


def _image_size(path):
    if not os.path.isfile(path):
        return None, None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return None, None


def _record_local_artwork(album_id, artist_id, directory, artist=False):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        asset_type = _local_asset_type(name, artist)
        if asset_type:
            _upsert_local_row(album_id, artist_id, asset_type, path)
    extra = os.path.join(directory, "extrafanart")
    if os.path.isdir(extra):
        for name in sorted(os.listdir(extra)):
            file_path = os.path.join(extra, name)
            if os.path.isfile(file_path) and not name.startswith("."):
                _upsert_local_row(album_id, artist_id, "extrafanart", file_path)


def _local_asset_type(name, artist):
    key = name.lower()
    if key in {"folder.jpg", "folder.jpeg", "cover.jpg", "thumb.jpg"}:
        return "artistthumb" if artist else "front"
    if key in {"fanart.jpg", "fanart.jpeg", "fanart.png", "backdrop.jpg"}:
        return "fanart"
    if key.startswith("fanart") and len(key) > 6 and key[6].isdigit():
        return "extrafanart"
    if re.match(r"^booklet\d+\.(?:png|jpe?g|pdf)$", key):
        return "booklet"
    stem = key.split(".", 1)[0]
    if stem.startswith("discart") or stem.startswith("cdart"):
        return "discart"
    return {
        "back.jpg": "back",
        "back.jpeg": "back",
        "discart.png": "discart",
        "discart.jpg": "discart",
        "cdart.png": "discart",
        "disc.png": "discart",
        "spine.jpg": "spine",
        "spine.png": "spine",
        "banner.jpg": "banner",
        "clearlogo.png": "clearlogo",
        "logo.png": "clearlogo",
        "clearart.png": "clearart",
        "landscape.jpg": "landscape",
        "booklet.pdf": "booklet",
        "booklet.jpg": "booklet",
        "booklet.jpeg": "booklet",
        "booklet.png": "booklet",
        "tray.jpg": "tray",
        "sleeve.jpg": "tray",
        "obi.jpg": "obi",
        "liner.jpg": "liner",
        "sticker.jpg": "sticker",
        "poster.jpg": "poster",
        "matrix.jpg": "matrix",
        "top.jpg": "top",
        "bottom.jpg": "bottom",
    }.get(key)


def _merge_ids(primary, extra):
    seen = set()
    ordered = []
    for album_id in list(primary or []) + list(extra or []):
        key = str(album_id)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _missing_album_ids(roots):
    """Albums already indexed that still lack a release id or release details."""
    if not roots:
        return []
    clauses = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    rows = db.fetchall(
        f"""
        SELECT al.id
        FROM albums al
        WHERE ({clauses})
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND NOT EXISTS (
            SELECT 1 FROM artists ar
            WHERE ar.id = al.artist_id
              AND (ar.status = 'IGNORED' OR COALESCE(ar.locked, FALSE))
          )
          AND (
            al.musicbrainz_release_id IS NULL
            OR al.musicbrainz_release_group_id IS NULL
            OR COALESCE(btrim(al.country), '') = ''
            OR COALESCE(btrim(al.label), '') = ''
            OR COALESCE(btrim(al.catalog), '') = ''
            OR EXISTS (
                SELECT 1 FROM tracks t
                WHERE t.album_id = al.id
                  AND (
                    t.musicbrainz_track_id IS NULL
                    OR t.year IS NULL
                    OR COALESCE(btrim(t.genre), '') = ''
                    OR COALESCE(btrim(t.tags->>'releasecountry'), '') = ''
                  )
            )
          )
        ORDER BY al.path
        """,
        params,
    )
    return [str(row["id"]) for row in rows]


def _scan_choice(cfg, key, mode, force):
    chosen = cfg.get(key)
    if not isinstance(chosen, dict):
        return False
    if chosen.get(mode):
        return True
    return bool(force and chosen.get("forced"))


def _rematch(progress, roots, album_ids=None, mode="incremental", force=False):
    mode = normalize_scan_mode(mode) if album_ids is not None else "deep"
    if album_ids is not None and not album_ids:
        skipped = (
            "MusicBrainz lookup skipped. No albums are new, changed, or missing release details."
            if mode == "full"
            else "MusicBrainz lookup skipped. No new or changed albums."
        )
        progress.log(skipped, phase="musicbrainz", message="MusicBrainz lookup skipped")
        return []
    if mode == "deep":
        progress.log("MusicBrainz and AcoustID lookup started", phase="musicbrainz", message="MusicBrainz lookup")
        scope = "each album"
    elif mode == "full":
        progress.log(
            f"MusicBrainz lookup for {len(album_ids)} albums that are new, changed, or missing details",
            phase="musicbrainz",
            message="MusicBrainz lookup",
        )
        scope = "each album that is new, changed, or missing details"
    else:
        progress.log(
            f"MusicBrainz lookup for {len(album_ids)} new or changed albums",
            phase="musicbrainz",
            message="MusicBrainz lookup",
        )
        scope = "each new or changed album"
    from resonance import artwork, match
    from resonance.jobs import ScanCancelled, begin_prompt

    cfg = load_settings()
    choose_release = _scan_choice(cfg, "choose_release_modes", mode, force)
    choose_artwork = _scan_choice(cfg, "artwork_lookup_modes", mode, force)
    kind = "forced " + mode if force else mode
    if choose_release:
        progress.log(f"Choose MB release is on for this {kind} scan. The scan pauses for {scope}.")
    if choose_artwork:
        progress.log(f"Artwork lookup is on for this {kind} scan. The scan pauses for artwork after {scope}.")
    clauses = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    where = clauses
    if album_ids is not None:
        where = f"({clauses}) AND al.id = ANY(%s::uuid[])"
        params.append(db.uuid_array(album_ids))
    albums = db.fetchall(
        f"""
        SELECT al.id, al.title, al.release_year, ar.name AS artist_name
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE {where}
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND ar.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(ar.locked, FALSE)
        ORDER BY lower(ar.name), lower(al.title)
        """,
        params,
    )
    progress.update(0, len(albums), "MusicBrainz lookup", "musicbrainz")
    labels = []
    for index, album in enumerate(albums, start=1):
        _checkpoint()
        label = f"{album['artist_name']} — {album['title']}"
        if album.get("release_year"):
            label = f"{label} ({album['release_year']})"
        labels.append(label)
        try:
            found = match.search(album["id"])
            candidates = found.get("candidates") or []
            if candidates:
                top = candidates[0]
                progress.log(f"MusicBrainz: {label}: {top.get('title') or 'release'} ({top.get('year') or '----'})")
            else:
                progress.log(f"MusicBrainz: {label}: no release")
            if choose_release:
                progress.log(f"Waiting for a release choice: {label}", message=f"Choose a release for {label}")
                decision = begin_prompt(
                    progress.job_id,
                    {
                        "kind": "release",
                        "album_id": album["id"],
                        "label": label,
                        "message": f"Choose a release for {label}",
                        "search": found,
                    },
                )
                _accept_scan_release(progress, album, label, decision)
            if choose_artwork:
                progress.log(f"Looking up artwork: {label}", message=f"Choose artwork for {label}")
                try:
                    artwork.harvest(str(album["id"]), scope="album", respect_enabled=False)
                except ScanCancelled:
                    raise
                except Exception as exc:
                    progress.log(f"Artwork lookup failed: {label}: {exc}")
                begin_prompt(
                    progress.job_id,
                    {
                        "kind": "artwork",
                        "album_id": album["id"],
                        "label": label,
                        "message": f"Choose artwork for {label}",
                    },
                )
                progress.log(f"Artwork: {label}: continued")
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"MusicBrainz: {label}: {exc}")
        progress.update(index, len(albums), f"MusicBrainz {label}", "musicbrainz")
    if choose_release or choose_artwork:
        progress.log("The scan waits for each choice. Apply match writes tags, .nfo, and lyrics.")
    else:
        progress.log("Lookups are suggestions only. Use Match or batch commit to write tags.")
    return labels


def _fill_stored_mb_metadata(progress, roots, mode, album_ids):
    """Copy blank MusicBrainz fields for albums that already have a release id.

    Full and deep scans check every album in the folders. An incremental scan
    checks new and changed albums only when that option is on.
    """
    mode = normalize_scan_mode(mode)
    if mode == "incremental" and load_settings().get("fill_mb_metadata_during_incremental", True) is False:
        progress.log(
            "MusicBrainz metadata fill is off for this incremental scan.",
            phase="musicbrainz",
            message="MusicBrainz metadata off",
        )
        return
    if album_ids is not None and not album_ids:
        progress.log(
            "MusicBrainz metadata: no new or changed albums.",
            phase="musicbrainz",
            message="MusicBrainz metadata",
        )
        return
    from resonance import match

    clauses = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    scope = ""
    if album_ids is not None:
        scope = " AND al.id = ANY(%s::uuid[])"
        params.append(db.uuid_array(album_ids))
    rows = db.fetchall(
        f"""
        SELECT al.id, al.title, ar.name AS artist_name
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE ({clauses})
          {scope}
          AND al.musicbrainz_release_id IS NOT NULL
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND ar.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(ar.locked, FALSE)
          AND (
            COALESCE(btrim(al.catalog), '') = ''
            OR COALESCE(btrim(al.barcode), '') = ''
            OR COALESCE(btrim(al.label), '') = ''
            OR COALESCE(btrim(al.country), '') = ''
            OR COALESCE(btrim(al.release_status), '') = ''
            OR al.musicbrainz_release_group_id IS NULL
            OR ar.musicbrainz_artist_id IS NULL
            OR EXISTS (
                SELECT 1 FROM tracks t
                WHERE t.album_id = al.id
                  AND (
                    t.musicbrainz_track_id IS NULL
                    OR t.year IS NULL
                    OR COALESCE(btrim(t.genre), '') = ''
                    OR COALESCE(btrim(t.tags->>'artists'), '') = ''
                    OR COALESCE(btrim(t.tags->>'artistsort'), '') = ''
                    OR COALESCE(btrim(t.tags->>'albumartists'), '') = ''
                    OR COALESCE(btrim(t.tags->>'albumartistsort'), '') = ''
                    OR COALESCE(btrim(t.tags->>'musicbrainz_recordingid'), '') = ''
                    OR COALESCE(btrim(t.tags->>'musicbrainz_artistid'), '') = ''
                    OR COALESCE(btrim(t.tags->>'musicbrainz_albumartistid'), '') = ''
                    OR COALESCE(btrim(t.tags->>'catalognumber'), '') = ''
                    OR COALESCE(btrim(t.tags->>'barcode'), '') = ''
                    OR COALESCE(btrim(t.tags->>'label'), '') = ''
                    OR COALESCE(btrim(t.tags->>'releasecountry'), '') = ''
                    OR COALESCE(btrim(t.tags->>'releasestatus'), '') = ''
                    OR COALESCE(btrim(t.tags->>'releasetype'), '') = ''
                  )
            )
          )
        ORDER BY lower(ar.name), lower(al.title)
        """,
        params,
    )
    if not rows:
        progress.log(
            "MusicBrainz metadata: nothing missing on albums that already have a release id.",
            phase="musicbrainz",
            message="MusicBrainz metadata",
        )
        return
    progress.log(
        f"MusicBrainz metadata: {len(rows)} albums with a release id and blank fields",
        phase="musicbrainz",
        message="MusicBrainz metadata",
    )
    progress.update(0, len(rows), "MusicBrainz metadata", "musicbrainz")
    filled_albums = 0
    for index, album in enumerate(rows, start=1):
        _checkpoint()
        label = f"{album.get('artist_name') or 'Artist'} — {album.get('title') or 'Album'}"
        try:
            count = match.fill_stored_release(str(album["id"]))
        except Exception as exc:
            from resonance.jobs import ScanCancelled

            if isinstance(exc, ScanCancelled):
                raise
            progress.log(f"MusicBrainz metadata: {label}: {exc}")
        else:
            if count:
                filled_albums += 1
                progress.log(f"MusicBrainz metadata: {label}: filled {count}")
            else:
                progress.log(f"MusicBrainz metadata: {label}: nothing new")
        progress.update(index, len(rows), f"MusicBrainz metadata {label}", "musicbrainz")
    progress.log(
        f"MusicBrainz metadata: filled {filled_albums} of {len(rows)} albums.",
        phase="musicbrainz",
        message="MusicBrainz metadata",
    )


def _accept_scan_release(progress, album, label, decision):
    from resonance import match
    from resonance.jobs import ScanCancelled

    if decision.get("action") != "release" or not decision.get("release_id"):
        progress.log(f"MusicBrainz: {label}: skipped")
        return
    try:
        proposal = match.build_proposal(str(album["id"]), decision["release_id"])["proposal"]
        match.remember_release(str(album["id"]), proposal)
        title = proposal.get("album_title") or decision["release_id"]
        if not decision.get("apply"):
            progress.log(f"MusicBrainz: {label}: matched {title}")
            return
        steps = [step for step in apply_steps() if step in {"tags", "nfo", "lyrics", "processed"}]
        if not any(step in steps for step in ("tags", "nfo", "lyrics")):
            progress.log(f"MusicBrainz: {label}: matched {title}. Tags, .nfo, and Lyrics are off, so files were left unchanged.")
            return
        detail = match.apply(str(album["id"]), proposal, steps=steps, notify=False)
        progress.log(f"MusicBrainz: {label}: applied {title}")
        for warning in detail.get("warnings") or []:
            progress.log(f"MusicBrainz: {label}: {warning}")
    except ScanCancelled:
        raise
    except Exception as exc:
        progress.log(f"MusicBrainz: {label}: {exc}")


def _refresh_discographies(progress, roots, album_ids=None):
    """Refresh MusicBrainz discographies that are missing or older than seven days.

    album_ids limits the pass to the artists of those albums. An incremental scan
    passes its new and changed albums so the rest of the library is left alone.
    """
    if load_settings().get("refresh_discography_during_scan", True) is False:
        return
    from resonance import discography
    from resonance.jobs import ScanCancelled

    if album_ids is not None and not album_ids:
        progress.log(
            "Discography: no new or changed albums, so no artist catalogs were checked.",
            phase="musicbrainz",
            message="Discography",
        )
        return
    clauses = " OR ".join(["path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    scope = ""
    if album_ids is not None:
        scope = " AND id IN (SELECT artist_id FROM albums WHERE id = ANY(%s::uuid[]))"
        params.append(db.uuid_array(album_ids))
    artists = db.fetchall(
        f"""
        SELECT id, name
        FROM artists
        WHERE musicbrainz_artist_id IS NOT NULL
          AND ({clauses})
          {scope}
          AND (
            discography_fetched_at IS NULL
            OR discography_fetched_at < NOW() - INTERVAL '7 days'
          )
        ORDER BY lower(name)
        """,
        params,
    )
    if not artists:
        progress.log("Discography: nothing older than 7 days.", phase="musicbrainz", message="Discography")
        return
    progress.log(
        f"Discography: {len(artists)} artists with a catalog missing or older than 7 days",
        phase="musicbrainz",
        message="Discography",
    )
    updated = 0
    for index, artist in enumerate(artists, start=1):
        _checkpoint()
        label = artist.get("name") or "Artist"
        try:
            discography.refresh(str(artist["id"]))
            updated += 1
            progress.log(f"Discography: {label}: updated")
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"Discography: {label}: {exc}")
        progress.update(index, len(artists), f"Discography {label}", "musicbrainz")
    progress.log(f"Discography: updated {updated}, left {len(artists) - updated}", phase="musicbrainz")


def _sidecar_summary(progress, roots):
    progress.update(0, 1, "Sidecar audit", "sidecars")
    clauses = " OR ".join(["path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    row = db.fetchone(
        f"""
        SELECT
            (SELECT COUNT(*)::int FROM artists WHERE has_nfo = TRUE AND ({clauses})) AS artist_nfo,
            (SELECT COUNT(*)::int FROM albums WHERE has_nfo = TRUE AND ({clauses})) AS album_nfo,
            (SELECT COUNT(*)::int FROM albums WHERE has_artwork = TRUE AND ({clauses})) AS covers
        """,
        params + params + params,
    )
    if row:
        progress.log(
            f"Sidecars: {row['artist_nfo']} artist NFO, {row['album_nfo']} album NFO, {row['covers']} folder.jpg",
            phase="sidecars",
            message="Sidecar audit",
        )


def _metadata_miss_days():
    from resonance.settings import load as load_settings

    try:
        days = int(load_settings().get("metadata_miss_days", 30))
    except (TypeError, ValueError):
        days = 30
    return max(0, min(days, 3650))


def _metadata_due_clause(column, days):
    allowed = {"biography_checked_at", "metadata_checked_at", "review_checked_at"}
    name = column[3:] if column.startswith("al.") else column
    if name not in allowed or column not in {name, f"al.{name}"}:
        raise ValueError(column)
    if not days:
        return "", []
    return f"AND ({column} IS NULL OR {column} < NOW() - (%s * INTERVAL '1 day'))", [days]


def _text_blank(column):
    return f"({column} IS NULL OR btrim({column}) = '')"


# Blank values here are enough to look the artist up. Gender, died, disbanded,
# and disambiguation are filled when a lookup runs, but they stay empty for many
# artists and do not schedule a lookup on their own.
_ARTIST_LOOKUP_GAPS = (
    "sortname",
    "formed",
    "origin",
    "years_active",
    "website",
    "discogs_url",
    "wikipedia_url",
    "style",
    "mood",
)

_SCAN_ARTIST_LIMITS = (
    ("type", 50),
    ("sortname", 255),
    ("gender", 40),
    ("disambiguation", 255),
    ("formed", 80),
    ("origin", 255),
    ("years_active", 255),
    ("died", 80),
    ("disbanded", 80),
    ("website", 500),
    ("discogs_url", 500),
    ("wikipedia_url", 500),
    ("style", 500),
    ("mood", 500),
    ("instruments", 500),
)


def _artist_gap_sql():
    parts = [_text_blank(column) for column in _ARTIST_LOOKUP_GAPS]
    parts.append("musicbrainz_artist_id IS NULL")
    parts.append("(COALESCE(genres_custom, FALSE) = FALSE AND COALESCE(genres_from_tags, TRUE) = TRUE)")
    parts.append(
        "("
        "genres IS NULL OR cardinality(COALESCE(genres, ARRAY[]::text[])) = 0 "
        "OR NOT EXISTS ("
        "SELECT 1 FROM unnest(COALESCE(genres, ARRAY[]::text[])) AS genre "
        "WHERE btrim(genre) <> '' AND genre !~ '^[0-9]+$'"
        ")"
        ")"
    )
    return "(" + " OR ".join(parts) + ")"


def _artist_metadata_where(longest):
    """Artists who still need a biography, or any artist.nfo field the lookup can fill."""
    if longest:
        biography = "COALESCE(biography_custom, FALSE) = FALSE"
    else:
        biography = "COALESCE(biography_custom, FALSE) = FALSE AND " + _text_blank("biography")
    return f"({biography} OR {_artist_gap_sql()})"


def _album_metadata_where():
    """Albums missing a review, style, or mood. Theme is saved when a lookup already runs."""
    parts = [_text_blank(f"al.{column}") for column in ("review", "style", "mood")]
    return "(" + " OR ".join(parts) + ")"


def _blank(value):
    return not str(value or "").strip()


def _named_genres(values):
    names = []
    for item in values or []:
        text = genre_name(item)
        if text and text.lower() not in {name.lower() for name in names}:
            names.append(text)
    return names


def _genres_need_names(values):
    names = [str(item).strip() for item in values or [] if str(item or "").strip()]
    return not any(name and not name.isdigit() for name in names)


def _with_skip(message, skipped):
    """Append how many albums an incremental pass left alone. None means the whole library."""
    if skipped is None:
        return message
    count = int(skipped)
    noun = "album" if count == 1 else "albums"
    return f"{message} · {count} {noun} left unchanged"


def _fill_missing_metadata(progress, roots, album_ids=None, skipped=None):
    """Fill blank biographies, artist.nfo fields, reviews, and album descriptors.

    album_ids limits the pass to those albums and their artists. None checks the whole library.
    """
    from resonance import profile
    from resonance.fields import clean_text
    from resonance.jobs import ScanCancelled
    from resonance.settings import load as load_settings
    from resonance.settings import metadata_sources
    from resonance.sources import lastfm

    longest = load_settings().get("biography_longest", True) is not False
    artist_clause = " OR ".join(["path LIKE %s ESCAPE '\\'"] * len(roots))
    album_clause = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots))
    params = [like_prefix(root) for root in roots]
    miss_days = _metadata_miss_days()
    artist_wait, artist_wait_params = _metadata_due_clause("metadata_checked_at", miss_days)
    album_wait, album_wait_params = _metadata_due_clause("al.review_checked_at", miss_days)
    if album_ids is not None and not album_ids:
        note = _with_skip("No new or changed albums", skipped)
        progress.log(f"Metadata: {note}.", phase="metadata", message=note)
        return
    artist_scope = ""
    album_scope = ""
    scope_params = []
    if album_ids is not None:
        artist_scope = " AND id IN (SELECT artist_id FROM albums WHERE id = ANY(%s::uuid[]))"
        album_scope = " AND al.id = ANY(%s::uuid[])"
        scope_params = [db.uuid_array(album_ids)]
    artists = db.fetchall(
        f"""
        SELECT * FROM artists
        WHERE {_artist_metadata_where(longest)}
          AND ({artist_clause})
          AND status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(locked, FALSE)
          {artist_scope}
          {artist_wait}
        ORDER BY lower(name)
        """,
        params + scope_params + artist_wait_params,
    )
    albums = db.fetchall(
        f"""
        SELECT al.*, ar.name AS artist_name
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE {_album_metadata_where()}
          AND ({album_clause})
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND ar.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(ar.locked, FALSE)
          {album_scope}
          {album_wait}
        ORDER BY lower(ar.name), lower(al.title)
        """,
        params + scope_params + album_wait_params,
    )
    total = len(artists) + len(albums)
    progress.update(0, total, _with_skip("Missing metadata", skipped), "metadata")
    if not total:
        if miss_days:
            note = _with_skip(f"Nothing due. Misses wait {miss_days} days", skipped)
            progress.log(f"Metadata: {note}.", phase="metadata", message=note)
        else:
            note = _with_skip("Nothing missing", skipped)
            progress.log(f"Metadata: {note}.", phase="metadata", message=note)
        return
    artist_note = "artists to check" if longest else "artists with missing metadata"
    progress.log(
        f"Metadata: {len(artists)} {artist_note}, {len(albums)} albums with missing metadata"
        + (f". Checked artists wait {miss_days} days" if miss_days else ""),
        phase="metadata",
        message=_with_skip("Missing metadata", skipped),
    )
    done = 0
    filled = 0
    for artist in artists:
        from resonance.jobs import cancelled as scan_cancelled
        from resonance.memory import wait as wait_for_memory

        wait_for_memory(progress.log, stop=scan_cancelled)
        _checkpoint()
        done += 1
        label = artist.get("name") or "Artist"
        try:
            found = profile.scrape(str(artist["id"]))
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"Metadata: {label}: {exc}")
            progress.update(done, total, _with_skip(f"Metadata {label}", skipped), "metadata")
            progress.note_library("metadata")
            continue
        outcome = _store_missing_artist(artist, found, longest)
        note = _metadata_note(outcome)
        if note:
            if outcome.get("biography") in {"saved", "replaced"} or outcome.get("fields"):
                filled += 1
            progress.log(f"Metadata: {label}: {note}")
        else:
            progress.log(f"Metadata: {label}: nothing new")
        db.execute(
            "UPDATE artists SET biography_checked_at = NOW(), metadata_checked_at = NOW() WHERE id = %s",
            (artist["id"],),
        )
        progress.update(done, total, _with_skip(f"Metadata {label}", skipped), "metadata")
        progress.note_library("metadata")
    review_order = metadata_sources("review")
    desc_order = metadata_sources("descriptors")
    for album in albums:
        _checkpoint()
        done += 1
        label = f"{album.get('artist_name') or 'Artist'} — {album.get('title') or 'Album'}"
        try:
            if _store_missing_album(album, review_order, desc_order, lastfm, clean_text):
                filled += 1
                progress.log(f"Metadata: {label}: metadata saved")
                _write_scanned_album_nfo(album)
            else:
                progress.log(f"Metadata: {label}: nothing new")
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"Metadata: {label}: {exc}")
        else:
            db.execute("UPDATE albums SET review_checked_at = NOW() WHERE id = %s", (album["id"],))
        progress.update(done, total, _with_skip(f"Metadata {label}", skipped), "metadata")
        progress.note_library("metadata")
    progress.log(
        f"Metadata: filled {filled}, left {total - filled} still empty.",
        phase="metadata",
        message=_with_skip("Metadata", skipped),
    )


def _metadata_note(outcome):
    biography = outcome.get("biography")
    count = len(outcome.get("fields") or [])
    parts = []
    if biography in {"saved", "replaced", "kept"}:
        parts.append(f"biography {biography}")
    if count:
        parts.append(f"{count} field{'s' if count != 1 else ''} filled")
    return ", ".join(parts)


def _store_missing_artist(artist, found, longest=False):
    """Save a blank biography and any blank artist.nfo field. Filled values stay put."""
    from psycopg.errors import UniqueViolation

    from resonance.fields import clean_text
    from resonance.settings import load as load_settings

    fields = (found or {}).get("fields") or {}
    sets = []
    params = []
    filled = []
    stored = str(artist.get("biography") or "").strip()
    biography = clean_text((found or {}).get("biography"), 20000)
    outcome = "kept" if stored else "missing"
    wrote_biography = False
    if biography and not artist.get("biography_custom"):
        if not stored:
            outcome = "saved"
            wrote_biography = True
        elif longest and len(biography) > len(stored):
            outcome = "replaced"
            wrote_biography = True
    if wrote_biography:
        sets.append("biography = %s")
        params.append(biography)
        sets.append("biography_custom = FALSE")
    for key, limit in _SCAN_ARTIST_LIMITS:
        if key == "type":
            continue
        value = clean_text(fields.get(key), limit)
        if value and _blank(artist.get(key)):
            sets.append(f"{key} = %s")
            params.append(value)
            filled.append(key)
    if not artist.get("type_custom"):
        kind = clean_text(fields.get("type"), 50)
        current_type = clean_text(artist.get("type"), 50) or ""
        if kind and kind.lower() != current_type.lower():
            sets.append("type = %s")
            params.append(kind)
            filled.append("type")
    if not artist.get("genres_custom"):
        genres = _named_genres(fields.get("genres"))
        current = _named_genres(artist.get("genres"))
        if genres and [name.lower() for name in current] != [name.lower() for name in genres]:
            sets.append("genres = %s::text[]")
            params.append(db.text_array(genres))
            filled.append("genres")
        sets.append("genres_from_tags = FALSE")
    if sets:
        params.append(artist["id"])
        db.execute(
            f"UPDATE artists SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
            tuple(params),
        )
    mbid = opt_uuid_loose(fields.get("musicbrainz_artist_id"))
    if mbid and not artist.get("musicbrainz_artist_id"):
        try:
            if db.artist_mbid_blocked(mbid, artist.get("name"), artist["id"]):
                raise UniqueViolation()
            db.execute(
                "UPDATE artists SET musicbrainz_artist_id = %s, updated_at = NOW() WHERE id = %s",
                (mbid, artist["id"]),
            )
        except UniqueViolation:
            logger.info("MusicBrainz artist id %s is already used; %s was left unchanged", mbid, artist.get("name"))
        else:
            filled.append("musicbrainz_artist_id")
    if (wrote_biography or filled) and load_settings().get("nfo_on_bio_save", True):
        try:
            from resonance.library import write_artist_nfo

            write_artist_nfo(str(artist["id"]))
        except Exception:
            logger.info("artist nfo was not rewritten for %s", artist.get("name"), exc_info=True)
    return {"biography": outcome, "fields": filled}


def _nfos_from_scan(progress, roots, mode, album_ids):
    """Write album.nfo after the scan has finished storing metadata.

    A missing file is always written. A new or changed album that already has a
    MusicBrainz id is rewritten so the file matches the database. Rewrite all
    replaces every artist and album file under the scanned folders.
    """
    from resonance.library import write_album_nfo, write_artist_nfo
    from resonance.paths import mount_writable

    rewrite = load_settings().get("scan_rewrite_nfo") is True
    roots = [root for root in roots or [] if root]
    if not roots and not album_ids:
        progress.log("NFO: nothing to write", phase="nfo", message="Write .nfo")
        return
    clauses = " OR ".join(["al.path LIKE %s ESCAPE '\\'"] * len(roots)) if roots else ""
    params = [like_prefix(root) for root in roots]
    where = f"({clauses})" if clauses else "TRUE"
    if album_ids is not None and not rewrite:
        if not album_ids:
            progress.log("NFO: nothing to write", phase="nfo", message="Write .nfo")
            return
        where = f"{where} AND al.id = ANY(%s::uuid[])"
        params.append(db.uuid_array(album_ids))
    albums = db.fetchall(
        f"""
        SELECT al.id, al.artist_id, al.title, al.path, al.has_nfo,
               ar.name AS artist_name, ar.path AS artist_path, ar.has_nfo AS artist_has_nfo,
               ar.musicbrainz_artist_id,
               (
                   al.musicbrainz_release_id IS NOT NULL
                   OR al.musicbrainz_release_group_id IS NOT NULL
                   OR EXISTS (
                       SELECT 1 FROM tracks t
                       WHERE t.album_id = al.id AND t.musicbrainz_track_id IS NOT NULL
                   )
               ) AS matched
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE {where}
          AND al.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(al.locked, FALSE)
          AND ar.status IS DISTINCT FROM 'IGNORED'
          AND NOT COALESCE(ar.locked, FALSE)
        ORDER BY lower(ar.name), lower(al.title)
        """,
        params,
    )
    if rewrite:
        due = list(albums)
    elif album_ids is None:
        due = [row for row in albums if not row.get("has_nfo")]
    else:
        due = [row for row in albums if not row.get("has_nfo") or row.get("matched")]
    if not due:
        progress.log("NFO: nothing to write", phase="nfo", message="Write .nfo")
        return
    written = 0
    artists_done = set()
    progress.update(0, len(due), "Write .nfo", "nfo")
    for index, album in enumerate(due, start=1):
        _checkpoint()
        label = f"{album.get('artist_name') or 'Artist'} — {album.get('title') or 'Album'}"
        progress.update(index, len(due), f"Write .nfo {label}", "nfo")
        artist_id = str(album.get("artist_id") or "")
        if artist_id and artist_id not in artists_done:
            artists_done.add(artist_id)
            artist_due = rewrite or not album.get("artist_has_nfo") or (
                album_ids is not None and album.get("musicbrainz_artist_id")
            )
            if artist_due and album.get("artist_path") and mount_writable(album["artist_path"]):
                try:
                    write_artist_nfo(artist_id)
                except Exception as exc:
                    progress.log(f"Could not write artist.nfo: {label}: {exc}")
        if not album.get("path") or not mount_writable(album["path"]):
            continue
        try:
            write_album_nfo(str(album["id"]))
            written += 1
        except Exception as exc:
            progress.log(f"Could not write album.nfo: {label}: {exc}")
    note = " Existing files were replaced." if rewrite and written else ""
    progress.log(f"NFO: {written} album files written.{note}", phase="nfo", message="Write .nfo")


def _write_scanned_album_nfo(album):
    """Rewrite album.nfo after a scan stores a review or descriptor."""
    from resonance.settings import load as load_settings

    if load_settings().get("nfo_on_bio_save", True) is False:
        return
    try:
        from resonance.library import write_album_nfo

        write_album_nfo(str(album["id"]))
    except Exception:
        logger.info("album nfo was not rewritten for %s", album.get("title"), exc_info=True)


def _store_missing_album(album, review_order, desc_order, lastfm, clean_text):
    from resonance import match

    artist_name = album.get("artist_name") or ""
    title = album.get("title") or ""
    year = album.get("release_year")
    page = None
    if "allmusic" in review_order or "allmusic" in desc_order:
        page = match._allmusic_album(title, artist_name, year)
    lastfm_album = {}
    if "lastfm" in review_order or "lastfm" in desc_order:
        lastfm_album = lastfm.album_text(artist_name, title) or {}
    group_key = str(album.get("musicbrainz_release_group_id") or "")
    review = "" if str(album.get("review") or "").strip() else match._review_from(
        review_order, page, group_key, title, artist_name, lastfm_album
    )
    style, mood, theme = match._album_descriptors(desc_order, page, group_key, lastfm_album)
    sets = []
    params = []
    for key, value, limit in (
        ("review", review, 20000),
        ("style", style, 500),
        ("mood", mood, 500),
        ("theme", theme, 500),
    ):
        text = clean_text(value, limit)
        if text and not str(album.get(key) or "").strip():
            sets.append(f"{key} = %s")
            params.append(text)
    if page and page.get("url") and not album.get("allmusic_url"):
        sets.append("allmusic_url = %s")
        params.append(page.get("url"))
    if not sets:
        return False
    params.append(album["id"])
    db.execute(
        f"UPDATE albums SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s",
        tuple(params),
    )
    return True


def _fill_missing_artwork(progress, roots, album_ids=None, skipped=None):
    """Download artwork that is still missing. Runs after the sidecar count.

    album_ids limits the pass to those albums and their artists. None checks the whole library.
    """
    from resonance import artwork
    from resonance.jobs import ScanCancelled
    from resonance.settings import load as load_settings

    limited = bool(load_settings().get("limited_artwork_during_scan"))
    progress.update(0, 0, _with_skip("Checking artwork", skipped), "artwork")
    if album_ids is not None and not album_ids:
        note = _with_skip("No new or changed albums", skipped)
        progress.log(f"Artwork: {note}.", phase="artwork", message=note)
        return
    artists, albums, artist_types, album_types = artwork.scan_targets(roots, limited, album_ids)
    total = len(artists) + len(albums)
    progress.update(0, total, _with_skip("Missing artwork", skipped), "artwork")
    if not total:
        note = _with_skip("Nothing missing", skipped)
        progress.log(f"Artwork: {note}.", phase="artwork", message=note)
        return
    if limited:
        summary = f"Artwork: {len(artists)} artists and {len(albums)} albums are missing a cover"
    else:
        summary = (
            f"Artwork: {len(artists)} artists and {len(albums)} albums are missing "
            "artwork that is turned on"
        )
    progress.log(summary, phase="artwork", message=_with_skip("Missing artwork", skipped))
    done = 0
    saved = 0
    for artist in artists:
        from resonance.jobs import cancelled as scan_cancelled
        from resonance.memory import wait as wait_for_memory

        wait_for_memory(progress.log, stop=scan_cancelled)
        _checkpoint()
        done += 1
        label = artist.get("name") or "Artist"
        try:
            result = artwork.deploy_missing_artist(str(artist["id"]), only_types=artist_types)
            deployed = result.get("deployed") or []
            if deployed:
                saved += 1
                progress.log(f"Artwork: {label}: saved {', '.join(deployed)}")
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"Artwork: {label}: {exc}")
        progress.update(done, total, _with_skip(f"Artwork {label}", skipped), "artwork")
        progress.note_library("artwork")
    for album in albums:
        _checkpoint()
        done += 1
        label = f"{album.get('artist_name') or 'Artist'} — {album.get('title') or 'Album'}"
        try:
            result = artwork.deploy_missing(str(album["id"]), scope="album", only_types=album_types)
            deployed = result.get("deployed") or []
            if deployed:
                saved += 1
                progress.log(f"Artwork: {label}: saved {', '.join(deployed)}")
            for warning in result.get("warnings") or []:
                progress.log(f"Artwork: {label}: {warning}")
        except ScanCancelled:
            raise
        except Exception as exc:
            progress.log(f"Artwork: {label}: {exc}")
        progress.update(done, total, _with_skip(f"Artwork {label}", skipped), "artwork")
        progress.note_library("artwork")
    progress.log(
        f"Artwork: saved images for {saved}. Existing art was left in place.",
        phase="artwork",
        message=_with_skip("Artwork", skipped),
    )


def _upsert_local_row(album_id, artist_id, asset_type, path):
    width, height = _image_size(path)
    resolution = f"{width}x{height}" if width and height else None
    try:
        size = os.path.getsize(path)
    except OSError:
        size = None
    existing = db.fetchone(
        """
        SELECT id FROM artwork_pool
        WHERE source_provider = 'local' AND local_path = %s AND asset_type = %s
        """,
        (path, asset_type),
    )
    if existing:
        db.execute(
            """
            UPDATE artwork_pool
            SET resolution = %s, file_size_bytes = %s, album_id = %s, artist_id = %s
            WHERE id = %s
            """,
            (resolution, size, album_id, artist_id, existing["id"]),
        )
        return
    already = db.fetchone(
        """
        SELECT id FROM artwork_pool
        WHERE asset_type = %s AND is_selected = TRUE
          AND (
            (%s::uuid IS NOT NULL AND album_id = %s::uuid)
            OR (%s::uuid IS NOT NULL AND artist_id = %s::uuid)
          )
        """,
        (asset_type, album_id, album_id, artist_id, artist_id),
    )
    selected = asset_type in {"front", "artistthumb"} and already is None
    db.execute(
        """
        INSERT INTO artwork_pool (
            album_id, artist_id, asset_type, source_url, local_path, resolution,
            file_size_bytes, is_selected, source_provider
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'local')
        """,
        (album_id, artist_id, asset_type, path, path, resolution, size, selected),
    )


def _restore_selected_cover(album_id):
    row = db.fetchone(
        """
        SELECT local_path FROM artwork_pool
        WHERE album_id = %s AND asset_type = 'front' AND is_selected = TRUE
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (album_id,),
    )
    _apply_selected_dimensions("albums", album_id, row)


def _restore_selected_artist_art(artist_id):
    row = db.fetchone(
        """
        SELECT local_path FROM artwork_pool
        WHERE artist_id = %s AND album_id IS NULL AND asset_type = 'artistthumb' AND is_selected = TRUE
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (artist_id,),
    )
    _apply_selected_dimensions("artists", artist_id, row)


def _apply_selected_dimensions(table, item_id, row):
    if table not in {"albums", "artists"} or not row or not row.get("local_path"):
        return
    if not os.path.isfile(row["local_path"]):
        return
    width, height = _image_size(row["local_path"])
    if not width or not height:
        return
    db.execute(
        f"""
        UPDATE {table}
        SET has_artwork = TRUE, artwork_width = %s, artwork_height = %s
        WHERE id = %s
        """,
        (width, height, item_id),
    )


def _lyrics_type(path):
    stem = os.path.splitext(path)[0]
    if os.path.isfile(stem + ".lrc"):
        return "lrc"
    if os.path.isfile(stem + ".txt"):
        return "txt"
    return "none"


def _is_audio(name):
    return os.path.splitext(name)[1].lower() in AUDIO_EXTS


def _natural(name):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _clean_folder(name):
    text = re.sub(r"^\d{4}\s*[-–]\s*", "", name).strip()
    return clean_text(text, 255)


def _guess_edition(name):
    lowered = name.lower()
    for phrase in (
        "super deluxe",
        "deluxe",
        "anniversary",
        "remastered",
        "remaster",
        "expanded",
        "special edition",
        "mono",
        "stereo",
    ):
        if phrase in lowered:
            return phrase.title()
    return None


def _guess_type(name):
    lowered = name.lower()
    if re.search(r"\blive\b", lowered):
        return "live"
    if "compilation" in lowered or "greatest hits" in lowered:
        return "compilation"
    if re.search(r"\bep\b", lowered):
        return "ep"
    if re.search(r"\bsingle\b", lowered):
        return "single"
    return "album"


def _split_genres(value):
    names = []
    for part in re.split(r"[;/|,]", value or ""):
        text = genre_name(part)
        if text and text.lower() not in {item.lower() for item in names}:
            names.append(text)
    return names


def _majority(values):
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _parse_filename(filename):
    match = re.match(r"^(\d+)\s*[-_.]\s*(\d+)\s*[-_. ]\s*(.+)$", filename)
    if match:
        return int(match.group(1)), int(match.group(2)), match.group(3)
    match = re.match(r"^(\d+)\s*[-_. ]\s*(.+)$", filename)
    if match:
        return None, int(match.group(1)), match.group(2)
    return None, None, filename


def _mbid_taken(conn, table, column, mbid, current_id):
    if not opt_uuid_loose(mbid):
        return True
    row = conn.execute(
        f"SELECT id FROM {table} WHERE {column} = %s",
        (mbid,),
    ).fetchone()
    if not row:
        return False
    return str(row["id"]) != str(current_id)


def _artist_mbid_from_nfo(path):
    for name in ("artist.nfo", "folder.nfo"):
        found = _mbid_in_nfo_file(os.path.join(path, name))
        if found:
            return found
    return None


def _remember_artist_website(artist_id, artist_path, album_paths):
    """Fill a blank artist website from artist.nfo or from one of the album nfos."""
    if not artist_id:
        return
    row = db.fetchone("SELECT website FROM artists WHERE id = %s", (artist_id,))
    if not row or clean_text(row.get("website")):
        return
    found = ""
    for name in ("artist.nfo", "folder.nfo"):
        found = _website_in_nfo_file(os.path.join(artist_path, name))
        if found:
            break
    if not found:
        for album_path in album_paths or []:
            for name in ("album.nfo", "folder.nfo"):
                found = _website_in_nfo_file(os.path.join(album_path, name))
                if found:
                    break
            if found:
                break
    if not found:
        return
    db.execute(
        """
        UPDATE artists
        SET website = %s, updated_at = NOW()
        WHERE id = %s AND (website IS NULL OR btrim(website) = '')
        """,
        (found, artist_id),
    )


def _website_in_nfo_file(file_path):
    from resonance.nfo import website_from_text

    if not file_path or not os.path.isfile(file_path):
        return ""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    return website_from_text(text)


def _mbid_in_nfo_file(file_path):
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(
        r"<musicbrainzartistid>\s*([0-9a-fA-F-]{36})\s*</musicbrainzartistid>",
        text,
        re.IGNORECASE,
    )
    if match:
        return opt_uuid_loose(match.group(1))
    return None


def _artist_mbid_from_audio(file_path):
    raw, _info = tags.read_easy(file_path)
    return opt_uuid_loose(raw.get("musicbrainz_artistid"))


def _mbid_near(path):
    """Artist id from a nearby tag or album NFO when the artist folder has none."""
    for audio in _audio_files(path)[:1]:
        found = _artist_mbid_from_audio(audio)
        if found:
            return found
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError:
        return None
    looked = 0
    for name in names:
        if name.startswith(".") or looked >= 12:
            continue
        child = os.path.join(path, name)
        if not os.path.isdir(child):
            continue
        looked += 1
        for nfo_name in ("album.nfo", "folder.nfo", "artist.nfo"):
            found = _mbid_in_nfo_file(os.path.join(child, nfo_name))
            if found:
                return found
        audios = _audio_files(child)
        if audios:
            found = _artist_mbid_from_audio(audios[0])
            if found:
                return found
    return None

