"""Switch the default audio of a dubbed release back to the original language.

A dual-language release (German.DL, DL.French, Italian.DUBBED) often marks the dubbed track as the
default. The original language comes from the scrape (movies.original_language and
tv_shows.original_language) first. When it is unknown, the release name names the dubbed
language and the one other audio language is taken as the original.

After the audio is switched, the default subtitle follows the preferred subtitle languages
(Settings, Files) in priority order. A file whose default tracks were set by hand is left alone.
Only MKV files are changed, with mkvpropedit, which rewrites the flag in place.
"""
from __future__ import annotations

import os
import re

from curator.video.languages import _LANG_ALIASES, language_label, normalize_lang

# Words a release name uses for a language: English names, and the short codes that sit next to DL.
_EXTRA_WORDS = {
    "truefrench": "fra", "vff": "fra", "vfq": "fra", "flemish": "nld", "castellano": "spa", "latino": "spa",
    "tamil": "tam", "telugu": "tel", "malayalam": "mal", "kannada": "kan", "bengali": "ben", "punjabi": "pan",
    "urdu": "urd", "persian": "per", "farsi": "per", "indonesian": "ind", "malay": "may", "catalan": "cat",
    "tagalog": "tgl", "filipino": "tgl", "mandarin": "chi", "cantonese": "chi",
}
_LANG_WORDS = {
    **{key: value for key, value in _LANG_ALIASES.items() if key.isalpha() and len(key) >= 3 and value != "und"},
    **_EXTRA_WORDS,
}
_DUB_MARKS = {"dl", "dubbed", "dub"}
_SPLIT = re.compile(r"[^a-z0-9]+")


def detect_dub(*names):
    """What a release name says about dubbing: {"dubbed": bool, "lang": code or ""}.

    GERMAN.DL, DL.GERMAN, GERMAN.DUBBED and DUBBED.GERMAN name the dubbed language. MULTI and
    DUAL (or DUAL.AUDIO) only say the file has more than one language.
    """
    loose = False
    for name in names:
        tokens = [token for token in _SPLIT.split(str(name or "").lower()) if token]
        for index, token in enumerate(tokens):
            after = tokens[index + 1] if index + 1 < len(tokens) else ""
            before = tokens[index - 1] if index else ""
            if token in _DUB_MARKS:
                for word in (before, after):
                    if word in _LANG_WORDS:
                        return {"dubbed": True, "lang": _LANG_WORDS[word]}
            if token == "multi" and not after.startswith("sub"):
                loose = True
            if token == "dual" and not after.startswith("sub"):
                loose = True
    return {"dubbed": loose, "lang": ""}


# Languages the shared alias table does not list. TMDB gives two-letter codes (ta, te, fa) and MKV tracks carry
# three-letter ones (tam, tel, per), so without this a Tamil film never matches its Tamil track. TMDB's "cn" is
# Cantonese, which MKV files tag as chi or yue.
_MORE_CODES = {
    "ta": "tam", "te": "tel", "ml": "mal", "kn": "kan", "bn": "ben", "mr": "mar", "pa": "pan", "gu": "guj", "ur": "urd",
    "fa": "per", "fas": "per", "id": "ind", "ms": "may", "msa": "may", "tl": "tgl", "fil": "tgl", "ca": "cat",
    "eu": "baq", "eus": "baq", "gl": "glg", "cy": "wel", "cym": "wel", "ga": "gle", "sq": "alb", "sqi": "alb",
    "mk": "mac", "mkd": "mac", "bs": "bos", "ka": "geo", "kat": "geo", "hy": "arm", "hye": "arm", "az": "aze",
    "kk": "kaz", "uz": "uzb", "mn": "mon", "ne": "nep", "si": "sin", "km": "khm", "lo": "lao", "my": "bur",
    "mya": "bur", "sw": "swa", "af": "afr", "am": "amh", "la": "lat", "cn": "chi", "yue": "chi",
}


def _code(value):
    code = normalize_lang(value or "")
    return _MORE_CODES.get(code, code)


def _lang(track):
    return _code((track or {}).get("lang") or "")


def _commentary(track):
    text = f"{(track or {}).get('title') or ''} {' '.join((track or {}).get('flags') or [])}".lower()
    return "comment" in text


def _sole_default(tracks, kind):
    """The track a player uses. Audio with no flag plays the first track. Subtitles stay off."""
    rows = list(tracks or [])
    for index, track in enumerate(rows):
        if track.get("default"):
            return index
    return 0 if kind == "audio" and rows else None


def _defaults(tracks):
    return [index for index, track in enumerate(tracks or []) if track.get("default")]


