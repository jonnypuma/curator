import logging
import os
import re

logger = logging.getLogger(__name__)

from psycopg.errors import UniqueViolation

from resonance import db
from resonance.errors import AppError
from resonance.fields import ascii_hyphen, title_with_type, year_from
from resonance.paths import inside, music_roots
from resonance.settings import load as load_settings

SKIP_LINE = "[RENAME SKIPPED] Preserving existing directory paths and file names unchanged."
SCOPES = {"none", "both", "folder", "file"}
TOKENS = {
    "albumartist",
    "albumartists",
    "albumartistsort",
    "artist",
    "artists",
    "artistsort",
    "album",
    "year",
    "title",
    "tracknumber",
    "discnumber",
    "totaldiscs",
    "multidisc",
    "format",
    "edition",
}
SIDECAR_NAMES = {
    "folder.jpg",
    "back.jpg",
    "discart.png",
    "spine.jpg",
    "clearlogo.png",
    "clearart.png",
    "banner.jpg",
    "fanart.jpg",
    "landscape.jpg",
    "booklet.pdf",
    "tray.jpg",
    "obi.jpg",
    "liner.jpg",
    "sticker.jpg",
    "poster.jpg",
    "matrix.jpg",
    "top.jpg",
    "bottom.jpg",
    "album.nfo",
    "artist.nfo",
    "folder.nfo",
    "thumb.jpg",
    "cover.jpg",
    "cdart.png",
}
ARTIST_SIDECARS = {
    "artist.nfo",
    "folder.nfo",
    "folder.jpg",
    "fanart.jpg",
    "banner.jpg",
    "clearlogo.png",
    "clearart.png",
    "landscape.jpg",
}
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
    ".ape",
    ".wv",
}
_NUM = re.compile(r"\$num\(\s*%([A-Za-z]+)%\s*,\s*(\d+)\s*\)")
_TOKEN = re.compile(r"%([A-Za-z]+)%")
_IF = re.compile(r"%if\s*\(", re.IGNORECASE)
_FUNC = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_ILLEGAL = re.compile(r'[\\:*?"<>|\x00-\x1f]')


class Move:
    def __init__(self, src, dest, kind, track_id=None):
        self.src = src
        self.dest = dest
        self.kind = kind
        self.track_id = track_id
        self.skip = ""
        self.original = src


def resolve_options(body, cfg):
    body = body or {}
    enabled = _flag(body["rename"]) if "rename" in body else bool(cfg.get("rename_enabled"))
    scope = body.get("rename_scope") or cfg.get("rename_scope") or "none"
    if scope not in SCOPES:
        scope = "none"
    folder = _text(body.get("rename_folder_pattern"), cfg.get("rename_folder_pattern"))
    file_pattern = _text(body.get("rename_file_pattern"), cfg.get("rename_file_pattern"))
    clean = _flag(body["rename_clean_chars"]) if "rename_clean_chars" in body else bool(cfg.get("rename_clean_chars", True))
    sidecars = _flag(body["rename_move_sidecars"]) if "rename_move_sidecars" in body else bool(cfg.get("rename_move_sidecars", True))
    prune = _flag(body["rename_prune_empty"]) if "rename_prune_empty" in body else bool(cfg.get("rename_prune_empty", False))
    quotes = _flag(body["rename_straight_quotes"]) if "rename_straight_quotes" in body else bool(cfg.get("rename_straight_quotes", False))
    junk = _flag(body["rename_strip_junk"]) if "rename_strip_junk" in body else bool(cfg.get("rename_strip_junk", False))
    transliterate = _flag(body["rename_transliterate"]) if "rename_transliterate" in body else bool(cfg.get("rename_transliterate", False))
    active = bool(enabled) and scope in {"both", "folder", "file"}
    return {
        "active": active,
        "scope": scope if active else "none",
        "folder_pattern": folder,
        "file_pattern": file_pattern,
        "clean": clean,
        "sidecars": sidecars,
        "prune": prune,
        "straight_quotes": quotes,
        "strip_junk": junk,
        "transliterate": transliterate,
    }


