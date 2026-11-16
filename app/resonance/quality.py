import re
import time

LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}


def is_lossless(file_format, bit_depth=None):
    """FLAC, WAV and the like are lossless. An m4a is when it reports a bit depth (ALAC), not for AAC."""
    ext = str(file_format or "").lower().lstrip(".")
    depth = int(bit_depth or 0)
    return ext in LOSSLESS or (ext in {"m4a", "mp4"} and depth >= 16)


def track_score(file_format, bit_depth, sample_rate, bitrate):
    depth = int(bit_depth or 0)
    kind = 1 if is_lossless(file_format, depth) else 0
    rate = int(sample_rate or 0)
    rate_kbps = min(int(bitrate or 0), 99999)
    return kind * 10**15 + depth * 10**10 + rate * 10**5 + rate_kbps


def album_score(tracks):
    scores = [
        track_score(
            track.get("file_format"),
            track.get("bit_depth"),
            track.get("sample_rate"),
            track.get("bitrate"),
        )
        for track in tracks or []
    ]
    if not scores:
        return 0
    return min(scores)


def format_summary(tracks):
    if not tracks:
        return {"format": "", "bit_depth": None, "sample_rate": None, "bitrate": None}
    weakest = min(
        tracks,
        key=lambda track: track_score(
            track.get("file_format"),
            track.get("bit_depth"),
            track.get("sample_rate"),
            track.get("bitrate"),
        ),
    )
    return {
        "format": str(weakest.get("file_format") or "").lstrip(".").upper(),
        "bit_depth": weakest.get("bit_depth"),
        "sample_rate": weakest.get("sample_rate"),
        "bitrate": weakest.get("bitrate"),
    }


def album_audio(tracks):
    """What the library list shows for an album: formats, bit depth, sample rate (Hz) and bitrate (kb/s).

    The weakest track gives the bit depth and sample rate, the same rule as quality_rank, so the columns
    agree with Upgrade available. The bitrate is the mean of the tracks that report one. `lossless` is true
    only when every track is, and None when the album has no tracks.
    """
    rows = list(tracks or [])
    if not rows:
        return {"format": "", "lossless": None, "bit_depth": None, "sample_rate": None, "bitrate": None}
    weakest = min(
        rows,
        key=lambda track: track_score(
            track.get("file_format"), track.get("bit_depth"), track.get("sample_rate"), track.get("bitrate")
        ),
    )
    counts = {}
    for track in rows:
        name = str(track.get("file_format") or "").lstrip(".").upper()
        if name:
            counts[name] = counts.get(name, 0) + 1
    names = sorted(counts, key=lambda name: (-counts[name], name))
    rates = [int(track["bitrate"]) for track in rows if track.get("bitrate")]
    return {
        "format": "/".join(names),
        "lossless": all(is_lossless(track.get("file_format"), track.get("bit_depth")) for track in rows),
        "bit_depth": weakest.get("bit_depth") or None,
        "sample_rate": weakest.get("sample_rate") or None,
        "bitrate": round(sum(rates) / len(rates)) if rates else None,
    }


_RELEASE_KINDS = {
    "album": "album",
    "studio": "album",
    "studio album": "album",
    "original studio album": "album",
    "single": "single",
    "ep": "ep",
    "compilation": "compilation",
    "live": "live",
    "live album": "live",
}


_REMIX_WORD = re.compile(r"\bremix(?:es|ed)?\b", re.IGNORECASE)
_MIXES_NOTE = re.compile(r"[(\[][^)\]]*\bmixes\b[^)\]]*[)\]]", re.IGNORECASE)
_SPECIAL_WORD = re.compile(
    r"\b(?:deluxe|expanded|anniversary|bonus|special|collector'?s|limited|extended|super\s+deluxe|box\s*set)\b", re.IGNORECASE
)
_rules_cache = {"at": -10.0, "value": {"duplicate": False, "upgrade": False}}


def copy_rules():
    """Whether a special release counts as a copy of the regular one, per relation: {"duplicate": bool, "upgrade":
    bool}, from Settings, Music. Read at most every 2 seconds."""
    now = time.monotonic()
    if now - _rules_cache["at"] > 2:
        try:
            from resonance.settings import load

            cfg = load()
            _rules_cache["value"] = {"duplicate": bool(cfg.get("dup_count_special_releases")),
                                     "upgrade": bool(cfg.get("upgrade_count_special_releases"))}
        except Exception:
            pass
        _rules_cache["at"] = now
    return _rules_cache["value"]


def special_allowed(purpose):
    return bool(copy_rules().get(purpose))


def is_remix(album):
    """A remix album: MusicBrainz release type Remix, or Remix / Remixes / Remixed in the title or edition."""
    row = album or {}
    for key in ("release_type", "releasetype"):
        tokens = re.split(r"[;,/]", str(row.get(key) or "").lower())
        if any(token.strip() == "remix" for token in tokens):
            return True
    text = " ".join(str(row.get(key) or "") for key in ("title", "edition", "version"))
    return bool(_REMIX_WORD.search(text) or _MIXES_NOTE.search(text))