def original_audio(audio, original, dub):
    """(language, reason) the default audio should be in. Empty language when it cannot be told."""
    langs = []
    for track in audio or []:
        code = _lang(track)
        if code and code != "und" and code not in langs:
            langs.append(code)
    original = _code(original)
    if original and original != "und":
        if original in langs:
            return original, "original language"
        return "", f"no {language_label(original) or original} audio track"
    if not dub.get("dubbed"):
        return "", "no original language and the name does not say it is dubbed"
    if not dub.get("lang"):
        return "", "the name says MULTI or DUAL but not which language is dubbed"
    others = [code for code in langs if code != dub["lang"]]
    if len(others) == 1 and dub["lang"] in langs:
        return others[0], f"the name marks {language_label(dub['lang'])} as dubbed"
    return "", "the audio languages do not show which one is the original"


def audio_index(audio, lang):
    """The first track in this language that is not a commentary."""
    matches = [index for index, track in enumerate(audio or []) if _lang(track) == lang]
    plain = [index for index in matches if not _commentary(audio[index])]
    return (plain or matches or [None])[0]


def _sub_rank(track):
    flags = {str(flag).lower() for flag in (track.get("flags") or [])}
    if "forced" in flags:
        return 2
    if "sdh" in flags or "hi" in flags:
        return 1
    return 0


def subtitle_choice(subs, audio_lang, preferred):
    """The subtitle index to make the default, or None for no default subtitle.

    The first preferred language with a full (or SDH) track wins. When the audio is in one of the
    preferred languages, only a forced track in that language may be chosen, so a film in your
    own language does not get full subtitles.
    """
    subs = list(subs or [])
    preferred = [_code(code) for code in preferred or [] if _code(code)]
    if audio_lang in preferred:
        forced = [index for index, track in enumerate(subs) if _lang(track) == audio_lang and _sub_rank(track) == 2]
        return forced[0] if forced else None
    for code in preferred:
        found = sorted(
            (index for index, track in enumerate(subs) if _lang(track) == code and _sub_rank(track) < 2),
            key=lambda index: (_sub_rank(subs[index]), index),
        )
        if found:
            return found[0]
    return None


def plan(audio, subs, original, names, preferred):
    """What to write: {"audio": index or None, "subtitle": index, "clear" or None, "lang": code, "note": text}.

    Subtitles are only touched when the audio is switched, or when the name says the release is dubbed.
    """
    dub = detect_dub(*names)
    lang, reason = original_audio(audio, original, dub)
    result = {"audio": None, "subtitle": None, "lang": lang, "note": reason}
    if not lang:
        return result
    index = audio_index(audio, lang)
    current = _sole_default(audio, "audio")
    if index is not None and (current is None or _lang(audio[current]) != lang or len(_defaults(audio)) > 1):
        result["audio"] = index
    if result["audio"] is None and not dub.get("dubbed"):
        result["note"] = "the default audio is already the original language"
        return result
    pick = subtitle_choice(subs, lang, preferred)
    flagged = _defaults(subs)
    if pick is None:
        if flagged:
            result["subtitle"] = "clear"
    elif flagged != [pick]:
        result["subtitle"] = pick
    if result["audio"] is None and result["subtitle"] is None:
        result["note"] = "the default tracks are already right"
    return result


def describe(item_plan, audio, subs):
    """Lines for the job log and the preview: ("Audio: German", "Audio: English (original language)")."""
    rows = []
    if item_plan.get("audio") is not None:
        before = _sole_default(audio, "audio")
        old = language_label(_lang(audio[before])) if before is not None else "none"
        rows.append((f"Audio: {old}", f"Audio: {language_label(item_plan['lang'])} ({item_plan['note']})"))
    choice = item_plan.get("subtitle")
    if choice is not None:
        before = _sole_default(subs, "subtitle")
        old = _sub_label(subs[before]) if before is not None else "none"
        new = "none" if choice == "clear" else _sub_label(subs[choice])
        rows.append((f"Subtitle: {old}", f"Subtitle: {new}"))
    return rows


def _sub_label(track):
    flags = [str(flag).capitalize() for flag in (track.get("flags") or []) if str(flag).lower() in {"forced", "sdh", "hi"}]
    return " ".join([language_label(_lang(track)) or "Unknown", *flags])


def user_set(file_row):
    """True when the default tracks were last set by hand and the file has not changed since."""
    mark = (file_row or {}).get("user_default_size")
    return mark is not None and mark == (file_row or {}).get("size_bytes")


def enabled(cfg, kind):
    key = "orig_lang_movies" if kind == "movie" else "orig_lang_tv"
    return bool((cfg or {}).get(key))