_SAMPLE = {
    "albumartist": "Radiohead",
    "albumartists": "Radiohead",
    "albumartistsort": "Radiohead",
    "artist": "Radiohead",
    "artists": "Radiohead",
    "artistsort": "Radiohead",
    "album": "In Rainbows",
    "year": "2007",
    "title": "15 Step",
    "tracknumber": "1",
    "discnumber": "1",
    "totaldiscs": "2",
    "multidisc": "1",
    "format": "FLAC",
    "edition": "",
    "releasegroup": "",
}


def example(folder, file):
    """One filled path for the pattern editor, using Radiohead — In Rainbows."""
    options = {}
    try:
        folder_out = _eval_text(folder or "", _SAMPLE, options).strip(" /")
        file_out = _eval_text(file or "", _SAMPLE, options).strip(" /")
    except AppError as exc:
        return {"error": str(exc), "folder": "", "file": "", "path": ""}
    return {"folder": folder_out, "file": file_out, "path": "/".join(part for part in (folder_out, file_out) if part)}


def preview(album_ids, body, cfg):
    from resonance.library import require_uuid

    ids = [str(require_uuid(item)) for item in album_ids or []]
    if not ids:
        raise AppError("Select at least one album")
    if len(ids) > 200:
        raise AppError("Preview at most 200 albums at a time")
    options = resolve_options(body, cfg)
    if options["active"]:
        validate_patterns(options["folder_pattern"], options["file_pattern"])
    rows = []
    notes = []
    for album_id in ids:
        album, artist, tracks = _load(album_id)
        label = f"{artist['name']} — {album['title']}"
        if not options["active"]:
            rows.extend(_unchanged(album, tracks))
            continue
        siblings = _siblings(artist["id"], album["id"])
        plan = plan_album(album, artist, tracks, options, siblings=siblings)
        if plan["error"]:
            notes.append(f"{label}: {plan['error']}")
            rows.extend(_unchanged(album, tracks, plan["error"]))
            continue
        rows.extend(plan["rows"])
        notes.extend(f"{label}: {item}" for item in plan["notes"])
    return {
        "enabled": options["active"],
        "scope": options["scope"],
        "pattern": f"{options['folder_pattern']}/{options['file_pattern']}",
        "rows": rows,
        "notes": notes,
    }


def commit(album_id, options):
    if not options.get("active"):
        return [SKIP_LINE]
    try:
        validate_patterns(options["folder_pattern"], options["file_pattern"])
    except AppError as exc:
        return [f"rename skipped: {exc}"]
    album, artist, tracks = _load(album_id)
    label = f"{artist['name']} — {album['title']}"
    lines = [f"[RENAME ACTIVE] Evaluated expressions for scope: {options['scope'].upper()}"]
    siblings = _siblings(artist["id"], album["id"])
    try:
        plan = plan_album(album, artist, tracks, options, siblings=siblings)
    except AppError as exc:
        lines.append(f"{label}: {exc}")
        return lines
    if plan["error"]:
        lines.append(f"{label}: {plan['error']}")
        return lines
    for move in plan["moves"]:
        if move.skip:
            lines.append(f"{label}: skipped: {move.skip} — {move.original}")
    actionable = [
        move
        for move in plan["moves"]
        if not move.skip and not _same_path(move.src, move.dest)
    ]
    if not actionable:
        lines.append(f"{label}: paths already match the pattern")
        return lines
    try:
        completed = perform(actionable, plan["root"])
    except OSError as exc:
        lines.append(f"{label}: rename failed: {exc}")
        return lines
    for move in actionable:
        if move.skip:
            lines.append(f"{label}: skipped: {move.skip} — {move.original}")
    try:
        warning = _persist(album, artist, completed, options, plan["root"], siblings)
    except UniqueViolation:
        warning = "files moved, and the library path is already used by another entry"
    if warning:
        lines.append(f"{label}: {warning}")
    for move in completed:
        kind = "sidecar" if move.kind != "audio" else "audio"
        lines.append(f"{label}: moved {kind}: {move.original} -> {move.dest}")
    if options.get("prune"):
        for path in prune_empty(album["path"], plan["root"], [move.dest for move in completed]):
            lines.append(f"{label}: removed empty folder {path}")
    if completed:
        fresh = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
        try:
            from resonance import artwork

            artwork.ensure_disc_arts(fresh or album)
        except Exception:
            logger.info("disc art after rename failed", exc_info=True)
        try:
            from resonance import webhooks

            webhooks.fire("rename")
        except Exception:
            logger.info("webhook after rename failed", exc_info=True)
    return lines


