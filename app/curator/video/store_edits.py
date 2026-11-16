"""Changes to stored video items: season and episode numbers, inline edits, matches, locks, and removing items."""
from __future__ import annotations

from psycopg.types.json import Jsonb
from resonance import db


def save_season_meta(season_id, values):
    allowed = ("title", "plot", "premiered", "trailer", "year", "sort_title", "tmdb_episode_count", "tmdb_episode_numbers")
    if values.get("premiered") and "year" not in values:
        text = str(values["premiered"])
        if len(text) >= 4 and text[:4].isdigit():
            values = dict(values)
            values["year"] = int(text[:4])
    columns = [column for column in allowed if column in values]
    ids = values.get("ids") if isinstance(values.get("ids"), dict) else None
    if not columns and not ids:
        return
    sets = [f"{column} = %s" for column in columns]
    params = [values[column] for column in columns]
    if ids:
        sets.append("ids = COALESCE(ids, '{}'::jsonb) || %s::jsonb")
        params.append(Jsonb({key: value for key, value in ids.items() if value}))
    params.append(season_id)
    db.execute(
        f"UPDATE tv_seasons SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s AND NOT locked",
        params,
    )


def _fold_episode(conn, source_id, target_id):
    """Fold the episode row source into target, which has the same season and number.

    A target that is only a placeholder for a file that is not on disk takes over the file. Otherwise the file
    becomes a second copy of the target, the way a scan stores a duplicate. The source row is removed."""
    target = conn.execute("SELECT missing FROM tv_episodes WHERE id = %s::uuid", (target_id,)).fetchone()
    if target and target["missing"]:
        conn.execute(
            "UPDATE tv_episodes t SET path = s.path, file_id = s.file_id, file_span = s.file_span, missing = FALSE, "
            "nfo_path = COALESCE(s.nfo_path, t.nfo_path), nfo_mtime = COALESCE(s.nfo_mtime, t.nfo_mtime), "
            "artwork = t.artwork || s.artwork, status = COALESCE(s.status, t.status), updated_at = NOW() "
            "FROM tv_episodes s WHERE t.id = %s::uuid AND s.id = %s::uuid", (target_id, source_id),
        )
    conn.execute(
        "INSERT INTO episode_copies (episode_id, path, file_id) "
        "SELECT %s::uuid, path, file_id FROM episode_copies WHERE episode_id = %s::uuid "
        + ("" if target and target["missing"] else
           "UNION SELECT %s::uuid, path, file_id FROM tv_episodes WHERE id = %s::uuid ")
        + "ON CONFLICT (episode_id, path) DO NOTHING",
        (target_id, source_id) if target and target["missing"] else (target_id, source_id, target_id, source_id),
    )
    conn.execute("DELETE FROM tv_episodes WHERE id = %s::uuid", (source_id,))


class SeasonExists(ValueError):
    """The season number asked for already belongs to another season of the show."""


def drop_empty_seasons(show_id, numbers):
    """Remove seasons of this show that have no episodes. Returns the numbers that were removed."""
    rows = db.fetchall(
        "DELETE FROM tv_seasons x WHERE x.show_id = %s AND x.season_number = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.season_id = x.id) RETURNING x.season_number",
        (show_id, list(numbers)),
    )
    return sorted(row["season_number"] for row in rows)


