from fastapi import APIRouter
from pydantic import BaseModel

from curator.routes.scrape import _ids
from curator.video import scanner, scrape, tags
from resonance.errors import AppError

router = APIRouter(prefix="/tags")


def _idle():
    if scanner.running() or scrape.running():
        raise AppError("Wait for the running scan or scrape to finish", 409)


@router.get("")
def list_tags(media: str = "movies", ids: str = ""):
    picked = _ids([item for item in ids.split(",") if item]) if ids else None
    return {"media": media, "tags": tags.list_tags(media, picked)}


class RenameBody(BaseModel):
    media: str
    old: str
    new: str


@router.post("/rename")
def rename_tag(body: RenameBody):
    _idle()
    changed = tags.rename(body.media, body.old, body.new)
    tags.write_nfos(body.media, changed)
    return {"changed": len(changed)}


class DeleteBody(BaseModel):
    media: str
    tag: str


@router.post("/delete")
def delete_tag(body: DeleteBody):
    _idle()
    changed = tags.delete(body.media, body.tag)
    tags.write_nfos(body.media, changed)
    return {"changed": len(changed)}


class ApplyBody(BaseModel):
    kind: str
    ids: list[str]
    add: list[str] = []
    remove: list[str] = []


@router.post("/apply")
def apply_tags(body: ApplyBody):
    _idle()
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item", 400)
    changed = tags.apply(body.kind, ids, body.add, body.remove)
    tags.write_nfos(body.kind, changed)
    return {"changed": len(changed), "locked": len(ids) - len(changed)}


class ScrapeBody(BaseModel):
    kind: str
    ids: list[str]


@router.post("/scrape")
def scrape_tags(body: ScrapeBody):
    _idle()
    ids = _ids(body.ids)
    if not ids:
        raise AppError("Pick at least one item", 400)
    changed, empty = tags.scrape(body.kind, ids)
    tags.write_nfos(body.kind, changed)
    return {"changed": len(changed), "without_keywords": empty}