def validate_patterns(folder_pattern, file_pattern):
    for label, pattern in (("Folder pattern", folder_pattern), ("File pattern", file_pattern)):
        _reject_unsupported(pattern, label)
    if "\\" in (folder_pattern or "") or "\\" in (file_pattern or ""):
        raise AppError("Use / between folders in the pattern.")
    if "/" in (file_pattern or ""):
        raise AppError("The file pattern cannot contain a directory.")


def render(pattern, values, options=None):
    _reject_unsupported(pattern, "Pattern")
    return _eval_text(pattern, values, options or {}).strip()


def plan_album(album, artist, tracks, options, siblings=(), root=None):
    result = {"moves": [], "rows": [], "notes": [], "error": "", "root": ""}
    library_root = root or root_for(album.get("path") or "")
    if not library_root:
        result["error"] = "Album is outside the music library; paths were left unchanged"
        return result
    result["root"] = library_root
    if not library_writable(album.get("path") or library_root):
        result["error"] = "read-only library; paths were left unchanged"
        return result
    scope = options["scope"]
    moves = []
    try:
        discs = _disc_count(album, tracks)
        for track in tracks:
            values = _values(album, artist, track, discs)
            src = track["file_path"]
            if not src or not os.path.isfile(src):
                result["notes"].append(f"missing file {src}")
                continue
            if not inside(library_root, src):
                result["error"] = "A track is outside the music library; paths were left unchanged"
                return result
            ext = os.path.splitext(src)[1]
            if scope == "file":
                dest_dir = os.path.dirname(os.path.abspath(src))
                name = _file_name(options["file_pattern"], values, options["clean"], ext, options)
            else:
                dest_dir = _folder_dir(library_root, options["folder_pattern"], values, options["clean"], options)
                if scope == "folder":
                    name = os.path.basename(src)
                else:
                    name = _file_name(options["file_pattern"], values, options["clean"], ext, options)
            dest = os.path.join(dest_dir, name)
            _ensure_inside(library_root, dest)
            moves.append(Move(src, dest, "audio", track_id=track["id"]))
            if options.get("sidecars"):
                for extra in (".lrc", ".txt"):
                    side = os.path.splitext(src)[0] + extra
                    if not os.path.isfile(side):
                        continue
                    side_name = os.path.basename(side) if scope == "folder" else os.path.splitext(name)[0] + extra
                    side_dest = os.path.join(dest_dir, side_name)
                    _ensure_inside(library_root, side_dest)
                    moves.append(Move(side, side_dest, "sidecar"))
        if scope in {"folder", "both"} and options.get("sidecars"):
            sidecar_dir = _sidecar_dir(library_root, moves, options, album, artist)
            _collect_sidecars(album.get("path") or "", sidecar_dir, library_root, moves)
            new_artist = os.path.dirname(sidecar_dir)
            if os.path.realpath(new_artist) != os.path.realpath(library_root) and _artist_abandoned(
                artist.get("path") or "", siblings, sidecar_dir
            ):
                _collect_artist_sidecars(artist.get("path") or "", new_artist, library_root, moves)
    except AppError as exc:
        result["error"] = str(exc)
        return result
    _mark_collisions(moves)
    result["moves"] = moves
    result["rows"] = [_row(album, move) for move in moves]
    return result