def renumber_season(season_id, new_number, with_episodes=True, merge=False):
    """Give a season another number. Returns (old number, episodes moved); None when the season is gone.

    A number that another season holds raises SeasonExists, unless merge is set: then the episodes go into that
    season and this one is removed. Other refusals raise ValueError with a message. The edited season and its
    episodes are locked on season_number, so a scan keeps the numbers they have been given."""
    lock = "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['season_number']))), updated_at = NOW()"
    with db.transaction() as conn:
        row = conn.execute("SELECT show_id, season_number FROM tv_seasons WHERE id = %s FOR UPDATE", (season_id,)).fetchone()
        if not row:
            return None
        old = row["season_number"]
        if old == new_number:
            return old, 0
        target = conn.execute(
            "SELECT id FROM tv_seasons WHERE show_id = %s AND season_number = %s", (row["show_id"], new_number)
        ).fetchone()
        if target and not merge:
            raise SeasonExists(f"Season {new_number} already exists in this show")
        moved = 0
        merged_into = None
        if target:
            # The same file stored under both numbers (a scan read it as S04 once and as S03 later) is one episode.
            conn.execute(
                "DELETE FROM tv_episodes a USING tv_episodes b WHERE a.season_id = %s AND b.season_id = %s "
                "AND a.episode_number = b.episode_number AND a.path = b.path", (season_id, target["id"]),
            )
            # The same episode number with another file is a second copy of that episode, as a scan stores one.
            clash = conn.execute(
                "SELECT a.id AS source_id, b.id AS target_id FROM tv_episodes a JOIN tv_episodes b "
                "ON b.episode_number = a.episode_number WHERE a.season_id = %s AND b.season_id = %s",
                (season_id, target["id"]),
            ).fetchall()
            for pair in clash:
                _fold_episode(conn, pair["source_id"], pair["target_id"])
            moved = conn.execute(
                f"UPDATE tv_episodes SET season_id = %s, season_number = %s, {lock} WHERE season_id = %s",
                (target["id"], new_number, season_id),
            ).rowcount
            conn.execute(
                "UPDATE tv_seasons t SET title = COALESCE(t.title, s.title), plot = COALESCE(t.plot, s.plot), "
                "premiered = COALESCE(t.premiered, s.premiered), year = COALESCE(t.year, s.year), "
                "artwork = s.artwork || t.artwork, updated_at = NOW() FROM tv_seasons s WHERE t.id = %s AND s.id = %s",
                (target["id"], season_id),
            )
            conn.execute("DELETE FROM tv_seasons WHERE id = %s", (season_id,))
            merged_into = target["id"]
        if not target:
            if with_episodes:
                if conn.execute("SELECT 1 FROM tv_episodes WHERE show_id = %s AND season_number = %s", (row["show_id"], new_number)).fetchone():
                    raise ValueError(f"Season {new_number} already has episodes")
                moved = conn.execute(
                    f"UPDATE tv_episodes SET season_number = %s, {lock} WHERE season_id = %s", (new_number, season_id),
                ).rowcount
            conn.execute(f"UPDATE tv_seasons SET season_number = %s, {lock} WHERE id = %s", (new_number, season_id))
            names = conn.execute("SELECT season_names FROM tv_shows WHERE id = %s", (row["show_id"],)).fetchone()
            names = dict((names or {}).get("season_names") or {})
            if str(old) in names and str(new_number) not in names:
                names[str(new_number)] = names.pop(str(old))
                conn.execute("UPDATE tv_shows SET season_names = %s WHERE id = %s", (Jsonb(names), row["show_id"]))
    if merged_into:
        try:
            from curator.video import copies

            copies.refresh_episode_seeds(copies.episode_seeds_for_seasons([merged_into]))
        except Exception:  # the Duplicate marks catch up on the next scan
            pass
    return old, moved


