"""Show a background task in the Jobs panel (a `work_jobs` row), without ever failing the task.

Subtitle OCR and the video preview copy run in their own threads; this just mirrors their
progress. Every database error is swallowed so tests and tools without a database still work.
"""
import logging
import time

logger = logging.getLogger(__name__)


def record(kind, message, status="completed"):
    """Leave a finished entry in the Jobs list for something that took no time, like a saved subtitle."""
    item = Tracked(kind, message, 1)
    item.finish(status, message, 1)


class Tracked:
    def __init__(self, kind, message, total=0):
        self.kind, self.total, self.id = kind, int(total or 0), None
        self._last = 0.0
        try:
            from resonance import jobs

            row = jobs.begin_work(kind, message, self.total)
            self.id = row["id"] if row else None
        except Exception:
            logger.debug("job tracking unavailable", exc_info=True)

    def update(self, processed, message, force=False):
        if self.id is None:
            return
        now = time.monotonic()
        if not force and now - self._last < 1.0:
            return
        self._last = now
        try:
            from resonance import jobs

            jobs.touch_work(self.id, int(processed), message, "")
        except Exception:
            logger.debug("job tracking failed", exc_info=True)

    def finish(self, status, message, processed=None):
        """status: completed | cancelled | failed."""
        if self.id is None:
            return
        try:
            from resonance import jobs

            jobs.finish_work(self.id, status, message, processed)
        except Exception:
            logger.debug("job tracking failed", exc_info=True)