def perform(moves, root):
    pending = [move for move in moves if not move.skip]
    staged = _stage_swaps(pending, root)
    completed = []
    try:
        for move in pending:
            if move.skip or _same_path(move.src, move.dest):
                continue
            parent = os.path.dirname(move.dest)
            os.makedirs(parent, exist_ok=True)
            _ensure_inside(root, move.dest)
            if os.stat(move.src).st_dev != os.stat(parent).st_dev:
                move.skip = "cross-device move is not used"
                continue
            os.replace(move.src, move.dest)
            try:
                from resonance import undo

                undo.snapshot_move(move.original, move.dest)
            except Exception:
                logger.exception("undo move snapshot failed")
            completed.append(move)
    except OSError:
        for move in reversed(completed):
            try:
                os.makedirs(os.path.dirname(move.original), exist_ok=True)
                if not os.path.exists(move.original):
                    os.replace(move.dest, move.original)
            except OSError:
                pass
        for move in staged:
            if os.path.exists(move.src) and not os.path.exists(move.original):
                try:
                    os.replace(move.src, move.original)
                except OSError:
                    pass
        raise
    for move in staged:
        if move in completed:
            continue
        if os.path.exists(move.src) and not os.path.exists(move.original):
            os.replace(move.src, move.original)
            move.src = move.original
    return completed


def prune_empty(old_path, root, destinations):
    if not old_path or not os.path.isdir(old_path):
        return []
    old = os.path.realpath(old_path)
    root_real = os.path.realpath(root)
    if old == root_real or not inside(root_real, old):
        return []
    protected = []
    for dest in destinations:
        if dest and os.path.exists(dest):
            protected.append(os.path.realpath(dest))
    removed = []
    for dirpath, _dirnames, _filenames in os.walk(old, topdown=False):
        real = os.path.realpath(dirpath)
        if real == root_real or not inside(root_real, real):
            continue
        if any(real == dest or inside(real, dest) for dest in protected):
            continue
        _clear_junk(real)
        if _contains_audio(real) or os.listdir(real):
            continue
        try:
            os.rmdir(real)
        except OSError:
            continue
        removed.append(real)
    return removed


def root_for(path):
    if not path:
        return ""
    real = os.path.realpath(path) if os.path.exists(path) else os.path.abspath(path)
    matches = []
    for root in music_roots():
        if inside(root, real) or os.path.realpath(root) == real:
            matches.append(os.path.realpath(root))
    if not matches:
        return ""
    return max(matches, key=len)


def library_writable(path):
    from resonance.paths import mount_writable

    return mount_writable(path)


def _load(album_id):
    album = db.fetchone("SELECT * FROM albums WHERE id = %s", (album_id,))
    if not album:
        raise AppError("Album not found", 404)
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (album["artist_id"],))
    if not artist:
        raise AppError("Artist not found", 404)
    tracks = db.fetchall(
        "SELECT * FROM tracks WHERE album_id = %s ORDER BY disc_number, track_number",
        (album_id,),
    )
    return album, artist, tracks


def _siblings(artist_id, album_id):
    rows = db.fetchall(
        "SELECT path FROM albums WHERE artist_id = %s AND id <> %s",
        (artist_id, album_id),
    )
    return [row["path"] for row in rows if row.get("path")]


def _disc_count(album, tracks):
    total = _positive(album.get("total_discs"), 1)
    for track in tracks or []:
        total = max(total, _positive(track.get("disc_number"), 1))
    return total


