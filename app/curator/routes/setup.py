"""The setup wizard: first-run status, and the folder and path-mapping checks behind its Test buttons.

Settings are saved through PUT /api/settings and connections are tested through the endpoints the Settings window
uses; these routes only add what the wizard needs on top.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from resonance.errors import AppError

router = APIRouter()


class FolderCheck(BaseModel):
    paths: list[str] = []
    media: str = "music"


class MappingCheck(BaseModel):
    app: str
    rows: list[dict] = []


@router.get("/setup/status")
def setup_status():
    from curator import setup_wizard

    return setup_wizard.status()


@router.post("/setup/done")
def setup_done():
    from curator import setup_wizard

    return setup_wizard.mark_done()


@router.post("/setup/check-folders")
def setup_check_folders(body: FolderCheck):
    from curator import setup_wizard
    from resonance.paths import discover_mounts

    if body.media not in setup_wizard.MEDIA_LABELS:
        raise AppError("Unknown media type", 400)
    mounts = discover_mounts()
    return {"results": [setup_wizard.check_folder(path, body.media, mounts) for path in body.paths[:20]]}


@router.post("/setup/check-mappings")
def setup_check_mappings(body: MappingCheck):
    from curator import setup_wizard

    try:
        return setup_wizard.check_mappings(body.app, body.rows)
    except ValueError as exc:
        raise AppError(str(exc), 400) from exc
    except RuntimeError as exc:
        raise AppError(str(exc), 502) from exc
