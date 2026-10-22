"""OpenSubtitles.com lookup and download for one movie or episode, under /api/v1/subs/find."""
from fastapi import APIRouter
from pydantic import BaseModel

from curator.video import config, opensubs
from resonance.errors import AppError

router = APIRouter()


class FindBody(BaseModel):
    kind: str
    id: str
    languages: str = ""
    hearing: str = ""


class GetBody(BaseModel):
    kind: str
    id: str
    file_id: int
    language: str
    hearing_impaired: bool = False
    hash_match: bool = False


class TestBody(BaseModel):
    key: str = ""
    username: str = ""
    password: str = ""


@router.post("/subs/find")
def find(body: FindBody):
    cfg = config.current()
    item = opensubs.target(body.kind, body.id)
    tags = [tag for _code, tag in (opensubs.wanted_languages({**cfg, "subs_languages": body.languages}) if body.languages.strip() else opensubs.wanted_languages(cfg))]
    hearing = body.hearing if body.hearing in ("include", "exclude", "only") else "include"
    results = opensubs.search(cfg, item, tags, hearing)
    have = sorted(opensubs.present_languages(item))
    return {
        "results": results, "languages": tags, "have": have, "path": item.get("path") or "",
        "can_download": opensubs.can_download(cfg),
        "title": item["title"] if item["kind"] == "movie" else f"{item['title']} S{int(item['season'] or 0):02d}E{int(item['episode'] or 0):02d}",
    }


@router.post("/subs/get")
def get(body: GetBody):
    cfg = config.current()
    item = opensubs.target(body.kind, body.id)
    result = {"file_id": body.file_id, "language": body.language, "hearing_impaired": body.hearing_impaired,
              "hash_match": body.hash_match}
    name, left = opensubs.download(cfg, item, result, background=True)
    message = f"Saved {name}."
    if cfg.get("subs_sync_after") and not body.hash_match:
        message += " Checking its timing against the audio in the background."
    if left is not None:
        message += f" {left} download{'s' if left != 1 else ''} left today."
    return {"saved": name, "remaining": left, "message": message}


@router.post("/subs/opensubtitles/test")
def test(body: TestBody):
    cfg = config.current()
    typed = {"opensubtitles_key": body.key.strip(), "subs_username": body.username.strip(), "opensubtitles_password": body.password.strip()}
    merged = {**cfg, **{key: value for key, value in typed.items() if value}}
    if not opensubs.configured(merged):
        raise AppError("Enter an OpenSubtitles API key first", 400)
    return opensubs.test(merged)
