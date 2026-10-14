"""Vehicle trajectory and tracking endpoints."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

from app.core.config import settings
from app.core.deps import get_db, require_role
from app.core.rate_limiter import check_api_rate_limit
from app.matching.haversine import est_speed_kmh
from app.matching.road_distance import async_get_snapped_segment
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
    try:
        dt = datetime.fromisoformat(val)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid datetime format: {e}",
        )
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="timezone-aware datetime required",
        )
    return dt


@router.get("/{plate}/trajectory", dependencies=[Depends(check_api_rate_limit)])
async def get_trajectory(
    plate: str,
    request: Request,
    from_param: str | None = Query(default=None, alias="from"),
    to_param: str | None = Query(default=None, alias="to"),
    db: SAAsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator", "admin")),
) -> dict[str, Any]:
    """Retrieve GeoJSON FeatureCollection trajectory for a vehicle ordered chronologically by timestamp.

    Uses SQL ORDER BY timestamp ASC, id for stable chronological ordering.
    """
    clean_plate = plate.strip().upper()
    from_ts = parse_dt(from_param)
    to_ts = parse_dt(to_param)
    await write_audit_log(
        db,
        user_id=user.id,
        action="trace",
        resource="vehicles",
        resource_id=clean_plate,
        ip=request.client.host if request.client else None,
    )
    await db.commit()

    # Query with SQL ORDER BY timestamp ASC, id
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
        .where(Sighting.plate_number == clean_plate)
    )

    if from_ts is not None:
        stmt = stmt.where(Sighting.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Sighting.timestamp <= to_ts)

    stmt = stmt.order_by(Sighting.timestamp.asc(), Sighting.id.asc())

    res = await db.execute(stmt)
    rows = res.all()
    n = len(rows)

    point_features: list[dict[str, Any]] = []
    linestring_coords: list[list[float]] = []
    segment_speeds: list[float] = []

    for i, row in enumerate(rows):
        lat = float(row.latitude)
        lon = float(row.longitude)
        coords = [lon, lat]
        linestring_coords.append(coords)

        # Gap time in seconds until next sighting (travel time between sightings)
        gap_seconds = None
        if i < n - 1:
            gap_seconds = max(
                0.0,
                (rows[i + 1].timestamp - row.timestamp).total_seconds(),
            )

        # Snapshot URL
        snapshot_url = None
        if row.snapshot_path:
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
                    "gap_seconds": gap_seconds,
                    "dwell_seconds": gap_seconds,
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

    # OSRM road-snapping for segments with straight-line fallback
    segment_geometries: list[list[list[float]]] = []
    is_road_snapped = False

    if n >= 2:
        try:
            async with httpx.AsyncClient(timeout=settings.osrm_timeout) as client:
                tasks = [
                    async_get_snapped_segment(
                        [rows[i].longitude, rows[i].latitude],
                        [rows[i + 1].longitude, rows[i + 1].latitude],
                        osrm_url=settings.osrm_url,
                        timeout=settings.osrm_timeout,
                        client=client,
                    )
                    for i in range(n - 1)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, res in enumerate(results):
                p1_coords = [float(rows[i].longitude), float(rows[i].latitude)]
                p2_coords = [float(rows[i + 1].longitude), float(rows[i + 1].latitude)]
                if isinstance(res, list) and len(res) >= 2:
                    segment_geometries.append(res)
                    if len(res) > 2 or res != [p1_coords, p2_coords]:
                        is_road_snapped = True
                else:
                    segment_geometries.append([p1_coords, p2_coords])
        except Exception:
            # Fallback to straight line segments if OSRM service is unreachable
            is_road_snapped = False
            segment_geometries = [
                [
                    [float(rows[i].longitude), float(rows[i].latitude)],
                    [float(rows[i + 1].longitude), float(rows[i + 1].latitude)],
                ]
                for i in range(n - 1)
            ]

    # Assemble line geometry: road-snapped if available, otherwise straight line
    if is_road_snapped:
        snapped_coords: list[list[float]] = []
        for seg in segment_geometries:
            if snapped_coords and seg:
                snapped_coords.extend(seg[1:])
            else:
                snapped_coords.extend(seg)
        final_linestring_coords = snapped_coords
    else:
        final_linestring_coords = linestring_coords

    linestring_feature: dict[str, Any] | None = None
    if n >= 1:
        linestring_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": final_linestring_coords,
            },
            "properties": {
                "plate": plate,
                "speeds": segment_speeds,
                "segment_speeds": segment_speeds,
                "speeds_kmh": segment_speeds,
                "segment_geometries": segment_geometries,
                "is_road_snapped": is_road_snapped,
                "total_points": len(final_linestring_coords),
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
            "is_road_snapped": is_road_snapped,
        },
    }
