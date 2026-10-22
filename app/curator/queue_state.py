from curator import arr_queue, ingest, library_queue


def snapshot():
    """Webhook, scan, ARR, and library-update queue state for the header countdown."""
    data = ingest.snapshot()
    try:
        data["arr"] = arr_queue.snapshot()
    except Exception:
        data["arr"] = []
    try:
        data["library"] = library_queue.snapshot()
    except Exception:
        data["library"] = []
    return data
