from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.ws import router as ws_router

app = FastAPI(
    title="RoadTrace AI",
    version="0.1.0",
    description="Multi-camera vehicle tracking and travel-path reconstruction system using ANPR",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(api_router)
app.include_router(ws_router)
