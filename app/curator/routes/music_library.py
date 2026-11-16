"""Music library reads and edits. Paths stay on /api so the page does not change."""

from __future__ import annotations

from fastapi import APIRouter, Query

from curator.routes.music_http import JsonBody, body_dict, cleaned, run
from resonance import backup, library, profile

from curator.routes.fast_json import json_reply

router = APIRouter()


@router.get("/api/library/progress")
async def library_filter_progress():
    return library.filter_progress()


@router.get("/api/library")
async def get_library(filter: str = Query("all"), q: str = Query("")):
    library.note_filter("artists", label="Reading artists")

    def work():
        import logging
        import time

        marks = [("start", time.monotonic())]

        def mark(name):
            marks.append((name, time.monotonic()))

        artists = library.library(filter_name=filter, query=(q or "").strip())
        mark("artists")
        library.note_filter("counts", label="Counting the library")
        totals = library.totals()
        mark("totals")
        filter_counts = library.filter_counts()
        mark("filter counts")
        payload = {
            "artists": artists,
            "totals": totals,
            "filter_counts": filter_counts,
            "as_of": library.clock(),
            "sort_ignore_the": library.sort_ignore_the(),
        }
        library.note_filter("sending", label="Sending the list")
        result = json_reply(cleaned(payload))
        mark("prepare reply")
        if marks[-1][1] - marks[0][1] > 3.0:
            steps = ", ".join(f"{marks[i + 1][0]} {marks[i + 1][1] - marks[i][1]:.1f}s" for i in range(len(marks) - 1))
            logging.getLogger(__name__).info("music library: %d artists, %s", len(artists), steps)
        return result

    return await run(work)


@router.post("/api/library/refresh")
async def refresh_library_rows(body: dict | None = JsonBody):
    """The artists an edit touched, read again under the open filter and search, so the page does not reload the
    whole library after changing one album. An artist that no longer matches the filter is simply not returned."""
    payload = body_dict(body)

    def work():
        named = [str(library.require_uuid(item)) for item in payload.get("artist_ids") or [] if item]
        wanted = library.refresh_scope(payload.get("album_ids") or [], named)
        artists = library.library(filter_name=str(payload.get("filter") or "all"),
                                  query=str(payload.get("q") or "").strip(), artist_ids=wanted)
        # An artist the page named that is gone (merged away, deleted) is in "requested" and not in "artists",
        # so the page drops it.
        return json_reply(cleaned({
            "requested": list(dict.fromkeys([*named, *wanted])),
            "artists": artists,
            "totals": library.totals(),
            "filter_counts": library.filter_counts(),
        }))

    return await run(work)


@router.get("/api/library/changes")
async def library_changes(since: str = Query("")):
    return await run(lambda: cleaned(library.changes(since)))


@router.post("/api/library/artist-search")
async def library_artist_search(body: dict | None = JsonBody):
    query = body_dict(body).get("query")
    return await run(lambda: cleaned(profile.search_by_name(query)))


@router.post("/api/library/artists")
async def library_add_artist(body: dict | None = JsonBody):
    mbid = body_dict(body).get("mbid")

    def work():
        library.require_uuid(mbid)
        return cleaned(library.add_remote_artist(mbid))

    return await run(work)


@router.post("/api/library/lock")
async def lock_library_rows(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: cleaned(library.set_locks(payload.get("kind"), payload.get("ids") or [], payload.get("locked"))))


@router.post("/api/library/lock-field")
async def lock_library_field(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: cleaned(library.toggle_field_lock(
        payload.get("kind"),
        payload.get("id"),
        payload.get("field"),
        payload.get("locked"),
    )))


@router.get("/api/library/held-albums")
async def held_albums():
    return await run(lambda: {"ids": library.held_album_ids()})


