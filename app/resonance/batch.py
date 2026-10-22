import copy
import logging
import threading

from resonance import artwork, db, library, lyrics, match, rename
from resonance.errors import AppError
from resonance.settings import load as load_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_STEPS = ("tags", "nfo", "art", "lyrics", "processed")


def start(album_ids, options):
    from resonance.settings import vlog

    ids = []
    for item in album_ids or []:
        ids.append(str(library.require_uuid(item)))
    if not ids:
        raise AppError("Select at least one album")
    chosen = {step for step in _STEPS if options.get(step)}
    rename_on = bool(options.get("rename"))
    gain_on = bool(options.get("replaygain"))
    rename_scope = options.get("rename_scope") or "both"
    if rename_scope not in {"both", "folder", "file"}:
        rename_scope = "both"
    if not chosen and not rename_on and not gain_on:
        raise AppError("Choose at least one batch action")
    vlog(logger, "batch started for %s albums: %s", len(ids), ", ".join(sorted(chosen)) or "rename/replaygain")
    if not _lock.acquire(blocking=False):
        return current_job(), False
    try:
        row = db.fetchone(
            """
            INSERT INTO batch_jobs (status, message, processed, total, log, started_at)
            VALUES ('running', 'Starting batch', 0, %s, '', NOW())
            RETURNING *
            """,
            (len(ids),),
        )
    except Exception:
        _lock.release()
        raise

    def run():
        from resonance import undo

        lines = []
        tokens = undo.bind(row["id"])
        succeeded = False
        try:
            if not rename_on:
                lines.append(rename.SKIP_LINE)
            for index, album_id in enumerate(ids, start=1):
                _step(row["id"], index - 1, len(ids), lines, f"Album {index} of {len(ids)}")
                try:
                    _commit(album_id, chosen, lines, rename_on, rename_scope, gain_on)
                except Exception as exc:
                    logger.exception("batch album failed")
                    lines.append(f"Failed: {exc}")
                    _step(row["id"], index, len(ids), lines, str(exc))
                    continue
                _step(row["id"], index, len(ids), lines, f"Finished {index} of {len(ids)}")
            db.execute(
                """
                UPDATE batch_jobs
                SET status = 'completed', message = %s, processed = %s, finished_at = NOW(), log = %s
                WHERE id = %s
                """,
                (f"Updated {len(ids)} albums", len(ids), "\n".join(lines[-200:]), row["id"]),
            )
            succeeded = True
            _note_work(chosen, len(ids))
        except Exception as exc:
            logger.exception("batch failed")
            lines.append(str(exc))
            db.execute(
                """
                UPDATE batch_jobs
                SET status = 'failed', message = %s, finished_at = NOW(), log = %s
                WHERE id = %s
                """,
                (str(exc), "\n".join(lines[-200:]), row["id"]),
            )
        finally:
            undo.reset(tokens)
            _lock.release()
            if succeeded:
                try:
                    from resonance import webhooks

                    webhooks.fire("batch")
                except Exception:
                    logger.info("webhook after batch failed", exc_info=True)

    threading.Thread(target=run, name="library-batch", daemon=True).start()
    return row, True


def current_job():
    row = db.fetchone(
        """
        SELECT * FROM batch_jobs
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
        """
    )
    if not row:
        return {"status": "idle", "message": "Idle", "processed": 0, "total": 0, "log": ""}
    return row


def _note_work(chosen, count):
    labels = {"tags": "tags", "art": "artwork", "lyrics": "lyrics"}
    for step, kind in labels.items():
        if step not in chosen:
            continue
        db.execute(
            """
            INSERT INTO work_jobs (kind, status, message, processed, total, log, started_at, finished_at)
            VALUES (%s, 'completed', %s, %s, %s, '', NOW(), NOW())
            """,
            (kind, f"{kind} {count}/{count}", count, count),
        )


