from fastapi import APIRouter

from curator.routes import arr_search, automation, copies, files, filters, insights, language, library, radarr, remux, opensubs, scan, scrape, split, sub_sync, system, tags, trakt, wanted

router = APIRouter(prefix="/api/v1")
router.include_router(system.router)
router.include_router(scan.router)
router.include_router(scrape.router)
router.include_router(library.router)
router.include_router(trakt.router)
router.include_router(automation.router)
router.include_router(radarr.router)
router.include_router(arr_search.router)
router.include_router(files.router)
router.include_router(split.router)
router.include_router(sub_sync.router)
router.include_router(opensubs.router)
router.include_router(language.router)
router.include_router(remux.router)
router.include_router(filters.router)
router.include_router(copies.router)
router.include_router(tags.router)
router.include_router(insights.router)
router.include_router(wanted.router)
