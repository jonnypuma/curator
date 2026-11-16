from fastapi import APIRouter
from pydantic import BaseModel

from curator import arr_orphans

router = APIRouter()


class DiscardBody(BaseModel):
    path: str
    app: str = ""
    arr_id: int | None = None


class RescanBody(BaseModel):
    app: str
    arr_id: int


class ForgetBody(BaseModel):
    paths: list[str] = []


@router.get("/arr-orphans")
def orphan_report():
    return arr_orphans.status()


@router.get("/arr-orphans/test")
def orphan_test():
    return {"results": arr_orphans.test_connections()}


@router.post("/arr-orphans/scan")
def orphan_scan():
    return {"started": arr_orphans.start()}


@router.post("/arr-orphans/discard")
def orphan_discard(body: DiscardBody):
    return {"ok": arr_orphans.discard(body.path, body.app, body.arr_id)}


@router.post("/arr-orphans/rescan")
def orphan_rescan(body: RescanBody):
    return {"ok": arr_orphans.rescan(body.app, body.arr_id)}


@router.post("/arr-orphans/forget")
def orphan_forget(body: ForgetBody):
    arr_orphans.forget(body.paths)
    return {"ok": True}


# The Kodi report (curator/kodi_report.py): Kodi's video library compared with Curator's, by file.

class KodiScanBody(BaseModel):
    folders: list[str] = []


@router.get("/kodi-report")
def kodi_report_status():
    from curator import kodi_report

    return kodi_report.status()


@router.post("/kodi-report/scan")
def kodi_report_start():
    from curator import kodi_report

    return kodi_report.start()


@router.post("/kodi-report/clean")
def kodi_report_clean():
    from curator import kodi_report

    return kodi_report.clean()


@router.post("/kodi-report/scan-folders")
def kodi_report_scan_folders(body: KodiScanBody):
    from curator import kodi_report

    return {"queued": kodi_report.scan_folders(body.folders)}
