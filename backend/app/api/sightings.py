from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_db, require_role
from app.matching.matcher import match_sighting
from app.models.camera import Camera
from app.models.enums import VehicleClass
from app.models.sighting import Sighting
from app.models.user import User
from app.schemas.sighting import SightingCreate, SightingOut
from app.services.audit import write_audit_log

router = APIRouter(prefix="/sightings", tags=["sightings"])


@router.post("", response_model=dict, status_code=201)
async def create_sighting(
    body: SightingCreate,
    request: Request,
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
):
    cam = await db.get(Camera, body.camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")

    plate = body.plate_number.strip().upper()
    sighting = Sighting(
        camera_id=body.camera_id,
        plate_number=plate,
        raw_plate_text=body.raw_plate_text or plate,
        ocr_confidence=body.ocr_confidence if body.ocr_confidence is not None else 1.0,
        vehicle_class=body.vehicle_class or VehicleClass.passenger_car,
        track_id=body.track_id or 1,
        timestamp=body.timestamp,
        location=WKTElement(f"POINT({body.longitude} {body.latitude})", srid=4326),
        frames_voted=body.frames_voted or 1,
        job_id=body.job_id or 1,
        snapshot_path=body.snapshot_path,
    )
    db.add(sighting)
    await db.flush()

    match_res = await match_sighting(sighting, db)

    await write_audit_log(
        db,
        user_id=user.id,
        action="create_sighting",
        resource="sightings",
        resource_id=plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(sighting)

    return {
        "status": "created",
        "id": sighting.id,
        "sighting_id": sighting.id,
        "plate_number": sighting.plate_number,
        "vehicle_id": sighting.vehicle_id,
        "match_tier": match_res.tier,
        "triggers_created": match_res.triggers_created,
    }


@router.get("", response_model=List[SightingOut])
async def search_sightings(
    request: Request,
    plate: Optional[str] = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
):
    if from_ts is not None and (from_ts.tzinfo is None or from_ts.utcoffset() is None):
        raise HTTPException(status_code=422, detail="timezone-aware datetime required")
    if to_ts is not None and (to_ts.tzinfo is None or to_ts.utcoffset() is None):
        raise HTTPException(status_code=422, detail="timezone-aware datetime required")

    stmt = select(Sighting)
    clean_plate = plate.strip().upper() if plate else None
    if clean_plate:
        stmt = stmt.where(Sighting.plate_number == clean_plate)
    if from_ts:
        stmt = stmt.where(Sighting.timestamp >= from_ts)
    if to_ts:
        stmt = stmt.where(Sighting.timestamp <= to_ts)
    stmt = stmt.order_by(Sighting.timestamp.desc()).limit(100)

    await write_audit_log(
        db,
        user_id=user.id,
        action="search",
        resource="sightings",
        resource_id=clean_plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    result = await db.execute(stmt)
    return result.scalars().all()
