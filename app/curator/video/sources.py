"""Release source and edition names.

The source strings are the ones Kodi, Jellyfin and scene tools already match in
filenames and in a movie or episode `<source>` tag. Kodi reads `<edition>` as its
own field and leaves `<source>` in the .nfo for the library.
"""
from __future__ import annotations

import os
import re

# (label stored and written to <source>, video_source used for the format icon)
SOURCE_PRESETS = (
    ("UHD Remux", "UHD Bluray"),
    ("UHD Blu-ray", "UHD Bluray"),
    ("Complete UHD Blu-ray", "UHD Bluray"),
    ("UHD Rip", "UHD Bluray"),
    ("Blu-ray Remux", "Bluray"),
    ("Blu-ray", "Bluray"),
    ("Blu-ray Rip", "BD-Rip"),
    ("Complete Blu-ray", "Bluray"),
    ("HD-DVD Remux", "HD-DVD"),
    ("HD-DVD", "HD-DVD"),
    ("WEB-DL", "WEB-DL"),
    ("WEBRip", "WEB-Rip"),
    ("WEBCap", "WEB-Rip"),
    ("HDTV", "HDTV"),
    ("PDTV", "HDTV"),
    ("DSR", "HDTV"),
    ("TVRip", "HDTV"),
    ("DVD", "DVD"),
    ("DVDRip", "DVD"),
    ("HDRip", "DVD"),
    ("VHS", "VHS"),
    ("VHSRip", "VHS"),
    ("Screener", "Screener"),
    ("Telecine", "Telecine"),
    ("Telesync", "Telesync"),
    ("CAM", "CAM"),
    ("Workprint", "Workprint"),
    ("R5", "R5"),
)
SOURCE_LABELS = {label for label, _group in SOURCE_PRESETS}
_SOURCE_GROUP = {label.lower(): (label, group) for label, group in SOURCE_PRESETS}

EDITION_PRESETS = (
    "Director's Cut",
    "Extended Cut",
    "Theatrical Cut",
    "Unrated",
    "Uncut",
    "Remastered",
    "Restored",
    "IMAX",
    "IMAX Enhanced",
    "Final Cut",
    "Ultimate Cut",
    "Ultimate Collector's Edition",
    "Criterion",
    "Criterion Collection",
    "Open Matte",
    "Assembly Cut",
    "Bootleg Cut",
    "International Cut",
    "Hong Kong Cut",
    "Mandarin Cut",
    "Recut",
    "Vinegar Syndrome",
    "Special Edition",
    "Anniversary Edition",
    "Collector's Edition",
    "Limited Edition",
)

_EDITIONS = (
    (r"\bimax[-\s.]?enhanced\b", "IMAX Enhanced"),
    (r"\b(directors?[-\s.]?cut|director'?s[-\s.]?cut)\b", "Director's Cut"),
    (r"\bextended[-\s.]?cut\b", "Extended Cut"),
    (r"\bextended\b", "Extended Cut"),
    (r"\btheatrical([-\s.]?cut)?\b", "Theatrical Cut"),
    (r"\bunrated\b", "Unrated"),
    (r"\buncut\b", "Uncut"),
    (r"\bremastered\b", "Remastered"),
    (r"\brestored\b", "Restored"),
    (r"\bimax\b", "IMAX"),
    (r"\bfinal[-\s.]?cut\b", "Final Cut"),
    (r"\bultimate[-\s.]?collectors?[-\s.]?edition\b", "Ultimate Collector's Edition"),
    (r"\bultimate([-\s.]?(cut|edition))?\b", "Ultimate Cut"),
    (r"\bcriterion[-\s.]?collection\b", "Criterion Collection"),
    (r"\bcriterion\b", "Criterion"),
    (r"\bopen[-\s.]?matte\b", "Open Matte"),
    (r"\bassembly[-\s.]?cut\b", "Assembly Cut"),
    (r"\bbootleg[-\s.]?cut\b", "Bootleg Cut"),
    (r"\binternational[-\s.]?cut\b", "International Cut"),
    (r"\bhong[-\s.]?kong[-\s.]?cut\b", "Hong Kong Cut"),
    (r"\bmandarin[-\s.]?cut\b", "Mandarin Cut"),
    (r"\bre[-.\s]?cut\b", "Recut"),
    (r"\bvinegar[-\s.]?syndrome\b", "Vinegar Syndrome"),
    (r"\bspecial[-\s.]?edition\b", "Special Edition"),
    (r"\banniversary([-\s.]?edition)?\b", "Anniversary Edition"),
    (r"\bcollectors?[-\s.]?edition\b", "Collector's Edition"),
    (r"\blimited([-\s.]?edition)?\b", "Limited Edition"),
    (r"\bdc\b", "Director's Cut"),
)

