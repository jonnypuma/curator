import threading
import time
from urllib.parse import urlparse

# Caps are at or under the published client limits. Unknown hosts use one
# request per second so a new image CDN cannot be sprayed.
# MusicBrainz: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
#   at most 1 request/second per application and IP. musicbrainzngs enforces this.
# Cover Art Archive: no fixed quota, but 503 is defined when a client is too fast.
#   JSON lookups and archive.org image downloads stay at 1/second.
# Last.fm: https://www.last.fm/api/intro allows 5 requests/second. We stay at 4.
# Fanart.tv does not publish a client quota. 2/second is the courtesy cap.
# Deezer: 50 requests / 5 seconds. We stop at 40 per 5 seconds.
# TheAudioDB free tier: 30 requests/minute (https://www.theaudiodb.com/free_music_api).
# LRCLIB: sequential calls with a 200–500 ms gap, and honor Retry-After.
# Wikipedia: bot etiquette, about 1 request/second, with a contact in the User-Agent.
# AllMusic has no published client quota. One request every 2.5 seconds keeps a lookup polite.
# AcoustID lookup is limited inside pyacoustid to 3 requests/second.


class Gate:
    def __init__(self, min_interval, windows=(), clock=None, sleep=None):
        self.min_interval = float(min_interval)
        self.windows = tuple(windows)
        self.clock = clock or time.monotonic
        self.sleep = sleep or _sleep
        self.hits = []
        self.lock = threading.Lock()
        self.session = None

    def acquire(self):
        with self.lock:
            self.wait_locked()

    def wait_locked(self):
        while True:
            now = self.clock()
            horizon = self._horizon()
            self.hits = [stamp for stamp in self.hits if now - stamp < horizon]
            delay = 0.0
            if self.hits and self.min_interval > 0:
                delay = max(delay, self.min_interval - (now - self.hits[-1]))
            for span, limit in self.windows:
                recent = [stamp for stamp in self.hits if now - stamp < span]
                if len(recent) >= limit:
                    delay = max(delay, span - (now - recent[0]))
            if delay <= 0:
                self.hits.append(now)
                return
            self.sleep(delay)

    def _horizon(self):
        spans = [span for span, _limit in self.windows]
        if self.min_interval > 0:
            spans.append(self.min_interval)
        return max(spans) if spans else 1.0


def _sleep(seconds):
    from resonance.jobs import ScanCancelled, cancelled

    end = time.monotonic() + seconds
    while True:
        if cancelled():
            raise ScanCancelled()
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.25))


_RULES = (
    ("musicbrainz.org", Gate(1.0)),
    ("coverartarchive.org", Gate(1.0)),
    ("archive.org", Gate(1.0)),
    ("audioscrobbler.com", Gate(0.25)),
    ("fanart.tv", Gate(0.5)),
    ("deezer.com", Gate(0.1, ((5, 40),))),
    ("dzcdn.net", Gate(0.2)),
    ("theaudiodb.com", Gate(2.0, ((60, 30),))),
    ("lrclib.net", Gate(0.4)),
    ("wikipedia.org", Gate(1.0)),
    ("allmusic.com", Gate(2.5)),
    ("wikimedia.org", Gate(1.0)),
)
_default_gates = {}
_default_lock = threading.Lock()


def gate_for(url):
    host = (urlparse(url).hostname or "").lower()
    for suffix, gate in _RULES:
        if host == suffix or host.endswith("." + suffix):
            return gate
    with _default_lock:
        gate = _default_gates.get(host)
        if gate is None:
            gate = Gate(1.0)
            _default_gates[host] = gate
        return gate
