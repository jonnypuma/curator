from urllib.parse import quote

from resonance import db
from resonance.errors import AppError
from resonance.fields import norm_name


def catalog_albums(groups):
    """Albums, EPs, singles, live albums, and compilations from MusicBrainz."""
    kept = []
    for group in groups or []:
        primary = str(group.get("primary-type") or group.get("primary_type") or "album").lower()
        secondary = [str(item).lower() for item in (group.get("secondary-type-list") or group.get("secondary_types") or [])]
        if "live" in secondary:
            kind = "live"
        elif "compilation" in secondary:
            kind = "compilation"
        elif primary in {"album", "ep", "single"}:
            kind = primary
        else:
            kind = "unknown"
        kept.append(
            {
                "id": group.get("id"),
                "title": group.get("title") or "",
                "year": _year(group.get("first-release-date") or group.get("year")),
                "type": kind,
            }
        )
    return kept


def studio_albums(groups):
    return [row for row in catalog_albums(groups) if row.get("type") == "album"]


def missing_studio(catalog, local_albums):
    """Studio albums in a stored discography that are not on disk."""
    studio = [row for row in catalog or [] if row.get("type") == "album"]
    missing = []
    for row in owned_summary(studio, local_albums)["releases"]:
        if row.get("owned"):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        missing.append({"id": str(row.get("id") or ""), "title": title, "year": row.get("year") or ""})
    return missing


def owned_summary(catalog, local_albums):
    local = list(local_albums or [])
    by_group = {}
    by_title = {}
    for album in local:
        group_id = str(album.get("musicbrainz_release_group_id") or "")
        if group_id and group_id not in by_group:
            by_group[group_id] = album
        title = norm_name(album.get("title"))
        if title and title not in by_title:
            by_title[title] = album
    rows = []
    owned = 0
    for group in catalog or []:
        match = by_group.get(str(group.get("id") or "")) or by_title.get(norm_name(group.get("title")))
        have = match is not None
        if have:
            owned += 1
        rows.append({**group, "owned": have, "album_id": str(match["id"]) if match else ""})
    total = len(rows)
    percent = int(round(100 * owned / total)) if total else 0
    return {"owned": owned, "total": total, "percent": percent, "releases": rows}


def links(group):
    title = group.get("title") or ""
    query = quote(title)
    return {
        "musicbrainz": f"https://musicbrainz.org/release-group/{group.get('id')}" if group.get("id") else "",
        "discogs": f"https://www.discogs.com/search/?q={query}&type=release",
        "bandcamp": f"https://bandcamp.com/search?q={query}",
    }


def cached(artist_id):
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    catalog = artist.get("discography") or []
    albums = db.fetchall("SELECT * FROM albums WHERE artist_id = %s", (artist_id,))
    summary = owned_summary(catalog, albums)
    summary["fetched_at"] = artist.get("discography_fetched_at")
    for row in summary["releases"]:
        row["links"] = links(row)
    return summary


def refresh(artist_id):
    artist = db.fetchone("SELECT * FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    if not artist.get("musicbrainz_artist_id"):
        clear_catalog(artist_id)
        summary = cached(artist_id)
        summary["message"] = "No MusicBrainz id on this artist. The stored discography was cleared."
        return summary
    from psycopg.types.json import Json

    from resonance.sources import musicbrainz

    groups = musicbrainz.browse_release_groups(str(artist["musicbrainz_artist_id"]))
    catalog = catalog_albums(groups)
    db.execute(
        """
        UPDATE artists
        SET discography = %s, discography_fetched_at = NOW(), updated_at = NOW()
        WHERE id = %s
        """,
        (Json(catalog), artist_id),
    )
    return cached(artist_id)


def clear_catalog(artist_id):
    """Drop a stored MusicBrainz list that no longer belongs to this artist."""
    db.execute(
        """
        UPDATE artists
        SET discography = '[]'::jsonb, discography_fetched_at = NULL, updated_at = NOW()
        WHERE id = %s
        """,
        (artist_id,),
    )


def _year(value):
    text = str(value or "")
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""
