"""AllMusic album and artist pages. Public HTML only, one request every few seconds."""

import json
import logging
import re
import threading
from urllib.parse import quote, urljoin

logger = logging.getLogger(__name__)

_HOME = "https://www.allmusic.com/"
_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
_LANGUAGE = "en-US,en;q=0.9"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_ALBUM_HREF = re.compile(r"/album/[^/?#]+-mw\d+/?$")
_ARTIST_HREF = re.compile(r"/artist/[^/?#]+-mn\d+/?$")
_session = None
_session_kind = None
_session_lock = threading.Lock()


def enabled():
    from resonance.settings import load

    return bool(load().get("allmusic_enabled", True))


def album(artist, title, year=None, active=None):
    """Styles, moods, themes, rating, and the editorial review for one release.

    The artist is chosen first (an mn address). The album is then taken from that
    artist's discography (an mw address), using the release year when several
    albums share a title. A general album search is only the fallback.
    """
    from resonance.settings import vlog

    artist = str(artist or "").strip()
    title = str(title or "").strip()
    if not artist or not title or not enabled():
        return None
    window = active or ((year, year) if year else None)
    hit = _from_discography(artist, title, year, window)
    if not hit:
        query = f"{artist} {title}"
        vlog(logger, "allmusic album search %s", query)
        html = _get(f"https://www.allmusic.com/search/albums/{quote(query)}")
        hit = _best(parse_search(html, "album"), artist, title, year, active=window) if html else None
        if not hit:
            logger.info("allmusic has no album for %s — %s", artist, title)
            return None
    page = hit.pop("_html", None) or _get(hit["url"])
    if not page:
        return None
    parsed = parse_album(page, hit["url"])
    if not parsed.get("title") and not parsed.get("review") and not parsed.get("styles"):
        return None
    vlog(logger, "allmusic album %s", parsed.get("url") or hit["url"])
    return parsed


def _from_discography(artist, title, year, active):
    from resonance.settings import vlog

    vlog(logger, "allmusic discography %s — %s", artist, title)
    html = _get(f"https://www.allmusic.com/search/artists/{quote(artist)}")
    if not html:
        return None
    person = _best(parse_search(html, "artist"), artist, artist, year, kind="artist", active=active)
    if not person:
        return None
    disc_url = person["url"].rstrip("/") + "/discography"
    disc = _get(disc_url)
    hits = parse_search(disc, "album") if disc else []
    if not hits:
        page = _get(person["url"])
        hits = parse_search(page, "album") if page else []
    for hit in hits:
        if not hit.get("artist"):
            hit["artist"] = artist
    chosen = _choose_album(hits, artist, title, year, active)
    if chosen:
        vlog(logger, "allmusic discography chose %s", chosen["url"])
    return chosen


def _choose_album(hits, artist, title, year, active):
    """Prefer the discography row for this title. Edition years on the album page break a tie."""
    ranked = _ranked(hits, artist, title, year, active=active)
    if not ranked or not year:
        return ranked[0] if ranked else None
    wanted = int(year)
    exact = [hit for hit in ranked if hit.get("year") and int(hit["year"]) == wanted]
    if exact:
        return exact[0]
    close = [hit for hit in ranked if _similar(_norm(hit.get("title")), _norm(title)) >= 0.9][:3]
    for hit in close:
        html = _get(hit["url"])
        if not html:
            continue
        parsed = parse_album(html, hit["url"])
        editions = parsed.get("release_years") or []
        if wanted in editions:
            hit["_html"] = html
            return hit
    return ranked[0]


def artist(name, active=None):
    """Styles and moods from an artist page.

    active is (first year, last year) from the library and MusicBrainz. It picks
    the namesake whose AllMusic decades overlap that span.
    """
    from resonance.settings import vlog

    name = str(name or "").strip()
    if not name or not enabled():
        return None
    vlog(logger, "allmusic artist search %s", name)
    html = _get(f"https://www.allmusic.com/search/artists/{quote(name)}")
    if not html:
        return None
    hit = _best(parse_search(html, "artist"), name, name, None, kind="artist", active=active)
    if not hit:
        logger.info("allmusic has no artist for %s", name)
        return None
    page = _get(hit["url"])
    if not page:
        return None
    parsed = parse_artist(page, hit["url"])
    if not parsed.get("styles") and not parsed.get("moods") and not parsed.get("biography"):
        return None
    vlog(logger, "allmusic artist %s", parsed.get("url") or hit["url"])
    return parsed


