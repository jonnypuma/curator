"""Find videos by audio or subtitle language, then set the MKV default track.

Search matches stored probe data. A file that has not been probed has no tracks to compare.
Save writes the container flag with mkvpropedit and only accepts MKV files.
"""
from __future__ import annotations

import os
import threading

from resonance.errors import AppError

PAGE = 1000
MODES = ("not_default", "is_default", "contains")

_lock = threading.Lock()
_state = {"status": "idle", "processed": 0, "total": 0, "message": "", "failed": []}


def languages():
    from curator.video.languages import _LANG_LABELS, language_label

    rows = [{"code": code, "label": language_label(code)} for code in _LANG_LABELS if code != "und"]
    rows.sort(key=lambda item: item["label"].lower())
    return rows


def scopes():
    from curator import folders

    found = []
    seen = set()
    for kind in ("movies", "tv"):
        for path in folders.mounted(kind):
            if path in seen:
                continue
            seen.add(path)
            found.append({"path": path, "label": path})
    return found


def subtitle_rank(track):
    """Full tracks first, then SDH or HI, then Forced."""
    flags = {str(flag).lower() for flag in (track.get("flags") or [])}
    if "forced" in flags:
        return 2
    if "sdh" in flags or "hi" in flags:
        return 1
    return 0


def preferred_index(tracks, lang, kind):
    """The track Save all would select for this language. None when the language is absent."""
    choices = [(index, track) for index, track in enumerate(tracks or []) if _same_lang(track, lang)]
    if not choices:
        return None
    if kind == "subtitle":
        choices.sort(key=lambda pair: (subtitle_rank(pair[1]), pair[0]))
    return choices[0][0]


def plan(audio, subs, lang, pick=None):
    """Indexes to write. A pick overrides the preferred track. An existing single default is left alone."""
    pick = pick or {}
    chosen = {}
    for kind, tracks in (("audio", audio or []), ("subtitle", subs or [])):
        if kind in pick and pick[kind] is not None:
            index = int(pick[kind])
        else:
            index = preferred_index(tracks, lang, kind)
        if index is None or index < 0 or index >= len(tracks):
            continue
        if _already(tracks, index):
            continue
        chosen[kind] = index
    return chosen


def matches(audio, subs, lang, mode):
    """True when this file belongs in the search mode for the language.

    Default is not means the file contains the language and neither its one default
    audio track nor its one default subtitle is that language. Extra tracks of the
    language do not count, and a subtitle with no default flag is not a default.
    """
    audio_has = _has(audio, lang)
    sub_has = _has(subs, lang)
    audio_default = _default_is(audio, lang, "audio")
    sub_default = _default_is(subs, lang, "subtitle")
    if mode == "contains":
        return audio_has or sub_has
    if mode == "is_default":
        return audio_default or sub_default
    if mode == "not_default":
        if audio_default or sub_default:
            return False
        return audio_has or sub_has
    return False


def search(mode, lang, filename="", scope="", offset=0):
    from curator.video.languages import normalize_lang
    from resonance import db
    from resonance.paths import display_path

    code = normalize_lang(lang)
    if not code or code == "und":
        raise AppError("Choose a language", 400)
    if mode not in MODES:
        raise AppError("Choose a match", 400)
    offset = max(0, int(offset or 0))
    rows = _rows(code, filename)
    matched = [
        row for row in rows
        if _in_scope(row.get("path") or "", scope, display_path)
        and matches(row.get("audio_tracks") or [], row.get("subtitle_tracks") or [], code, mode)
    ]
    matched.sort(key=lambda row: str(row.get("path") or "").lower())
    page = matched[offset:offset + PAGE]
    return {
        "lang": code,
        "mode": mode,
        "total": len(matched),
        "offset": offset,
        "limit": PAGE,
        "files": [_file(row, display_path) for row in page],
    }


def start_save(lang, ids, picks):
    from curator.video import files, scanner
    from curator.video.languages import normalize_lang

    code = normalize_lang(lang)
    if not code or code == "und":
        raise AppError("Choose a language", 400)
    if scanner.running() or files.running():
        raise AppError("Wait for the running scan or file job to finish", 409)
    chosen = [str(item) for item in (ids or []) if str(item).strip()][:PAGE]
    if not chosen:
        raise AppError("Nothing on this page to save", 400)
    with _lock:
        if _state["status"] == "running":
            raise AppError("A language save is already running", 409)
        _state.update({"status": "running", "processed": 0, "total": len(chosen), "message": "Setting default tracks", "failed": []})
    threading.Thread(target=_save, args=(code, chosen, picks or {}), name="language-defaults", daemon=True).start()
    return status()


def status():
    with _lock:
        return dict(_state)


def _save(lang, ids, picks):
    from curator.video import reprobe, tracks
    from resonance import db

    failed = []
    processed = 0
    try:
        for file_id in ids:
            row = db.fetchone("SELECT * FROM video_files WHERE id = %s", (file_id,))
            processed += 1
            if not row:
                failed.append("A file is no longer in the library")
                _touch(processed, failed)
                continue
            audio = row.get("audio_tracks") or []
            subs = row.get("subtitle_tracks") or []
            path = row.get("path") or ""
            if os.path.splitext(path)[1].lower() != ".mkv":
                _touch(processed, failed)
                continue
            try:
                chosen = plan(audio, subs, lang, picks.get(file_id) or picks.get(str(file_id)))
                if chosen.get("audio") is not None:
                    tracks.apply(path, "audio", chosen["audio"], audio)
                if chosen.get("subtitle") is not None:
                    tracks.apply(path, "subtitle", chosen["subtitle"], subs)
                if chosen:
                    _refresh(row)
            except Exception as exc:
                failed.append(f"{os.path.basename(path)}: {exc}")
            _touch(processed, failed)
        message = "Default tracks saved." if not failed else f"Saved with {len(failed)} problem{'s' if len(failed) != 1 else ''}."
    except Exception as exc:
        failed.append(str(exc))
        message = "The language save stopped."
    with _lock:
        _state.update({"status": "done", "processed": processed, "message": message, "failed": failed[:8]})