def is_special_edition(album):
    """Deluxe, Expanded, Anniversary, bonus tracks, Special, Collector's, Limited, Extended or a box set."""
    row = album or {}
    text = " ".join(str(row.get(key) or "") for key in ("edition", "version", "title"))
    return bool(_SPECIAL_WORD.search(text))


def _track_count(album):
    for key in ("track_count", "tracks_count"):
        value = (album or {}).get(key)
        if isinstance(value, int) and value > 0:
            return value
    return None


def special_pair(left, right):
    """One of the two is a special release of the other: only one carries an edition word (Deluxe, Expanded, bonus
    tracks...), or both track counts are known and differ (more or fewer tracks)."""
    if is_special_edition(left) != is_special_edition(right):
        return True
    left_count, right_count = _track_count(left), _track_count(right)
    return bool(left_count and right_count and left_count != right_count)


def copy_kind(album, purpose="duplicate"):
    """What albums must share to be grouped as copies of each other: the release kind, and unless Settings, Music
    counts special releases for this relation, whether it is a special edition and how many tracks it has. Hashable."""
    if special_allowed(purpose):
        return (release_kind(album), None, None)
    return (release_kind(album), is_special_edition(album), _track_count(album))


def release_kind(album):
    """Studio album, single, EP, compilation, live album, or remix album."""
    row = album or {}
    if is_remix(row):
        return "remix"
    for key in ("edition", "release_type", "releasetype", "type", "version"):
        raw = row.get(key) or ""
        if key in {"release_type", "releasetype"}:
            raw = str(raw).split(";")[0].split(",")[0]
        token = str(raw).strip().lower()
        if token in _RELEASE_KINDS:
            return _RELEASE_KINDS[token]
    token = str(row.get("type") or "").strip().lower()
    return token or "album"


def same_release_kind(left, right, purpose="duplicate"):
    """Singles match singles, studio albums match studio albums, a remix album matches only remix albums (always).
    A special release (Deluxe and the like, or a different number of tracks) matches the regular release only when
    Settings, Music counts special releases for this relation: purpose "duplicate" or "upgrade"."""
    if release_kind(left) != release_kind(right):
        return False
    if special_pair(left, right) and not special_allowed(purpose):
        return False
    return True


def is_single(album):
    return release_kind(album) == "single"


def same_version(left, right, purpose="upgrade"):
    """Same artist, title, edition, and release type. A higher-quality copy of that version is an upgrade."""
    if not same_release_kind(left, right, purpose):
        return False
    from resonance.fields import norm_name
    from resonance.upgrade import version_label

    if norm_name(left.get("artist_name")) != norm_name(right.get("artist_name")):
        return False
    if norm_name(left.get("title")) != norm_name(right.get("title")):
        return False
    left_version = left.get("version") or version_label(left.get("edition"), "", left.get("type"))
    right_version = right.get("version") or version_label(right.get("edition"), "", right.get("type"))
    return left_version == right_version


def similar_copies(album, peers):
    """Every indexed copy of this version, with the open album first."""
    found = []
    seen = set()
    current_id = str(album.get("id"))
    for peer in list(peers or []) + [album]:
        identity = str(peer.get("id"))
        if identity in seen:
            continue
        if identity != current_id and not same_version(album, peer):
            continue
        seen.add(identity)
        found.append(peer)
    others = [peer for peer in found if str(peer.get("id")) != current_id]
    others.sort(key=lambda peer: (-int(peer.get("quality_rank") or 0), str(peer.get("path") or "")))
    current = next(peer for peer in found if str(peer.get("id")) == current_id)
    return [current] + others


def upgrade_source(album, peers):
    score = int(album.get("quality_rank") or 0)
    best = None
    for peer in peers:
        if str(peer.get("id")) == str(album.get("id")):
            continue
        if not same_version(album, peer):
            continue
        peer_score = int(peer.get("quality_rank") or 0)
        if peer_score > score and (best is None or peer_score > int(best.get("quality_rank") or 0)):
            best = peer
    return best


def higher_copy(album, peers):
    """A better-sounding copy of the same album, including another edition.

    The tree pill uses this. A remaster and the original studio album are not the
    same edition, and the replace button stays off for that pair.
    """
    from resonance.fields import norm_name

    artist = norm_name(album.get("artist_name"))
    title = norm_name(album.get("title"))
    if not artist or not title:
        return None
    score = int(album.get("quality_rank") or 0)
    best = None
    for peer in peers or []:
        if str(peer.get("id")) == str(album.get("id")):
            continue
        if not same_release_kind(album, peer, "upgrade"):
            continue
        if norm_name(peer.get("artist_name")) != artist or norm_name(peer.get("title")) != title:
            continue
        peer_score = int(peer.get("quality_rank") or 0)
        if peer_score > score and (best is None or peer_score > int(best.get("quality_rank") or 0)):
            best = peer
    return best
