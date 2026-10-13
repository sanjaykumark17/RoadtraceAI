"""Three-Tier Matcher with Haversine Kinematic Verification (Tiers 1, 2, 3)."""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz.distance import Levenshtein
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.matching.haversine import est_speed_kmh
from app.models.alert import Alert
from app.models.alert_trigger import AlertTrigger
from app.models.camera import Camera
from app.models.sighting import Sighting
from app.models.vehicle import Vehicle

logger = logging.getLogger("roadtrace.matching")


@dataclass
class MatchResult:
    """Result of multi-tier spatio-temporal matching."""

    vehicle: Vehicle
    tier: str  # 'exact', 'fuzzy', or 'new'
    speed_kmh: Optional[float]
    flag: Optional[str]
    triggers_created: int


async def get_vehicle_last_sighting(
    vehicle_id: int,
    session: AsyncSession,
    before_timestamp: datetime,
    exclude_sighting_id: Optional[int] = None,
) -> Optional[Tuple[Sighting, float, float]]:
    """Retrieve the vehicle's most recent prior sighting and its camera (lat, lon)."""
    stmt = (
        select(Sighting, Camera.latitude, Camera.longitude)
        .join(Camera, Camera.id == Sighting.camera_id)
        .where(
            Sighting.vehicle_id == vehicle_id,
            Sighting.timestamp <= before_timestamp,
        )
    )
    if exclude_sighting_id is not None:
        stmt = stmt.where(Sighting.id != exclude_sighting_id)

    stmt = stmt.order_by(Sighting.timestamp.desc()).limit(1)
    res = await session.execute(stmt)
    row = res.first()
    if row:
        sighting, lat, lon = row
        return sighting, float(lat), float(lon)
    return None