def _commit(album_id, steps, lines, rename_on=False, rename_scope="both", gain_on=False):
    """Find metadata, artwork, lyrics, album.nfo, then ReplayGain, rename, and mark processed."""
    album, artist, _tracks = match._context(album_id)
    label = f"{artist['name']} — {album['title']}"
    active = set(steps)
    if "tags" in active:
        proposal, note = _proposal(album_id)
        lines.append(f"{label}: {note}")
        if proposal:
            detail = match.apply(album_id, proposal, steps=["tags"], notify=False)
            after = detail["album"]["title"]
            lines.append(f"{label}: {album['title']} → {after}")
            for warning in detail.get("warnings") or []:
                lines.append(f"{label}: {warning}")
    if "art" in active:
        _download_missing_art(album_id, label, lines)
    if "lyrics" in active:
        result = lyrics.fetch_album(album_id)
        lines.append(
            f"{label}: lyrics written {result['written']}, missing {result['missing']}"
        )
    if "nfo" in active:
        _write_album_nfo(album_id, label, lines)
    if gain_on:
        from resonance import gain

        lines.extend(gain.album_lines(album_id))
    library.refresh_match_tier(album_id)
    _rename_album(album_id, rename_on, rename_scope, lines)
    if "processed" in active:
        library.mark("album", album_id, "processed")
        library.mark("artist", artist["id"], "processed")
        lines.append(f"{label}: marked processed")


def _rename_album(album_id, rename_on, rename_scope, lines):
    if not rename_on:
        return
    options = rename.resolve_options(
        {"rename": True, "rename_scope": rename_scope},
        load_settings(),
    )
    lines.extend(rename.commit(album_id, options))


def _write_album_nfo(album_id, label, lines):
    from resonance import nfo

    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        lines.append(f"Failed — {label} — album was not found")
        return
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    payload = nfo.album_context(album, artist)
    _cfg = load_settings()
    nfo.write_album(album["path"], _cfg["nfo_profile"], payload, tracks, _cfg["nfo_dialect"], _cfg["nfo_backup"])
    db.execute(
        "UPDATE albums SET has_nfo = TRUE, nfo_digest = %s, updated_at = NOW() WHERE id = %s",
        (nfo.album_digest(payload, tracks), album_id),
    )
    lines.append(f"{label}: wrote album.nfo")


def _download_missing_art(album_id, label, lines):
    try:
        result = artwork.deploy_missing(album_id, scope="album")
    except Exception as exc:
        logger.exception("batch artwork download failed")
        lines.append(f"Failed — {label} — {exc}")
        return
    deployed = result.get("deployed") or []
    warnings = result.get("warnings") or []
    missing = [item for item in (result.get("missing") or []) if item not in deployed]
    if deployed and missing:
        lines.append(f"Saved — {label} — {', '.join(deployed)}. No artwork for {', '.join(missing)}")
    elif deployed and warnings:
        lines.append(f"Saved — {label} — {', '.join(deployed)}. {warnings[0]}")
    elif deployed:
        lines.append(f"Saved — {label} — {', '.join(deployed)}")
    elif warnings:
        lines.append(f"Failed — {label} — {warnings[0]}")
    elif missing:
        lines.append(f"No artwork — {label}")
    else:
        lines.append(f"Already complete — {label}")


def _proposal(album_id):
    album = db.fetchone("SELECT musicbrainz_release_id, title FROM albums WHERE id = %s", (album_id,))
    release_id = album["musicbrainz_release_id"] if album else None
    note = "using the linked MusicBrainz release"
    if not release_id:
        found = match.search(album_id)
        candidates = found.get("candidates") or []
        if not candidates:
            return None, "no MusicBrainz release found; tags were not written"
        release_id = candidates[0]["release_id"]
        note = f"using top candidate {candidates[0].get('title') or release_id}"
    built = match.build_proposal(album_id, release_id)
    return built["proposal"], note


def _step(job_id, processed, total, lines, message):
    db.execute(
        """
        UPDATE batch_jobs
        SET processed = %s, total = %s, message = %s, log = %s
        WHERE id = %s
        """,
        (processed, total, message, "\n".join(lines[-200:]), job_id),
    )


_BRIEF_KEYS = (
    "release_id",
    "title",
    "artist",
    "year",
    "country",
    "edition",
    "type",
    "type_label",
    "track_count",
    "format",
    "label",
    "score",
    "match_percent",
    "locked",
    "disc_match",
    "acoustid_match",
)
_lookup_lock = threading.Lock()
_lookup = {
    "status": "idle",
    "mode": "",
    "message": "Idle",
    "processed": 0,
    "total": 0,
    "applied": 0,
    "log": "",
    "items": [],
}