def parse_search(html, kind):
    soup = _soup(html)
    if soup is None:
        return []
    pattern = _ALBUM_HREF if kind == "album" else _ARTIST_HREF
    hits = []
    seen = set()
    for link in soup.find_all("a", href=True):
        href = _page_url(link["href"])
        path = _site_path(href)
        if not pattern.search(path):
            continue
        title = link.get_text(" ", strip=True)
        if not title or title.lower() in {"read more", "allmusic"}:
            continue
        if href in seen:
            continue
        seen.add(href)
        container = _result_container(link)
        other = ""
        year = None
        start = end = None
        if container is not None:
            other_link = container.find("a", href=_ARTIST_HREF if kind == "album" else _ALBUM_HREF)
            if other_link is not None and other_link is not link:
                other = other_link.get_text(" ", strip=True)
            start, end = _active_span(container.get_text(" ", strip=True))
            if start and end and start == end:
                year = start
        hits.append({
            "url": href,
            "title": title,
            "artist": other,
            "year": year,
            "start": start,
            "end": end,
        })
    return hits


def parse_album(html, url=""):
    soup = _soup(html)
    result = {
        "url": url,
        "title": None,
        "artist": None,
        "date": None,
        "rating": None,
        "styles": [],
        "moods": [],
        "themes": [],
        "review": None,
        "review_author": None,
        "user_rating": None,
        "votes": None,
        "release_years": [],
    }
    if soup is None:
        return result
    for block in _jsonld(soup):
        if _ld_type(block) != "MusicAlbum":
            continue
        result["title"] = result["title"] or _text(block.get("name"))
        result["artist"] = result["artist"] or _artist_name(block.get("byArtist"))
        result["date"] = result["date"] or _text(block.get("datePublished"))
        if result["rating"] is None:
            result["rating"] = _scale((block.get("aggregateRating") or {}).get("ratingValue"))
        if result["votes"] is None:
            aggregate = block.get("aggregateRating") or {}
            result["votes"] = _votes(aggregate.get("ratingCount") or aggregate.get("reviewCount"))
    if result["rating"] is None:
        result["rating"] = _dom_rating(soup)
    result["user_rating"] = _user_rating(soup)
    result["release_years"] = _release_years(soup, result.get("date"))
    result["styles"] = _taxonomy(soup, "style")
    result["moods"] = _taxonomy(soup, "mood")
    result["themes"] = _taxonomy(soup, "theme")
    author, review = _editorial_review(soup)
    result["review_author"] = author
    if author and review and author.lower() not in review[:120].lower():
        review = f"{author}\n\n{review}"
    result["review"] = review
    return result


def parse_artist(html, url=""):
    soup = _soup(html)
    result = {"url": url, "name": None, "styles": [], "moods": [], "biography": None}
    if soup is None:
        return result
    for block in _jsonld(soup):
        if _ld_type(block) in {"MusicGroup", "Person"}:
            result["name"] = result["name"] or _text(block.get("name"))
    result["styles"] = _taxonomy(soup, "style")
    result["moods"] = _taxonomy(soup, "mood")
    result["biography"] = _biography_text(soup)
    return result


def _ranked(hits, artist, title, year, kind="album", active=None):
    artist_key = _norm(artist)
    title_key = _norm(title)
    hint = _hint(year, active)
    ranked = []
    for index, hit in enumerate(hits):
        if kind == "artist":
            score = _similar(_norm(hit.get("title")), artist_key)
            if score < 0.72:
                continue
            score += _span_adjust(hit, hint)
            ranked.append((score, -index, hit))
            continue
        title_score = _similar(_norm(hit.get("title")), title_key)
        other = _norm(hit.get("artist"))
        artist_score = _similar(other, artist_key) if other else 0.5
        if title_score < 0.72 or artist_score < 0.45:
            continue
        score = title_score * 2 + artist_score + _span_adjust(hit, hint)
        if year and hit.get("year") and int(hit["year"]) == int(year):
            score += 0.35
        ranked.append((score, -index, hit))
    if not ranked:
        return []
    ranked.sort(reverse=True)
    return [hit for _score, _index, hit in ranked]


def _best(hits, artist, title, year, kind="album", active=None):
    found = _ranked(hits, artist, title, year, kind=kind, active=active)
    return found[0] if found else None


