import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from curator import insights
from resonance.errors import AppError

router = APIRouter()


@router.get("/analytics")
def analytics(media: str = "all", root: str = ""):
    if media not in {"all", "music", "movies", "tv"}:
        raise AppError("Analytics cover all libraries, music, movies or tv", 400)
    return insights.present(media, root or None)


@router.get("/brands/missing")
def missing_network_icons(format: str = "json", media: str = "tv"):
    """Studios or networks in the library with no logo, with how many items use each.

    media=tv looks at TV networks (media/network), media=movies at movie studios (media/studios).
    """
    from curator.video import brands
    from resonance import db

    if media not in {"tv", "movies"}:
        raise AppError("Choose tv or movies", 400)
    table, kind = ("tv_shows", "network") if media == "tv" else ("movies", "studios")
    rows = db.fetchall(
        f"SELECT btrim(name) AS name, COUNT(*) AS shows FROM {table}, unnest(studios) AS name "
        "WHERE btrim(name) <> '' GROUP BY btrim(name)"
    )
    found = brands.missing({row["name"]: row["shows"] for row in rows}, kind)
    if format == "csv":
        lines = ["name,items"] + ['"%s",%d' % (row["name"].replace('"', '""'), row["shows"]) for row in found]
        return Response(
            "\n".join(lines) + "\n",
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="%s-without-icons.csv"' % ("networks" if media == "tv" else "studios")},
        )
    return {"count": len(found), "networks": found}


@router.post("/brands/upload")
async def upload_brand_logo(kind: str = Form(...), name: str = Form(...), file: UploadFile = File(...)):
    """Add a logo for a network or studio name that has none. It is kept in the data folder."""
    from curator.video import brands

    if kind not in {"network", "studios"}:
        raise AppError("Logos can be added for networks and studios", 400)
    data = await file.read(brands.MAX_LOGO_BYTES + 1)
    filename = await run_in_threadpool(brands.save_custom, name, kind, data)
    return {"saved": True, "file": filename, "matched": bool(brands.file_for(name, kind))}


@router.get("/brands/unused")
def unused_network_icons():
    """Logo files in media/network that no TV network in the library uses."""
    from curator.video import brands
    from resonance import db

    rows = db.fetchall(
        "SELECT DISTINCT btrim(name) AS name FROM tv_shows, unnest(studios) AS name WHERE btrim(name) <> ''"
    )
    files = brands.unused([row["name"] for row in rows], "network")
    return {"count": len(files), "files": files}


@router.get("/analytics/scans")
def scans(range: str = "month"):
    return insights.scans(range)


class ExportBody(BaseModel):
    media: str
    ids: list[str]
    format: str = "csv"
    roots: list[str] = []


@router.post("/export")
def export(body: ExportBody):
    try:
        ids = [str(uuid.UUID(str(item))) for item in body.ids][:100000]
    except ValueError as exc:
        raise AppError("Unknown item", 400) from exc
    if not ids:
        raise AppError("Nothing to export. Clear the filter or pick another scan path.", 400)
    name, media_type, text, count = insights.export(body.media, ids, body.format, [root for root in body.roots if root])
    return Response(content=text.encode("utf-8"), media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Export-Count": str(count)})