def brief_candidates(candidates, limit=12):
    rows = []
    for item in candidates or []:
        release_id = str((item or {}).get("release_id") or "")
        if not release_id:
            continue
        brief = {key: item.get(key) for key in _BRIEF_KEYS}
        brief["release_id"] = release_id
        rows.append(brief)
        if len(rows) >= limit:
            break
    return rows


def closest_release(candidates):
    for item in candidates or []:
        release_id = str((item or {}).get("release_id") or "")
        if release_id:
            return release_id
    return ""


def lookup_state():
    with _lookup_lock:
        return copy.deepcopy(_lookup)


def lookup_job():
    state = lookup_state()
    return {
        "status": state.get("status") or "idle",
        "message": state.get("message") or "Idle",
        "processed": state.get("processed") or 0,
        "total": state.get("total") or 0,
        "log": state.get("log") or "",
    }


def start_lookup(album_ids, mode):
    from resonance.settings import vlog

    if mode not in {"review", "auto"}:
        raise AppError("Choose review or automatic matching")
    ids = [str(library.require_uuid(item)) for item in album_ids or []]
    if not ids:
        raise AppError("Select at least one album")
    vlog(logger, "metadata lookup started for %s albums (%s)", len(ids), mode)
    if not _lock.acquire(blocking=False):
        return lookup_state(), False
    handed = False
    try:
        items = []
        for album_id in ids:
            label = _album_label(album_id)
            if label:
                items.append(label)
            else:
                items.append(_empty_item(album_id, "failed", "Album is not in the library"))
        _replace_lookup(
            {
                "status": "running",
                "mode": mode,
                "message": "Looking up releases",
                "processed": 0,
                "total": len(ids),
                "applied": 0,
                "log": "",
                "items": items,
            }
        )
        handed = True
    finally:
        if not handed:
            _lock.release()

    def run():
        lines = []
        try:
            for index, album_id in enumerate(ids, start=1):
                _patch_item(album_id, status="searching", note="Looking up MusicBrainz")
                _touch_lookup(index - 1, len(ids), lines, f"Looking up {index} of {len(ids)}", None)
                try:
                    found = match.search(album_id)
                    briefs = brief_candidates((found or {}).get("candidates"))
                except Exception as exc:
                    logger.exception("lookup failed")
                    lines.append(f"Failed — {_item_label(album_id)} — {exc}")
                    _patch_item(album_id, status="failed", note=str(exc), candidates=[], chosen="")
                    _touch_lookup(index, len(ids), lines, f"Finished {index} of {len(ids)}", None)
                    continue
                chosen = closest_release(briefs)
                if not chosen:
                    lines.append(f"No release — {_item_label(album_id)}")
                    _patch_item(
                        album_id,
                        status="none",
                        note="No MusicBrainz release found",
                        candidates=[],
                        chosen="",
                    )
                    _touch_lookup(index, len(ids), lines, f"Finished {index} of {len(ids)}", None)
                    continue
                title = briefs[0].get("title") or chosen
                note = f"Closest match: {title}"
                _patch_item(album_id, status="suggested", note=note, candidates=briefs, chosen=chosen)
                lines.append(f"Found — {_item_label(album_id)} — {title}")
                _touch_lookup(index, len(ids), lines, f"Finished {index} of {len(ids)}", None)
            _set_lookup(
                status="review",
                message="Choose a release. Files stay as they are until you apply.",
                processed=len(ids),
                applied=0,
                log="\n".join(lines[-200:]),
            )
        except Exception as exc:
            logger.exception("lookup failed")
            lines.append(str(exc))
            _set_lookup(status="failed", message=str(exc), log="\n".join(lines[-200:]))
        finally:
            _lock.release()

    threading.Thread(target=run, name="library-lookup", daemon=True).start()
    return lookup_state(), True


def _lookup_write_steps(steps):
    if steps is None:
        return ["tags", "nfo", "art", "lyrics", "processed"]
    if not isinstance(steps, list):
        raise AppError("Choose what to write")
    names = {"tags": "tags", "nfo": "nfo", "art": "art", "artwork": "art", "lyrics": "lyrics"}
    chosen = []
    for step in steps:
        key = names.get(str(step or "").strip().lower())
        if not key:
            raise AppError("Unknown write step")
        if key not in chosen:
            chosen.append(key)
    if not chosen:
        raise AppError("Turn on Tags, .nfo, Artwork, or Lyrics")
    if "tags" in chosen:
        chosen.append("processed")
    return chosen


