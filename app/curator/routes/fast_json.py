"""A JSON reply for large lists that are already cleaned by db.clean.

Returning a dict makes FastAPI walk every value through jsonable_encoder first. For a library of tens of thousands of
albums that walk took longer than building the list. db.clean already leaves only JSON values, so they go straight to
json.dumps. The GZip middleware still compresses the reply.
"""
import json
from decimal import Decimal
from uuid import UUID

from fastapi.responses import Response


def _fallback(value):
    """Anything db.clean left as it was, written the way jsonable_encoder would have."""
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def json_reply(value):
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_fallback, allow_nan=False)
    return Response(content=body.encode("utf-8"), media_type="application/json")
