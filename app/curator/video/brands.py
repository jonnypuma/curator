"""Match a network, studio, or record label name to a logo in media/.

Names that only differ by spacing, punctuation, or a known spelling (Apple TV+, ATV,
Sky Showtime) share one icon. A name with no logo is left out.
"""
from __future__ import annotations

import os
import re
import threading
import unicodedata
from urllib.parse import quote

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "media")
_FOLDERS = {
    "network": "network", "studios": "studios", "codecs": "codecs", "format": "format",
    "recordlabels": "recordlabels", "resolution": "resolution", "aspectratios": "aspectratios",
    "audiochannels": "audiochannels", "audiochannels_room": "audiochannels_room",
}
_LABEL_SUFFIXES = ("recordings", "records", "recording", "musicgroup", "music", "label")
_lock = threading.Lock()
_tables: dict[str, dict[str, str]] = {}

# Folded name -> preferred folded icon, tried before the name's own file.
_PREFERRED = {
    "atv": "appleplus",
    "hannabarberacartoons": "hannabarbera",
    "illumination": "illuminationentertainment",
    "20thcenturyfoxanimation": "20thcenturystudiosanimation",
    "alibabapicturesgroup": "alibaba",
    "canalpluspolska": "canalplus",
    "studiocanaluk": "studiocanal",
    "tf1filmsproduction": "tf1filmsproductions",
    "sfstudios": "sf",
    "marvelknights": "marvelstudios",
    "marvelentertainmentgroup": "marvelstudios",
    "cartoonnetworkmovies": "cartoonnetwork",
    "starzanimation": "starz",
    "spyglassmediagroup": "spyglassentertainment",
    "amblinpartners": "amblinentertainment",
    "annapurnafilms": "annapurnapictures",
    "lionsgatepremiere": "lionsgate",
    "dcstudios": "dcentertainment",
    "dcfilms": "dcentertainment",
    "amazonkidsplus": "amazonkids",
    "dcuniverse": "dc",
    "thecomedychannel": "thecomedyhannel",
    "tv3ie": "tv3ireland",
    "yahooscreen": "yahoo",
    "xboxvideo": "xbox",
    "dailywireplus": "dailywire",
    "caracoltv": "caracoltelevision",
    "animefriend": "animefriends",
    "fr3": "france3",
    "antenne2": "france2",
    "seoulbroadcastingsystem": "sbskr",
    "universaltelevisionentertainment": "universal",
    "universaltelevision": "universal",
    "tv3estonia": "tv3no",
    "danmarksradiodr": "dr",
    "abctv": "abc",
    "skydeutschland": "sky",
    "amazonfreevee": "freevee",
    "thehub": "hub",
    "boomerang": "boomeranghdus",
    "appletv": "appleplus",
    "appletvplus": "appleplus",
    "appletelevision": "appleplus",
    "appletvplusus": "appleplus",
}
# Extra folded keys to try after the name itself.
_ALIASES = {
    "primevideo": ("prime", "amazon"),
    "amazonprime": ("prime", "amazon"),
    "amazonprimevideo": ("amazonprimevideo", "prime", "amazon"),
    "hbomax": ("hbomax", "hbo"),
    "max": ("hbomax",),
    "natgeo": ("nationalgeographic", "ngc"),
    "nationalgeographicwild": ("natgeowild", "nationalgeographic"),
    "daserste": ("ard",),
    "ard1": ("ard",),
    "peacocktv": ("peacock",),
    "nbcpeacock": ("peacock",),
    "nrk1": ("nrk",),
    "nrk2": ("nrk",),
    "nrk3": ("nrk",),
    "nrksuper": ("nrk",),
    "tvn": ("tvnorge",),
    "tv2norge": ("tv2",),
    "tv2direkte": ("tv2",),
    "tv2play": ("tv2",),
    "tv2zebra": ("tv2",),
    "tv2nyheter": ("tv2",),
    "tv2sport": ("tv2",),
    "viaplayno": ("viaplay",),
    "viaplayse": ("viaplay",),
    "viaplaydk": ("viaplay",),
    # A country in brackets names one of several channels with the same logo.
    "abcus": ("abc",),
    "skyatlanticuk": ("skyatlantic",),
    "comedycentraluk": ("comedycentral",),
    "discoverychanneluk": ("discoverychannel",),
    "mtvuk": ("mtv",),
    "nationalgeographicuk": ("nationalgeographic",),
    "usanetworkca": ("usanetwork",),
    "discoveryplusno": ("discoveryplus",),
    "discoveryplusuk": ("discoveryplus",),
    "americanmovieclassicsamc": ("amc",),
    "historycanada": ("history",),
    # Other spellings of a name that has a logo.
    "spike": ("spiketv",),
    "youtubepremium": ("youtube",),
    "more4": ("4more",),
    "ndrfernsehen": ("ndr",),
    "elreynetwork": ("elrey",),
    "kabel1doku": ("kabeleinsdoku",),
    "britishbroadcastingcorporationbbc": ("bbc",),
    "tvglobo": ("globo",),
    "fs1": ("foxsports1",),
    "hbonordic": ("hbo",),
    "hboeurope": ("hbo",),
    "hbolatinamerica": ("hbo",),
    "hbobrazil": ("hbo",),
    "nhk": ("nhkworldjapan",),
    "nhkg": ("nhkworldjapan",),
    "nhkbspremium": ("nhkworldjapan",),
}
# Networks whose name merely contains one of these (folded) words use that logo.
_CONTAINS = (
    ("norskrikskringkasting", "nrk"),
    ("norskrikskringkastning", "nrk"),
    ("viaplay", "viaplay"),
)
# Country and quality tags at the end of a logo file name (sky-one-uk.png, tf1-hd-fr.png). A name that has no
# logo of its own matches the same file with these tags removed. The first country listed wins a tie.
_TAGS = (
    "uk", "us", "ca", "au", "nz", "ie", "de", "fr", "it", "es", "se", "no", "dk", "fi", "nl", "be", "at", "ch", "pt",
    "pl", "ru", "tr", "gr", "za", "in", "mx", "ar", "br", "jp", "kr", "il", "is", "hu", "cz", "ro", "bg", "hr", "my",
    "int", "afr", "hd", "hz",
)
_SUFFIXES = (
    "network", "channel", "television", "studios", "pictures", "films", "film",
    "productions", "entertainment", "broadcasting", "hd",
)


