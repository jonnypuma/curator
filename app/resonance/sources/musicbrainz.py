import logging
import re
import threading
from difflib import SequenceMatcher

import musicbrainzngs

from resonance import settings
from resonance.fields import norm_name

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_state = {"state": "ready", "detail": "MusicBrainz API"}
_patched = False
_timeout = threading.local()


def status():
    return dict(_state)


def _configure():
    global _patched
    contact = settings.load().get("musicbrainz_contact") or "resonance@localhost"
    musicbrainzngs.set_useragent("Resonance", "1.0", contact)
    # MusicBrainz requires at most one request per second per application.
    musicbrainzngs.set_rate_limit(1.0, 1)
    musicbrainzngs.set_hostname("musicbrainz.org", use_https=True)
    if not _patched:
        _limit_requests()
        _patched = True


def _limit_requests():
    module = musicbrainzngs.musicbrainz
    original = module._safe_read

    class _Opener:
        def __init__(self, opener):
            self.opener = opener

        def open(self, req, data=None, timeout=8):
            from resonance.jobs import ScanCancelled, cancelled

            if cancelled():
                raise ScanCancelled()
            limit = getattr(_timeout, "seconds", None) or timeout or 8
            if data is None:
                return self.opener.open(req, timeout=limit)
            return self.opener.open(req, data, timeout=limit)

    def _safe_read(opener, req, body=None, max_retries=8, retry_delay_delta=2.0):
        from resonance.jobs import ScanCancelled, cancelled

        if cancelled():
            raise ScanCancelled()
        return original(_Opener(opener), req, body, max_retries=2, retry_delay_delta=0.5)

    module._safe_read = _safe_read


def call(func):
    _configure()
    with _lock:
        try:
            result = func()
            _state["state"] = "connected"
            _state["detail"] = "Connected to MusicBrainz API"
            return result
        except Exception as exc:
            from resonance.jobs import ScanCancelled

            if isinstance(exc, ScanCancelled):
                raise
            _state["state"] = "error"
            _state["detail"] = str(exc)[:180]
            logger.info("musicbrainz error: %s", exc)
            raise


def search_release_groups(artist, title, limit=5):
    def run():
        cap = max(1, min(int(limit or 5), 25))
        result = musicbrainzngs.search_release_groups(artist=artist or "", releasegroup=title or "", limit=cap)
        groups = result.get("release-group-list") or []
        if groups or not title:
            return groups
        result = musicbrainzngs.search_release_groups(releasegroup=title, limit=cap)
        return result.get("release-group-list") or []

    return call(run)


def browse_release_groups(artist_id):
    def run():
        collected = []
        offset = 0
        while offset <= 700:
            result = musicbrainzngs.browse_release_groups(
                artist=artist_id,
                release_type=["album", "single", "ep"],
                limit=100,
                offset=offset,
            )
            page = result.get("release-group-list") or []
            collected.extend(page)
            try:
                total = int(result.get("release-group-count") or len(collected))
            except (TypeError, ValueError):
                total = len(collected)
            offset += 100
            if not page or offset >= total or offset > 700:
                break
        return collected

    return call(run)


def browse_releases(release_group_id):
    def run():
        collected = []
        offset = 0
        while offset <= 300:
            try:
                result = musicbrainzngs.browse_releases(
                    release_group=release_group_id,
                    includes=["media", "labels", "artist-credits"],
                    limit=100,
                    offset=offset,
                )
            except Exception:
                if offset:
                    break
                result = musicbrainzngs.browse_releases(
                    release_group=release_group_id,
                    limit=100,
                    offset=offset,
                )
            page = result.get("release-list") or []
            collected.extend(page)
            try:
                total = int(result.get("release-count") or len(collected))
            except (TypeError, ValueError):
                total = len(collected)
            offset += 100
            if not page or offset >= total or offset > 300:
                break
        return collected

    return call(run)