def move_episode(episode_id, new_season):
    """Put one episode in another season of its show, creating that season when it is not there yet.

    Returns the season id; None when the episode is gone. Raises ValueError when the number is taken."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT show_id, season_number, episode_number FROM tv_episodes WHERE id = %s FOR UPDATE", (episode_id,)
        ).fetchone()
        if not row:
            return None
        if row["season_number"] == new_season:
            return True
        twin = conn.execute(
            "SELECT id FROM tv_episodes WHERE show_id = %s AND season_number = %s AND episode_number = %s",
            (row["show_id"], new_season, row["episode_number"]),
        ).fetchone()
        if twin:
            _fold_episode(conn, episode_id, twin["id"])
            return twin["id"]
        season = conn.execute(
            "INSERT INTO tv_seasons (show_id, season_number) VALUES (%s, %s) "
            "ON CONFLICT (show_id, season_number) DO UPDATE SET updated_at = NOW() RETURNING id", (row["show_id"], new_season),
        ).fetchone()
        conn.execute(
            "UPDATE tv_episodes SET season_id = %s, season_number = %s, "
            "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['season_number']))), updated_at = NOW() "
            "WHERE id = %s", (season["id"], new_season, episode_id),
        )
    return season["id"]


def set_episode_number(episode_id, new_number):
    """Give one episode another number inside its season. A placeholder for a missing episode that holds the number is
    replaced. Raises ValueError when a real episode already has it."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT show_id, season_id, season_number, episode_number FROM tv_episodes WHERE id = %s FOR UPDATE", (episode_id,)
        ).fetchone()
        if not row or row["episode_number"] == new_number:
            return bool(row)
        twin = conn.execute(
            "SELECT id, missing, path FROM tv_episodes WHERE season_id = %s AND episode_number = %s AND id <> %s",
            (row["season_id"], new_number, episode_id),
        ).fetchone()
        if twin:
            if not (twin["missing"] and str(twin["path"] or "").startswith("missing://")):
                raise ValueError(f"Episode {new_number} already exists in this season")
            conn.execute("DELETE FROM tv_episodes WHERE id = %s", (twin["id"],))
        conn.execute(
            "UPDATE tv_episodes SET episode_number = %s, "
            "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['episode_number']))), updated_at = NOW() "
            "WHERE id = %s", (new_number, episode_id),
        )
    return True


def merge_season_name(show_id, number, name):
    """Remember a season title that is a name, so tvshow.nfo can write namedseason."""
    if not show_id or number is None:
        return
    text = str(name or "").strip()
    if not text:
        db.execute(
            """
            UPDATE tv_shows
            SET season_names = COALESCE(season_names, '{}'::jsonb) - %s, updated_at = NOW()
            WHERE id = %s AND NOT locked
            """,
            (str(number), show_id),
        )
        return
    db.execute(
        """
        UPDATE tv_shows
        SET season_names = COALESCE(season_names, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
        WHERE id = %s AND NOT locked
        """,
        (Jsonb({str(number): text}), show_id),
    )


def save_nfo_state(table, row_id, nfo_path, nfo_mtime):
    db.execute(
        f"UPDATE {table} SET nfo_path = %s, nfo_mtime = %s WHERE id = %s", (nfo_path, nfo_mtime, row_id)
    )


def link_set(movie_id, info):
    set_id = store.save_set(info)
    row = db.fetchone(
        "SELECT set_id FROM movies WHERE id = %s AND NOT locked AND NOT ('set' = ANY(locked_fields))",
        (movie_id,),
    )
    if not row:
        return set_id
    previous = row.get("set_id")
    db.execute("UPDATE movies SET set_id = %s WHERE id = %s", (set_id, movie_id))
    if str(previous or "") != str(set_id):
        store.note_set_new(set_id)
    return set_id


def set_watched(kind, row_id, watched):
    """Mark a movie or episode watched without lowering a play count that is already above one."""
    table = store.table_for(kind)
    if table not in {"movies", "tv_episodes"}:
        raise ValueError(kind)
    if watched:
        assignment = "playcount = GREATEST(COALESCE(playcount, 0), 1)"
        locked = ["playcount"]
    else:
        assignment = "playcount = 0, last_played = NULL"
        locked = ["playcount", "last_played"]
    db.execute(
        f"UPDATE {table} SET {assignment}, "
        "locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))), "
        "updated_at = NOW() WHERE id = %s AND NOT locked",
        (locked, row_id),
    )


def edit(kind, row_id, values):
    """Inline edit from the UI. Every edited field joins locked_fields so scrapes leave it alone."""
    table = store.table_for(kind)
    allowed = store.FIELDS[table]
    values = dict(values)
    locked_extra = []
    if kind == "movie" and "set_name" in values:
        set_name = str(values.pop("set_name") or "").strip()
        set_overview = str(values.pop("set_overview", "") or "").strip()
        if set_name:
            values["set_id"] = store.save_set({"name": set_name, "overview": set_overview})
        else:
            values["set_id"] = None
        locked_extra.append("set")
    if "ids" in values:
        ids = {key: str(val).strip()[:80] for key, val in (values["ids"] or {}).items()
               if key in store.EDITABLE_ID_KEYS and str(val or "").strip()}
        values["ids"] = ids
        for key, column in store.ID_COLUMNS.items():
            if column in store.ID_ON_TABLE.get(table, ()):
                values[column] = ids.get(key)
        locked_extra += [column for column in store.ID_COLUMNS.values() if column in values]
    columns = [column for column in values if column in allowed or column == "set_id"]
    if not columns:
        return False
    sets = [f"{column} = %s" for column in columns]
    params = [store._value(column, values[column]) for column in columns]
    locked_cols = [col for col in columns if col != "set_id"] + locked_extra
    sets.append("locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[])))")
    params.append(locked_cols)
    sets.append("updated_at = NOW()")
    params.append(row_id)
    row = db.fetchone(f"UPDATE {table} SET {', '.join(sets)} WHERE id = %s RETURNING id", params)
    return bool(row)