# Studio families that share one logo. A name that starts with the first part uses the file named by the second,
# after an exact match has been tried.
_STUDIO_FAMILIES = (
    ("waltdisney", "waltdisneypicturespresents"),
    ("warnerbro", "warnerbroshomeentertainmentgroup"),
    ("universalpictures", "universal"),
    ("universalinternational", "universal"),
    ("universalproductions", "universal"),
    ("sonypictures", "sonypictures"),
    ("paramount", "paramount"),
    ("bbc", "bbc"),
    ("nordiskfilm", "nordiskfilm"),
    ("zentropa", "zentropaentertainments"),
)


def _family(folded):
    """Channel families that share one logo: any TV4 channel, and any C More channel."""
    keys = []
    if folded.startswith("tv4") and folded != "tv4":
        keys.append("tv4")
    if folded.startswith("c") and "more" in folded and folded != "cmore":
        keys.append("cmore")
    if folded.startswith("nrk") and folded != "nrk":
        keys.append("nrk")
    if folded.startswith("tv2") and folded != "tv2":
        keys.append("tv2")
    return keys


def fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("&", "and").replace("+", "plus")
    return re.sub(r"[^a-z0-9]+", "", text)


def _keys(name, kind):
    folded = fold(name)
    if not folded:
        return []
    ordered = []

    def add(key):
        if key and key not in ordered:
            ordered.append(key)

    preferred = _PREFERRED.get(folded)
    if preferred:
        add(preferred)
    add(folded)
    for key in _family(folded):
        add(key)
    for key in _ALIASES.get(folded, ()):
        if folded == "max" and kind != "network":
            continue
        add(key)
    for suffix in _SUFFIXES:
        if folded.endswith(suffix) and len(folded) > len(suffix) + 2:
            add(folded[: -len(suffix)])
    if kind == "studios":
        for start, key in _STUDIO_FAMILIES:
            if folded.startswith(start):
                add(key)
    if kind == "network":
        for word, key in _CONTAINS:
            if word in folded:
                add(key)
    if kind == "recordlabels":
        for suffix in _LABEL_SUFFIXES:
            if folded.endswith(suffix) and len(folded) > len(suffix) + 2:
                add(folded[: -len(suffix)])
    return ordered


def _score(filename):
    stem = os.path.splitext(filename)[0].lower()
    penalty = 0
    if "old" in stem:
        penalty += 5
    if re.search(r"(^|[_\s-])hd($|[_\s-])", stem):
        penalty += 2
    return penalty, len(filename), filename.lower()


def _tag_free(stem):
    """The folded file name without its trailing country and quality tags, or "" when it has none."""
    parts = [part for part in re.split(r"[-_\s]+", stem.lower()) if part]
    kept = list(parts)
    while len(kept) > 1 and kept[-1] in _TAGS:
        kept.pop()
    return fold("".join(kept)) if len(kept) < len(parts) else ""