@router.post("/api/library/forget")
async def forget_library_rows(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        if payload.get("artist_ids"):
            return cleaned(library.forget_artists(payload.get("artist_ids") or []))
        return cleaned(library.forget_albums(payload.get("album_ids") or []))

    return await run(work)


@router.post("/api/library/delete")
async def delete_library_files(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        import logging
        import os

        from curator.routes.scrape import BUSY_ITEM
        from curator.video import activity
        from resonance import db
        from resonance.errors import AppError

        artist_ids = [str(library.require_uuid(item)) for item in payload.get("artist_ids") or [] if item]
        album_ids = [str(library.require_uuid(item)) for item in payload.get("album_ids") or [] if item]
        # Leave out what a running batch or lookup is writing right now, the way the video delete does.
        held_labels = []
        if artist_ids:
            rows = db.fetchall("SELECT id::text AS id, artist_id::text AS artist_id, title FROM albums "
                               "WHERE artist_id = ANY(%s::uuid[])", (db.uuid_array(artist_ids),))
            busy = set(activity.conflicts("album", [row["id"] for row in rows]))
            held_artists = {row["artist_id"] for row in rows if row["id"] in busy}
            held_labels = [row["title"] for row in rows if row["id"] in busy]
            artist_ids = [item for item in artist_ids if item not in held_artists]
        else:
            free, held = activity.partition("album", album_ids)
            if held:
                rows = db.fetchall("SELECT title FROM albums WHERE id = ANY(%s::uuid[])", (db.uuid_array(held),))
                held_labels = [row["title"] for row in rows]
            album_ids = free
        if held_labels and not (artist_ids or album_ids):
            raise AppError(BUSY_ITEM, 409)
        # The artist folders, read before the rows go, so the players can be told where to clean.
        if artist_ids:
            places = db.fetchall("SELECT path FROM artists WHERE id = ANY(%s::uuid[])", (db.uuid_array(artist_ids),))
            folders = {row["path"] for row in places if row.get("path")}
        else:
            places = db.fetchall("SELECT path FROM albums WHERE id = ANY(%s::uuid[])", (db.uuid_array(album_ids),))
            folders = {os.path.dirname(str(row["path"]).rstrip("/")) for row in places if row.get("path")}
        backup.snapshot_before("deleting music", len(artist_ids or album_ids))
        if artist_ids:
            result = library.delete_artists_from_disk(artist_ids)
        else:
            result = library.delete_albums_from_disk(album_ids)
        result["errors"] = list(result.get("errors") or []) + [f"{title}: {BUSY_ITEM}" for title in held_labels]
        if result.get("deleted") and folders:
            # Kodi and the other players keep a deleted album until they are cleaned, as with a video delete.
            try:
                from curator import notify

                notify.request("music", folders=sorted(folders), clean=True)
            except Exception:
                logging.getLogger(__name__).info("the library clean after a music delete was not sent", exc_info=True)
        return cleaned(result)

    return await run(work)


@router.post("/api/albums/mark")
async def mark_albums(body: dict | None = JsonBody):
    payload = body_dict(body)
    return await run(lambda: cleaned(library.mark_many(payload.get("ids") or [], payload.get("status"))))


@router.post("/api/albums/nfo")
async def rewrite_album_nfos(body: dict | None = JsonBody):
    ids = body_dict(body).get("album_ids") or []
    return await run(lambda: cleaned(library.rewrite_nfos(ids)))


@router.get("/api/artists/{artist_id}")
async def get_artist(artist_id: str):
    def work():
        library.require_uuid(artist_id)
        return cleaned(library.artist_detail(artist_id))

    return await run(work)


@router.get("/api/artists/{artist_id}/nfo")
async def artist_nfo(artist_id: str):
    def work():
        library.require_uuid(artist_id)
        return cleaned(library.read_artist_nfo(artist_id))

    return await run(work)


@router.post("/api/artists/{artist_id}/scrape")
async def scrape_artist(artist_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(artist_id)
        if payload.get("mbid"):
            library.require_uuid(payload.get("mbid"))
        return cleaned(profile.scrape(artist_id, query=payload.get("query"), mbid=payload.get("mbid")))

    return await run(work)


@router.post("/api/artists/{artist_id}/search")
async def search_artist_metadata(artist_id: str, body: dict | None = JsonBody):
    query = body_dict(body).get("query")

    def work():
        library.require_uuid(artist_id)
        return cleaned(profile.search_choices(artist_id, query))

    return await run(work)


@router.post("/api/artists/{artist_id}/biography")
async def save_artist_biography(artist_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(artist_id)
        return cleaned(profile.save_biography(
            artist_id,
            payload.get("biography"),
            payload.get("fields"),
            only_if_longer=bool(payload.get("only_if_longer")),
        ))

    return await run(work)


@router.post("/api/artists/{artist_id}/profile")
async def save_artist_profile(artist_id: str, body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        library.require_uuid(artist_id)
        return cleaned(library.save_artist_profile(artist_id, payload))

    return await run(work)


@router.post("/api/artists/{artist_id}/name")
async def rename_artist(artist_id: str, body: dict | None = JsonBody):
    name = body_dict(body).get("name")

    def work():
        library.require_uuid(artist_id)
        return cleaned(library.rename_artist(artist_id, name))

    return await run(work)


@router.post("/api/artists/{artist_id}/nfo")
async def write_artist_nfo_route(artist_id: str):
    def work():
        library.require_uuid(artist_id)
        return cleaned(library.write_artist_nfo(artist_id))

    return await run(work)


@router.post("/api/artists/{artist_id}/mark")
async def mark_artist(artist_id: str, body: dict | None = JsonBody):
    status = body_dict(body).get("status")

    def work():
        library.require_uuid(artist_id)
        return cleaned(library.mark("artist", artist_id, status))

    return await run(work)


@router.get("/api/albums/{album_id}")
async def get_album(album_id: str):
    def work():
        library.require_uuid(album_id)
        return cleaned(library.album_detail(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/title")
async def rename_album(album_id: str, body: dict | None = JsonBody):
    title = body_dict(body).get("title")

    def work():
        library.require_uuid(album_id)
        return cleaned(library.rename_album(album_id, title))

    return await run(work)


@router.post("/api/albums/{album_id}/nfo")
async def write_album_nfo_route(album_id: str):
    def work():
        library.require_uuid(album_id)
        library.write_album_nfo(album_id)
        return cleaned(library.album_detail(album_id))

    return await run(work)


@router.get("/api/albums/{album_id}/nfo")
async def album_nfo(album_id: str):
    def work():
        library.require_uuid(album_id)
        return cleaned(library.read_album_nfo(album_id))

    return await run(work)


@router.post("/api/albums/{album_id}/mark")
async def mark_album(album_id: str, body: dict | None = JsonBody):
    status = body_dict(body).get("status")

    def work():
        library.require_uuid(album_id)
        return cleaned(library.mark("album", album_id, status))

    return await run(work)


@router.post("/api/albums/batch-edit")
async def albums_batch_edit(body: dict | None = JsonBody):
    payload = body_dict(body)

    def work():
        return cleaned(library.batch_edit_albums(payload.get("ids") or [], payload.get("fields") or {}))

    return await run(work)


@router.get("/api/tracks/{track_id}")
async def get_track(track_id: str):
    def work():
        library.require_uuid(track_id)
        return cleaned({"track": library._track_out(library.get_track(track_id))})

    return await run(work)
