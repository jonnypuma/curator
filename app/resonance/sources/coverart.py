from resonance.sources.client import get_json


def images_for_release(release_id):
    if not release_id:
        return []
    data = get_json(f"https://coverartarchive.org/release/{release_id}")
    return _images(data)


def images_for_group(release_group_id):
    if not release_group_id:
        return []
    data = get_json(f"https://coverartarchive.org/release-group/{release_group_id}")
    return _images(data)


def _images(data):
    rows = []
    for image in (data or {}).get("images") or []:
        url = image.get("image")
        if not url:
            continue
        thumbs = image.get("thumbnails") or {}
        edge = 0
        for key in thumbs:
            try:
                edge = max(edge, int(key))
            except ValueError:
                continue
        types = [item.lower() for item in image.get("types") or []]
        rows.append(
            {
                "url": url,
                "types": types,
                "front": bool(image.get("front")),
                "back": bool(image.get("back")),
                "comment": str(image.get("comment") or ""),
                "edge": edge or None,
            }
        )
    return rows
