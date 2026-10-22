"""Named views for one library, and the tags a movie or TV scan writes from them.

The payload is the view on screen: column filters, ribbon keys, and the search box.
Music stores the preset in the filter menu. A scan matches the ribbon keys and the
column values it can read from the database. The search box stays on the view only.
"""
from __future__ import annotations

import json

from psycopg.types.json import Jsonb

from curator.video import tags
from resonance import db
from resonance.errors import AppError

MEDIA = {"movies", "tv", "sets", "music"}

RIBBONS = {
    "fel": "(COALESCE(f.dovi_profile, '') LIKE '7%%' AND upper(COALESCE(f.dovi_el_type, '')) = 'FEL')",
    "dv": "f.hdr_format = 'dovi'",
    "hdr10plus": "(f.hdr_format = 'hdr10plus' OR f.hdr_secondary = 'HDR10+')",
    "hdr10": "(f.hdr_format = 'hdr10' OR f.hdr_secondary = 'HDR10')",
    "hlg": "(f.hdr_format = 'hlg' OR f.hdr_secondary = 'HLG')",
    "sdr": "f.hdr_format = 'sdr'",
    "uhd": "f.resolution IN ('4K', '8K')",
    "fhd": "f.resolution = '1080p'",
}

# These read a column on the movie or show itself, so the table alias depends on the library.
# A row that was never checked (NULL) matches neither, the same as in the filter menu.
OWN_RIBBONS = {
    "missing_trailer": {"movies": "m.has_local_trailer = false", "tv": "s.has_local_trailer = false"},
    "missing_theme": {"movies": "m.has_local_theme = false", "tv": "s.has_local_theme = false"},
}


def list_filters(media):
    media = _media(media)
    rows = db.fetchall(
        "SELECT id, media, name, payload, tag FROM saved_filters WHERE media = %s ORDER BY lower(name), name",
        (media,),
    )
    return [db.clean(dict(row)) for row in rows]


def save_filter(media, name, payload, tag=None):
    media = _media(media)
    name = _name(name)
    stored_tag, stored = _stored(media, payload, tag)
    row = db.fetchone(
        """
        INSERT INTO saved_filters (media, name, payload, tag)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (media, name) DO UPDATE SET payload = EXCLUDED.payload, tag = EXCLUDED.tag
        RETURNING id, media, name, payload, tag
        """,
        (media, name, Jsonb(stored), stored_tag),
    )
    return db.clean(dict(row))


def delete_filter(filter_id):
    row = db.fetchone("DELETE FROM saved_filters WHERE id = %s RETURNING id", (filter_id,))
    if not row:
        raise AppError("That saved filter is gone", 404)


def tag_clauses(payload, media):
    """SQL fragments a scan can match. The search box is omitted."""
    payload = _payload(payload)
    parts, params = [], []
    for key in payload.get("ribbons") or []:
        sql = RIBBONS.get(str(key)) or OWN_RIBBONS.get(str(key), {}).get(media)
        if sql:
            parts.append(sql)
    edition = "COALESCE(NULLIF(m.edition, ''), NULLIF(f.edition, ''), '')" if media == "movies" else "COALESCE(f.edition, '')"
    top = "COALESCE(m.top250::text, '')" if media == "movies" else "COALESCE(s.top250::text, '')"
    columns = {
        "hdr_el": "upper(COALESCE(f.dovi_el_type, ''))",
        "hdr_profile": "CASE WHEN f.hdr_format = 'dovi' AND COALESCE(f.dovi_profile, '') <> '' THEN 'P' || f.dovi_profile ELSE '' END",
        "source": "COALESCE(f.video_source, '')",
        "source_format": "COALESCE(NULLIF(f.source_format, ''), NULLIF(f.video_source, ''), '')",
        "edition": edition,
        "top250": top,
    }
    for key, query in (payload.get("filters") or {}).items():
        expr = columns.get(str(key))
        if not expr:
            continue
        values = query if isinstance(query, list) else [query]
        cleaned = []
        for value in values:
            text = " ".join(str(value or "").split())
            if text:
                cleaned.append(text.upper() if key == "hdr_el" else text)
        if not cleaned:
            continue
        holders = " OR ".join([f"lower({expr}) = lower(%s)" for _ in cleaned])
        parts.append(f"({holders})")
        params.extend(cleaned)
    return parts, params