def _refresh(row):
    from curator.video import reprobe
    from resonance import db

    movie = db.fetchone("SELECT id FROM movies WHERE file_id = %s", (row["id"],))
    if movie:
        reprobe.refresh("movie", [movie["id"]])
        return
    episode = db.fetchone("SELECT id FROM tv_episodes WHERE file_id = %s ORDER BY season_number, episode_number", (row["id"],))
    if episode:
        reprobe.refresh("episode", [episode["id"]])


def _touch(processed, failed):
    with _lock:
        _state["processed"] = processed
        _state["failed"] = failed[:8]
        _state["message"] = f"Setting default tracks {processed} of {_state['total']}"


def _in_scope(path, scope, display_path):
    """True when the file sits in the chosen folder, including a second mount of that folder.

    A movie scanned under /movies can be shown as /EC2480/Media/Movies. The scope list offers both.
    """
    root = str(scope or "").strip().replace("\\", "/").rstrip("/")
    if not root:
        return True
    raw = str(path or "").replace("\\", "/").rstrip("/")
    if raw == root or raw.startswith(root + "/"):
        return True
    shown = str(display_path(path) or "").replace("\\", "/").rstrip("/")
    return shown == root or shown.startswith(root + "/")


def _rows(lang, filename):
    from resonance import db

    clauses = ["""(
        EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(f.audio_tracks, '[]'::jsonb)) track WHERE lower(track->>'lang') = %s)
        OR EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(f.subtitle_tracks, '[]'::jsonb)) track WHERE lower(track->>'lang') = %s)
    )"""]
    params = [lang, lang]
    needle = str(filename or "").strip()
    if needle:
        clauses.append("f.path ILIKE %s ESCAPE '\\'")
        params.append(f"%{_like(needle)}%")
    return db.fetchall(
        f"""
        SELECT DISTINCT ON (f.id)
               f.id, f.path, f.audio_tracks, f.subtitle_tracks,
               m.id AS movie_id, m.title AS movie_title,
               e.id AS episode_id, e.title AS episode_title, e.season_number, e.episode_number,
               s.title AS show_title
        FROM video_files f
        LEFT JOIN movies m ON m.file_id = f.id
        LEFT JOIN tv_episodes e ON e.file_id = f.id
        LEFT JOIN tv_shows s ON s.id = e.show_id
        WHERE {" AND ".join(clauses)}
        ORDER BY f.id
        """,
        tuple(params),
    )


def _file(row, display_path):
    path = row.get("path") or ""
    audio = row.get("audio_tracks") or []
    subs = row.get("subtitle_tracks") or []
    title, media, item_id = _title(row)
    return {
        "id": str(row["id"]),
        "path": display_path(path) or path,
        "name": os.path.basename(path),
        "mkv": os.path.splitext(path)[1].lower() == ".mkv",
        "title": title,
        "media": media,
        "item_id": item_id,
        "audio": _marked(audio, "audio", _audio),
        "subtitles": _marked(subs, "subtitle", _subtitle),
    }


def _title(row):
    if row.get("movie_id"):
        return row.get("movie_title") or "", "movie", str(row["movie_id"])
    if row.get("episode_id"):
        show = row.get("show_title") or ""
        season = int(row.get("season_number") or 0)
        episode = int(row.get("episode_number") or 0)
        name = row.get("episode_title") or ""
        label = " ".join(part for part in (show, f"S{season:02d}E{episode:02d}", name) if part)
        return label, "episode", str(row["episode_id"])
    return "", "", ""


def _audio(track, index):
    return {
        "index": index,
        "lang": track.get("lang") or "",
        "codec": track.get("codec") or "",
        "channels": track.get("channels") or "",
        "default": bool(track.get("default")),
        "title": track.get("title") or "",
    }


def _subtitle(track, index):
    flags = [str(flag).lower() for flag in (track.get("flags") or [])]
    return {
        "index": index,
        "lang": track.get("lang") or "",
        "flags": flags,
        "default": bool(track.get("default")),
        "title": track.get("title") or "",
    }


def _same_lang(track, lang):
    return str((track or {}).get("lang") or "").lower() == lang


def _has(tracks, lang):
    return any(_same_lang(track, lang) for track in tracks or [])


def _sole_default(tracks, kind):
    """The one default track. Audio with no flag plays the first track. Subtitles stay unset."""
    rows = list(tracks or [])
    flagged = [track for track in rows if track.get("default")]
    if flagged:
        return flagged[0]
    if kind == "audio" and rows:
        return rows[0]
    return None


def _marked(tracks, kind, build):
    """One default badge per audio and per subtitle, even when the probe flagged several."""
    chosen = _sole_default(tracks, kind)
    marked = []
    for index, track in enumerate(tracks or []):
        item = build(track, index)
        item["default"] = chosen is not None and track is chosen
        marked.append(item)
    return marked


def _default_is(tracks, lang, kind="audio"):
    """True when the one default track of this kind is the language."""
    return _same_lang(_sole_default(tracks, kind), lang)


def _already(tracks, index):
    if not tracks[index].get("default"):
        return False
    return sum(1 for track in tracks if track.get("default")) == 1


def _like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
