"""Rename movie and TV files and folders from the Jinja2 patterns, together with their sidecars.

A plan lists the moves first so the UI can show them. Applying a plan renames on disk (rolling back
the moves already made when one fails), then points the stored paths at the new names.
"""
from __future__ import annotations

import os

from curator.video import delete, naming, renamer, store, writes
from resonance.errors import AppError


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _move(source, target, is_dir=False):
    return {"from": source, "to": target, "dir": is_dir}


def _title(row):
    return f"{row['title']} ({row['year']})" if row.get("year") else row.get("title") or ""


def _companions(folder, old_stem, new_stem, target_folder, protected):
    """stem.nfo, stem-poster.jpg, stem.en.srt next to a video, renamed to the new stem."""
    moves = []
    for path in delete.sidecars(folder, [old_stem], protected):
        name = os.path.basename(path)
        if naming.is_video(name):
            continue
        moves.append(_move(path, os.path.join(target_folder, new_stem + name[len(old_stem):])))
    return moves


def _check(plan):
    """Refuse a plan whose targets collide with each other or with files already there."""
    sources = {_norm(move["from"]) for move in plan["moves"]}
    seen = set()
    for move in plan["moves"]:
        target = _norm(move["to"])
        if target in seen:
            raise AppError(f"Two files would be named {os.path.basename(move['to'])}")
        seen.add(target)
        if os.path.exists(move["to"]) and target not in sources and not _same(move["from"], move["to"]):
            raise AppError(f"{move['to']} already exists")


def _same(source, target):
    try:
        return os.path.samefile(source, target)
    except OSError:
        return False


def _finish(plan):
    plan["moves"] = [move for move in plan["moves"] if move["from"] != move["to"]]
    try:
        _check(plan)
    except AppError as exc:
        plan["error"] = str(exc)
    return plan


def plan_movie(movie_id, cfg):
    row = store.movie_row(movie_id)
    if not row:
        return None
    plan = {"kind": "movie", "id": str(movie_id), "title": _title(row), "moves": [], "db_only": [], "error": None,
            "folders": [row["folder"]]}
    templates = cfg["rename"]
    folder = row["folder"]
    try:
        own = row["path"] == folder
        parts = list(row.get("parts") or [])
        if parts and not row.get("disc_format"):
            for part in parts:
                delete._guard(part, row["root"], "movies")
            names = []
            for index, part in enumerate(parts):
                old_stem, ext = os.path.splitext(os.path.basename(part))
                context = renamer.movie_context(row, row.get("file"), renamer.part_label(index, len(parts)), old_stem)
                new_stem = renamer.render(templates["movie_file"], context)
                if not new_stem:
                    raise AppError("The movie file pattern gave an empty name")
                names.append((part, old_stem, new_stem))
                plan["moves"].append(_move(part, os.path.join(folder, new_stem + ext.lower())))
            neighbours = delete._indexed_videos(folder, [movie_id], "movies")
            for part, old_stem, new_stem in names:
                others = [other for other in parts if other != part] + neighbours
                plan["moves"] += _companions(folder, old_stem, new_stem, folder, others)
            own_stems = [old_stem for _part, old_stem, _new in names]
            heads = [stem for stem in delete.stems_for(parts) if stem not in own_stems]
            if heads:
                new_head = renamer.render(templates["movie_file"], renamer.movie_context(row, row.get("file")))
                for old_head in heads:
                    plan["moves"] += _companions(folder, old_head, new_head, folder, parts + neighbours)
        if own:
            delete._guard(folder, row["root"], "movies")
            name = renamer.render(templates["movie_folder"], renamer.movie_context(row, row.get("file")))
            if not name:
                raise AppError("The movie folder pattern gave an empty name")
            target = os.path.join(os.path.dirname(folder), name)
            if target != folder:
                plan["moves"].append(_move(folder, target, True))
                plan["folders"] = [target]
    except AppError as exc:
        plan["error"] = str(exc)
        return plan
    return _finish(plan)


