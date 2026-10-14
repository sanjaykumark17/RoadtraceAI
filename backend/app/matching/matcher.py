"""Three-Tier Matcher with Haversine Kinematic Verification (Tiers 1, 2, 3)."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz.distance import Levenshtein
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


async def get_vehicle_previous_sighting(
    vehicle_id: int,
    session: AsyncSession,
    before_timestamp: datetime,
    exclude_sighting_id: Optional[int] = None,
) -> Optional[Tuple[Sighting, float, float]]:
    """Retrieve the vehicle's most recent prior sighting (timestamp <= before_timestamp) and its camera coordinates."""
    if before_timestamp.tzinfo is None:
        before_timestamp = before_timestamp.replace(tzinfo=timezone.utc)
    else:
        before_timestamp = before_timestamp.astimezone(timezone.utc)

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

    stmt = stmt.order_by(Sighting.timestamp.desc(), Sighting.id.desc()).limit(1)
    res = await session.execute(stmt)
    row = res.first()
    if row:
        sighting, lat, lon = row
        return sighting, float(lat), float(lon)
    return None


async def get_vehicle_next_sighting(
    vehicle_id: int,
    session: AsyncSession,
    after_timestamp: datetime,
    exclude_sighting_id: Optional[int] = None,
) -> Optional[Tuple[Sighting, float, float]]:
    """Retrieve the vehicle's earliest subsequent sighting (timestamp >= after_timestamp) and its camera coordinates."""
    if after_timestamp.tzinfo is None:
        after_timestamp = after_timestamp.replace(tzinfo=timezone.utc)
    else:
        after_timestamp = after_timestamp.astimezone(timezone.utc)

    stmt = (
        select(Sighting, Camera.latitude, Camera.longitude)
        .join(Camera, Camera.id == Sighting.camera_id)
        .where(
            Sighting.vehicle_id == vehicle_id,
            Sighting.timestamp >= after_timestamp,
        )
    )
    if exclude_sighting_id is not None:
        stmt = stmt.where(Sighting.id != exclude_sighting_id)

    stmt = stmt.order_by(Sighting.timestamp.asc(), Sighting.id.asc()).limit(1)
    res = await session.execute(stmt)
    row = res.first()
    if row:
        sighting, lat, lon = row
        return sighting, float(lat), float(lon)
    return None


# Backward-compatible alias
get_vehicle_last_sighting = get_vehicle_previous_sighting