def _positive(value, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _values(album, artist, track, discs=None):
    tags = track.get("tags") or {}
    year = album.get("release_year") or track.get("year") or tags.get("year") or ""
    albumartist = _albumartist_value(album, artist, tags)
    artist_name = track.get("artist_name") or tags.get("artist") or artist.get("name") or ""
    count = discs if discs is not None else _disc_count(album, [track])
    return {
        "albumartist": ascii_hyphen(albumartist),
        "albumartists": ascii_hyphen(tags.get("albumartists") or albumartist),
        "albumartistsort": ascii_hyphen(tags.get("albumartistsort") or ""),
        "artist": ascii_hyphen(artist_name),
        "artists": ascii_hyphen(tags.get("artists") or artist_name),
        "artistsort": ascii_hyphen(tags.get("artistsort") or ""),
        "album": ascii_hyphen(title_with_type(
            album.get("title") or track.get("album_name") or "",
            album.get("type"),
            load_settings().get("title_suffix_types"),
        )),
        "year": str(year),
        "title": ascii_hyphen(track.get("title") or ""),
        "tracknumber": str(track.get("track_number") or ""),
        "discnumber": str(track.get("disc_number") or 1),
        "totaldiscs": str(count),
        "multidisc": "1" if count > 1 else "",
        "format": str(track.get("file_format") or "").lstrip(".").upper(),
        "edition": album.get("edition") or tags.get("edition") or "",
        "releasegroup": album.get("release_group") or "",
    }


def _albumartist_value(album, artist, tags):
    tagged = tags.get("albumartist") or ""
    if (album.get("type") or "") == "compilation" and tagged:
        return tagged
    return artist.get("name") or tagged or ""


def _file_name(pattern, values, clean, ext, options=None):
    rendered = render(pattern, values, options).strip()
    if "/" in rendered or "\\" in rendered:
        raise AppError("The file pattern cannot contain a directory.")
    stem = _segment(rendered, clean)
    if stem.lower().endswith(ext.lower()) and ext:
        stem = stem[: -len(ext)]
        stem = _segment(stem, clean)
    if not stem:
        raise AppError("The file pattern is empty.")
    return stem + ext


def _folder_dir(root, pattern, values, clean, options=None):
    rendered = render(pattern, values, options).strip()
    if not rendered:
        raise AppError("The folder pattern is empty.")
    if rendered.startswith("/") or rendered.endswith("/") or "//" in rendered:
        raise AppError("The folder pattern produced an empty path segment.")
    parts = []
    for part in rendered.split("/"):
        segment = _segment(part, clean)
        if not segment or segment in {".", ".."}:
            raise AppError("The folder pattern produced an empty path segment.")
        parts.append(segment)
    return _join_root(root, parts)


def _segment(text, clean):
    value = _ILLEGAL.sub("-", text) if clean else text.strip()
    value = value.strip().rstrip(".")
    return value


def _join_root(root, parts):
    current = os.path.realpath(root)
    for part in parts:
        if part in {".", ".."} or os.path.isabs(part) or "/" in part or "\\" in part:
            raise AppError("The folder pattern leaves the music library.")
        current = os.path.abspath(os.path.join(current, part))
    _ensure_inside(root, current)
    return current


def _ensure_inside(root, path):
    parent = path if os.path.isdir(path) else os.path.dirname(path)
    if os.path.realpath(root) == os.path.abspath(path):
        raise AppError("The folder pattern leaves the music library.")
    if not inside(root, parent) and not inside(root, path):
        raise AppError("The folder pattern leaves the music library.")


def _sidecar_dir(root, moves, options, album, artist):
    dirs = [os.path.dirname(move.dest) for move in moves if move.kind == "audio" and not move.skip]
    if not dirs:
        values = _values(album, artist, {"tags": {}, "file_format": "", "title": album.get("title") or ""}, _disc_count(album, []))
        return _folder_dir(root, options["folder_pattern"], values, options["clean"], options)
    return os.path.commonpath(dirs)


def _collect_sidecars(album_path, dest_dir, root, moves):
    if not album_path or not os.path.isdir(album_path):
        return
    known = {os.path.normcase(os.path.abspath(move.src)) for move in moves}
    for name in os.listdir(album_path):
        src = os.path.join(album_path, name)
        if os.path.normcase(os.path.abspath(src)) in known:
            continue
        if os.path.isfile(src) and _is_sidecar(name):
            dest = os.path.join(dest_dir, name)
            _ensure_inside(root, dest)
            moves.append(Move(src, dest, "sidecar"))
        elif os.path.isdir(src) and name.lower() == "extrafanart":
            dest = os.path.join(dest_dir, name)
            _ensure_inside(root, dest)
            moves.append(Move(src, dest, "sidecar"))


def _collect_artist_sidecars(artist_path, dest_dir, root, moves):
    if not artist_path or not os.path.isdir(artist_path) or not dest_dir:
        return
    if os.path.normcase(os.path.abspath(artist_path)) == os.path.normcase(os.path.abspath(dest_dir)):
        return
    known = {os.path.normcase(os.path.abspath(move.src)) for move in moves}
    for name in os.listdir(artist_path):
        if name not in ARTIST_SIDECARS and name.lower() != "extrafanart" and not _is_fanart_file(name):
            continue
        src = os.path.join(artist_path, name)
        if os.path.normcase(os.path.abspath(src)) in known:
            continue
        dest = os.path.join(dest_dir, name)
        _ensure_inside(root, dest)
        moves.append(Move(src, dest, "sidecar"))


def _artist_abandoned(artist_path, siblings, sidecar_dir):
    if not artist_path or not sidecar_dir:
        return False
    new_artist = os.path.dirname(sidecar_dir)
    if os.path.normcase(os.path.abspath(artist_path)) == os.path.normcase(os.path.abspath(new_artist)):
        return False
    for path in siblings:
        if not path:
            continue
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(artist_path)):
            return False
        if inside(artist_path, path):
            return False
    return True


