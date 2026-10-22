import hmac
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def token_matches(provided):
    from resonance.settings import load

    cfg = load()
    if not cfg.get("lidarr_enabled"):
        return False
    expected = str(cfg.get("lidarr_token") or "")
    got = str(provided or "")
    if not expected or len(expected) != len(got):
        return False
    return hmac.compare_digest(expected, got)


def accept(payload):
    """Handle one Lidarr Connect webhook. Import and upgrade can scan that album."""
    from resonance.settings import load
    from resonance.settings import vlog

    body = payload if isinstance(payload, dict) else {}
    event = str(body.get("eventType") or "").strip()
    if event == "Test":
        return {"ok": True}
    if event == "Grab":
        return _note_grab(body)
    if event == "DownloadFailure":
        return _note_failure(body, "download")
    if event == "ImportFailure":
        return _note_failure(body, "import")
    if event != "Download":
        return {"ok": True, "ignored": True}
    if not load().get("lidarr_import_scan"):
        vlog(logger, "lidarr import left unscanned: automatic scan is off")
        return {"ok": True, "scanned": False, "reason": "Automatic scan of a Lidarr import is off."}
    album, artist, label, error = locate(body)
    if error:
        logger.warning("lidarr webhook skipped: %s", error)
        vlog(logger, "lidarr webhook skipped: %s", error)
        return {"ok": True, "scanned": False, "reason": error}
    from resonance import jobs

    result = jobs.enqueue_lidarr(album, artist, label)
    logger.info("lidarr webhook for %s started=%s", label, result["started"])
    vlog(logger, "lidarr webhook for %s started=%s duplicate=%s", label, result["started"], result["duplicate"])
    return {
        "ok": True,
        "path": album,
        "started": result["started"],
        "queued": not result["started"],
    }


def locate(payload):
    from resonance.paths import inside, music_roots, path_kind
    from resonance.settings import load

    mapped = [map_path(path, load().get("lidarr_paths") or []) for path in file_paths(payload)]
    mapped = [path for path in mapped if path]
    if not mapped:
        return None, None, None, "Lidarr did not include any imported file paths."
    parents = []
    for path in mapped:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if folder:
            parents.append(os.path.normpath(folder))
    if not parents:
        return None, None, None, "Lidarr did not include a folder."
    try:
        album = os.path.commonpath(parents)
    except ValueError:
        return None, None, None, "Imported files are not under one folder."
    if not os.path.isdir(album):
        return None, None, None, f"Album folder is not available: {album}"
    root = _library_root(album, music_roots(), inside)
    if not root:
        return None, None, None, f"Album folder is outside the music library: {album}"
    parent = os.path.dirname(album.rstrip(os.sep))
    if parent and inside(root, parent) and not _same(parent, root):
        artist = parent
    elif path_kind(root) == "artist":
        artist = root
    else:
        artist = album
    artist_name = str((payload.get("artist") or {}).get("name") or "").strip() or os.path.basename(artist.rstrip(os.sep))
    album_name = str((payload.get("album") or {}).get("title") or "").strip() or os.path.basename(album.rstrip(os.sep))
    return album, artist, f"{artist_name} — {album_name}", None


def file_paths(payload):
    found = []
    for key in ("trackFiles", "tracks"):
        for item in payload.get(key) or []:
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
            elif isinstance(item, dict):
                path = item.get("path") or item.get("Path") or ""
                if str(path).strip():
                    found.append(str(path).strip())
    return found


def map_path(path, pairs):
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return ""
    ranked = []
    for item in pairs or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("lidarr") or "").strip().replace("\\", "/").rstrip("/")
        target = str(item.get("resonance") or "").strip().rstrip("/\\")
        if source and target:
            ranked.append((source, target))
    ranked.sort(key=lambda item: len(item[0]), reverse=True)
    for source, target in ranked:
        if text == source or text.startswith(source + "/"):
            rest = text[len(source):]
            return os.path.normpath(target + rest.replace("/", os.sep))
    return os.path.normpath(text.replace("/", os.sep))


