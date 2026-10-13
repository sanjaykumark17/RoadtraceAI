from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.models.camera import Camera
from app.models.user import User
from app.schemas.camera import CameraCreate, CameraOut, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=List[CameraOut])
async def list_cameras(
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Camera).order_by(Camera.id))
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(
    camera_id: int,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    return cam


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(
    body: CameraCreate,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    cam = Camera(
        name=body.name,
        latitude=body.latitude,
        longitude=body.longitude,
        intersection_name=body.intersection_name,
        heading_deg=body.heading_deg,
        status=body.status,
        location=WKTElement(f"POINT({body.longitude} {body.latitude})", srid=4326),
    )
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.put("/{camera_id}", response_model=CameraOut)
async def update_camera(
    camera_id: int,
    body: CameraUpdate,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(cam, field, value)
    if "latitude" in updates or "longitude" in updates:
        lat = updates.get("latitude", cam.latitude)
        lon = updates.get("longitude", cam.longitude)
        cam.location = WKTElement(f"POINT({lon} {lat})", srid=4326)
    await db.commit()
    await db.refresh(cam)
    return cam


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(
    camera_id: int,
    db: SAAsyncSession = Depends(get_db),
    _user: User = Depends(require_role("admin")),
):
    cam = await db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    await db.delete(cam)
    await db.commit()