def apply_lookup(choices, steps=None):
    if not isinstance(choices, list):
        raise AppError("Expected a list of albums")
    active = _lookup_write_steps(steps)
    parsed = []
    for item in choices:
        if not isinstance(item, dict):
            continue
        album_id = str(library.require_uuid(item.get("album_id")))
        raw_release = item.get("release_id") or ""
        release_id = str(library.require_uuid(raw_release)) if raw_release else ""
        parsed.append((album_id, release_id))
    if not _lock.acquire(blocking=False):
        return lookup_state(), False
    handed = False
    job = None
    plan = []
    try:
        state = lookup_state()
        if state["status"] != "review":
            raise AppError("Review the suggestions before applying them")
        known = {row["album_id"]: row for row in state["items"]}
        for album_id, release_id in parsed:
            row = known.get(album_id)
            if not row:
                continue
            if release_id:
                allowed = {str(candidate.get("release_id")) for candidate in row.get("candidates") or []}
                if release_id not in allowed:
                    raise AppError("Pick a release from the suggestions for that album")
            plan.append((album_id, release_id))
        if not plan:
            raise AppError("Choose at least one album")
        if not any(release_id for _, release_id in plan):
            for album_id, _release_id in plan:
                _patch_item(album_id, status="skipped", note="Skipped")
            _set_lookup(
                status="completed",
                message="Nothing applied",
                processed=len(plan),
                total=len(plan),
                applied=0,
            )
            return lookup_state(), True
        job = _insert_job(len(plan), "Applying approved releases")
        _set_lookup(
            status="applying",
            message="Writing approved releases",
            processed=0,
            total=len(plan),
            applied=0,
            log="Writing approved releases",
        )
        handed = True
    finally:
        if not handed:
            _lock.release()

    def run():
        from resonance import undo

        lines = []
        tokens = undo.bind(job["id"])
        applied = 0
        try:
            for index, (album_id, release_id) in enumerate(plan, start=1):
                if not release_id:
                    _patch_item(album_id, status="skipped", note="Skipped")
                    lines.append(f"{_item_label(album_id)}: skipped")
                    _touch_lookup(index, len(plan), lines, f"Finished {index} of {len(plan)}", job)
                    continue
                if _apply_release(album_id, release_id, lines, job, index - 1, len(plan), active):
                    applied += 1
                _touch_lookup(index, len(plan), lines, f"Finished {index} of {len(plan)}", job)
            _finish_job(job, f"Updated {applied} albums", len(plan), lines)
            _set_lookup(
                status="completed",
                message=f"Updated {applied} albums",
                processed=len(plan),
                applied=applied,
                log="\n".join(lines[-200:]),
            )
            if applied:
                _fire_batch()
        except Exception as exc:
            logger.exception("approved lookup failed")
            lines.append(str(exc))
            _fail_job(job, exc, lines)
            _set_lookup(status="failed", message=str(exc), log="\n".join(lines[-200:]))
        finally:
            undo.reset(tokens)
            _lock.release()

    threading.Thread(target=run, name="library-lookup-apply", daemon=True).start()
    return lookup_state(), True


def _album_label(album_id):
    row = db.fetchone(
        """
        SELECT al.id, al.title, al.path, al.release_year, al.edition, al.country,
               al.catalog, al.label, al.type::text AS release_type, al.total_tracks,
               ar.name AS artist_name,
               (SELECT COUNT(*)::int FROM tracks t WHERE t.album_id = al.id) AS track_count
        FROM albums al
        JOIN artists ar ON ar.id = al.artist_id
        WHERE al.id = %s
        """,
        (album_id,),
    )
    if not row:
        return None
    counted = int(row.get("track_count") or 0)
    stored = int(row.get("total_tracks") or 0)
    country = str(row.get("country") or "").strip()
    if not country:
        country = library._tag_countries([row["id"]]).get(str(row["id"]), "") or ""
    return {
        "album_id": str(row["id"]),
        "artist": row.get("artist_name") or "",
        "title": row.get("title") or "",
        "year": row.get("release_year"),
        "edition": row.get("edition") or "",
        "country": country,
        "catalog": row.get("catalog") or "",
        "label": row.get("label") or "",
        "type": row.get("release_type") or "",
        "track_count": counted or stored,
        "folder": _folder_name(row.get("path")),
        "path": str(row.get("path") or ""),
        "status": "pending",
        "note": "",
        "chosen": "",
        "candidates": [],
    }