# NFO and filename spellings that mean one of the labels above.
_EDITION_ALIASES = {
    "directors cut": "Director's Cut",
    "director cut": "Director's Cut",
    "dc": "Director's Cut",
    "extended": "Extended Cut",
    "extended cut": "Extended Cut",
    "extended edition": "Extended Cut",
    "extended version": "Extended Cut",
    "theatrical": "Theatrical Cut",
    "theatrical cut": "Theatrical Cut",
    "theatrical edition": "Theatrical Cut",
    "theatrical version": "Theatrical Cut",
    "unrated": "Unrated",
    "unrated version": "Unrated",
    "unrated edition": "Unrated",
    "uncut": "Uncut",
    "uncut version": "Uncut",
    "uncut edition": "Uncut",
    "remastered": "Remastered",
    "remastered version": "Remastered",
    "remastered edition": "Remastered",
    "restored": "Restored",
    "restored version": "Restored",
    "imax enhanced": "IMAX Enhanced",
    "imax": "IMAX",
    "final cut": "Final Cut",
    "ultimate": "Ultimate Cut",
    "ultimate cut": "Ultimate Cut",
    "ultimate edition": "Ultimate Cut",
    "ultimate collectors edition": "Ultimate Collector's Edition",
    "ultimate collector edition": "Ultimate Collector's Edition",
    "criterion": "Criterion",
    "criterion collection": "Criterion Collection",
    "open matte": "Open Matte",
    "assembly cut": "Assembly Cut",
    "bootleg cut": "Bootleg Cut",
    "international cut": "International Cut",
    "hong kong cut": "Hong Kong Cut",
    "mandarin cut": "Mandarin Cut",
    "recut": "Recut",
    "re cut": "Recut",
    "vinegar syndrome": "Vinegar Syndrome",
    "special edition": "Special Edition",
    "anniversary": "Anniversary Edition",
    "anniversary edition": "Anniversary Edition",
    "collectors edition": "Collector's Edition",
    "collector edition": "Collector's Edition",
    "limited": "Limited Edition",
    "limited edition": "Limited Edition",
    "standard edition": "Standard Edition",
    "4k": "4K",
}


def _stem(name):
    from curator.video.naming import SUBTITLE_EXTS, VIDEO_EXTS

    base = os.path.basename(str(name or ""))
    root, ext = os.path.splitext(base)
    if ext.lower() in VIDEO_EXTS or ext.lower() in SUBTITLE_EXTS:
        base = root
    return base.lower()


def _has(pattern, text):
    return re.search(pattern, text) is not None


def canonical_source(label):
    """Return (source label, icon group). An empty label clears both."""
    text = str(label or "").strip()
    if not text:
        return None, None
    found = _SOURCE_GROUP.get(text.lower())
    if found:
        return found
    return text[:40], None


def video_source_for(label):
    _label, group = canonical_source(label)
    return group


def _edition_key(label):
    text = str(label or "").lower().replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def canonical_edition(label):
    """One display name for an edition from a filename or an .nfo value.

    CRITERION_COLLECTION and Criterion.Collection both become Criterion Collection.
    A name that is not one of the known editions is title-cased.
    """
    text = str(label or "").strip()
    if not text:
        return None
    key = _edition_key(text)
    if key == "none":
        return None
    found = _EDITION_ALIASES.get(key)
    if found:
        return found
    words = []
    for word in key.split():
        if word == "imax":
            words.append("IMAX")
        elif word == "uhd":
            words.append("UHD")
        elif word == "4k":
            words.append("4K")
        else:
            words.append(word.capitalize())
    return " ".join(words) or None


def classify_edition(name):
    """Edition named anywhere in a file or folder name.

    Criterion in the middle or at the end, as in Movie.1957.1080p.BluRay.Criterion, is the
    Criterion edition. Criterion Collection stays that longer name.
    """
    text = _stem(name)
    for pattern, label in _EDITIONS:
        if _has(pattern, text):
            return label
    return None


def edition_from_path(path):
    """Edition from the file name, then the folder name when the file does not say."""
    edition = classify_edition(os.path.basename(str(path or "")))
    if edition:
        return edition
    folder = os.path.basename(os.path.dirname(str(path or "")))
    if not folder or folder in {".", ".."}:
        return None
    return classify_edition(folder)


def release_hybrid(name):
    stem = _stem(name).strip()
    match = re.search(r"\bhybrid\b", stem, re.IGNORECASE)
    if not match:
        return False
    return match.start() > 0


_STEREO = (
    (r"\b(?:half[-.\s]?sbs|hsbs)\b", "HSBS"),
    (r"\b(?:full[-.\s]?sbs|fsbs)\b", "SBS"),
    (r"\b(?:half[-.\s]?(?:ou|over[-.\s]?under)|hou)\b", "HOU"),
    (r"\b(?:full[-.\s]?ou|over[-.\s]?under)\b", "OU"),
    (r"\bmvc\b", "MVC"),
    (r"\b3d\b", "3D"),
)