def _tag_rank(stem, filename):
    tags = [part for part in re.split(r"[-_\s]+", stem.lower()) if part in _TAGS]
    first = next((_TAGS.index(tag) for tag in tags if tag not in ("hd", "hz")), len(_TAGS))
    quality = 1 if any(tag in ("hd", "hz") for tag in tags) else 0
    return quality, first, _score(filename)


_loose = {}


def _custom_folder(folder):
    from resonance.paths import custom_brands_dir

    return os.path.join(custom_brands_dir(), folder)


def _listing(folder):
    """Logo file names from the app's own folder and from the logos you added. Yours win a tie."""
    names = {}
    for path in (os.path.join(_ROOT, folder), _custom_folder(folder)):
        try:
            for filename in os.listdir(path):
                names[filename] = path
        except OSError:
            continue
    return list(names)


def reset():
    """Forget the logo tables so a newly added file is found."""
    with _lock:
        _tables.clear()


def _index(folder):
    table = {}
    _loose.pop(folder, None)
    names = _listing(folder)
    if not names:
        return table
    for filename in names:
        if not filename.lower().endswith(".png"):
            continue
        key = fold(os.path.splitext(filename)[0])
        if not key:
            continue
        current = table.get(key)
        if current is None or _score(filename) < _score(current):
            table[key] = filename
    if folder == "network":
        loose = {}
        for filename in names:
            if not filename.lower().endswith(".png"):
                continue
            stem = os.path.splitext(filename)[0]
            key = _tag_free(stem)
            if key and key not in table:
                best = loose.get(key)
                if best is None or _tag_rank(stem, filename) < _tag_rank(os.path.splitext(best)[0], best):
                    loose[key] = filename
        _loose[folder] = loose
    return table


def table(kind):
    folder = _FOLDERS.get(kind)
    if not folder:
        return {}
    with _lock:
        cached = _tables.get(kind)
        if cached is None:
            cached = _index(folder)
            _tables[kind] = cached
        return cached


def file_for(name, kind):
    files = table(kind)
    for key in _keys(name, kind):
        found = files.get(key)
        if found:
            return found
    loose = _loose.get(_FOLDERS.get(kind), {})
    for key in _keys(name, kind):
        found = loose.get(key)
        if found:
            return found
    return None


def missing(counts, kind):
    """Names with no logo, busiest first. counts maps a name to how many items carry it."""
    rows = []
    for name, count in (counts or {}).items():
        text = str(name or "").strip()
        if text and not file_for(text, kind):
            rows.append({"name": text, "shows": int(count)})
    rows.sort(key=lambda row: (-row["shows"], row["name"].lower()))
    return rows


def unused(names, kind):
    """Logo files in the folder that no name in `names` resolves to."""
    folder = _FOLDERS.get(kind)
    if not folder:
        return []
    used = {file_for(str(name or "").strip(), kind) for name in names or []}
    found = _listing(folder)
    return sorted((f for f in found if f.lower().endswith(".png") and f not in used), key=str.lower)


def icons(names, kind):
    """The first name that has a logo. Names before it with no file are skipped."""
    for name in names or []:
        filename = file_for(name, kind)
        if not filename:
            continue
        return [{
            "name": str(name).strip(),
            "src": f"/media/{_FOLDERS[kind]}/{quote(filename)}",
        }]
    return []


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_LOGO_BYTES = 5 * 1024 * 1024


def save_custom(name, kind, data):
    """Store a logo you uploaded for this name. The file is named after the name, so the name matches it."""
    import io

    from PIL import Image

    from resonance.errors import AppError

    folder = _FOLDERS.get(kind)
    if kind not in {"network", "studios"} or not folder:
        raise AppError("Logos can be added for networks and studios", 400)
    text = _UNSAFE.sub("", str(name or "")).strip().strip(".")
    if not text or not fold(text):
        raise AppError("That name cannot be used as a file name", 400)
    if not data:
        raise AppError("Choose an image file", 400)
    if len(data) > MAX_LOGO_BYTES:
        raise AppError("Logos must be 5 MB or smaller", 400)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode not in ("RGBA", "LA", "RGB", "L", "P"):
                image = image.convert("RGBA")
            image = image.convert("RGBA")
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
    except Exception as exc:
        raise AppError("That file is not an image", 400) from exc
    target_dir = _custom_folder(folder)
    os.makedirs(target_dir, exist_ok=True)
    filename = f"{text}.png"
    path = os.path.join(target_dir, filename)
    temp = path + ".tmp"
    with open(temp, "wb") as handle:
        handle.write(buffer.getvalue())
    os.replace(temp, path)
    reset()
    return filename


def custom_file(folder, filename):
    """The path of a logo you added, when there is one with this name."""
    if folder not in _FOLDERS.values() or "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = os.path.join(_custom_folder(folder), filename)
    return path if os.path.isfile(path) else None