async def match(
    new_sighting: Sighting,
    session: AsyncSession,
) -> MatchResult:
    """Match a new sighting using the 3-tier matching engine in a single DB transaction.

    Tier 1 (Exact):
        Look up vehicle by plate_number (indexed). If found, attach sighting.
        If v_est > 150 km/h, flag as 'suspicious_duplicate_plate'.

    Tier 2 (Fuzzy + Kinematic):
        Pre-filter by same length and first 2 characters in SQL.
        Filter by Levenshtein distance <= 2 using rapidfuzz.
        Compute kinematic speed v_est to each candidate's last sighting.
        Accept closest candidate ONLY if v_est <= 150 km/h.

    Tier 3 (New):
        Otherwise create a new vehicle row and attach sighting.

    Finally:
        Update vehicles.last_seen and sighting_count.
        Create alert_triggers rows if plate is on an active alert.
    """
    plate = new_sighting.plate_number.strip().upper()
    new_sighting.plate_number = plate

    # Determine latitude and longitude of new_sighting's camera
    new_lat = 0.0
    new_lon = 0.0
    if new_sighting.camera_id:
        cam = await session.get(Camera, new_sighting.camera_id)
        if cam:
            new_lat = float(cam.latitude)
            new_lon = float(cam.longitude)

    matched_vehicle: Optional[Vehicle] = None
    matched_tier: str = "new"
    est_speed: Optional[float] = None
    flag: Optional[str] = new_sighting.flag

    # -------------------------------------------------------------
    # TIER 1: EXACT MATCH
    # -------------------------------------------------------------
    exact_stmt = select(Vehicle).where(Vehicle.plate_number == plate)
    exact_res = await session.execute(exact_stmt)
    exact_vehicle = exact_res.scalar_one_or_none()

    if exact_vehicle is not None:
        matched_vehicle = exact_vehicle
        matched_tier = "exact"
        new_sighting.vehicle_id = exact_vehicle.id

        # Kinematic speed check against its last sighting
        last_info = await get_vehicle_last_sighting(
            vehicle_id=exact_vehicle.id,
            session=session,
            before_timestamp=new_sighting.timestamp,
            exclude_sighting_id=new_sighting.id,
        )
        if last_info is not None:
            last_sighting, last_lat, last_lon = last_info
            est_speed = est_speed_kmh(
                last_lat,
                last_lon,
                last_sighting.timestamp,
                new_lat,
                new_lon,
                new_sighting.timestamp,
                radius_km=settings.earth_radius_km,
            )
            if est_speed > settings.v_max_kmh:
                flag = "suspicious_duplicate_plate"
                new_sighting.flag = flag
                logger.warning(
                    f"Tier 1 duplicate plate detected: {plate} estimated speed {est_speed:.1f} km/h > {settings.v_max_kmh} km/h"
                )

    # -------------------------------------------------------------
    # TIER 2: FUZZY + KINEMATIC
    # -------------------------------------------------------------
    if matched_vehicle is None:
        plate_len = len(plate)
        prefix = plate[:2]

        # Pre-filter in SQL by same length and same first 2 characters
        cand_stmt = select(Vehicle).where(
            func.length(Vehicle.plate_number) == plate_len,
            Vehicle.plate_number.startswith(prefix),
        )
        cand_res = await session.execute(cand_stmt)
        candidates = cand_res.scalars().all()

        eligible_candidates: List[Dict[str, Any]] = []
        for cand in candidates:
            dist = Levenshtein.distance(cand.plate_number, plate)
            if dist <= settings.levenshtein_max:
                # Compute kinematic speed v_est to candidate's last sighting
                last_info = await get_vehicle_last_sighting(
                    vehicle_id=cand.id,
                    session=session,
                    before_timestamp=new_sighting.timestamp,
                    exclude_sighting_id=new_sighting.id,
                )
                if last_info is None:
                    continue

                last_sighting, last_lat, last_lon = last_info
                cand_speed = est_speed_kmh(
                    last_lat,
                    last_lon,
                    last_sighting.timestamp,
                    new_lat,
                    new_lon,
                    new_sighting.timestamp,
                    radius_km=settings.earth_radius_km,
                )

                # Kinematic validation gate: accept ONLY if speed <= 150 km/h
                if cand_speed <= settings.v_max_kmh:
                    eligible_candidates.append(
                        {
                            "vehicle": cand,
                            "distance": dist,
                            "speed": cand_speed,
                        }
                    )
                else:
                    logger.info(
                        f"Tier 2 rejected candidate {cand.plate_number} for {plate}: "
                        f"speed {cand_speed:.1f} km/h exceeds limit {settings.v_max_kmh} km/h"
                    )

        if eligible_candidates:
            # Pick closest candidate by lowest Levenshtein distance, tie-break by lowest speed
            eligible_candidates.sort(key=lambda item: (item["distance"], item["speed"]))
            best = eligible_candidates[0]
            matched_vehicle = best["vehicle"]
            matched_tier = "fuzzy"
            est_speed = best["speed"]
            new_sighting.vehicle_id = matched_vehicle.id
            logger.info(
                f"Tier 2 fuzzy match: read '{plate}' linked to vehicle '{matched_vehicle.plate_number}' "
                f"(dist={best['distance']}, speed={est_speed:.1f} km/h)"
            )

    # -------------------------------------------------------------
    # TIER 3: NEW VEHICLE
    # -------------------------------------------------------------
    if matched_vehicle is None:
        new_vehicle = Vehicle(
            plate_number=plate,
            vehicle_class=new_sighting.vehicle_class,
            first_seen=new_sighting.timestamp,
            last_seen=new_sighting.timestamp,
            sighting_count=0,  # Will be incremented below
        )
        session.add(new_vehicle)
        await session.flush()
        matched_vehicle = new_vehicle
        matched_tier = "new"
        new_sighting.vehicle_id = new_vehicle.id
        logger.info(f"Tier 3 new vehicle created: {plate}")

    # -------------------------------------------------------------
    # VEHICLE STATS UPDATE
    # -------------------------------------------------------------
    if matched_vehicle.last_seen is None or new_sighting.timestamp > matched_vehicle.last_seen:
        matched_vehicle.last_seen = new_sighting.timestamp
    matched_vehicle.sighting_count = (matched_vehicle.sighting_count or 0) + 1

    # -------------------------------------------------------------
    # SIGHTING PERSISTENCE
    # -------------------------------------------------------------
    if new_sighting.id is None:
        session.add(new_sighting)
    await session.flush()

    # -------------------------------------------------------------
    # ACTIVE ALERTS CHECK & TRIGGER
    # -------------------------------------------------------------
    alert_plates = {matched_vehicle.plate_number, plate}
    alert_stmt = select(Alert).where(
        Alert.is_active == True,
        Alert.plate_number.in_(list(alert_plates)),
    )
    alert_res = await session.execute(alert_stmt)
    active_alerts = alert_res.scalars().all()

    triggers_created = 0
    for alert in active_alerts:
        trigger = AlertTrigger(
            alert_id=alert.id,
            sighting_id=new_sighting.id,
            triggered_at=new_sighting.timestamp,
        )
        session.add(trigger)
        triggers_created += 1
        logger.warning(
            f"ALERT TRIGGERED! Alert id={alert.id} for plate={alert.plate_number} "
            f"on sighting id={new_sighting.id}"
        )

    await session.commit()
    await session.refresh(matched_vehicle)
    await session.refresh(new_sighting)

    return MatchResult(
        vehicle=matched_vehicle,
        tier=matched_tier,
        speed_kmh=est_speed,
        flag=flag,
        triggers_created=triggers_created,
    )