def classify_stereo(name):
    """3D layout from the filename: HSBS, SBS, HOU, OU, MVC, or plain 3D."""
    text = _stem(name)
    for pattern, label in _STEREO:
        if _has(pattern, text):
            return label
    if os.path.splitext(str(name or ""))[1].lower() == ".mk3d":
        return "MVC"
    return None


def classify_source(name, resolution=None, disc=False):
    """The release source printed in the filename, or None when it does not say.

    An .iso is a full disc. UHD Blu-ray on that disc is a complete UHD Blu-ray,
    including a 2160 token with no trailing p.
    """
    base = os.path.basename(str(name or ""))
    extension = os.path.splitext(base)[1].lower()
    text = _stem(name)
    uhd = resolution in ("4K", "8K") or _has(r"\b(2160p?|4320p?|uhd|4k|8k)\b", text)
    remux = _has(r"\b(remux|bd[-.\s]?remux|br[-.\s]?remux)\b", text)
    rip = _has(r"\b(bdrip|brrip|blu[-\s.]?ray[-\s.]?rip)\b", text)
    disk = _has(r"\b(br[-\s.]?disk|complete[-\s.]?bluray|complete[-\s.]?blu[-\s.]?ray|bdmv)\b", text)
    bluray = _has(r"\b(blu[-\s.]?ray|bluray|bd[-.\s]?remux|br[-.\s]?remux|bdmv)\b", text)
    full_disc = disc or extension == ".iso" or disk
    if _has(r"\b(hd[-\s.]?dvd|hddvd)\b", text):
        return "HD-DVD Remux" if remux else "HD-DVD"
    if _has(r"\b(web[-\s.]?dl|webdl)\b", text):
        return "WEB-DL"
    if _has(r"\bweb[-\s.]?cap\b", text):
        return "WEBCap"
    if _has(r"\bweb[-\s.]?rip\b", text):
        return "WEBRip"
    if _has(r"\bweb\b", text):
        return "WEB-DL"
    if _has(r"\b(dvdscr|screener|bdscr)\b", text):
        return "Screener"
    if _has(r"\b(telecine|hd[-\s.]?tc)\b", text) or _has(r"(?<=[.\s_-])tc(?:[.\s_-]|$)", text):
        return "Telecine"
    if _has(r"\b(telesync|hd[-\s.]?ts)\b", text) or _has(r"(?<=[.\s_-])ts(?:[.\s_-]|$)", text):
        return "Telesync"
    if _has(r"\b(hdcam|camrip)\b", text) or _has(r"(?<=[.\s_-])cam(?:[.\s_-]|$)", text):
        return "CAM"
    if _has(r"\bworkprint\b", text) or _has(r"(?<=[.\s_-])wp(?:[.\s_-]|$)", text):
        return "Workprint"
    if _has(r"(?<=[.\s_-])r5(?:[.\s_-]|$)", text):
        return "R5"
    if _has(r"\bpdtv\b", text):
        return "PDTV"
    if _has(r"\b(dsr|dsrip|satrip|dvbrip|dvb)\b", text):
        return "DSR"
    if _has(r"\btvrip\b", text):
        return "TVRip"
    if _has(r"\bhdtv\b", text):
        return "HDTV"
    if _has(r"\bdvd[.\s_-]*rip\b", text):
        return "DVDRip"
    if _has(r"\bhdrip\b", text):
        return "HDRip"
    if _has(r"\bvhsrip\b", text):
        return "VHSRip"
    if _has(r"\bvhs\b", text):
        return "VHS"
    if _has(r"\bdvd\b", text) and not uhd and not bluray:
        return "DVD"
    if full_disc and uhd:
        return "Complete UHD Blu-ray"
    if full_disc and bluray:
        return "Complete Blu-ray"
    if uhd and remux:
        return "UHD Remux"
    if uhd and rip:
        return "UHD Rip"
    if uhd and (bluray or disk):
        return "UHD Blu-ray"
    if disk:
        return "Complete Blu-ray"
    if remux and (bluray or not uhd):
        return "Blu-ray Remux"
    if rip:
        return "Blu-ray Rip"
    if bluray:
        return "Blu-ray"
    return None


def classify_path(path, resolution=None):
    """Source from the file name, then from the folder name when the file does not say."""
    disc = os.path.splitext(str(path or ""))[1].lower() == ".iso"
    source = classify_source(os.path.basename(str(path or "")), resolution, disc=disc)
    if source:
        return source
    folder = os.path.basename(os.path.dirname(str(path or "")))
    if not folder or folder in {".", ".."}:
        return None
    return classify_source(folder, resolution, disc=disc)