def targets(kind, ids):
    """One row per video file: the file, its original language and the names to read."""
    from resonance import db

    ids = [str(item) for item in ids or []]
    if not ids:
        return []
    if kind == "movie":
        rows = db.fetchall(
            """
            SELECT m.id::text AS item_id, 'movie' AS kind, m.title AS label, m.original_language,
                   vf.id::text AS file_id, vf.path, vf.size_bytes, vf.user_default_size, vf.audio_tracks, vf.subtitle_tracks
            FROM movies m JOIN video_files vf ON vf.id = m.file_id
            WHERE m.id = ANY(%s::uuid[]) AND m.disc_format IS NULL
            """,
            (ids,),
        )
    else:
        column = {"show": "e.show_id", "season": "e.season_id"}.get(kind, "e.id")
        rows = db.fetchall(
            f"""
            SELECT e.id::text AS item_id, 'episode' AS kind,
                   s.title || ' S' || lpad(e.season_number::text, 2, '0') || 'E' || lpad(e.episode_number::text, 2, '0') AS label,
                   s.original_language,
                   vf.id::text AS file_id, vf.path, vf.size_bytes, vf.user_default_size, vf.audio_tracks, vf.subtitle_tracks
            FROM tv_episodes e JOIN tv_shows s ON s.id = e.show_id JOIN video_files vf ON vf.id = e.file_id
            WHERE {column} = ANY(%s::uuid[]) AND NOT e.missing
            ORDER BY s.title, e.season_number, e.episode_number
            """,
            (ids,),
        )
    seen, found = set(), []
    for row in rows:
        if row["file_id"] in seen:
            continue
        seen.add(row["file_id"])
        found.append(row)
    return found


def _names(path):
    folder = os.path.dirname(path or "")
    return [os.path.basename(path or ""), os.path.basename(folder)]


def file_plan(row, cfg, manual=False):
    """The plan for one target row, or (None, reason) when the file is left alone."""
    path = row.get("path") or ""
    if os.path.splitext(path)[1].lower() != ".mkv":
        return None, "not an MKV file, it needs a remux"
    if not manual and user_set(row):
        return None, "the default tracks were set by hand"
    audio = row.get("audio_tracks") or []
    if len(audio) < 2:
        return None, "only one audio track"
    item_plan = plan(audio, row.get("subtitle_tracks") or [], row.get("original_language"), _names(path),
                     (cfg or {}).get("sub_pref_langs") or [])
    if item_plan["audio"] is None and item_plan["subtitle"] is None:
        return None, item_plan["note"]
    return item_plan, ""


def preview(kind, ids, cfg):
    """The changes a run would make, in the file job preview layout."""
    plans, moves = [], 0
    for row in targets(kind, ids):
        item_plan, reason = file_plan(row, cfg, manual=True)
        if not item_plan:
            continue
        lines = describe(item_plan, row.get("audio_tracks") or [], row.get("subtitle_tracks") or [])
        moves += len(lines)
        plans.append({"title": row["label"], "error": None,
                      "moves": [{"from": old, "to": new, "dir": False} for old, new in lines]})
    return plans, moves


def apply(row, cfg, log, manual=False):
    """Write the default flags for one file. Returns True when the file changed."""
    from curator.video import reprobe, tracks

    item_plan, reason = file_plan(row, cfg, manual)
    if not item_plan:
        if manual:
            log(f"{row['label']}: left alone, {reason}")
        return False
    audio = row.get("audio_tracks") or []
    subs = row.get("subtitle_tracks") or []
    lines = describe(item_plan, audio, subs)
    if item_plan["audio"] is not None:
        tracks.apply(row["path"], "audio", item_plan["audio"], audio)
    if item_plan["subtitle"] == "clear":
        tracks.clear(row["path"], "subtitle", subs)
    elif item_plan["subtitle"] is not None:
        tracks.apply(row["path"], "subtitle", item_plan["subtitle"], subs)
    reprobe.refresh(row["kind"], [row["item_id"]])
    log(f"{row['label']}: " + ", ".join(f"{old} to {new.split(': ', 1)[1]}" for old, new in lines))
    return True


def after_import(kind, ids, log):
    """Run on freshly imported movies or episodes when the switch for that media is on."""
    from curator.video import config

    cfg = config.current()
    if not enabled(cfg, kind):
        return 0
    changed = 0
    for row in targets(kind, ids):
        try:
            changed += bool(apply(row, cfg, log))
        except Exception as exc:
            log(f"{row['label']}: could not switch to the original language: {exc}")
    return changed