def _result_container(link):
    """The row around one artist (mn) or album (mw), not the whole list."""
    own = link.get("href") or ""
    pattern = _ARTIST_HREF if _ARTIST_HREF.search(own) else _ALBUM_HREF
    container = link
    for _ in range(6):
        parent = getattr(container, "parent", None)
        if parent is None or getattr(parent, "name", None) in {"body", "html", "[document]"}:
            break
        matches = 0
        for anchor in parent.find_all("a", href=True):
            path = _site_path(anchor["href"])
            if pattern.search(path):
                matches += 1
        if matches > 1:
            break
        container = parent
        classes = " ".join(container.get("class") or []).lower()
        if container.name in {"li", "tr", "article"} or "result" in classes:
            break
    return container


def _active_span(text):
    """Turn '2000s - 2020s' or '1981' into an inclusive year range."""
    if not text:
        return None, None
    decade = re.search(r"((?:19|20)\d{2})s(?:\s*[-–—]\s*((?:19|20)\d{2})s)?", text)
    if decade:
        start = int(decade.group(1))
        end = int(decade.group(2)) + 9 if decade.group(2) else start + 9
        return start, end
    years = [int(item) for item in re.findall(r"\b(?:19|20)\d{2}\b", text)]
    if not years:
        return None, None
    return min(years), max(years)


def _hint(year, active):
    start = end = None
    if isinstance(active, (tuple, list)) and len(active) >= 2:
        start = _year(active[0])
        end = _year(active[1])
    point = _year(year)
    if point:
        start = point if start is None else min(start, point)
        end = point if end is None else max(end, point)
    if start and end is None:
        end = start
    if start and end and start > end:
        start, end = end, start
    return start, end


def _year(value):
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if year < 1000 or year > 3000:
        return None
    return year


def _span_adjust(hit, hint):
    start, end = hint
    if not start or not end:
        return 0.0
    first, last = hit.get("start"), hit.get("end")
    if not first or not last:
        return 0.0
    if first <= end and start <= last:
        return 0.55
    return -0.45


def _taxonomy(soup, slug):
    names = []
    for link in soup.find_all("a", href=re.compile(rf"/{slug}/")):
        name = link.get_text(" ", strip=True)
        if name and name not in names:
            names.append(name)
        if len(names) >= 12:
            break
    return names


_REVIEW_STOP = re.compile(
    r"\b(?:User Reviews|Track Listing|Track List|All Credits|Additional Releases|Similar Albums|Moods and Themes)\b",
    re.I,
)


def _editorial_review(soup):
    found = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        label = heading.get_text(" ", strip=True)
        if "user review" in label.lower():
            continue
        match = re.search(r"Review by\s+(.+)$", label, re.I)
        if not match:
            continue
        author = match.group(1).strip(" .")
        if author.lower() == "allmusic":
            author = None
        text = _review_from(heading.find_next_siblings())
        parent = getattr(heading, "parent", None)
        if not text and parent is not None:
            text = _review_from(parent.find_next_siblings())
        if text:
            found.append((author, text))
    named = [(author, text) for author, text in found if author and text]
    pool = named or found
    if pool:
        return max(pool, key=lambda item: len(item[1]))
    author, text = _review_section(soup)
    if text:
        return author, text
    node = soup.select_one("[itemprop='reviewBody']")
    if node is not None:
        paragraphs = node.find_all("p")
        text = "\n\n".join(part.get_text(" ", strip=True) for part in paragraphs if part.get_text(strip=True))
        if not text:
            text = _clip_review(node.get_text(" ", strip=True))
        if text:
            return None, text
    return _jsonld_review(soup)


def _review_from(siblings):
    chunks = []
    for sib in siblings:
        name = getattr(sib, "name", None)
        if name in {"h1", "h2", "h3", "h4"}:
            break
        if name in {"script", "style", "form", "nav", "footer", "noscript"}:
            continue
        label_text = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else ""
        if re.search(r"\buser reviews\b", label_text, re.I) and len(label_text) < 80:
            break
        paragraphs = sib.find_all("p") if hasattr(sib, "find_all") else []
        paragraph_text = [node.get_text(" ", strip=True) for node in paragraphs]
        paragraph_text = [part for part in paragraph_text if part]
        if name == "p" and label_text:
            paragraph_text = [label_text]
        if paragraph_text:
            chunks.extend(_clip_review(part) for part in paragraph_text)
            continue
        clipped = _clip_review(label_text)
        if len(clipped) >= 80:
            chunks.append(clipped)
    text = "\n\n".join(part for part in chunks if part)
    return text or None


