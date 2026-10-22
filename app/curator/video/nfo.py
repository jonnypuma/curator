"""Read Kodi movie, tvshow and episode .nfo files.

Kodi allows a scraper URL after the XML. v22 wants one <episodedetails> file per episode.
Older libraries still use one file with several blocks, so the reader pulls out each root block.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET

_CONTROL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def _read_text(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(4 * 1024 * 1024)
    except OSError:
        return ""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return _CONTROL.sub("", text)


def _blocks(text, tag):
    found = []
    for match in re.finditer(rf"<{tag}(?:\s[^>]*)?>[\s\S]*?</{tag}>", text, re.I):
        try:
            found.append(ET.fromstring(match.group(0)))
        except ET.ParseError:
            continue
    return found


def _local(node):
    return node.tag.split("}")[-1].lower()


def _child(root, name):
    for node in root:
        if _local(node) == name:
            return node
    return None


def _text(root, name):
    node = _child(root, name)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _edition_label(value):
    from curator.video.sources import canonical_edition

    return canonical_edition(value)


def _texts(root, name):
    values = []
    seen = set()
    for node in root:
        if _local(node) == name and node.text and node.text.strip():
            for part in node.text.split(" / "):
                part = part.strip()
                key = part.casefold()
                if key and key not in seen:
                    seen.add(key)
                    values.append(part)
    return values


def _int(value):
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


def _float(value):
    if value is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(match.group(0).replace(",", ".")) if match else None


def _year(root):
    for name in ("year", "premiered", "aired", "releasedate"):
        value = _text(root, name)
        if value:
            match = _YEAR.search(value)
            if match:
                return int(match.group(1))
    return None


def _ids(root, legacy_id=None):
    ids = {}
    default = None
    for node in root:
        if _local(node) != "uniqueid" or not node.text or not node.text.strip():
            continue
        kind = (node.attrib.get("type") or "unknown").strip().lower()
        if kind == "themoviedb":
            kind = "tmdb"
        ids[kind] = node.text.strip()
        if str(node.attrib.get("default", "")).lower() == "true":
            default = kind
    for kind in ("imdb", "tmdb", "tvdb"):
        value = _text(root, f"{kind}id")
        if value and kind not in ids:
            ids[kind] = value
    legacy = _text(root, "id")
    if legacy and legacy_id:
        if legacy.startswith("tt"):
            ids.setdefault("imdb", legacy)
        else:
            ids.setdefault(legacy_id, legacy)
    guide = _text(root, "episodeguide")
    if guide and guide.lstrip().startswith("{"):
        try:
            payload = json.loads(guide)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key, value in payload.items():
                kind = str(key or "").strip().lower()
                text = str(value or "").strip()
                if kind and text:
                    ids.setdefault(kind, text)
    return ids, default


def _ratings(root):
    ratings = {}
    default = None
    holder = _child(root, "ratings")
    for node in list(holder) if holder is not None else []:
        if _local(node) != "rating":
            continue
        name = (node.attrib.get("name") or "default").strip().lower()
        if name == "tmdb":
            name = "themoviedb"
        value = _float(_text(node, "value"))
        if value is None:
            continue
        ratings[name] = {
            "value": value,
            "votes": _int(_text(node, "votes")),
            "max": _int(node.attrib.get("max")) or 10,
        }
        if str(node.attrib.get("default", "")).lower() == "true":
            default = name
    legacy = _float(_text(root, "rating"))
    if legacy is not None and not ratings:
        ratings["default"] = {"value": legacy, "votes": _int(_text(root, "votes")), "max": 10}
        default = "default"
    if not default and ratings:
        default = next(iter(ratings))
    return ratings, default


def _actors(root, limit=60):
    actors = []
    for node in root:
        if _local(node) != "actor":
            continue
        name = _text(node, "name")
        if not name:
            continue
        actors.append({
            "name": name,
            "role": _text(node, "role") or "",
            "order": _int(_text(node, "order")),
            "thumb": _text(node, "thumb") or "",
        })
        if len(actors) >= limit:
            break
    actors.sort(key=lambda item: (item["order"] is None, item["order"] or 0))
    return actors


def _set(root):
    node = _child(root, "set")
    if node is None:
        return None
    name = _text(node, "name") or (node.text or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "overview": _text(node, "overview") or "",
        "tmdb_id": (node.attrib.get("tmdbcolid") or "").strip() or None,
    }


def _common(root, legacy_id):
    ids, default_id = _ids(root, legacy_id)
    ratings, default_rating = _ratings(root)
    rating = ratings.get(default_rating) if default_rating else None
    playcount = _int(_text(root, "playcount")) or 0
    watched = (_text(root, "watched") or "").lower() == "true"
    return {
        "title": _text(root, "title"),
        "original_title": _text(root, "originaltitle"),
        "english_title": _text(root, "englishtitle"),
        "sort_title": _text(root, "sorttitle"),
        "year": _year(root),
        "premiered": _text(root, "premiered") or _text(root, "releasedate"),
        "plot": _text(root, "plot"),
        "outline": _text(root, "outline"),
        "tagline": _text(root, "tagline"),
        "runtime": _int(_text(root, "runtime")),
        "mpaa": _text(root, "mpaa"),
        "genres": _texts(root, "genre"),
        "countries": _texts(root, "country"),
        "studios": _texts(root, "studio"),
        "tags": _texts(root, "tag"),
        "directors": _texts(root, "director"),
        "writers": _texts(root, "credits") or _texts(root, "writer"),
        "actors": _actors(root),
        "ids": ids,
        "default_id": default_id,
        "ratings": ratings,
        "rating": rating["value"] if rating else None,
        "votes": rating["votes"] if rating else None,
        "user_rating": _float(_text(root, "userrating")),
        "top250": _int(_text(root, "top250")),
        "playcount": max(playcount, 1 if watched else 0),
        "last_played": _text(root, "lastplayed"),
        "date_added": _text(root, "dateadded"),
        "trailer": _text(root, "trailer"),
        "source": _text(root, "source"),
        "certifications": _certifications(root),
    }


def _certifications(root):
    found = {}
    for node in root:
        if _local(node) != "certification":
            continue
        country = (node.attrib.get("country") or _text(node, "country") or "").upper()
        value = node.attrib.get("value") or _text(node, "value") or (node.text or "")
        value = str(value or "").strip()
        if country and value:
            found[country] = value
    return found


def read_movie(path):
    roots = _blocks(_read_text(path), "movie")
    if not roots:
        return None
    root = roots[0]
    data = _common(root, "tmdb")
    data["set"] = _set(root)
    explicit = _text(root, "edition")
    data["edition"] = _edition_label(explicit or _text(root, "videoassettitle"))
    if data["edition"] == "Standard Edition" and not explicit:
        data["edition"] = None
    return data


def read_show(path):
    roots = _blocks(_read_text(path), "tvshow")
    if not roots:
        return None
    root = roots[0]
    data = _common(root, "tvdb")
    data["show_status"] = _text(root, "status")
    data["original_language"] = _text(root, "originallanguage")
    names = {}
    plots = {}
    for node in root:
        if _local(node) == "namedseason" and node.text and node.text.strip():
            number = _int(node.attrib.get("number"))
            if number is not None:
                names[str(number)] = node.text.strip()
        elif _local(node) == "seasonplot" and node.text and node.text.strip():
            number = _int(node.attrib.get("number"))
            if number is not None:
                plots[str(number)] = node.text.strip()
    data["season_names"] = names
    data["season_plots"] = plots
    return data


def read_season(path):
    roots = _blocks(_read_text(path), "season")
    if not roots:
        return None
    root = roots[0]
    data = _common(root, "tmdb")
    data["season"] = _int(_text(root, "seasonnumber"))
    return data


def read_episodes(path):
    """Every <episodedetails> block in the file, in file order."""
    episodes = []
    for root in _blocks(_read_text(path), "episodedetails"):
        data = _common(root, "tvdb")
        data["season"] = _int(_text(root, "season"))
        data["episode"] = _int(_text(root, "episode"))
        data["display_season"] = _int(_text(root, "displayseason"))
        data["display_episode"] = _int(_text(root, "displayepisode"))
        data["aired"] = _text(root, "aired") or _text(root, "premiered")
        data["thumb"] = _text(root, "thumb")
        resume = _child(root, "resume")
        data["resume_position"] = _float(_text(resume, "position")) if resume is not None else None
        data["resume_total"] = _float(_text(resume, "total")) if resume is not None else None
        episodes.append(data)
    return episodes


def changes(kind, row, text, seasons=None):
    """Fields in the stored .nfo that do not match the database values Curator would write."""
    parsed = _parsed(kind, text, row)
    if parsed is None:
        return {"changes": [], "notes": ["The .nfo could not be read"]}
    current = _current(kind, row or {}, seasons)
    found = []
    for key, label in _DIFF_FIELDS[kind]:
        stored = _cell(parsed.get(key))
        database = _cell(current.get(key))
        if _same(stored, database, zero_blank=key in {"playcount", "votes"}):
            continue
        row_id = str((row or {}).get("id") or "")
        column = "name" if kind == "set" and key == "title" else _KEEP.get(key)
        item = {"label": label, "file": stored, "database": database}
        if column and row_id:
            item.update({"field": column, "kind": kind, "id": row_id})
        found.append(item)
    if kind == "show":
        found.extend(_season_plot_changes(parsed.get("season_plots") or {}, seasons, (row or {}).get("id")))
    return {"changes": found, "notes": []}


_DIFF_FIELDS = {
    "movie": (
        ("title", "Title"), ("original_title", "Original title"), ("sort_title", "Sort title"),
        ("year", "Year"), ("edition", "Edition"), ("tagline", "Tagline"), ("outline", "Outline"),
        ("plot", "Plot"), ("runtime", "Runtime"), ("mpaa", "Certification"), ("premiered", "Premiered"),
        ("genres", "Genres"), ("countries", "Countries"), ("studios", "Studios"), ("tags", "Tags"),
        ("directors", "Directors"), ("writers", "Writers"), ("rating", "Rating"), ("votes", "Votes"),
        ("user_rating", "User rating"), ("top250", "Top 250"),         ("imdb_id", "IMDb id"),
        ("tmdb_id", "TMDB id"), ("trailer", "Trailer"), ("english_title", "English title"),
        ("playcount", "Play count"), ("last_played", "Last played"),
    ),
    "show": (
        ("title", "Title"), ("original_title", "Original title"), ("sort_title", "Sort title"),
        ("year", "Year"), ("tagline", "Tagline"), ("outline", "Outline"), ("plot", "Plot"),
        ("runtime", "Runtime"), ("mpaa", "Certification"), ("premiered", "Premiered"),
        ("show_status", "Status"), ("genres", "Genres"), ("countries", "Countries"),
        ("studios", "Studios"), ("tags", "Tags"), ("directors", "Directors"),
        ("rating", "Rating"), ("votes", "Votes"), ("user_rating", "User rating"), ("top250", "Top 250"),
        ("imdb_id", "IMDb id"), ("tmdb_id", "TMDB id"), ("tvdb_id", "TVDB id"),
        ("original_language", "Original language"), ("english_title", "English title"),
        ("trailer", "Trailer"),
        ("playcount", "Play count"), ("last_played", "Last played"),
    ),
    "season": (
        ("title", "Title"), ("sort_title", "Sort title"), ("plot", "Plot"), ("premiered", "Premiered"),
        ("year", "Year"), ("season_number", "Season"), ("ids", "Ids"),
    ),
    "episode": (
        ("title", "Title"), ("original_title", "Original title"), ("english_title", "English title"),
        ("plot", "Plot"), ("aired", "Aired"), ("season_number", "Season"),
        ("episode_number", "Episode"), ("runtime", "Runtime"), ("directors", "Directors"),
        ("writers", "Writers"), ("mpaa", "Certification"), ("certifications", "Certifications"),
        ("rating", "Rating"), ("votes", "Votes"),
        ("user_rating", "User rating"),
        ("display_season", "Display season"), ("display_episode", "Display episode"),
        ("playcount", "Play count"), ("last_played", "Last played"),
        ("resume_position", "Resume position"), ("resume_total", "Resume length"),
    ),
    "set": (
        ("title", "Title"), ("original_title", "Original title"), ("overview", "Overview"),
    ),
}

# NFO field -> database column a Keep .nfo field button may write.
_KEEP = {
    "title": "title", "original_title": "original_title", "sort_title": "sort_title",
    "year": "year", "edition": "edition", "tagline": "tagline", "outline": "outline",
    "plot": "plot", "overview": "overview", "runtime": "runtime_minutes", "mpaa": "mpaa",
    "premiered": "premiered", "show_status": "show_status", "genres": "genres",
    "countries": "countries", "studios": "studios", "tags": "tags", "directors": "directors",
    "writers": "writers", "rating": "rating", "votes": "votes", "user_rating": "user_rating",
    "top250": "top250", "imdb_id": "imdb_id", "tmdb_id": "tmdb_id", "tvdb_id": "tvdb_id",
    "original_language": "original_language", "english_title": "english_title",
    "trailer": "trailer", "playcount": "playcount",
    "last_played": "last_played", "aired": "aired", "display_season": "display_season",
    "display_episode": "display_episode", "resume_position": "resume_position",
    "resume_total": "resume_total", "certifications": "certifications",
}
_NFO_KEY = {column: key for key, column in _KEEP.items()}
_NFO_KEY["name"] = "title"


def file_field(kind, row, text, field, season_number=None):
    """The raw value of one keepable field in this .nfo. None when the field is absent."""
    parsed = _parsed(kind, text, row)
    if not parsed:
        return None
    if field == "plot" and season_number is not None and kind == "show":
        plots = parsed.get("season_plots") or {}
        number = str(season_number)
        if number not in plots:
            return None
        return plots[number]
    key = _NFO_KEY.get(field, field)
    if key not in parsed:
        return None
    return parsed.get(key)


def _parsed(kind, text, row):
    if kind == "movie":
        data = None
        roots = _blocks(text or "", "movie")
        if roots:
            data = _common(roots[0], "tmdb")
            # "Standard Edition" in videoassettitle is what the writer puts there when the movie has no
            # edition, so it is not an edition the user set.
            asset = _text(roots[0], "videoassettitle")
            if str(asset or "").strip().lower() == "standard edition":
                asset = None
            data["edition"] = _edition_label(_text(roots[0], "edition") or asset)
        return _from_common(data) if data else None
    if kind == "show":
        data = None
        roots = _blocks(text or "", "tvshow")
        if roots:
            data = _common(roots[0], "tvdb")
            data["show_status"] = _text(roots[0], "status")
            data["original_language"] = _text(roots[0], "originallanguage")
            plots = {}
            for node in roots[0]:
                if _local(node) == "seasonplot" and node.text and node.text.strip():
                    number = _int(node.attrib.get("number"))
                    if number is not None:
                        plots[str(number)] = node.text.strip()
            data["season_plots"] = plots
        return _from_common(data) if data else None
    if kind == "season":
        roots = _blocks(text or "", "season")
        if not roots:
            return None
        data = _from_common(_common(roots[0], "tmdb"))
        data["season_number"] = _int(_text(roots[0], "seasonnumber"))
        return data
    if kind == "episode":
        blocks = []
        for root in _blocks(text or "", "episodedetails"):
            data = _common(root, "tvdb")
            data["season_number"] = _int(_text(root, "season"))
            data["episode_number"] = _int(_text(root, "episode"))
            data["aired"] = _text(root, "aired") or _text(root, "premiered")
            data["display_season"] = _int(_text(root, "displayseason"))
            data["display_episode"] = _int(_text(root, "displayepisode"))
            resume = _child(root, "resume")
            data["resume_position"] = _float(_text(resume, "position")) if resume is not None else None
            data["resume_total"] = _float(_text(resume, "total")) if resume is not None else None
            blocks.append(data)
        if not blocks:
            return None
        wanted = (row or {}).get("season_number"), (row or {}).get("episode_number")
        for block in blocks:
            if (block.get("season_number"), block.get("episode_number")) == wanted:
                return block
        return blocks[0]
    if kind == "set":
        roots = _blocks(text or "", "set")
        if not roots:
            return None
        root = roots[0]
        return {
            "title": _text(root, "title"),
            "original_title": _text(root, "originaltitle"),
            "overview": _text(root, "overview"),
        }
    return None


def _from_common(data):
    ids = data.get("ids") or {}
    data["imdb_id"] = ids.get("imdb")
    data["tmdb_id"] = ids.get("tmdb")
    data["tvdb_id"] = ids.get("tvdb")
    return data


def _season_plot_changes(file_plots, seasons, show_id=None):
    database = {}
    owners = {}
    for season in seasons or []:
        number = season.get("season_number")
        plot = str(season.get("plot") or "").strip()
        if number is None:
            continue
        key = str(number)
        if plot:
            database[key] = plot
        if season.get("id"):
            owners[key] = str(season["id"])
    numbers = sorted(set(file_plots) | set(database), key=lambda item: int(item) if str(item).lstrip("-").isdigit() else 0)
    rows = []
    for number in numbers:
        stored = str(file_plots.get(number) or "").strip()
        current = database.get(number) or ""
        if not stored or stored == current:
            continue
        item = {"label": f"Season {number} plot", "file": stored, "database": current}
        if owners.get(number) and show_id:
            item.update({
                "field": "plot", "kind": "season", "id": owners[number],
                "from_kind": "show", "from_id": str(show_id),
            })
        rows.append(item)
    return rows


def _current(kind, row, seasons):
    ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
    current = {
        "title": row.get("title") or row.get("name"),
        "original_title": row.get("original_title"),
        "english_title": row.get("english_title"),
        "sort_title": row.get("sort_title"),
        "year": row.get("year"),
        "edition": _edition_label(row.get("edition")),     # a stored NONE means no edition
        "tagline": row.get("tagline"),
        "outline": row.get("outline"),
        "plot": row.get("plot") or row.get("overview"),
        "overview": row.get("overview"),
        "runtime": row.get("runtime_minutes"),
        "mpaa": row.get("mpaa"),
        "certifications": row.get("certifications"),
        "premiered": row.get("premiered"),
        "show_status": row.get("show_status"),
        "genres": row.get("genres"),
        "countries": row.get("countries"),
        "studios": row.get("studios"),
        "tags": row.get("tags"),
        "directors": row.get("directors"),
        "writers": row.get("writers"),
        "rating": row.get("rating"),
        "votes": row.get("votes"),
        "user_rating": row.get("user_rating"),
        "top250": row.get("top250"),
        "imdb_id": row.get("imdb_id") or ids.get("imdb"),
        "tmdb_id": row.get("tmdb_id") or row.get("tmdb_collection_id") or ids.get("tmdb"),
        "tvdb_id": row.get("tvdb_id") or ids.get("tvdb"),
        "original_language": row.get("original_language"),
        "trailer": row.get("trailer"),
        "playcount": row.get("playcount"),
        "last_played": row.get("last_played"),
        "aired": row.get("aired"),
        "season_number": row.get("season_number"),
        "episode_number": row.get("episode_number"),
        "ids": ids,
        "display_season": row.get("display_season"),
        "display_episode": row.get("display_episode"),
        "resume_position": row.get("resume_position"),
        "resume_total": row.get("resume_total"),
    }
    rating, votes = _written_score(row)
    current["rating"] = rating
    current["votes"] = votes
    return current


def _preferred_rating():
    """The rating name written into an .nfo as the default."""
    try:
        from curator.video.config import current as video_config
        return (video_config() or {}).get("default_rating") or "themoviedb"
    except Exception:
        return "themoviedb"


def _written_score(row):
    """Rating and votes Curator writes. The single rating column can lag the ratings list."""
    ratings = row.get("ratings") if isinstance(row.get("ratings"), dict) else None
    if not ratings:
        return row.get("rating"), row.get("votes")
    from curator.scrapers.merge import default_rating
    value, votes = default_rating(ratings, _preferred_rating())
    if value is None:
        return row.get("rating"), row.get("votes")
    return value, votes if votes is not None else row.get("votes")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(
            f"{key} {value[key]}" for key in sorted(value) if value[key] not in (None, "", [])
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    if number == int(number) and "e" not in text.lower():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _same(stored, database, zero_blank=False):
    if zero_blank and stored in {"", "0"} and database in {"", "0"}:
        return True
    return stored.lower() == database.lower()


def named_changes(prefix, rows):
    """Prefix each diff row so a show modal can name the season or episode."""
    return [{**row, "label": f"{prefix} · {row['label']}"} for row in rows or []]


def mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
