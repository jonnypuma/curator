"""Actions that wait in the shared job queue and then run on their own thread.

Each function runs to the end before the queue moves on. They return a short message for the log.
"""
from __future__ import annotations


def apply_matches(ids=None):
    from curator.video import scrape

    if not scrape.apply_pending(ids, wait=True):
        return "No unmatched movies or shows were waiting"
    return "Matches applied"


def split_restore(episode_id):
    from curator.video import split

    return split.restore(episode_id, queued=True).get("message") or "Split restored"


def split_delete_source(episode_id):
    from curator.video import split

    return split.delete_source(episode_id, queued=True).get("message") or "Source deleted"


ACTIONS = {
    "apply_matches": apply_matches,
    "split_restore": split_restore,
    "split_delete_source": split_delete_source,
}