def _empty_item(album_id, status, note):
    return {
        "album_id": str(album_id),
        "artist": "",
        "title": "Missing album",
        "year": None,
        "edition": "",
        "country": "",
        "catalog": "",
        "label": "",
        "type": "",
        "track_count": 0,
        "folder": "",
        "status": status,
        "note": note,
        "chosen": "",
        "candidates": [],
    }


def _folder_name(path):
    text = str(path or "").rstrip("/\\")
    if not text:
        return ""
    return text.replace("\\", "/").rsplit("/", 1)[-1]


def _replace_lookup(payload):
    with _lookup_lock:
        _lookup.clear()
        _lookup.update(payload)


def _set_lookup(**fields):
    with _lookup_lock:
        _lookup.update(fields)


def _patch_item(album_id, **fields):
    with _lookup_lock:
        for item in _lookup["items"]:
            if item["album_id"] == str(album_id):
                item.update(fields)
                return


def _item_label(album_id):
    state = lookup_state()
    for item in state["items"]:
        if item["album_id"] == str(album_id):
            artist = item.get("artist") or ""
            title = item.get("title") or ""
            if artist or title:
                return f"{artist} — {title}".strip(" —")
    return str(album_id)


def _apply_release(album_id, release_id, lines, job=None, processed=0, total=0, steps=None):
    active = list(steps or ("tags", "nfo", "art", "lyrics", "processed"))
    label = _item_label(album_id)

    def report(text):
        lines.append(f"{label}: {text}")
        _patch_item(album_id, status="applying", note=text)
        _touch_lookup(processed, total, lines, f"{label}: {text}", job)

    report("loading the MusicBrainz release")
    try:
        built = match.build_proposal(album_id, release_id)
        proposal = built["proposal"]
        if "tags" not in active and any(step in active for step in ("nfo", "art")):
            album, artist, _tracks = match._context(album_id)
            held = []
            match._update_release_rows(album, artist, proposal, held, mark_processed=False)
            for item in held:
                report(item)
        detail = match.apply(album_id, proposal, steps=active, notify=False, on_progress=report)
    except Exception as exc:
        logger.exception("apply lookup failed")
        lines.append(f"Failed — {label} — {exc}")
        _patch_item(album_id, status="failed", note=str(exc))
        _touch_lookup(processed, total, lines, f"{label}: {exc}", job)
        return False
    warnings = [str(item) for item in (detail.get("warnings") or []) if item]
    labels = {"tags": "tags", "nfo": "NFO", "art": "artwork", "lyrics": "lyrics"}
    written = [labels[step] for step in active if step in labels]
    note = "; ".join(warnings[:3]) if warnings else f"Wrote {', '.join(written)}"
    lines.append(f"{label}: {note}")
    _patch_item(album_id, status="applied", note=note)
    _touch_lookup(processed, total, lines, f"{label}: {note}", job)
    return True


def _insert_job(total, message):
    return db.fetchone(
        """
        INSERT INTO batch_jobs (status, message, processed, total, log, started_at)
        VALUES ('running', %s, 0, %s, '', NOW())
        RETURNING *
        """,
        (message, total),
    )


def _touch_lookup(processed, total, lines, message, job):
    text = "\n".join(lines[-200:])
    _set_lookup(processed=processed, total=total, message=message, log=text)
    if not job:
        return
    db.execute(
        """
        UPDATE batch_jobs
        SET processed = %s, total = %s, message = %s, log = %s
        WHERE id = %s
        """,
        (processed, total, message, text, job["id"]),
    )


def _finish_job(job, message, total, lines):
    if not job:
        return
    db.execute(
        """
        UPDATE batch_jobs
        SET status = 'completed', message = %s, processed = %s, finished_at = NOW(), log = %s
        WHERE id = %s
        """,
        (message, total, "\n".join(lines[-200:]), job["id"]),
    )


def _fail_job(job, exc, lines):
    if not job:
        return
    db.execute(
        """
        UPDATE batch_jobs
        SET status = 'failed', message = %s, finished_at = NOW(), log = %s
        WHERE id = %s
        """,
        (str(exc), "\n".join(lines[-200:]), job["id"]),
    )


def _fire_batch():
    try:
        from resonance import webhooks

        webhooks.fire("batch")
    except Exception:
        logger.info("webhook after lookup failed", exc_info=True)