def match_ids(source, source_id, extra=None):
    """Ids to store for a Fix Match pick. Companions from the search hit are kept; anything else is dropped."""
    allowed = {"tmdb", "imdb", "tvdb", "trakt"}
    ids = {}
    for key, value in (extra or {}).items():
        text = str(value or "").strip()
        if text and key in allowed:
            ids[key] = text
    source_id = str(source_id or "").strip()
    if source == "omdb":
        ids["imdb"] = source_id
    elif source in allowed:
        ids[source] = source_id
    return ids


def set_match(kind, row_id, source, source_id, extra=None):
    """Point an item at a different scraper id. Old ids are dropped so the next scrape cannot mix two titles.

    Returns the duplicate and upgrade flags for the copies that share the old or new identity.
    None means the item is locked or gone.
    """
    from curator.video import copies, match_undo

    ids = match_ids(source, source_id, extra)
    if kind in ("movie", "show") and source in {"tmdb", "tvdb", "omdb", "trakt"}:
        locked = db.fetchone(f"SELECT locked FROM {'movies' if kind == 'movie' else 'tv_shows'} WHERE id = %s", (row_id,))
        if locked and not locked.get("locked"):
            match_undo.snapshot(kind, row_id)          # what Undo Fix Match puts back
    if kind == "movie" and source in {"tmdb", "tvdb", "omdb", "trakt"}:
        before = copies.movie_seed_rows([row_id])
        row = db.fetchone(
            "UPDATE movies SET ids = %s, tmdb_id = %s, imdb_id = %s, trakt_id = %s "
            "WHERE id = %s AND NOT locked RETURNING id",
            (Jsonb(ids), ids.get("tmdb"), ids.get("imdb"), ids.get("trakt"), row_id),
        )
    elif kind == "show" and source in {"tmdb", "tvdb", "omdb", "trakt"}:
        before = copies.episode_seeds_for_shows([row_id])
        row = db.fetchone(
            "UPDATE tv_shows SET ids = %s, tmdb_id = %s, tvdb_id = %s, imdb_id = %s, trakt_id = %s "
            "WHERE id = %s AND NOT locked RETURNING id",
            (Jsonb(ids), ids.get("tmdb"), ids.get("tvdb"), ids.get("imdb"), ids.get("trakt"), row_id),
        )
    elif kind == "set" and source == "tmdb":
        row = db.fetchone(
            "UPDATE movie_sets SET tmdb_collection_id = %s, updated_at = NOW() "
            "WHERE id = %s AND NOT COALESCE(locked, FALSE) RETURNING id",
            (ids.get("tmdb"), row_id),
        )
        return [] if row else None
    else:
        raise ValueError(f"{kind}/{source}")
    if not row:
        return None
    # A title the user matched by hand is no longer waiting for Apply match.
    store.clear_pending_match("movies" if kind == "movie" else "tv_shows", row_id)
    if kind == "movie":
        seeds = list(before) + list(copies.movie_seed_rows([row_id]))
        copies.refresh_movie_seeds(seeds)
        return copies.peer_flags("movie", seeds)
    seeds = list(before) + list(copies.episode_seeds_for_shows([row_id]))
    copies.refresh_episode_seeds(seeds)
    return copies.peer_flags("episode", seeds)


_PREF_TABLES = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes"}