def _is_fanart_file(name):
    return re.match(r"^fanart\d*\.(?:jpg|jpeg|png)$", name, re.IGNORECASE) is not None


def _is_booklet_file(name):
    return re.match(r"^booklet\d*\.(?:png|jpe?g|pdf)$", name, re.IGNORECASE) is not None


def _is_sidecar(name):
    lowered = name.lower()
    if lowered in SIDECAR_NAMES or _is_booklet_file(name):
        return True
    if re.match(r"^(?:discart|cdart)\d+\.(?:png|jpe?g)$", lowered):
        return True
    return lowered.endswith(".lrc") or lowered.endswith(".nfo")


def _mark_collisions(moves):
    groups = {}
    sources = set()
    for move in moves:
        if not os.path.exists(move.src):
            move.skip = "source file is missing"
            continue
        sources.add(os.path.normcase(os.path.realpath(move.src)))
        if _same_path(move.src, move.dest):
            move.skip = ""
            continue
        key = os.path.normcase(os.path.abspath(move.dest))
        groups.setdefault(key, []).append(move)
    for group in groups.values():
        if len(group) > 1:
            for move in group:
                move.skip = "two files resolve to the same destination"
    for move in moves:
        if move.skip or _same_path(move.src, move.dest):
            if _same_path(move.src, move.dest):
                move.skip = ""
            continue
        if os.path.exists(move.dest):
            dest_real = os.path.normcase(os.path.realpath(move.dest))
            src_real = os.path.normcase(os.path.realpath(move.src))
            if dest_real != src_real and dest_real not in sources:
                move.skip = "destination already exists"