def apply_scan_tags(job, roots, targets=None):
    """Tag unlocked movies or shows that match a saved filter, then rewrite their .nfo."""
    if job.media not in {"movies", "tv"}:
        return
    roots = [root for root in roots or [] if root]
    if not roots:
        return
    rows = db.fetchall(
        "SELECT id, name, tag, payload FROM saved_filters WHERE media = %s AND COALESCE(tag, '') <> '' ORDER BY name",
        (job.media,),
    )
    if not rows:
        return
    changed = []
    seen = set()
    for row in rows:
        if job.cancelled:
            return
        payload = _payload(row.get("payload"))
        if str(payload.get("search") or "").strip():
            job.log(f"{row['name']}: the search box is not used for tagging.")
        clauses, params = tag_clauses(payload, job.media)
        if not clauses:
            job.log(f"{row['name']}: nothing in this filter can be matched during a scan.")
            continue
        ids = _matching(job.media, roots, targets, clauses, params, row["tag"])
        if not ids:
            continue
        updated = tags.apply("movies" if job.media == "movies" else "tv", ids, add=[row["tag"]])
        for item_id in updated:
            if item_id not in seen:
                seen.add(item_id)
                changed.append(item_id)
        job.log(f"{row['name']}: tagged {len(updated)} with {row['tag']}.")
    if not changed or job.cancelled:
        return
    _write(job, changed)


def _matching(media, roots, targets, clauses, params, tag):
    from curator.video import store

    where = list(clauses)
    query = list(params)
    if media == "movies":
        where.append("m.root = ANY(%s)")
        query.append(list(roots))
        where.append("NOT m.locked")
        where.append("NOT (lower(%s) = ANY (SELECT lower(t) FROM unnest(COALESCE(m.tags, ARRAY[]::text[])) AS t))")
        query.append(tag)
        if targets:
            under, extra = store._under(targets)
            where.append(f"({under.replace('path', 'm.path')})")
            query.extend(extra)
        sql = f"SELECT m.id FROM movies m LEFT JOIN video_files f ON f.id = m.file_id WHERE {' AND '.join(where)}"
    else:
        where.append("s.root = ANY(%s)")
        query.append(list(roots))
        where.append("NOT s.locked")
        where.append("NOT (lower(%s) = ANY (SELECT lower(t) FROM unnest(COALESCE(s.tags, ARRAY[]::text[])) AS t))")
        query.append(tag)
        if targets:
            under, extra = store._under(targets)
            show = under.replace("path", "s.path")
            file = under.replace("path", "f.path")
            where.append(f"(({show}) OR ({file}))")
            query.extend(extra)
            query.extend(extra)
        sql = (
            "SELECT DISTINCT s.id FROM tv_shows s "
            "LEFT JOIN tv_episodes e ON e.show_id = s.id "
            "LEFT JOIN video_files f ON f.id = e.file_id "
            f"WHERE {' AND '.join(where)}"
        )
    return [str(item["id"]) for item in db.fetchall(sql, tuple(query))]


def _write(job, ids):
    from curator.video import config, exports

    cfg = config.current()
    written = 0
    for item_id in ids:
        if job.cancelled:
            return
        try:
            if job.media == "movies":
                exports.write_movie(item_id, cfg, "overwrite")
            else:
                exports.write_show(item_id, cfg, "overwrite")
            written += 1
        except Exception as exc:
            job.log(f"Could not write the tagged .nfo: {exc}")
    job.log(f"Tags: {len(ids)} item(s), {written} .nfo written.")


def _stored(media, payload, tag):
    if media == "music":
        preset = " ".join(str((payload or {}).get("preset") or "all").split())[:40] or "all"
        return None, {"preset": preset}
    text = " ".join(str(tag or "").split())[: tags.MAX_TAG]
    view = _view(payload)
    return (text or None), view


def _view(payload):
    payload = _payload(payload)
    filters = {}
    for key, value in (payload.get("filters") or {}).items():
        if isinstance(value, list):
            filters[str(key)] = [" ".join(str(item or "").split()) for item in value if str(item or "").strip()]
        else:
            text = " ".join(str(value or "").split())
            if text:
                filters[str(key)] = text
    ribbons = []
    for key in payload.get("ribbons") or []:
        text = str(key or "").strip()
        if text and text not in ribbons:
            ribbons.append(text)
    return {"filters": filters, "ribbons": ribbons, "search": " ".join(str(payload.get("search") or "").split())}


def _payload(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _media(media):
    if media not in MEDIA:
        raise AppError("Filters are saved per library", 400)
    return media


def _name(name):
    text = " ".join(str(name or "").split())
    if not text:
        raise AppError("Name the filter", 400)
    return text[:80]