def scrape_prefs(kind, row_id):
    table = _PREF_TABLES.get(kind)
    if not table:
        raise ValueError(kind)
    columns = "preferred_source, preferred_art"
    if kind == "show":
        columns += ", episode_order"
    row = db.fetchone(f"SELECT {columns} FROM {table} WHERE id = %s", (row_id,))
    return dict(row) if row else None


def save_scrape_prefs(kind, row_id, source, art, episode_order=None):
    """Store a per-item provider. Empty values mean the global chain. Episode order locks like Edit."""
    table = _PREF_TABLES.get(kind)
    if not table:
        raise ValueError(kind)
    source = source or None
    art = art or None
    if kind != "show":
        row = db.fetchone(
            f"UPDATE {table} SET preferred_source = %s, preferred_art = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            (source, art, row_id),
        )
        return bool(row)
    if episode_order:
        row = db.fetchone(
            """
            UPDATE tv_shows
            SET preferred_source = %s, preferred_art = %s, episode_order = %s,
                locked_fields = (
                    SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || ARRAY['episode_order']::text[]))
                ),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (source, art, episode_order, row_id),
        )
    else:
        row = db.fetchone(
            """
            UPDATE tv_shows
            SET preferred_source = %s, preferred_art = %s, episode_order = NULL,
                locked_fields = ARRAY(
                    SELECT unnest(locked_fields) EXCEPT SELECT 'episode_order'
                ),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (source, art, row_id),
        )
    return bool(row)


def lock_fields(kind, row_id, fields):
    table = store.table_for(kind)
    db.execute(
        f"UPDATE {table} SET locked_fields = (SELECT ARRAY(SELECT DISTINCT unnest(locked_fields || %s::text[]))), "
        "updated_at = NOW() WHERE id = %s",
        (list(fields), row_id),
    )


def unlock_fields(kind, row_id, fields):
    table = store.table_for(kind)
    db.execute(
        f"UPDATE {table} SET locked_fields = ARRAY(SELECT unnest(locked_fields) EXCEPT SELECT unnest(%s::text[])), "
        "updated_at = NOW() WHERE id = %s",
        (list(fields), row_id),
    )