def _library_root(album, roots, inside):
    chosen = None
    for root in roots or []:
        if root and (inside(root, album) or _same(root, album)):
            if chosen is None or len(os.path.normpath(root)) > len(os.path.normpath(chosen)):
                chosen = root
    return chosen


def test(url=None, key=None):
    """Check the address and API key. Used by Settings, Integrations."""
    from resonance.errors import AppError

    saved_url, saved_key = _api_credentials()
    url = (url or saved_url).rstrip("/")
    key = key or saved_key
    if not url or not key:
        raise AppError("Lidarr is not set up. Add its address and API key under Settings, Integrations.", 400)
    status = _api("GET", "/api/v1/system/status", url, key, timeout=(5, 20))
    return f"Connected to Lidarr {(status or {}).get('version') or ''}".strip()


def _require_search():
    from curator.automation import require_integration
    from resonance.errors import AppError

    require_integration("lidarr")
    url, key = _api_credentials()
    if not url or not key:
        raise AppError("Set the Lidarr address and API key under Settings, Integrations.", 400)
    return url, key


def search_release(artist_mbid, artist_name, release_group_id, title, owned, year=""):
    """Ask Lidarr to search one release. A missing album is added first."""
    from resonance.errors import AppError

    url, key = _require_search()
    if not artist_mbid or not release_group_id:
        raise AppError("This release needs a MusicBrainz id before Lidarr can search for it.", 400)
    artist = _lidarr_artist(url, key, artist_mbid)
    added_artist = False
    if not artist:
        artist = _add_lidarr_artist(url, key, artist_mbid)
        added_artist = True
    album = _lidarr_album(url, key, artist.get("id"), release_group_id)
    if not album:
        album = _add_lidarr_album(url, key, artist.get("id"), release_group_id, title, search=not owned)
    if not album or not album.get("id"):
        raise AppError("Lidarr did not return an album id.", 502)
    if not album.get("monitored"):
        album = dict(album)
        album["monitored"] = True
        _api("PUT", f"/api/v1/album/{album['id']}", url, key, payload=album)
    started = datetime.now(timezone.utc)
    command = _api("POST", "/api/v1/command", url, key, payload={"name": "AlbumSearch", "albumIds": [album["id"]]})
    label = release_label(artist_name, title or album.get("title"), year or _year(album.get("releaseDate")))
    if command and command.get("id"):
        _start_watch(command["id"], album["id"], label, started)
    root = artist.get("rootFolderPath") or ""
    if owned:
        message = f"Lidarr is searching for another copy of {label}."
    elif added_artist:
        where = f" under {root}" if root else ""
        message = f"Lidarr added {artist_name or 'the artist'}{where} and is searching for {label}."
    else:
        message = f"Lidarr is searching for {label}."
    return {"ok": True, "message": message, "owned": bool(owned), "pending": bool(command and command.get("id"))}


def queue_releases(artist_id, releases):
    """Queue a Lidarr search. The ARR worker runs it, one item at a time."""
    from curator.arr_queue import enqueue
    from resonance import db, jobs
    from resonance.errors import AppError
    from resonance.fields import opt_uuid

    artist_id = str(opt_uuid(artist_id, "Artist"))
    artist = db.fetchone("SELECT id, name, musicbrainz_artist_id FROM artists WHERE id = %s", (artist_id,))
    if not artist:
        raise AppError("Artist not found", 404)
    _require_search()
    items = []
    for item in releases or []:
        group_id = str((item or {}).get("release_group_id") or (item or {}).get("id") or "").strip()
        if not group_id:
            continue
        items.append(
            {
                "release_group_id": group_id,
                "title": str((item or {}).get("title") or ""),
                "year": str((item or {}).get("year") or ""),
                "owned": bool((item or {}).get("owned")),
            }
        )
    if not items:
        raise AppError("Choose a release with a MusicBrainz id.", 400)
    name = artist.get("name") or "Artist"
    if len(items) == 1:
        label = release_label(name, items[0]["title"], items[0]["year"])
    else:
        label = f"{len(items)} missing studio albums by {name}"
    row = jobs.queue_work("lidarr-search", f"Lidarr is searching for {label}.", len(items))
    payload = {
        "job_id": str(row["id"]),
        "artist": {
            "id": str(artist.get("id") or ""),
            "name": name,
            "musicbrainz_artist_id": str(artist.get("musicbrainz_artist_id") or ""),
        },
        "items": items,
    }
    try:
        enqueue("lidarr", label, "lidarr", payload)
    except Exception:
        jobs.finish_work(row["id"], "failed", "Lidarr search could not be queued")
        raise
    message = f"{label} is queued."
    return {"ok": True, "started": False, "queued": True, "pending": True, "message": message, "job": row}


