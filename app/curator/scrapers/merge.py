"""Combine scraper results in chain order, then decide what reaches the database under the overwrite policy."""
from __future__ import annotations

UNION = {"ids", "ratings", "season_names", "certifications"}
SKIP = {"source", "art", "seasons", "episodes", "set", "mpaa_fallback", "awards"}


def empty(value):
    return value is None or value == "" or value == [] or value == {}


def unique_names(value):
    """Keep the first spelling of each name. Repeated studios stay one entry."""
    if not isinstance(value, list):
        return value
    seen = set()
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            cleaned.append(item)
            continue
        text = item.strip()
        key = text.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def combine(results):
    """Field-level merge. The first source in the chain that has a value wins; ids and ratings are unioned."""
    merged = {"sources": [], "art": [], "seasons": {}}
    for result in results:
        if not result:
            continue
        merged["sources"].append(result.get("source"))
        for key, value in result.items():
            if key in SKIP:
                continue
            if key in UNION:
                bucket = merged.setdefault(key, {})
                for name, item in (value or {}).items():
                    if not empty(item):
                        bucket.setdefault(name, item)
            elif empty(merged.get(key)) and not empty(value):
                merged[key] = unique_names(value) if key == "studios" else value
        if result.get("set") and not merged.get("set"):
            merged["set"] = result["set"]
        if result.get("mpaa_fallback") and empty(merged.get("mpaa_fallback")):
            merged["mpaa_fallback"] = result["mpaa_fallback"]
        merged["art"].extend(result.get("art") or [])
        for number, season in (result.get("seasons") or {}).items():
            target = merged["seasons"].setdefault(number, {"art": []})
            for key, value in season.items():
                if key == "art":
                    target["art"].extend(value or [])
                elif key == "ids" and isinstance(value, dict):
                    bucket = target.setdefault("ids", {})
                    for name, item in value.items():
                        if not empty(item):
                            bucket.setdefault(name, item)
                elif empty(target.get(key)) and not empty(value):
                    target[key] = value
    if empty(merged.get("mpaa")) and merged.get("mpaa_fallback"):
        merged["mpaa"] = merged["mpaa_fallback"]
    merged.pop("mpaa_fallback", None)
    return merged


def default_rating(ratings, preferred):
    if not ratings:
        return None, None
    name = preferred if preferred in ratings else next(iter(ratings))
    item = ratings[name]
    value = item.get("value")
    if value is not None and (item.get("max") or 10) != 10:
        value = round(float(value) * 10 / float(item["max"]), 1)
    return value, item.get("votes")


def updates(current, scraped, fields, policy, locked_fields=()):
    """Column values to write. overwrite replaces anything the scrape has; merge and missing only fill blanks.
    ids and ratings are always unioned, with fresh values replacing old ones under overwrite."""
    locked = set(locked_fields or ())
    out = {}
    for field in fields:
        if field in locked or field not in scraped:
            continue
        new = unique_names(scraped[field]) if field == "studios" else scraped[field]
        if empty(new):
            continue
        old = current.get(field)
        if field in UNION:
            if policy == "overwrite":
                combined = {**(old or {}), **new}
            else:
                combined = {**new, **(old or {})}
            if combined != (old or {}):
                out[field] = combined
            continue
        if policy == "overwrite" or empty(old):
            if new != old:
                out[field] = new
    return out


def _wanted_langs(langs, lang):
    """Ordered artwork languages. Blank slots are unused. "none" is textless. None keeps the older ranking."""
    if langs is None:
        return None
    wanted = []
    for item in langs:
        text = str(item or "").strip().lower()
        if not text:
            continue
        if text in {"none", "textless", "null"}:
            wanted.append("")
        else:
            wanted.append(text.split("-")[0][:2])
    return wanted or [str(lang or "en").split("-")[0]]


def rank_art(candidates, kind, *, lang, sources, min_width=0, langs=None):
    """Candidates for one Kodi art type, best first.

    Images known to be under the minimum width are skipped while anything else remains.
    When every image is smaller, the largest of those is used.
    """
    order = {name: index for index, name in enumerate(sources)}
    wanted = _wanted_langs(langs, lang)
    eligible, smaller = [], []
    for item in candidates:
        if item.get("kind") != kind:
            continue
        width = item.get("width") or 0
        if min_width and width and width < min_width:
            smaller.append(item)
        else:
            eligible.append(item)

    def key(item):
        item_lang = item.get("lang") or ""
        if wanted is None:
            if kind == "fanart":
                lang_rank = 0 if not item_lang else (1 if item_lang == lang else 2)
            else:
                lang_rank = 0 if item_lang == lang else (1 if not item_lang else (2 if item_lang == "en" else 3))
        else:
            try:
                lang_rank = wanted.index(item_lang)
            except ValueError:
                lang_rank = len(wanted) if not item_lang else len(wanted) + 1
        return (lang_rank, order.get(item.get("source"), 99), -(item.get("score") or 0), -(item.get("width") or 0))

    pool = eligible or smaller
    return sorted(pool, key=key)
