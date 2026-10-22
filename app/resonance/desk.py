"""Pure helpers for the command palette and the match aligner."""


def duration_tone(local_seconds, remote_seconds):
    try:
        local = int(local_seconds or 0)
        remote = int(remote_seconds or 0)
    except (TypeError, ValueError):
        return ""
    if remote <= 0:
        return ""
    if abs(local - remote) > 3:
        return "danger"
    return "ok"


def palette_items(query, actions, artists):
    text = (query or "").strip()
    action_rows = [
        {"kind": "action", "id": item["id"], "label": item["label"]}
        for item in actions or []
    ]
    if not text or text == ">":
        return action_rows
    if text.startswith(">"):
        needle = text[1:].strip().lower()
        if not needle:
            return action_rows
        return [
            row
            for row in action_rows
            if needle in row["label"].lower() or needle in row["id"].lower()
        ]
    needle = text.lower()
    rows = []
    for artist in artists or []:
        name = artist.get("name") or ""
        if needle in name.lower():
            rows.append({"kind": "artist", "id": str(artist.get("id") or ""), "label": name})
        for album in artist.get("albums") or []:
            title = album.get("title") or ""
            if needle in title.lower() or needle in name.lower():
                rows.append(
                    {
                        "kind": "album",
                        "id": str(album.get("id") or ""),
                        "label": title,
                        "hint": name,
                    }
                )
    return rows