def run_queued(payload):
    """Run one queued Lidarr search in the ARR worker."""
    from resonance import jobs

    jobs.claim_work(payload["job_id"])
    _search_job(payload["job_id"], payload.get("artist") or {}, payload.get("items") or [])


def queue_missing_studio(artist_id):
    """Queue every MusicBrainz studio album that is not already on disk."""
    from resonance import discography
    from resonance.errors import AppError

    catalog = discography.cached(artist_id)
    if not catalog.get("fetched_at"):
        raise AppError("Refresh the MusicBrainz discography before searching Lidarr.", 400)
    releases = [
        {
            "release_group_id": item.get("id") or "",
            "title": item.get("title") or "",
            "year": item.get("year") or "",
            "owned": False,
        }
        for item in catalog.get("releases") or []
        if item.get("type") == "album" and not item.get("owned") and item.get("id")
    ]
    if not releases:
        raise AppError("Every studio album in this discography is already on disk.", 400)
    return queue_releases(artist_id, releases)


def _search_job(job_id, artist, items):
    from resonance import jobs

    name = artist.get("name") or ""
    mbid = str(artist.get("musicbrainz_artist_id") or "")
    done = []
    ok = 0
    try:
        for index, item in enumerate(items, start=1):
            label = release_label(name, item.get("title"), item.get("year"))
            jobs.touch_work(job_id, index - 1, f"Searching {label}", "\n".join(done[:80]))
            try:
                result = search_release(
                    mbid,
                    name,
                    item.get("release_group_id"),
                    item.get("title"),
                    item.get("owned"),
                    item.get("year"),
                )
            except Exception as exc:
                logger.exception("lidarr search failed")
                done.insert(0, f"Failed — {label} — {exc}")
                continue
            ok += 1
            done.insert(0, result.get("message") or f"Queued — {label}")
        status = "completed" if ok else "failed"
        summary = f"Lidarr accepted {ok} of {len(items)}."
        jobs.finish_work(job_id, status, summary, len(items), "\n".join(done[:80]))
    except Exception as exc:
        logger.exception("lidarr search job failed")
        jobs.finish_work(job_id, "failed", str(exc)[:300], log="\n".join(done[:80]))


def release_label(artist_name, title, year=""):
    artist = str(artist_name or "").strip() or "Unknown artist"
    album = str(title or "").strip() or "Unknown album"
    text = f"{artist} — {album}"
    year_text = str(year or "").strip()
    if len(year_text) >= 4 and year_text[:4].isdigit():
        text += f" ({year_text[:4]})"
    return text


def feed():
    """Notices for the open browser, plus whether a search is still running."""
    with _lock:
        return {"pending": _pending > 0, "notices": list(_notices)}


def _note_grab(body):
    artist = (body.get("artist") or {}).get("name")
    albums = body.get("albums") or []
    album = albums[0] if albums else {}
    with _lock:
        stored = _album_labels.get(str(album.get("id") or "")) or ""
    label = stored or release_label(artist, album.get("title"), _year(album.get("releaseDate")))
    client = str(body.get("downloadClient") or "").strip() or "the download client"
    release = body.get("release") or {}
    title = str(release.get("releaseTitle") or release.get("title") or "").strip()
    download_id = str(body.get("downloadId") or "")
    album_id = album.get("id")
    _announce_sent(album_id, label, client, title, download_id)
    return {"ok": True, "grabbed": True}