def _stage_swaps(moves, root):
    sources = {}
    for move in moves:
        if os.path.exists(move.src):
            sources[os.path.normcase(os.path.realpath(move.src))] = move
    staged = []
    seen = set()
    for move in moves:
        if not os.path.exists(move.dest):
            continue
        dest_real = os.path.normcase(os.path.realpath(move.dest))
        src_real = os.path.normcase(os.path.realpath(move.src))
        other = sources.get(dest_real)
        if other is None or dest_real == src_real or id(other) in seen:
            continue
        seen.add(id(other))
        temp = other.src + ".resonance-swap"
        _ensure_inside(root, temp)
        os.replace(other.src, temp)
        other.src = temp
        staged.append(other)
    return staged


def _persist(album, artist, completed, options, root, siblings):
    for move in completed:
        if move.track_id:
            db.execute("UPDATE tracks SET file_path = %s WHERE id = %s", (move.dest, move.track_id))
        _retarget_artwork(album["id"], artist["id"], move.original, move.dest)
    if options.get("scope") == "file":
        return ""
    audio_dirs = [os.path.dirname(move.dest) for move in completed if move.kind == "audio"]
    if not audio_dirs:
        return ""
    new_album = os.path.commonpath(audio_dirs)
    if os.path.realpath(new_album) == os.path.realpath(root) or not inside(root, new_album):
        return ""
    clash = db.fetchone("SELECT id FROM albums WHERE path = %s AND id <> %s", (new_album, album["id"]))
    if clash:
        return "files moved, and the library path is already used by another entry"
    from resonance import undo

    undo.snapshot_path("album", album["id"], album.get("path"))
    db.execute("UPDATE albums SET path = %s, updated_at = NOW() WHERE id = %s", (new_album, album["id"]))
    new_artist = os.path.dirname(new_album)
    if os.path.realpath(new_artist) == os.path.realpath(root) or not inside(root, new_artist):
        return ""
    if not _artist_abandoned(artist.get("path") or "", siblings, new_album):
        return ""
    taken = db.fetchone("SELECT id FROM artists WHERE path = %s AND id <> %s", (new_artist, artist["id"]))
    if taken:
        return ""
    undo.snapshot_path("artist", artist["id"], artist.get("path"))
    db.execute("UPDATE artists SET path = %s, updated_at = NOW() WHERE id = %s", (new_artist, artist["id"]))
    return ""


def _retarget_artwork(album_id, artist_id, old, new):
    rows = db.fetchall(
        """
        SELECT id, local_path FROM artwork_pool
        WHERE local_path IS NOT NULL AND (album_id = %s OR artist_id = %s)
        """,
        (album_id, artist_id),
    )
    for row in rows:
        updated = _replace_prefix(row["local_path"], old, new)
        if updated and updated != row["local_path"]:
            from resonance import undo

            undo.snapshot_path("artwork", row["id"], row["local_path"])
            db.execute("UPDATE artwork_pool SET local_path = %s WHERE id = %s", (updated, row["id"]))


def _replace_prefix(path, old, new):
    path_norm = os.path.normpath(path)
    old_norm = os.path.normpath(old)
    if path_norm == old_norm:
        return os.path.normpath(new)
    prefix = old_norm + os.sep
    if path_norm.startswith(prefix):
        return os.path.normpath(os.path.join(new, path_norm[len(prefix) :]))
    return ""


def _clear_junk(directory):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name.lower() not in {".ds_store", "thumbs.db"}:
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                continue


def _contains_audio(directory):
    for _dirpath, _dirnames, files in os.walk(directory):
        for name in files:
            if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                return True
    return False


def _unchanged(album, tracks, note=""):
    rows = []
    for track in tracks:
        path = track.get("file_path") or ""
        rows.append(
            {
                "album": album.get("title") or "",
                "track": track.get("title") or "",
                "current": path,
                "destination": f"[UNCHANGED] {path}",
                "unchanged": True,
                "kind": "audio",
                "note": note,
            }
        )
    return rows


