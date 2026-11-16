from fastapi import APIRouter
from pydantic import BaseModel

from resonance import trash
from resonance.errors import AppError

router = APIRouter()


class TrashIds(BaseModel):
    ids: list[str] = []


@router.get("/disk")
def disk_dashboard():
    from curator import disk

    return disk.dashboard()


@router.get("/trash")
def list_trash():
    on, days = trash.settings()
    rows = trash.items()
    return {"enabled": on, "days": days, "items": rows, "size_bytes": sum(int(row.get("size_bytes") or 0) for row in rows)}


@router.post("/trash/restore")
def restore_trash(body: TrashIds):
    if not body.ids:
        raise AppError("Choose what to restore", 400)
    restored, errors = trash.restore(body.ids)
    queued = 0
    if restored:
        from curator import ingest

        try:
            queued = ingest.queue_restored(restored)
        except Exception as exc:
            errors = [*errors, f"Restored, but the scan was not started: {exc}"]
    return {"restored": restored, "errors": errors, "queued": queued}


@router.post("/trash/delete")
def delete_trash(body: TrashIds):
    if not body.ids:
        raise AppError("Choose what to delete", 400)
    return {"deleted": trash.delete(body.ids)}


@router.post("/trash/empty")
def empty_trash():
    return {"deleted": trash.delete(None)}