def _review_section(soup):
    root = soup.find(id=re.compile(r"^review$", re.I))
    if root is None:
        return None, None
    author = None
    for heading in root.find_all(["h2", "h3", "h4"]):
        label = heading.get_text(" ", strip=True)
        match = re.search(r"Review by\s+(.+)$", label, re.I)
        if not match:
            continue
        name = match.group(1).strip(" .")
        if name.lower() != "allmusic":
            author = name
            break
    paragraphs = [node.get_text(" ", strip=True) for node in root.find_all("p")]
    paragraphs = [_clip_review(part) for part in paragraphs if part]
    text = "\n\n".join(part for part in paragraphs if part)
    if not text:
        text = _clip_review(root.get_text(" ", strip=True))
        text = re.sub(r"^.*?Review by\s+(?:AllMusic|.+?)\s*", "", text, count=1, flags=re.I).strip()
    if author and text.lower().startswith(author.lower()):
        text = text[len(author):].strip(" .:-")
    if len(text) < 80:
        return None, None
    return author, text


def _jsonld_review(soup):
    for block in _jsonld(soup):
        kind = _ld_type(block)
        body = None
        author = None
        if kind in {"Review", "CriticReview"}:
            body = _text(block.get("reviewBody"))
            author = _artist_name(block.get("author")) or _text(block.get("author"))
        elif kind == "MusicAlbum":
            review = block.get("review")
            if isinstance(review, list) and review:
                review = review[0]
            if isinstance(review, dict):
                body = _text(review.get("reviewBody"))
                author = _artist_name(review.get("author")) or _text(review.get("author"))
        if not body or len(body) < 80:
            continue
        if author and author.lower() == "allmusic":
            author = None
        return author, body
    return None, None


def _clip_review(text):
    text = _REVIEW_STOP.split(str(text or ""), maxsplit=1)[0]
    return " ".join(text.split())


def _page_url(href):
    raw = str(href or "").split("#", 1)[0].split("?", 1)[0]
    return urljoin(_HOME, raw)


def _site_path(href):
    return _page_url(href).replace("https://www.allmusic.com", "").replace("http://www.allmusic.com", "")


def _browser_check(text):
    """A Cloudflare interstitial, not an album page that also mentions the check."""
    lowered = str(text or "").lower()
    if "sorry, you have been blocked" in lowered:
        return True
    if "attention required" in lowered and "cloudflare" in lowered and "review by" not in lowered:
        return True
    challenge = "just a moment" in lowered and (
        "cloudflare" in lowered or "cf-challenge" in lowered or "challenge-platform" in lowered
    )
    if not challenge:
        return False
    if "review by" in lowered or "musicalbum" in lowered:
        return False
    return True


def _dom_rating(soup):
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class") or [])
        if re.search(r"user", classes, re.I):
            continue
        raw = tag.get("data-rating")
        if raw:
            value = _scale(raw)
            if value is not None:
                return value
        match = re.search(r"rating[-_]?allmusic[-_]?(\d+(?:\.\d+)?)", classes, re.I)
        if match:
            value = _scale(match.group(1))
            if value is not None:
                return value
    node = soup.find(attrs={"itemprop": "ratingValue"})
    if node is not None:
        return _scale(node.get("content") or node.get_text(" ", strip=True))
    return None


def _user_rating(soup):
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class") or []).lower()
        blob = f"{classes} {tag.get('id') or ''}".lower()
        if "user" not in blob or "rating" not in blob or "your" in blob:
            continue
        raw = tag.get("data-rating") or tag.get("content") or tag.get("title") or ""
        value = _scale(raw) or _scale(_first_number(tag.get_text(" ", strip=True)))
        if value:
            return value
    for heading in soup.find_all(["h2", "h3", "h4", "div", "span", "p"]):
        label = heading.get_text(" ", strip=True).lower()
        if not label.startswith("user rating") or "your rating" in label:
            continue
        sibling = heading.find_next(string=re.compile(r"\d"))
        value = _scale(_first_number(str(sibling or "")))
        if value:
            return value
    return None


def _release_years(soup, published):
    years = []
    headline = _first_year(published)
    if headline:
        years.append(headline)
    root = soup.find(id=re.compile(r"^releases?$", re.I))
    if root is None:
        for heading in soup.find_all(["h2", "h3", "h4"]):
            label = heading.get_text(" ", strip=True).lower()
            if label in {"releases", "additional releases"}:
                root = heading.find_parent("section") or heading.parent
                break
    if root is None:
        return years
    rows = root.find_all(["tr", "li"]) or [root]
    for row in rows:
        for year in _years_in(row.get_text(" ", strip=True)):
            if year not in years:
                years.append(year)
    return years