def _row(album, move):
    if move.skip:
        destination = f"[SKIPPED] {move.skip}"
        unchanged = True
    elif _same_path(move.src, move.dest):
        destination = f"[UNCHANGED] {move.original}"
        unchanged = True
    else:
        destination = move.dest
        unchanged = False
    return {
        "album": album.get("title") or "",
        "track": os.path.basename(move.original),
        "current": move.original,
        "destination": destination,
        "unchanged": unchanged,
        "kind": move.kind,
        "note": move.skip,
    }


def _same_path(left, right):
    if os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right)):
        return True
    try:
        return os.path.exists(left) and os.path.exists(right) and os.path.samefile(left, right)
    except OSError:
        return False


def _reject_unsupported(pattern, label):
    if not pattern:
        raise AppError(f"{label} is empty.")
    for match in _FUNC.finditer(pattern):
        if match.group(1).lower() not in {"num", "if", "decade"}:
            raise AppError(f"${match.group(1)} is not available yet.")


def _eval_text(text, values, options):
    out = []
    index = 0
    while index < len(text):
        if text.startswith("$if(", index) or text.lower().startswith("%if(", index):
            args, index = _parse_args(text, index + 3)
            if len(args) < 2:
                raise AppError("$if needs a condition and a value.")
            condition = _eval_text(args[0], values, options).strip()
            chosen = args[1] if condition else (args[2] if len(args) > 2 else "")
            out.append(_eval_text(chosen, values, options))
            continue
        if text.startswith("$num(", index):
            args, index = _parse_args(text, index + 4)
            out.append(_eval_num(args, values, options))
            continue
        if text.startswith("$decade(", index):
            args, index = _parse_args(text, index + 7)
            out.append(_eval_decade(args, values, options))
            continue
        token = _TOKEN.match(text, index)
        if token:
            out.append(_token_value(token.group(1), values, options))
            index = token.end()
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _parse_args(text, open_paren):
    if open_paren >= len(text) or text[open_paren] != "(":
        raise AppError("Expression is missing (.")
    args = []
    start = open_paren + 1
    depth = 1
    index = start
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                args.append(text[start:index])
                return args, index + 1
        elif char == "," and depth == 1:
            args.append(text[start:index])
            start = index + 1
        index += 1
    raise AppError("Expression is missing ).")


def _eval_num(args, values, options):
    if len(args) < 2:
        raise AppError("$num needs a value and a width.")
    rendered = _eval_text(args[0], values, options)
    try:
        width = int(str(_eval_text(args[1], values, options)).strip())
    except ValueError as exc:
        raise AppError("$num width must be a number.") from exc
    width = max(1, min(width, 6))
    digits = "".join(ch for ch in rendered if ch.isdigit()) or "0"
    return digits.zfill(width)


def _eval_decade(args, values, options):
    if not args:
        raise AppError("$decade needs a date.")
    rendered = _eval_text(args[0], values, options).strip()
    shorten = True
    if len(args) > 1:
        flag = _eval_text(args[1], values, options).strip().lower()
        shorten = flag not in {"0", "false", "no", "off"}
    year = year_from(rendered)
    if year is None:
        return ""
    start = year - (year % 10)
    if shorten and 1920 <= start <= 2000:
        return f"{start % 100:02d}s"
    return f"{start}s"


def _token_value(key, values, options):
    name = key.lower()
    if name not in TOKENS:
        raise AppError(f"Unknown token %{key}%.")
    text = str(values.get(name) or "").replace("/", "-").replace("\\", "-")
    if options.get("straight_quotes"):
        text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    if options.get("strip_junk"):
        text = _JUNK.sub("", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
    if options.get("transliterate") and text:
        from unidecode import unidecode

        text = unidecode(text)
    return text


_JUNK = re.compile(
    r"\((?:Official Music Video|Remastered(?: \d{4})?)\)|\[(?:FLAC[^\]]*|Bonus Track)\]",
    re.IGNORECASE,
)


def _flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value, fallback):
    if isinstance(value, str) and value.strip():
        return " ".join(value.splitlines()).strip()
    return fallback or ""
