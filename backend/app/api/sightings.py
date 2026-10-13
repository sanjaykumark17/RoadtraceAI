from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_current_user, get_db, require_role
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
    # matching service is a stub for now; will be implemented in later steps
    await write_audit_log(
        db,
        user_id=user.id,
        action="create_sighting",
        resource="sightings",
        resource_id=body.plate_number,
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return {
        "status": "queued",
        "plate_number": body.plate_number,
        "message": "matching service stub: sighting recorded for processing",
    }


@router.get("", response_model=List[SightingOut])
async def search_sightings(
    request: Request,
    plate: Optional[str] = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Sighting)
    if plate:
        stmt = stmt.where(Sighting.plate_number == plate)
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
        resource_id=plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    result = await db.execute(stmt)
    return result.scalars().all()
