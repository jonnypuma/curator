import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from curator import trakt, trakt_sync
from resonance.errors import AppError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trakt")


def _base_url(request: Request):
    return str(request.base_url).rstrip("/")


class ClientBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class AuthorizeBody(BaseModel):
    signup: bool = False
    force_login: bool = False


@router.get("/status")
def status(request: Request):
    data = trakt.status()
    data["redirect_uri"] = trakt.redirect_uri(_base_url(request))
    return data


@router.put("/client")
def save_client(body: ClientBody, request: Request):
    data = trakt.save_client(body.client_id, body.client_secret)
    data["redirect_uri"] = trakt.redirect_uri(_base_url(request))
    return data


@router.post("/device")
def device_start():
    return trakt.start_device()


@router.get("/device")
def device_poll():
    return trakt.poll_device()


@router.delete("/device")
def device_cancel():
    return trakt.cancel_device()


@router.post("/authorize")
def authorize(body: AuthorizeBody, request: Request):
    return trakt.authorize_url(_base_url(request), signup=body.signup, force_login=body.force_login)


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse("/?trakt=denied", status_code=303)
    try:
        await run_in_threadpool(trakt.finish, state, code)
    except AppError as exc:
        logger.warning("Trakt sign-in failed: %s", exc)
        return RedirectResponse("/?trakt=failed", status_code=303)
    return RedirectResponse("/?trakt=connected", status_code=303)


@router.post("/disconnect")
def disconnect():
    return trakt.disconnect()


class SyncBody(BaseModel):
    mode: str = "both"


@router.post("/sync")
def start_sync(body: SyncBody):
    if not trakt_sync.start(body.mode):
        raise AppError("A Trakt sync is already running", 409)
    return trakt_sync.status()


@router.get("/sync")
def sync_status():
    return trakt_sync.status()
