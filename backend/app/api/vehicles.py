"""Vehicle trajectory and tracking endpoints."""

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.config import settings
from app.core.deps import get_db, require_role
from app.matching.haversine import est_speed_kmh
from app.models.camera import Camera
from app.models.sighting import Sighting
from app.models.user import User
from app.services.audit import write_audit_log

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    val = val.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    if " " in val and "+" not in val:
        val = val.replace(" ", "+")
    return datetime.fromisoformat(val)


@router.get("/{plate}/trajectory")
async def get_trajectory(
    plate: str,
    request: Request,
    from_param: str | None = Query(default=None, alias="from"),
    to_param: str | None = Query(default=None, alias="to"),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
) -> dict[str, Any]:
    """Retrieve GeoJSON FeatureCollection trajectory for a vehicle ordered chronologically by timestamp.

    Uses the composite index (plate_number, timestamp DESC) for optimal latency.
    """
    from_ts = parse_dt(from_param)
    to_ts = parse_dt(to_param)
    await write_audit_log(
        db,
        user_id=user.id,
        action="trace",
        resource="vehicles",
        resource_id=plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    # Query matching index (plate_number, timestamp DESC)
    stmt = (
        select(
            Sighting.id,
            Sighting.plate_number,
            Sighting.ocr_confidence,
            Sighting.timestamp,
            Sighting.snapshot_path,
            Camera.name.label("camera_name"),
            Camera.latitude,
            Camera.longitude,
        )
        .join(Camera, Camera.id == Sighting.camera_id)
        .where(Sighting.plate_number == plate)
    )

    if from_ts is not None:
        stmt = stmt.where(Sighting.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Sighting.timestamp <= to_ts)

    stmt = stmt.order_by(Sighting.timestamp.desc())

    res = await db.execute(stmt)
    # Reverse rows to return trajectory in chronological order (earliest to latest)
    rows = list(reversed(res.all()))
    n = len(rows)

    point_features: list[dict[str, Any]] = []
    linestring_coords: list[list[float]] = []
    segment_speeds: list[float] = []

    for i, row in enumerate(rows):
        lat = float(row.latitude)
        lon = float(row.longitude)
        coords = [lon, lat]
        linestring_coords.append(coords)

        # Dwell time in seconds until next sighting
        dwell_seconds = None
        if i < n - 1:
            dwell_seconds = max(
                0.0,
                (rows[i + 1].timestamp - row.timestamp).total_seconds(),
            )

        # Snapshot URL
        snapshot_url = None
        if row.snapshot_path:
            if row.snapshot_path.startswith("http") or row.snapshot_path.startswith("/"):
                snapshot_url = row.snapshot_path
            else:
                snapshot_url = f"/snapshots/{Path(row.snapshot_path).name}"

        point_features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": coords,
                },
                "properties": {
                    "camera_name": row.camera_name,
                    "camera": row.camera_name,
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": row.timestamp.isoformat(),
                    "plate": row.plate_number,
                    "plate_number": row.plate_number,
                    "ocr_confidence": (
                        float(row.ocr_confidence)
                        if row.ocr_confidence is not None
                        else 1.0
                    ),
                    "snapshot_url": snapshot_url,
                    "dwell_seconds": dwell_seconds,
                },
            }
        )

    # Compute per-segment estimated speed using Haversine / delta t
    for i in range(n - 1):
        spd = est_speed_kmh(
            rows[i].latitude,
            rows[i].longitude,
            rows[i].timestamp,
            rows[i + 1].latitude,
            rows[i + 1].longitude,
            rows[i + 1].timestamp,
            radius_km=settings.earth_radius_km,
        )
        segment_speeds.append(round(spd, 2))

    linestring_feature: dict[str, Any] | None = None
    if n >= 1:
        linestring_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": linestring_coords,
            },
            "properties": {
                "plate": plate,
                "speeds": segment_speeds,
                "segment_speeds": segment_speeds,
                "speeds_kmh": segment_speeds,
                "total_points": n,
            },
        }

    features = point_features + ([linestring_feature] if linestring_feature else [])

    return {
        "type": "FeatureCollection",
        "plate": plate,
        "features": features,
        "properties": {
            "plate": plate,
            "total_sightings": n,
            "total_segments": len(segment_speeds),
        },
    }
