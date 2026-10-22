"""Write .nfo files from what the database holds, and remember their mtimes so the next scan skips them."""
from __future__ import annotations

import os
import shutil

from curator.video import naming, nfo_write, store


def _stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def movie_nfo_path(movie, cfg):
    """Where this movie's .nfo is written.

    A video inside CD1 or CD2, or a cd1 file beside a cd2 file in the movie folder,
    uses that folder's own name. Pornography.2009.DVDRip.XviD-DOMiNO.nfo, not
    Pornography.2009-cd2.nfo.
    """
    release = naming.release_nfo_dir(movie.get("folder") or "", movie.get("parts") or [], movie.get("root") or "")
    existing = str(movie.get("nfo_path") or "")
    if existing and not (release and _part_nfo(existing)):
        return existing
    if release:
        return os.path.join(release, f"{os.path.basename(release)}.nfo")
    if existing:
        return existing
    folder = movie["folder"]
    own = movie["path"] == folder
    parts = movie.get("parts") or []
    if own and (movie.get("disc_format") or not parts or cfg["movie_nfo_name"] == "movie"):
        return os.path.join(folder, "movie.nfo")
    if len(parts) > 1:
        match = naming._STACK.match(_stem(parts[0]))
        head = (match.group(1) or "").strip(" ._-") if match else ""
        if head:
            return os.path.join(folder, f"{head}.nfo")
        if own:
            return os.path.join(folder, "movie.nfo")
    return os.path.join(folder, f"{_stem(parts[0] if parts else movie['path'])}.nfo")


def _part_nfo(path):
    """True when this .nfo is named after a disc file or sits inside CD1/CD2."""
    if naming.part_dir_number(os.path.basename(os.path.dirname(path or ""))) is not None:
        return True
    return naming.stack_key(os.path.basename(path or "")) is not None


def write_set(set_id, cfg, policy="overwrite"):
    """set.nfo in the set's folder, or in the movie set information folder."""
    from curator.video import sets, writes
    from resonance import db
    from resonance.errors import AppError

    row = db.fetchone("SELECT * FROM movie_sets WHERE id = %s", (set_id,))
    if not row:
        return None
    row = dict(row)
    folder = str(row.get("folder") or "").strip()
    if not folder:
        root = str(cfg.get("set_folder") or "").strip()
        if not root:
            raise AppError("Set a movie set information folder before writing set.nfo", 400)
        folder = sets.folder_for(root, row.get("name"))
    writes.ensure_dir(folder)
    path = os.path.join(folder, sets.nfo_name(cfg.get("nfo_dialect")))
    text = nfo_write.set_xml(row)
    written, mtime = nfo_write.write(path, text, policy=policy, backup=cfg["nfo_backup"])
    if mtime is not None and (written or row.get("nfo_path") != path or nfo_write.same_text(path, text)):
        store.save_nfo_state("movie_sets", set_id, path, mtime)
        if not row.get("folder"):
            db.execute("UPDATE movie_sets SET folder = %s WHERE id = %s AND (folder IS NULL OR folder = '')", (folder, set_id))
        stamped = dict(row)
        stamped["nfo_path"] = path
        store._stamp_nfo("movie_sets", set_id, stamped)
    return path if written else None


def write_movie(movie_id, cfg, policy="overwrite"):
    movie = store.movie_row(movie_id)
    if not movie:
        return None
    path = movie_nfo_path(movie, cfg)
    text = nfo_write.movie_xml(movie, dialect=cfg["nfo_dialect"], default_rating=cfg["default_rating"],
                               actor_thumbs=cfg["actor_thumbs"], versions=store.movie_version_peers(movie))
    written, mtime = nfo_write.write(path, text, policy=policy, backup=cfg["nfo_backup"])
    if mtime is not None and (written or movie.get("nfo_path") != path or nfo_write.same_text(path, text)):
        store.save_nfo_state("movies", movie_id, path, mtime)
        movie = dict(movie)
        movie["nfo_path"] = path
        store._stamp_nfo("movies", movie_id, movie)
    return path if written else None


def season_needs_nfo(season, show, episodes):
    """A season folder, or a season that has an episode file, gets a season .nfo.

    Episodes that live in the show folder use season01.nfo beside tvshow.nfo.
    """
    folder = str(season.get("path") or "")
    show_path = str((show or {}).get("path") or "")
    if folder and show_path:
        try:
            own = os.path.realpath(folder) != os.path.realpath(show_path)
        except OSError:
            own = os.path.normpath(folder) != os.path.normpath(show_path)
        if own:
            return True
    number = season.get("season_number")
    for episode in episodes or []:
        if episode.get("season_number") != number or episode.get("missing"):
            continue
        path = str(episode.get("path") or "")
        if path and not path.startswith("missing://"):
            return True
    return False


