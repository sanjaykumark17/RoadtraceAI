from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api import api_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.security import decode_token
from app.db.session import AsyncSession
from app.models.user import User
from app.services.notifier import broadcaster


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broadcaster.start()
    yield
    await broadcaster.stop()


app = FastAPI(
    title="RoadTrace AI",
    version="0.1.0",
    description="Multi-camera vehicle tracking and travel-path reconstruction system using ANPR",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def get_authenticated_user_for_snapshot(
    request: Request,
    token: str | None = Query(default=None),
) -> User:
    auth_token = token
    if not auth_token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ", 1)[1]

    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to view snapshots",
        )

    payload = decode_token(auth_token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    async with AsyncSession() as session:
        user = await session.scalar(select(User).where(User.id == int(user_id)))
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )
        return user


@app.get("/snapshots/{filename}")
async def get_snapshot(
    filename: str,
    _user: User = Depends(get_authenticated_user_for_snapshot),
):
    """Serve vehicle snapshot JPEG via authenticated route with path traversal protection."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename",
        )

    base_dir = Path(settings.snapshots_dir).resolve()
    target_path = (base_dir / filename).resolve()

    # Prevent directory traversal outside snapshots_dir
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal forbidden",
        )

    if not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Snapshot image not found",
        )

    return FileResponse(path=str(target_path), media_type="image/jpeg")


app.include_router(api_router)
app.include_router(ws_router)

