from fastapi import APIRouter

from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.cameras import router as cameras_router
from app.api.jobs import router as jobs_router
from app.api.search import router as search_router
from app.api.sightings import router as sightings_router
from app.api.vehicles import router as vehicles_router
from app.api.ws import router as ws_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(cameras_router)
api_router.include_router(jobs_router)
api_router.include_router(sightings_router)
api_router.include_router(vehicles_router)
api_router.include_router(alerts_router)
api_router.include_router(search_router)
api_router.include_router(ws_router)