def plan_show(show_id, cfg, episode_ids=None, rename_folder=True):
    show, seasons, episodes = store.show_rows(show_id)
    if not show:
        return None
    plan = {"kind": "show", "id": str(show_id), "title": _title(show), "moves": [], "db_only": [], "error": None,
            "folders": [show["path"]]}
    templates = cfg["rename"]
    wanted = {str(item) for item in episode_ids} if episode_ids else None
    by_path = {}
    for episode in episodes:
        if wanted is None or str(episode["id"]) in wanted:
            by_path.setdefault(episode["path"], [])
    for episode in episodes:
        if episode["path"] in by_path:
            by_path[episode["path"]].append(episode)
    show_path = show["path"]
    try:
        all_files = sorted({row["path"] for row in episodes})
        new_dirs = {}
        for path, rows in sorted(by_path.items()):
            delete._guard(path, show["root"], "tv")
            file = store.file_row(rows[0].get("file_id"))
            context = renamer.episode_context(show, rows, file)
            season_dir = renamer.render(templates["season_folder"], context)
            target_folder = os.path.join(show_path, season_dir) if season_dir else show_path
            old_stem, ext = os.path.splitext(os.path.basename(path))
            new_stem = renamer.render(templates["episode_file"], context)
            if not new_stem:
                raise AppError("The episode file pattern gave an empty name")
            plan["moves"].append(_move(path, os.path.join(target_folder, new_stem + ext.lower())))
            others = [other for other in all_files if other != path and os.path.dirname(other) == os.path.dirname(path)]
            plan["moves"] += _companions(os.path.dirname(path), old_stem, new_stem, target_folder, others)
            new_dirs[rows[0]["season_number"]] = target_folder
        for season in seasons:
            target = new_dirs.get(season["season_number"])
            whole = all(row["path"] in by_path for row in episodes if row["season_number"] == season["season_number"])
            if target and whole and season.get("path") and season["path"] != target:
                plan["db_only"].append((season["path"], target, False))
        if rename_folder:
            delete._guard(show_path, show["root"], "tv")
            name = renamer.render(templates["show_folder"], renamer.show_context(show))
            if not name:
                raise AppError("The show folder pattern gave an empty name")
            target = os.path.join(os.path.dirname(show_path), name)
            if target != show_path:
                plan["moves"].append(_move(show_path, target, True))
                plan["folders"] = [target]
    except AppError as exc:
        plan["error"] = str(exc)
        return plan
    return _finish(plan)


def apply(plan):
    """Run the moves of one plan. Returns the number of paths changed."""
    if plan.get("error"):
        raise AppError(plan["error"])
    _check(plan)
    done = []
    emptied = set()
    try:
        for move in plan["moves"]:
            source, target = move["from"], move["to"]
            writes.check(source)
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                writes.ensure_dir(parent)
            writes.check(parent)
            # Atomic check-and-rename: attempt the rename directly and handle
            # FileExistsError, avoiding the TOCTOU race of exists()-then-rename().
            try:
                if _same(source, target):
                    # Case-only rename on a case-insensitive filesystem: go via a temp name.
                    tmp = target + ".__curator_tmp__"
                    os.rename(source, tmp)
                    os.rename(tmp, target)
                else:
                    os.rename(source, target)
            except FileExistsError:
                raise AppError(f"{target} already exists")
            done.append(move)
            if not move["dir"]:
                emptied.add(os.path.dirname(source))
    except OSError as exc:
        _rollback(done)
        raise AppError(f"Could not rename {os.path.basename(move['from'])}: {exc.strerror or exc}") from exc
    except AppError:
        _rollback(done)
        raise
    files = [(move["from"], move["to"], False) for move in done if not move["dir"]]
    folders = [(move["from"], move["to"], True) for move in done if move["dir"]]
    # Wrap DB update so a failure here triggers a filesystem rollback too.
    try:
        store.rewrite_paths(files + list(plan.get("db_only") or []) + folders)
    except Exception as exc:
        _rollback(done)
        raise AppError(f"DB update failed after rename, changes rolled back: {exc}") from exc
    folder_moves = [(move["from"], move["to"]) for move in done if move["dir"]]
    for folder in sorted(emptied, key=len, reverse=True):
        _remove_if_empty(_after(folder, folder_moves))
    return len(done)


def _after(path, folder_moves):
    for old, new in folder_moves:
        if path == old or path.startswith(old + os.sep):
            return new + path[len(old):]
    return path


def _remove_if_empty(folder):
    try:
        if os.path.isdir(folder) and not os.listdir(folder):
            writes.check(folder)
            os.rmdir(folder)
    except (OSError, AppError):
        pass


def _rollback(done):
    for move in reversed(done):
        try:
            os.rename(move["to"], move["from"])
        except OSError:
            pass


def new_videos(plan):
    """Video paths after the plan ran, for refreshing their subtitle lists."""
    folder_moves = [(move["from"], move["to"]) for move in plan["moves"] if move["dir"]]
    return [_after(move["to"], folder_moves) for move in plan["moves"]
            if not move["dir"] and naming.is_video(move["to"])]
