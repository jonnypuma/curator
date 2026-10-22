import logging
import time
from urllib.parse import urlsplit

import requests

from resonance import settings
from resonance.sources.pace import gate_for

logger = logging.getLogger(__name__)
_down_until = {}


def _call(url, func):
    gate = gate_for(url)
    with gate.lock:
        gate.wait_locked()
        if gate.session is None:
            gate.session = requests.Session()
        contact = settings.load().get("musicbrainz_contact") or "resonance@localhost"
        gate.session.headers["User-Agent"] = f"Resonance/1.0 ({contact})"
        return func(gate.session)


def _retry_delay(response, status):
    raw = (response.headers.get("Retry-After") or "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 5.0 if status == 429 else 2.0
    return max(0.5, min(seconds, 120.0))


def _pause(seconds):
    from resonance.sources.pace import _sleep

    _sleep(seconds)


def _origin(url):
    return urlsplit(url).netloc.lower()


def _origin_down(url):
    return time.monotonic() < _down_until.get(_origin(url), 0)


def _mark_down(url, seconds=45):
    _down_until[_origin(url)] = time.monotonic() + seconds


def get_json(url, params=None, headers=None):
    from resonance.jobs import ScanCancelled

    if _origin_down(url):
        return None
    last = None
    for attempt in range(3):
        try:
            response = _call(
                url,
                lambda session: session.get(url, params=params, headers=headers, timeout=20),
            )
            status = response.status_code
            if status == 404:
                return None
            if status in (429, 503):
                if attempt < 2:
                    logger.info("backing off %s after HTTP %s", url, status)
                    _pause(_retry_delay(response, status))
                    continue
                _mark_down(url)
                logger.info("giving up on %s after HTTP %s", url, status)
                from resonance.connections import note_url

                note_url(url, f"{_origin(url)} answered HTTP {status}")
                return None
            if status >= 400:
                raise requests.HTTPError(f"{status} for {url}")
            from resonance.connections import clear_url

            clear_url(url)
            return response.json()
        except ScanCancelled:
            raise
        except Exception as exc:
            last = exc
            logger.info("request failed %s: %s", url, exc)
            if attempt < 2:
                _pause(1.0 + attempt)
                continue
            return None
    logger.info("request failed %s: %s", url, last)
    from resonance.connections import note_url

    note_url(url, f"{_origin(url)}: {last}")
    return None


def host_down(url):
    return _origin_down(url)


def get_bytes(url, limit=20 * 1024 * 1024):
    from resonance.jobs import ScanCancelled

    if _origin_down(url):
        return None, None

    def read(session):
        response = session.get(url, stream=True, timeout=30)
        try:
            if response.status_code == 404:
                return None, None
            if response.status_code in (429, 503):
                return response.status_code, _retry_delay(response, response.status_code)
            if response.status_code >= 400:
                logger.info("download failed %s: HTTP %s", url, response.status_code)
                return None, None
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if content_type.startswith("text/"):
                return None, content_type
            buffer = bytearray()
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    return None, content_type
            return bytes(buffer), content_type
        finally:
            response.close()

    for attempt in range(3):
        try:
            body, extra = _call(url, read)
        except ScanCancelled:
            raise
        except Exception as exc:
            logger.info("download failed %s: %s", url, exc)
            if attempt < 2:
                _pause(1.0 + attempt)
                continue
            return None, None
        if body in (429, 503):
            if attempt >= 2:
                _mark_down(url)
                return None, None
            logger.info("backing off %s after HTTP %s", url, body)
            _pause(extra or 2)
            continue
        return body, extra
    return None, None


def probe_image(url, size=128 * 1024):
    """The first bytes of an image and its full size, without downloading the rest.

    Asks for a byte range. A server that ignores the range sends the whole file, and only the first bytes are read
    before the connection is closed. Returns (data, total) with total None when the size is unknown, or (None, None).
    """
    if _origin_down(url):
        return None, None

    def read(session):
        response = session.get(url, headers={"Range": f"bytes=0-{size - 1}"}, stream=True, timeout=20)
        try:
            if response.status_code >= 400 and response.status_code != 416:
                return None, None
            if (response.headers.get("Content-Type") or "").startswith("text/"):
                return None, None
            total = None
            part = response.headers.get("Content-Range") or ""
            if "/" in part and part.rsplit("/", 1)[1].strip().isdigit():
                total = int(part.rsplit("/", 1)[1])
            elif response.status_code == 200:
                length = (response.headers.get("Content-Length") or "").strip()
                total = int(length) if length.isdigit() else None
            buffer = bytearray()
            for chunk in response.iter_content(32 * 1024):
                buffer.extend(chunk)
                if len(buffer) >= size:
                    break
            return bytes(buffer[:size]), total
        finally:
            response.close()

    try:
        return _call(url, read)
    except Exception as exc:
        from resonance.jobs import ScanCancelled

        if isinstance(exc, ScanCancelled):
            raise
        logger.info("could not look at %s: %s", url, exc)
        return None, None