async def match(
    new_sighting: Sighting,
    session: AsyncSession,
) -> MatchResult:
    """Match a new sighting using the 3-tier matching engine in a single DB transaction.

    Tier 1 (Exact):
        Look up vehicle by plate_number (indexed). If found, attach sighting.
        If v_est > 150 km/h, flag as 'suspicious_duplicate_plate'.

    Tier 2 (Fuzzy + Kinematic):
        Pre-filter by plate length within +-2 in SQL (no first-two-characters rule).
        Filter by Levenshtein distance <= 2 using rapidfuzz.
        Validate kinematic speed against both previous and next sightings.
        Accept closest candidate ONLY if all estimated speeds <= 150 km/h.

    Tier 3 (New):
        Use INSERT ... ON CONFLICT for new vehicles to avoid races.

    Finally:
        Update sighting_count and last_seen via atomic SQL.
        Create alert_triggers rows if plate is on an active alert.
    """
    plate = new_sighting.plate_number.strip().upper()
    new_sighting.plate_number = plate

    # Normalize naive timestamps to UTC
    if new_sighting.timestamp.tzinfo is None:
        new_sighting.timestamp = new_sighting.timestamp.replace(tzinfo=timezone.utc)
    else:
        new_sighting.timestamp = new_sighting.timestamp.astimezone(timezone.utc)

    # Determine latitude and longitude of new_sighting's camera; raise error if missing
    if not new_sighting.camera_id:
        raise ValueError("Sighting camera_id is required")

    cam = await session.get(Camera, new_sighting.camera_id)
    if not cam:
        raise ValueError(f"Camera with id {new_sighting.camera_id} not found")

    new_lat = float(cam.latitude)
    new_lon = float(cam.longitude)

    async def validate_vehicle_kinematics(vehicle_id: int) -> Tuple[bool, Optional[float]]:
        """Validate kinematic feasibility against both previous and next sighting."""
        speeds: List[float] = []

        prev_info = await get_vehicle_previous_sighting(
            vehicle_id=vehicle_id,
            session=session,
            before_timestamp=new_sighting.timestamp,
            exclude_sighting_id=new_sighting.id,
        )
        if prev_info is not None:
            prev_sighting, prev_lat, prev_lon = prev_info
            v_prev = est_speed_kmh(
                prev_lat,
                prev_lon,
                prev_sighting.timestamp,
                new_lat,
                new_lon,
                new_sighting.timestamp,
                radius_km=settings.earth_radius_km,
            )
            speeds.append(v_prev)
            if v_prev > settings.v_max_kmh:
                return False, v_prev

        next_info = await get_vehicle_next_sighting(
            vehicle_id=vehicle_id,
            session=session,
            after_timestamp=new_sighting.timestamp,
            exclude_sighting_id=new_sighting.id,
        )
        if next_info is not None:
            next_sighting, next_lat, next_lon = next_info
            v_next = est_speed_kmh(
                new_lat,
                new_lon,
                new_sighting.timestamp,
                next_lat,
                next_lon,
                next_sighting.timestamp,
                radius_km=settings.earth_radius_km,
            )
            speeds.append(v_next)
            if v_next > settings.v_max_kmh:
                return False, v_next

        est_spd = max(speeds) if speeds else None
        return True, est_spd

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

        is_plausible, v_speed = await validate_vehicle_kinematics(exact_vehicle.id)
        est_speed = v_speed
        if not is_plausible:
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
        # Pre-filter by length within +-2 of observed plate (no first-two-characters rule)
        cand_stmt = select(Vehicle).where(
            func.length(Vehicle.plate_number) >= plate_len - 2,
            func.length(Vehicle.plate_number) <= plate_len + 2,
        )
        cand_res = await session.execute(cand_stmt)
        candidates = cand_res.scalars().all()

        eligible_candidates: List[Dict[str, Any]] = []
        for cand in candidates:
            dist = Levenshtein.distance(cand.plate_number, plate)
            if dist <= settings.levenshtein_max:
                is_plausible, cand_speed = await validate_vehicle_kinematics(cand.id)
                if cand_speed is not None and is_plausible:
                    eligible_candidates.append(
                        {
                            "vehicle": cand,
                            "distance": dist,
                            "speed": cand_speed,
                        }
                    )
                elif cand_speed is not None and not is_plausible:
                    logger.info(
                        f"Tier 2 rejected candidate {cand.plate_number} for {plate}: "
                        f"speed {cand_speed:.1f} km/h exceeds limit {settings.v_max_kmh} km/h"
                    )

        if eligible_candidates:
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
    # TIER 3: NEW VEHICLE OR ATOMIC STATS UPDATE
    # -------------------------------------------------------------
    if matched_vehicle is None:
        # Atomic INSERT ... ON CONFLICT to avoid worker races
        insert_stmt = (
            pg_insert(Vehicle)
            .values(
                plate_number=plate,
                vehicle_class=new_sighting.vehicle_class,
                first_seen=new_sighting.timestamp,
                last_seen=new_sighting.timestamp,
                sighting_count=1,
            )
            .on_conflict_do_update(
                index_elements=["plate_number"],
                set_={
                    "sighting_count": Vehicle.sighting_count + 1,
                    "last_seen": func.greatest(Vehicle.last_seen, new_sighting.timestamp),
                },
            )
            .returning(Vehicle)
        )
        res = await session.execute(insert_stmt)
        matched_vehicle = res.scalar_one()
        matched_tier = "new"
        new_sighting.vehicle_id = matched_vehicle.id
        logger.info(f"Tier 3 new vehicle created/upserted: {plate}")
    else:
        # Atomic stats update on matched vehicle
        update_stmt = (
            update(Vehicle)
            .where(Vehicle.id == matched_vehicle.id)
            .values(
                sighting_count=Vehicle.sighting_count + 1,
                last_seen=func.greatest(Vehicle.last_seen, new_sighting.timestamp),
            )
            .returning(Vehicle)
        )
        res = await session.execute(update_stmt)
        matched_vehicle = res.scalar_one()

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
        Alert.is_active.is_(True),
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
