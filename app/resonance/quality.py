LOSSLESS = {"flac", "wav", "aiff", "aif", "alac", "ape", "wv"}


def track_score(file_format, bit_depth, sample_rate, bitrate):
    ext = str(file_format or "").lower().lstrip(".")
    depth = int(bit_depth or 0)
    lossless = ext in LOSSLESS or (ext in {"m4a", "mp4"} and depth >= 16)
    kind = 1 if lossless else 0
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


def release_kind(album):
    """Studio album, single, EP, compilation, or live album."""
    row = album or {}
    for key in ("edition", "release_type", "releasetype", "type", "version"):
        raw = row.get(key) or ""
        if key in {"release_type", "releasetype"}:
            raw = str(raw).split(";")[0].split(",")[0]
        token = str(raw).strip().lower()
        if token in _RELEASE_KINDS:
            return _RELEASE_KINDS[token]
    token = str(row.get("type") or "").strip().lower()
    return token or "album"


def same_release_kind(left, right):
    """Singles match singles, studio albums match studio albums, and so on."""
    return release_kind(left) == release_kind(right)


def is_single(album):
    return release_kind(album) == "single"


def same_version(left, right):
    """Same artist, title, edition, and release type. A higher-quality copy of that version is an upgrade."""
    if not same_release_kind(left, right):
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
        if not same_release_kind(album, peer):
            continue
        if norm_name(peer.get("artist_name")) != artist or norm_name(peer.get("title")) != title:
            continue
        peer_score = int(peer.get("quality_rank") or 0)
        if peer_score > score and (best is None or peer_score > int(best.get("quality_rank") or 0)):
            best = peer
    return best