_LEADING_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def search_artists(name, limit=3):
    """Artists whose name matches the typed words, closest name first.

    An unquoted MusicBrainz query treats each word on its own, so "The Casuals"
    ranks The Beatles first. The phrase query keeps the words together, and a
    loose search is only added when that phrase has no close name.
    """
    wanted = max(1, min(int(limit or 3), 25))
    query = str(name or "").strip()

    def run():
        hits = _artist_hits(query, strict=True)
        ranked = _rank_artists(query, hits)
        if ranked and _artist_similarity(query, ranked[0]) >= 0.8:
            return ranked[:wanted]
        try:
            loose = _artist_hits(query, strict=False)
        except Exception:
            logger.info("musicbrainz artist search fallback failed", exc_info=True)
            return ranked[:wanted]
        return _rank_artists(query, _merge_artists(hits, loose))[:wanted]

    return call(run)


def _artist_hits(query, strict):
    result = musicbrainzngs.search_artists(artist=query, limit=25, strict=strict)
    return result.get("artist-list") or []


def _merge_artists(first, second):
    merged = list(first or [])
    seen = {str(hit.get("id") or "") for hit in merged}
    for hit in second or []:
        ident = str(hit.get("id") or "")
        if ident and ident in seen:
            continue
        if ident:
            seen.add(ident)
        merged.append(hit)
    return merged


def _artist_rank_keys(value):
    text = str(value or "").strip()
    keys = []
    full = norm_name(text)
    if full:
        keys.append(full)
    bare = norm_name(_LEADING_ARTICLE.sub("", text))
    if bare and bare not in keys:
        keys.append(bare)
    return keys


def _artist_similarity(query, hit):
    left = _artist_rank_keys(query)
    if not left:
        return 0.0
    names = [hit.get("name") or "", hit.get("sort-name") or ""]
    aliases = hit.get("alias-list") or []
    if isinstance(aliases, dict):
        aliases = [aliases]
    for alias in aliases:
        if isinstance(alias, dict):
            names.append(alias.get("alias") or "")
    best = 0.0
    for name in names:
        for left_key in left:
            for right_key in _artist_rank_keys(name):
                if left_key == right_key:
                    return 1.0
                best = max(best, SequenceMatcher(None, left_key, right_key).ratio())
    return best


def _rank_artists(query, hits):
    ordered = list(enumerate(hits or []))
    ordered.sort(key=lambda item: (-_artist_similarity(query, item[1]), item[0]))
    return [hit for _index, hit in ordered]


def get_artist(mbid):
    def run():
        result = musicbrainzngs.get_artist_by_id(mbid, includes=["url-rels", "tags"])
        return result.get("artist") or {}

    return call(run)


def get_release(release_id):
    def run():
        result = musicbrainzngs.get_release_by_id(
            release_id,
            includes=["artists", "recordings", "isrcs", "artist-credits", "release-groups", "labels", "tags", "media"],
        )
        return result.get("release") or {}

    # A box set with every recording is much larger than a search page.
    _timeout.seconds = 45
    try:
        return call(run)
    finally:
        _timeout.seconds = None


def get_release_group(mbid):
    def run():
        result = musicbrainzngs.get_release_group_by_id(mbid, includes=["artists"])
        return result.get("release-group") or {}

    return call(run)


def releases_by_discid(discid):
    def run():
        result = musicbrainzngs.get_releases_by_discid(
            discid,
            includes=["artists", "labels", "release-groups", "recordings", "media"],
        )
        disc = result.get("disc") or {}
        return disc.get("release-list") or []

    return call(run)


def recording_release_groups(recording_id):
    def run():
        result = musicbrainzngs.get_recording_by_id(recording_id, includes=["releases"])
        recording = result.get("recording") or {}
        groups = []
        releases = []
        for release in recording.get("release-list") or []:
            if release.get("id"):
                releases.append(release["id"])
            group_id = (release.get("release-group") or {}).get("id")
            if group_id and group_id not in groups:
                groups.append(group_id)
        return {"groups": groups, "releases": releases}

    return call(run)
