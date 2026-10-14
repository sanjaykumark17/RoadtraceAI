"""Search endpoint for vehicle plates with fuzzy suggestions (Levenshtein <= 2) in SQL."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.deps import get_db, require_role
from app.core.rate_limiter import check_api_rate_limit
from app.models.user import User
from app.services.audit import write_audit_log

router = APIRouter(tags=["search"])


@router.get("/search", dependencies=[Depends(check_api_rate_limit)])
async def search_plates(
    request: Request,
    plate: str | None = Query(default=None),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
) -> dict[str, Any]:
    """Search for vehicle license plates with fuzzy suggestions (Levenshtein distance <= 2)."""
    search_plate = (plate or "").strip().upper()

    await write_audit_log(
        db,
        user_id=user.id,
        action="search",
        resource="vehicles",
        resource_id=search_plate,
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
            "total": 0,
        }

    min_len = max(1, len(search_plate) - 2)
    max_len = len(search_plate) + 2

    sql_query = text("""
        SELECT id, plate_number, sighting_count, vehicle_class, first_seen, last_seen,
               levenshtein(plate_number, :search_plate) AS distance
        FROM vehicles
        WHERE length(plate_number) BETWEEN :min_len AND :max_len
          AND levenshtein(plate_number, :search_plate) <= 2
        ORDER BY distance ASC, sighting_count DESC
        LIMIT 50
    """)
    res = await db.execute(
        sql_query,
        {
            "search_plate": search_plate,
            "min_len": min_len,
            "max_len": max_len,
        },
    )
    rows = res.mappings().all()

    candidates: list[dict[str, Any]] = []
    for r in rows:
        v_class = r["vehicle_class"]
        v_class_str = v_class.value if hasattr(v_class, "value") else str(v_class)
        candidates.append(
            {
                "vehicle_id": r["id"],
                "plate_number": r["plate_number"],
                "plate": r["plate_number"],
                "distance": int(r["distance"]),
                "sighting_count": r["sighting_count"] or 0,
                "vehicle_class": v_class_str,
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                "is_exact": int(r["distance"]) == 0,
            }
        )

    return {
        "query": plate,
        "plate": plate,
        "suggestions": candidates,
        "results": candidates,
        "matches": candidates,
        "total": len(candidates),
    }
