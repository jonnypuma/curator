"""Album matching score.

Picard weights title, artist, album, length, track count, and release type to
decide which album a set of files belongs to. Release country and format stay
out of that score so two pressings of one release group remain a choice.
"""

from difflib import SequenceMatcher

from resonance.fields import norm_name, release_type

# Picard similarity weights. Country and format are intentionally absent.
WEIGHTS = {
    "title": 13,
    "artist": 4,
    "album": 5,
    "length": 10,
    "totaltracks": 4,
    "releasetype": 20,
}
LENGTH_TOLERANCE = 2
ACOUSTID_BONUS = 110
IDENTIFIED_BONUS = 1000


def text_similarity(left, right):
    first = norm_name(left)
    second = norm_name(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    return SequenceMatcher(None, first, second).ratio()


def length_similarity(local_seconds, remote_seconds):
    local = _positive_int(local_seconds)
    remote = _positive_int(remote_seconds)
    if local is None or remote is None:
        return None
    diff = abs(local - remote)
    if diff <= LENGTH_TOLERANCE:
        return 1.0
    return max(0.0, 1.0 - (diff - LENGTH_TOLERANCE) / 30.0)


def track_count_similarity(local_count, remote_count):
    local = _positive_int(local_count)
    remote = _positive_int(remote_count)
    if local is None or remote is None:
        return None
    if local == remote:
        return 1.0
    return max(0.0, 1.0 - abs(local - remote) / max(local, remote))


def type_similarity(local_type, remote_type):
    local = release_type(local_type) if local_type else "unknown"
    remote = release_type(remote_type) if remote_type else "unknown"
    if local == "unknown" or remote == "unknown":
        return None
    return 1.0 if local == remote else 0.0


def match_percent(parts):
    """Metadata similarity as a whole percent from 0 to 100."""
    return max(0, min(100, int(round(metadata_score(parts)))))


def metadata_score(parts):
    """Weighted similarity from 0 to 100. Missing parts are left out of the weight."""
    numerator = 0.0
    denominator = 0.0
    for key, similarity in (parts or {}).items():
        if similarity is None or key not in WEIGHTS:
            continue
        weight = WEIGHTS[key]
        numerator += float(similarity) * weight
        denominator += weight
    if not denominator:
        return 0.0
    return 100.0 * numerator / denominator


def release_score(parts, acoustid=False, identified=False):
    score = metadata_score(parts)
    if acoustid:
        score += ACOUSTID_BONUS
    if identified:
        score += IDENTIFIED_BONUS
    return score


def track_evidence(local_tracks, remote_tracks):
    """Average title and length similarity, plus the mean duration gap in seconds."""
    if not local_tracks or not remote_tracks:
        return None, None, None
    titles = []
    lengths = []
    gaps = []
    used = set()
    for track in local_tracks:
        best_index = None
        best_similarity = -1.0
        for index, remote in enumerate(remote_tracks):
            if index in used:
                continue
            similarity = text_similarity(track.get("title"), remote.get("title"))
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index
        if best_index is None:
            continue
        used.add(best_index)
        titles.append(max(0.0, best_similarity))
        local_length = _positive_int(track.get("duration_seconds"))
        remote_length = _positive_int(remote_tracks[best_index].get("duration_seconds"))
        if local_length is None or remote_length is None:
            continue
        gaps.append(abs(local_length - remote_length))
        similarity = length_similarity(local_length, remote_length)
        if similarity is not None:
            lengths.append(similarity)
    title = sum(titles) / len(titles) if titles else None
    length = sum(lengths) / len(lengths) if lengths else None
    distance = sum(gaps) / len(gaps) if gaps else None
    return title, length, distance


def edition_order(candidate):
    """Closest track count, then measured duration. Country and format do not decide."""
    try:
        duration_key = float(candidate.get("duration_distance"))
        measured = 0
    except (TypeError, ValueError):
        duration_key = 0.0
        measured = 1
    return (
        0 if candidate.get("locked") else 1,
        0 if candidate.get("disc_match") else 1,
        abs(int(candidate.get("track_count") or 0) - int(candidate.get("local_tracks") or 0)),
        measured,
        duration_key,
        0 if candidate.get("status") == "Official" else 1,
        int(candidate.get("year") or 9999),
    )


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number
