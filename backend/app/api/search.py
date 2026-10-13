"""Search endpoint for vehicle plates with fuzzy suggestions (Levenshtein <= 2)."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from rapidfuzz.distance import Levenshtein
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.audit import write_audit_log

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_plates(
    request: Request,
    plate: str | None = Query(default=None),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search for vehicle license plates with fuzzy suggestions (Levenshtein distance <= 2)."""
    search_plate = (plate or "").strip().upper()

    await write_audit_log(
        db,
        user_id=user.id,
        action="search",
        resource="vehicles",
        resource_id=plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    if not search_plate:
        return {
            "query": plate or "",
            "plate": plate or "",
            "suggestions": [],
            "results": [],
            "matches": [],
        }

    # Fetch vehicles to match against
    stmt = select(
        Vehicle.id,
        Vehicle.plate_number,
        Vehicle.sighting_count,
        Vehicle.vehicle_class,
        Vehicle.first_seen,
        Vehicle.last_seen,
    )
    res = await db.execute(stmt)
    vehicles = res.all()

    candidates: list[dict[str, Any]] = []
    for v in vehicles:
        dist = Levenshtein.distance(v.plate_number, search_plate)
        if dist <= 2:
            candidates.append(
                {
                    "vehicle_id": v.id,
                    "plate_number": v.plate_number,
                    "plate": v.plate_number,
                    "distance": dist,
                    "sighting_count": v.sighting_count or 0,
                    "vehicle_class": (
                        v.vehicle_class.value
                        if hasattr(v.vehicle_class, "value")
                        else str(v.vehicle_class)
                    ),
                    "first_seen": v.first_seen.isoformat() if v.first_seen else None,
                    "last_seen": v.last_seen.isoformat() if v.last_seen else None,
                    "is_exact": dist == 0,
                }
            )

    # Sort: lowest Levenshtein distance first, then highest sighting count
    candidates.sort(key=lambda c: (c["distance"], -(c["sighting_count"] or 0)))

    return {
        "query": plate,
        "plate": plate,
        "suggestions": candidates,
        "results": candidates,
        "matches": candidates,
        "total": len(candidates),
    }