def _biography_text(soup):
    root = soup.find(id=re.compile(r"^biography$", re.I))
    if root is None:
        for heading in soup.find_all(["h2", "h3", "h4"]):
            if "biography" in heading.get_text(" ", strip=True).lower():
                root = heading.find_parent("section") or heading.parent
                break
    if root is None:
        return None
    paragraphs = [node.get_text(" ", strip=True) for node in root.find_all("p")]
    paragraphs = [part for part in paragraphs if part and part.lower() not in {"read more", "biography"}]
    text = "\n\n".join(paragraphs)
    return text or None


def _first_number(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return match.group(0) if match else ""


def _first_year(value):
    match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
    return int(match.group(0)) if match else None


def _years_in(text):
    return [int(item) for item in re.findall(r"\b(?:19|20)\d{2}\b", text or "")]


def _jsonld(soup):
    found = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        found.extend(_flatten_ld(data))
    return found


def _flatten_ld(data):
    if isinstance(data, list):
        rows = []
        for item in data:
            rows.extend(_flatten_ld(item))
        return rows
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            return _flatten_ld(graph)
        return [data]
    return []


def _ld_type(block):
    kind = block.get("@type")
    if isinstance(kind, list):
        return str(kind[0] if kind else "")
    return str(kind or "")


def _artist_name(value):
    if isinstance(value, list) and value:
        return _artist_name(value[0])
    if isinstance(value, dict):
        return _text(value.get("name"))
    return None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _scale(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 5:
        number = number / 2.0
    if number <= 0 or number > 5:
        return None
    return round(number, 1)


def _votes(value):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _norm(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _similar(left, right):
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.86
    left_words = set(left.split())
    right_words = set(right.split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _soup(html):
    if not html:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.info("beautifulsoup4 is not installed, so AllMusic pages cannot be read")
        return None
    return BeautifulSoup(html, "html.parser")


def _get(url):
    from resonance.jobs import ScanCancelled
    from resonance.sources.client import _mark_down, _origin_down, _pause
    from resonance.sources.pace import gate_for

    if not url or _origin_down(url):
        return None
    gate = gate_for(url)
    last = None
    for attempt in range(3):
        try:
            response = _fetch(gate, url)
        except ScanCancelled:
            raise
        except Exception as exc:
            last = exc
            logger.info("allmusic request failed %s: %s", url, exc)
            if attempt < 2:
                _pause(1.5 + attempt)
                continue
            return None
        status = getattr(response, "status_code", 0) or 0
        if status == 404:
            return None
        if status in (403, 429, 503):
            if attempt < 2:
                _pause(3.0 if status == 403 else 5.0)
                continue
            _mark_down(url, 180)
            logger.info("allmusic refused %s: HTTP %s", url, status)
            return None
        if status >= 400:
            logger.info("allmusic failed %s: HTTP %s", url, status)
            return None
        text = response.text or ""
        if _browser_check(text):
            _mark_down(url, 180)
            logger.info("allmusic presented a browser check for %s", url)
            return None
        return text
    logger.info("allmusic request failed %s: %s", url, last)
    return None


def _fetch(gate, url):
    headers = {
        "Accept": _ACCEPT,
        "Accept-Language": _LANGUAGE,
        "Referer": _HOME,
    }
    with gate.lock:
        gate.wait_locked()
        session, kind = _browser()
        if kind == "chrome":
            try:
                return session.get(url, impersonate="chrome", headers=headers, timeout=20)
            except Exception as exc:
                if "impersonate" not in str(exc).lower():
                    raise
                return session.get(url, impersonate="chrome124", headers=headers, timeout=20)
        headers["User-Agent"] = _UA
        return session.get(url, headers=headers, timeout=20)


def _browser():
    global _session, _session_kind
    with _session_lock:
        if _session is not None:
            return _session, _session_kind
        try:
            from curl_cffi import requests as chrome_requests

            _session = chrome_requests.Session()
            _session_kind = "chrome"
        except ImportError:
            import requests

            _session = requests.Session()
            _session_kind = "requests"
            logger.info("curl_cffi is not installed; AllMusic requests use the normal HTTP client")
        return _session, _session_kind