def write_season(season_id, cfg, policy="overwrite"):
    """One season.nfo for this season. A season folder gets season.nfo; otherwise the show folder gets season01.nfo."""
    season = store.season_row(season_id)
    if not season:
        return None
    show = store.show_row(season["show_id"])
    if not show:
        return None
    path = _season_nfo_path(season, show)
    text = nfo_write.season_xml(season, show.get("title"), cfg["nfo_dialect"])
    written, mtime = nfo_write.write(path, text, policy=policy, backup=cfg["nfo_backup"])
    if mtime is not None and (written or season.get("nfo_path") != path or nfo_write.same_text(path, text)):
        store.save_nfo_state("tv_seasons", season["id"], path, mtime)
        season = dict(season)
        season["nfo_path"] = path
        store._stamp_nfo("tv_seasons", season["id"], season)
    return path if written else None


def _season_nfo_path(season, show):
    existing = str(season.get("nfo_path") or "")
    if existing.lower().endswith(".nfo"):
        return existing
    show_path = show["path"]
    folder = season.get("path") or ""
    own = False
    if folder:
        try:
            own = os.path.realpath(folder) != os.path.realpath(show_path)
        except OSError:
            own = os.path.normpath(folder) != os.path.normpath(show_path)
    if own:
        return os.path.join(folder, "season.nfo")
    number = int(season.get("season_number") or 0)
    return os.path.join(show_path, f"season{number:02d}.nfo")


def episode_nfo_path(video, season, episode, multi):
    """One NFO beside the video. A multi-episode file uses <stem>-SxxEyy.nfo, as Kodi v22 requires."""
    stem = _stem(video)
    name = f"{stem}-{naming.episode_mark(season, episode)}.nfo" if multi else f"{stem}.nfo"
    return os.path.join(os.path.dirname(video), name)


def write_show(show_id, cfg, policy="overwrite", episode_ids=None, episodes_only=False):
    """tvshow.nfo, season.nfo in real season folders, and one <episodedetails> file per episode.

    episodes_only writes the selected episode files and leaves tvshow.nfo and season.nfo alone.
    """
    show, seasons, episodes = store.show_rows(show_id)
    if not show:
        return []
    options = {"dialect": cfg["nfo_dialect"], "default_rating": cfg["default_rating"],
               "actor_thumbs": cfg["actor_thumbs"]}
    written = []
    if not episodes_only:
        path = os.path.join(show["path"], "tvshow.nfo")
        present = [item for item in episodes if not item.get("missing")
                   and not str(item.get("path") or "").startswith("missing://")]
        text = nfo_write.show_xml(show, seasons=seasons, episode_count=len(present), **options)
        done, mtime = nfo_write.write(path, text, policy=policy, backup=cfg["nfo_backup"])
        if mtime is not None:
            store.save_nfo_state("tv_shows", show_id, path, mtime)
            show = dict(show)
            show["nfo_path"] = path
            store._stamp_nfo("tv_shows", show_id, show)
        if done:
            written.append(path)
        for season in seasons:
            if not season_needs_nfo(season, show, episodes):
                continue
            season_path = _season_nfo_path(season, show)
            text = nfo_write.season_xml(season, show.get("title"), cfg["nfo_dialect"])
            done, mtime = nfo_write.write(season_path, text, policy=policy, backup=cfg["nfo_backup"])
            if mtime is not None:
                store.save_nfo_state("tv_seasons", season["id"], season_path, mtime)
                stamped = dict(season)
                stamped["nfo_path"] = season_path
                store._stamp_nfo("tv_seasons", season["id"], stamped)
            if done:
                written.append(season_path)
    wanted = {str(item) for item in episode_ids} if episode_ids else None
    by_file = {}
    for episode in episodes:
        if str(episode.get("path") or "").startswith("missing://"):
            continue
        by_file.setdefault(episode["path"], []).append(episode)
    for video, group in by_file.items():
        if wanted is not None and not any(str(item["id"]) in wanted for item in group):
            continue
        file = store.file_row(group[0].get("file_id"))
        multi = len(group) > 1
        for item in group:
            nfo_path = episode_nfo_path(video, item.get("season_number"), item.get("episode_number"), multi)
            text = nfo_write.episodes_xml([item], show, file, **options)
            done, mtime = nfo_write.write(nfo_path, text, policy=policy, backup=cfg["nfo_backup"])
            if mtime is not None:
                store.save_nfo_state("tv_episodes", item["id"], nfo_path, mtime)
                stamped = dict(item)
                stamped["nfo_path"] = nfo_path
                store._stamp_nfo("tv_episodes", item["id"], stamped)
            if done:
                written.append(nfo_path)
        if multi:
            _retire_combined(os.path.join(os.path.dirname(video), f"{_stem(video)}.nfo"), cfg["nfo_backup"])
    return written


def _retire_combined(path, backup):
    """Kodi v22 ignores an NFO that holds several <episodedetails> blocks."""
    if not os.path.isfile(path):
        return
    if backup:
        copy = f"{path}.bak"
        if not os.path.exists(copy):
            try:
                shutil.copy2(path, copy)
            except OSError:
                pass
    try:
        os.remove(path)
    except OSError:
        pass
