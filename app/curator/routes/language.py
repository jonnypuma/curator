from fastapi import APIRouter
from pydantic import BaseModel

from curator.video import language_defaults

router = APIRouter()


class SearchBody(BaseModel):
    mode: str = "not_default"
    lang: str = "eng"
    filename: str = ""
    scope: str = ""
    offset: int = 0


class SaveBody(BaseModel):
    lang: str
    ids: list[str]
    picks: dict = {}


@router.get("/language-defaults")
def language_options():
    return {"languages": language_defaults.languages(), "scopes": language_defaults.scopes(), "save": language_defaults.status()}


@router.post("/language-defaults/search")
def language_search(body: SearchBody):
    return language_defaults.search(body.mode, body.lang, body.filename, body.scope, body.offset)


@router.post("/language-defaults/save")
def language_save(body: SaveBody):
    return language_defaults.start_save(body.lang, body.ids, body.picks or {})


@router.get("/language-defaults/save")
def language_save_status():
    return language_defaults.status()