def set_lock(kind, ids, locked):
    ids = list(ids)
    with db.transaction() as conn:
        if kind == "movie":
            conn.execute("UPDATE movies SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "show":
            conn.execute("UPDATE tv_shows SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_seasons SET locked = %s WHERE show_id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE show_id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "season":
            conn.execute("UPDATE tv_seasons SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE season_id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "episode":
            conn.execute("UPDATE tv_episodes SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        elif kind == "set":
            conn.execute("UPDATE movie_sets SET locked = %s WHERE id = ANY(%s::uuid[])", (locked, ids))
        else:
            raise ValueError(kind)


def remove(kind, ids):
    ids = list(ids)
    flag_kind, seeds, flag_ids = _removal_seeds(kind, ids)
    table = {"movie": "movies", "show": "tv_shows", "season": "tv_seasons", "episode": "tv_episodes", "set": "movie_sets"}.get(kind)
    if not table:
        raise ValueError(kind)
    if not ids:
        return []
    file_ids, paths, set_ids = [], [], []
    with db.transaction() as conn:
        if kind in {"show", "season"}:
            column = "show_id" if kind == "show" else "season_id"
            held = conn.execute(
                f"""
                SELECT e.file_id, e.path FROM tv_episodes e WHERE e.{column} = ANY(%s::uuid[])
                UNION ALL
                SELECT c.file_id, NULL::text FROM episode_copies c
                JOIN tv_episodes e ON e.id = c.episode_id
                WHERE e.{column} = ANY(%s::uuid[])
                """,
                (ids, ids),
            ).fetchall()
            for row in held:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                if row["path"]:
                    paths.append(row["path"])
        if kind == "movie":
            rows = conn.execute(
                "DELETE FROM movies WHERE id = ANY(%s::uuid[]) RETURNING id, file_id, parts, set_id",
                (ids,),
            ).fetchall()
            for row in rows:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                paths.extend(row["parts"] or [])
                if row["set_id"]:
                    set_ids.append(row["set_id"])
        elif kind == "episode":
            copies = conn.execute(
                "SELECT file_id FROM episode_copies WHERE episode_id = ANY(%s::uuid[])",
                (ids,),
            ).fetchall()
            file_ids.extend(row["file_id"] for row in copies if row["file_id"])
            rows = conn.execute(
                "DELETE FROM tv_episodes WHERE id = ANY(%s::uuid[]) RETURNING id, file_id, path",
                (ids,),
            ).fetchall()
            for row in rows:
                if row["file_id"]:
                    file_ids.append(row["file_id"])
                if row["path"]:
                    paths.append(row["path"])
        else:
            rows = conn.execute(f"DELETE FROM {table} WHERE id = ANY(%s::uuid[]) RETURNING id", (ids,)).fetchall()
    _drop_released_files(file_ids, paths)
    _drop_empty_sets(set_ids)
    removed = [str(row["id"]) for row in rows]
    peers = _settle_removed_flags(flag_kind, seeds, flag_ids) if removed else []
    return removed, peers


def _removal_seeds(kind, ids):
    """Identity rows and the item ids whose Not duplicates rows should go, read before the delete."""
    from curator.video import copies

    if kind == "movie":
        return "movie", copies.movie_seed_rows(ids), list(ids)
    if kind == "episode":
        return "episode", copies.episode_seed_rows(ids), list(ids)
    if kind == "season":
        rows = db.fetchall(
            "SELECT id::text AS id FROM tv_episodes WHERE season_id = ANY(%s::uuid[])",
            (list(ids),),
        )
        return "episode", copies.episode_seeds_for_seasons(ids), [row["id"] for row in rows]
    if kind == "show":
        rows = db.fetchall(
            "SELECT id::text AS id FROM tv_episodes WHERE show_id = ANY(%s::uuid[])",
            (list(ids),),
        )
        return "episode", copies.episode_seeds_for_shows(ids), [row["id"] for row in rows]
    return "", [], []


def _settle_removed_flags(kind, seeds, ids):
    """Drop Not duplicates rows for the removed copies and rewrite the flags on whatever remains."""
    from curator.video import copies

    ids = [str(item) for item in ids or [] if item]
    if ids and kind in {"movie", "episode"}:
        db.execute(
            """
            DELETE FROM video_dismissed_duplicates
            WHERE kind = %s AND (left_id = ANY(%s::uuid[]) OR right_id = ANY(%s::uuid[]))
            """,
            (kind, ids, ids),
        )
    if kind == "movie":
        copies.refresh_movie_seeds(seeds)
        return copies.peer_flags("movie", seeds)
    if kind == "episode":
        copies.refresh_episode_seeds(seeds)
        return copies.peer_flags("episode", seeds)
    return []


def _drop_released_files(file_ids, paths):
    """Drop probe rows that belonged to the items just removed and are not used by anything left."""
    file_ids = [item for item in file_ids if item] or ["00000000-0000-0000-0000-000000000000"]
    paths = [item for item in paths if item]
    if paths == [] and file_ids == ["00000000-0000-0000-0000-000000000000"]:
        return
    if not paths:
        paths = [""]
    db.execute(
        """
        DELETE FROM video_files f
        WHERE (f.id = ANY(%s::uuid[]) OR f.path = ANY(%s))
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.file_id = f.id OR f.path = ANY(m.parts))
          AND NOT EXISTS (SELECT 1 FROM tv_episodes e WHERE e.file_id = f.id)
          AND NOT EXISTS (SELECT 1 FROM episode_copies c WHERE c.file_id = f.id)
          AND NOT EXISTS (SELECT 1 FROM music_videos v WHERE v.file_id = f.id)
        """,
        (file_ids, paths),
    )


def _drop_empty_sets(set_ids):
    set_ids = [item for item in set_ids if item]
    if not set_ids:
        return
    db.execute(
        """
        DELETE FROM movie_sets s
        WHERE s.id = ANY(%s::uuid[])
          AND NOT EXISTS (SELECT 1 FROM movies m WHERE m.set_id = s.id)
        """,
        (set_ids,),
    )

# Imported last: the old module imports this one's names, so importing it first must not start a cycle.
from curator.video import store  # noqa: E402