def _note_failure(body, kind):
    download_id = str(body.get("downloadId") or "")
    with _lock:
        known = _download_labels.get(download_id) or ""
        if not known:
            albums = body.get("albums") or []
            album = body.get("album") or (albums[0] if albums else {}) or {}
            known = _album_labels.get(str(album.get("id") or "")) or ""
    label = known or _payload_label(body)
    if kind == "import":
        message = f"Lidarr could not import {label}."
    else:
        message = f"Lidarr download failed for {label}."
    reason = str(body.get("message") or "").strip()
    if reason:
        message = f"{message} {reason}"
    _push(message, "error")
    logger.info("lidarr %s failure: %s", kind, message)
    return {"ok": True, "failed": True}


def _api_credentials():
    from resonance.settings import load

    cfg = load()
    url = str(cfg.get("lidarr_url") or "").strip().rstrip("/")
    key = str(cfg.get("lidarr_api_key") or "").strip()
    return url, key


def _api(method, path, url, key, payload=None, params=None, timeout=None):
    import requests

    from resonance.errors import AppError

    # Local Lidarr calls should answer quickly. Lookup calls wait on MusicBrainz.
    if timeout is None:
        timeout = (5, 30)
    try:
        response = requests.request(
            method,
            url + path,
            headers={"X-Api-Key": key},
            json=payload,
            params=params,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        from resonance.connections import note

        message = f"Lidarr accepted the connection but did not answer in time: {exc}"
        note("lidarr", message)
        raise AppError(message, 502) from exc
    except requests.RequestException as exc:
        from resonance.connections import note

        message = f"Lidarr could not be reached: {exc}"
        note("lidarr", message)
        raise AppError(message, 502) from exc
    if response.status_code >= 400:
        detail = ""
        try:
            body = response.json()
            detail = body.get("message") or body.get("title") or ""
        except ValueError:
            detail = (response.text or "")[:180]
        from resonance.connections import note

        message = f"Lidarr returned HTTP {response.status_code}. {detail}".strip()
        note("lidarr", message)
        raise AppError(message, 502)
    from resonance.connections import clear

    clear("lidarr")
    if not response.content:
        return None
    return response.json()


def _lookup(path, url, key, params):
    """MusicBrainz search inside Lidarr. A timeout returns None so a local add can still run."""
    from resonance.errors import AppError

    try:
        return _api("GET", path, url, key, params=params, timeout=(5, 90)) or []
    except AppError as exc:
        if "did not answer in time" in str(exc):
            return None
        raise


def _lidarr_artist(url, key, artist_mbid):
    """The artist already stored in Lidarr. This does not ask MusicBrainz."""
    wanted = str(artist_mbid).lower()
    try:
        # Asking for one artist is quick; the full list of a big library can take longer than a minute.
        for artist in _api("GET", "/api/v1/artist", url, key, params={"mbId": artist_mbid}) or []:
            if str(artist.get("foreignArtistId") or "").lower() == wanted and artist.get("id"):
                return artist
    except Exception:
        pass
    for artist in _api("GET", "/api/v1/artist", url, key, timeout=(5, 180)) or []:
        if str(artist.get("foreignArtistId") or "").lower() == wanted and artist.get("id"):
            return artist
    return None


def _add_lidarr_artist(url, key, artist_mbid):
    from resonance.errors import AppError

    found = _lookup("/api/v1/artist/lookup", url, key, params={"term": f"mbid:{artist_mbid}"})
    if found is None:
        raise AppError(
            "Lidarr did not finish the MusicBrainz artist lookup. Add the artist in Lidarr, then search again.",
            502,
        )
    artist = None
    for item in found:
        if str(item.get("foreignArtistId") or "").lower() == str(artist_mbid).lower():
            artist = item
            break
    if not artist and found:
        artist = found[0]
    if not artist:
        raise AppError("Lidarr could not find that MusicBrainz artist.", 404)
    root, quality, metadata = _lidarr_defaults(url, key)
    artist["qualityProfileId"] = quality
    artist["metadataProfileId"] = metadata
    artist["rootFolderPath"] = root
    artist["monitored"] = True
    artist["addOptions"] = {"monitor": _new_artist_monitor(), "searchForMissingAlbums": False}
    return _api("POST", "/api/v1/artist", url, key, payload=artist)


def _new_artist_monitor():
    from resonance.settings import load

    if load().get("lidarr_monitor_new", True) is False:
        return "none"
    return "all"


def add_artist(artist_mbid):
    """Add a MusicBrainz artist to Lidarr. The caller has already checked they are new."""
    url, key = _api_credentials()
    if not url or not key:
        from resonance.errors import AppError

        raise AppError("Set the Lidarr address and API key in Settings.", 400)
    return _add_lidarr_artist(url, key, artist_mbid)


def stored_artist(artist_mbid):
    """The Lidarr artist for this MusicBrainz id, or None when Lidarr does not have them."""
    from resonance.errors import AppError

    url, key = _api_credentials()
    if not url or not key:
        raise AppError("Set the Lidarr address and API key in Settings.", 400)
    return _lidarr_artist(url, key, artist_mbid)


def _lidarr_album(url, key, artist_id, release_group_id):
    if not artist_id:
        return None
    albums = _api("GET", "/api/v1/album", url, key, params={"artistId": artist_id}) or []
    wanted = str(release_group_id).lower()
    for album in albums:
        if str(album.get("foreignAlbumId") or "").lower() == wanted:
            return album
    return None


def _add_lidarr_album(url, key, artist_id, release_group_id, title, search):
    wanted = str(release_group_id).lower()
    looked = _lookup("/api/v1/album/lookup", url, key, params={"term": f"mbid:{release_group_id}"}) or []
    album = None
    for item in looked:
        if str(item.get("foreignAlbumId") or "").lower() == wanted:
            album = item
            break
    if album:
        album["artistId"] = artist_id
        album["monitored"] = True
        album["anyReleaseOk"] = True
        album["addOptions"] = {"searchForNewAlbum": bool(search)}
        nested = album.get("artist") or {}
        if not nested.get("id"):
            nested["id"] = artist_id
            album["artist"] = nested
        return _api("POST", "/api/v1/album", url, key, payload=album)
    return _api(
        "POST",
        "/api/v1/album",
        url,
        key,
        payload={
            "title": title or "Album",
            "foreignAlbumId": release_group_id,
            "artistId": artist_id,
            "monitored": True,
            "anyReleaseOk": True,
            "addOptions": {"searchForNewAlbum": bool(search)},
        },
    )


def normalize(data):
    """Saved root folder and profiles. Zero means Lidarr's first profile."""
    data = data if isinstance(data, dict) else {}

    def number(key):
        try:
            return max(0, int(data.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    from curator.radarr import _profile_list, _profile_name

    return {
        "root_folder": str(data.get("root_folder") or "").strip(),
        "quality_profile": number("quality_profile"),
        "quality_profile_name": _profile_name(data.get("quality_profile_name")),
        "quality_profiles": _profile_list(data.get("quality_profiles")),
        "metadata_profile": number("metadata_profile"),
        "metadata_profile_name": _profile_name(data.get("metadata_profile_name")),
        "metadata_profiles": _profile_list(data.get("metadata_profiles")),
    }


def options(url=None, key=None):
    """Root folders, quality profiles and metadata profiles for the settings form."""
    saved_url, saved_key = _api_credentials()
    url = (url or saved_url).rstrip("/")
    key = key or saved_key
    roots = _api("GET", "/api/v1/rootfolder", url, key) or []
    qualities = _api("GET", "/api/v1/qualityprofile", url, key) or []
    metadata = _api("GET", "/api/v1/metadataprofile", url, key) or []
    return {
        "root_folders": [{"path": item.get("path")} for item in roots if item.get("path")],
        "quality_profiles": [{"id": item.get("id"), "name": item.get("name")} for item in qualities if item.get("id")],
        "metadata_profiles": [{"id": item.get("id"), "name": item.get("name")} for item in metadata if item.get("id")],
    }


def _lidarr_defaults(url, key):
    from resonance.errors import AppError
    from resonance.settings import load

    chosen = normalize(load().get("lidarr") or {})
    root, quality, metadata = chosen["root_folder"], chosen["quality_profile"], chosen["metadata_profile"]
    if root and quality and metadata:
        return root, quality, metadata
    roots = _api("GET", "/api/v1/rootfolder", url, key) or []
    qualities = _api("GET", "/api/v1/qualityprofile", url, key) or []
    profiles = _api("GET", "/api/v1/metadataprofile", url, key) or []
    if not roots:
        raise AppError("Lidarr has no root folder yet.", 400)
    if not qualities or not profiles:
        raise AppError("Lidarr needs a quality profile and a metadata profile.", 400)
    return root or roots[0].get("path"), quality or qualities[0].get("id"), metadata or profiles[0].get("id")


_lock = threading.Lock()
_notices = []
_notice_seq = 0
_pending = 0
_sent_ids = set()
_download_labels = {}
_grabbed_albums = set()
_album_labels = {}


def _push(message, kind):
    global _notice_seq
    text = str(message or "").strip()
    if not text:
        return
    with _lock:
        _notice_seq += 1
        _notices.append({"id": _notice_seq, "message": text, "kind": kind or "info"})
        del _notices[:-40]


def _announce_sent(album_id, label, client, release_title, download_id):
    with _lock:
        if download_id and download_id in _sent_ids:
            return False
        if album_id and str(album_id) in _grabbed_albums:
            if download_id:
                _sent_ids.add(download_id)
                _download_labels[download_id] = label
            return False
        if download_id:
            _sent_ids.add(download_id)
            _download_labels[download_id] = label
        if album_id:
            _grabbed_albums.add(str(album_id))
    release = f" ({release_title})" if release_title else ""
    _push(f"Lidarr found a release for {label} and sent it to {client} for download{release}.", "info")
    return True


def _payload_label(body):
    artist = str((body.get("artist") or {}).get("name") or "").strip()
    albums = body.get("albums") or []
    album = body.get("album") or (albums[0] if albums else {}) or {}
    title = str(album.get("title") or "").strip()
    if artist or title:
        return release_label(artist, title, _year(album.get("releaseDate")))
    return str(body.get("releaseTitle") or "that download").strip() or "that download"


def _start_watch(command_id, album_id, label, started):
    global _pending
    with _lock:
        _pending += 1
        _grabbed_albums.discard(str(album_id))
        _album_labels[str(album_id)] = label
    threading.Thread(
        target=_watch_search,
        args=(command_id, album_id, label, started),
        name="lidarr-search",
        daemon=True,
    ).start()


def _watch_search(command_id, album_id, label, started):
    global _pending
    try:
        status, detail = _wait_command(command_id)
        if status == "failed":
            _push(f"Lidarr search failed for {label}. {detail}".strip(), "error")
            return
        if status == "timeout":
            _push(f"Lidarr is still searching for {label}.", "warning")
            return
        time.sleep(2)
        outcome = _search_outcome(album_id, started)
        if outcome["kind"] == "sent":
            _announce_sent(album_id, label, outcome["client"], outcome["title"], outcome["download_id"])
        elif outcome["kind"] == "failed":
            _push(f"Lidarr download failed for {label}. {outcome['detail']}".strip(), "error")
        elif str(album_id) not in _grabbed_albums:
            _push(f"Lidarr could not find a release for {label}.", "warning")
    except Exception as exc:
        logger.exception("lidarr search follow-up failed")
        _push(f"Lidarr search for {label} could not be checked. {exc}", "error")
    finally:
        with _lock:
            _pending = max(0, _pending - 1)


def _wait_command(command_id):
    deadline = time.time() + 240
    status = ""
    detail = ""
    while time.time() < deadline:
        status, detail = _command_status(command_id)
        if status not in {"queued", "started", "running", ""}:
            return status or "completed", detail
        time.sleep(3)
    return "timeout", detail


def _command_status(command_id):
    from resonance.errors import AppError

    url, key = _api_credentials()
    try:
        body = _api("GET", f"/api/v1/command/{command_id}", url, key) or {}
    except AppError as exc:
        if "404" in str(exc):
            return "completed", ""
        raise
    return str(body.get("status") or "").lower(), str(body.get("message") or body.get("exception") or "")


def _search_outcome(album_id, started):
    url, key = _api_credentials()
    history = _api(
        "GET",
        "/api/v1/history",
        url,
        key,
        params={"page": 1, "pageSize": 40, "sortKey": "date", "sortDirection": "descending", "albumId": album_id},
    ) or {}
    records = history.get("records") if isinstance(history, dict) else history
    for record in records or []:
        if record.get("albumId") and str(record.get("albumId")) != str(album_id):
            continue
        when = _parse_time(record.get("date"))
        if when and when < started - timedelta(seconds=15):
            continue
        if _history_kind(record.get("eventType")) == "grab":
            data = record.get("data") or {}
            return {
                "kind": "sent",
                "client": data.get("downloadClientName") or data.get("downloadClient") or "the download client",
                "title": record.get("sourceTitle") or "",
                "download_id": str(data.get("downloadId") or ""),
            }
        if _history_kind(record.get("eventType")) == "fail":
            return {"kind": "failed", "detail": record.get("sourceTitle") or ""}
    queue = _api("GET", "/api/v1/queue", url, key) or {}
    rows = queue.get("records") if isinstance(queue, dict) else queue
    for item in rows or []:
        if str(item.get("albumId") or "") != str(album_id):
            continue
        state = str(item.get("status") or item.get("trackedDownloadStatus") or "").lower()
        title = item.get("title") or ""
        if state in {"failed", "warning"}:
            return {"kind": "failed", "detail": title}
        if state in {"queued", "downloading", "paused", "delay", "completed", "importpending"}:
            return {"kind": "sent", "client": "the download client", "title": title, "download_id": str(item.get("downloadId") or "")}
    return {"kind": "none"}


def _history_kind(event):
    text = str(event or "").strip().lower()
    if text in {"1", "grabbed"}:
        return "grab"
    if text in {"4", "downloadfailed"}:
        return "fail"
    return ""


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _year(value):
    text = str(value or "")
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _same(left, right):
    if not left or not right:
        return False
    left_real = os.path.realpath(left) if os.path.exists(left) else os.path.normpath(left)
    right_real = os.path.realpath(right) if os.path.exists(right) else os.path.normpath(right)
    return os.path.normcase(left_real) == os.path.normcase(right_real)


def _command_info(url, key, sent):
    """What Lidarr did with the command: running now, or queued behind which other tasks. Always truthy."""
    info = {"status": "", "ahead": []}
    try:
        command_id = (sent or {}).get("id")
        info["status"] = str((sent or {}).get("status") or "").lower()
        rows = _api("GET", "/api/v1/command", url, key, timeout=(5, 10)) or []
        for row in rows:
            if row.get("id") == command_id:
                info["status"] = str(row.get("status") or info["status"]).lower()
            elif str(row.get("status") or "").lower() in {"queued", "started"} and (
                command_id is None or (row.get("id") or 0) < command_id
            ):
                info["ahead"].append(str(row.get("name") or "a task"))
    except Exception:
        pass
    return info


def rescan_artist(artist_mbid=None, artist_id=None, strict=False):
    """Tell Lidarr to refresh the artist, which also rescans the artist folder and updates album track paths.

    Lidarr has no RescanArtist command (it answers 500, "Sequence contains no matching element");
    RefreshArtist is the one that reads the disk again.
    """
    from resonance.settings import load

    cfg = load()
    url = str(cfg.get("lidarr_url") or "").strip().rstrip("/")
    key = str(cfg.get("lidarr_api_key") or "").strip()
    if not url or not key:
        return False
    try:
        target_id = artist_id
        if not target_id and artist_mbid:
            artist = _lidarr_artist(url, key, artist_mbid)
            if artist and artist.get("id"):
                target_id = artist["id"]
        if not target_id:
            return False
        sent = _api("POST", "/api/v1/command", url, key, payload={"name": "RefreshArtist", "artistId": int(target_id)})
        return _command_info(url, key, sent)
    except Exception as exc:
        if strict:
            raise
        logger.warning("Lidarr RefreshArtist failed for mbid=%s id=%s: %s", artist_mbid, artist_id, exc)
        return False

