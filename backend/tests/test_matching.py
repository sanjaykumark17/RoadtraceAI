"""Unit tests for spatio-temporal matching, haversine distance, and kinematic speed filter."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.seed import seed_database
from app.db.session import AsyncSession
from app.matching.haversine import est_speed_kmh, haversine_km
from app.matching.matcher import match
from app.models.alert import Alert
from app.models.alert_trigger import AlertTrigger
from app.models.camera import Camera
from app.models.enums import VehicleClass
from app.models.sighting import Sighting
from app.models.vehicle import Vehicle
from app.services.matching_service import matching_service


@pytest.fixture(autouse=True, scope="module")
def setup_seed():
    seed_database()


def test_haversine_known_distances():
    """Verify haversine formula against known reference geographical distances."""
    # Chennai Central (13.0827, 80.2707) to Chennai Airport (12.9866, 80.1707) is ~15.2 km
    dist = haversine_km(13.0827, 80.2707, 12.9866, 80.1707, radius_km=6371.0)
    assert 14.0 < dist < 16.5

    # Same location must return exactly 0.0
    assert haversine_km(13.0, 80.0, 13.0, 80.0) == 0.0


def test_est_speed_guards_delta_t():
    """Verify speed estimation guards delta_t <= 0 and enforces minimum 1 second."""
    t0 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Identical timestamps (delta_t == 0) -> guarded to 1 sec, non-zero distance gives finite speed
    speed_zero_dt = est_speed_kmh(13.0, 80.0, t0, 13.01, 80.01, t0)
    assert speed_zero_dt > 0.0
    assert not (speed_zero_dt == float("inf"))

    # Negative delta_t (t2 < t1) -> absolute difference taken, guarded to minimum 1 sec
    t_past = t0 - timedelta(seconds=10)
    speed_rev = est_speed_kmh(13.0, 80.0, t0, 13.01, 80.01, t_past)
    assert speed_rev > 0.0

    # 500 km in 10 minutes (600 seconds) -> 3000 km/h
    t_10m = t0 + timedelta(minutes=10)
    # 500 km distance points: 4.5 degrees latitude approx 500 km
    lat1, lon1 = 13.0, 80.0
    lat2, lon2 = 13.0 + (500.0 / 111.0), 80.0
    speed_500km = est_speed_kmh(lat1, lon1, t0, lat2, lon2, t_10m)
    assert 2900.0 < speed_500km < 3100.0


@pytest.mark.asyncio
async def test_matcher_tier_1_exact_hit():
    """Tier 1: look up vehicle by plate_number (indexed). If found, attach the sighting."""
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    plate = f"TN09AB{tag}"

    async with AsyncSession() as session:
        # Pre-seed an existing vehicle
        v = Vehicle(
            plate_number=plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t0,
            sighting_count=1,
        )
        session.add(v)
        await session.commit()
        await session.refresh(v)
        v_id = v.id

    t1 = t0 + timedelta(minutes=5)
    new_sighting = Sighting(
        camera_id=1,
        plate_number=plate,
        raw_plate_text=plate,
        ocr_confidence=0.95,
        vehicle_class=VehicleClass.passenger_car,
        track_id=101,
        timestamp=t1,
        frames_voted=10,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(new_sighting, session)
        assert res.tier == "exact"
        assert res.vehicle.id == v_id
        assert new_sighting.vehicle_id == v_id
        assert res.vehicle.sighting_count == 2
        assert res.flag is None


@pytest.mark.asyncio
async def test_matcher_tier_1_suspicious_duplicate_plate_speed():
    """Tier 1: if v_est > 150 km/h, keep sighting but set flag='suspicious_duplicate_plate'."""
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    plate = f"TN09SP{tag}"

    async with AsyncSession() as session:
        # Get Camera 1 and Camera 6 coordinates (distance is ~8 km)
        cam1 = await session.get(Camera, 1)
        cam6 = await session.get(Camera, 6)
        assert cam1 is not None and cam6 is not None

        v = Vehicle(
            plate_number=plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t0,
            sighting_count=1,
        )
        session.add(v)
        await session.flush()

        s1 = Sighting(
            vehicle_id=v.id,
            camera_id=cam1.id,
            plate_number=plate,
            raw_plate_text=plate,
            ocr_confidence=0.96,
            vehicle_class=VehicleClass.passenger_car,
            track_id=1,
            timestamp=t0,
            frames_voted=8,
            job_id=1,
        )
        session.add(s1)
        await session.commit()

    # Second sighting appears 5 seconds later at camera 6 (8 km away => speed > 5000 km/h!)
    t2 = t0 + timedelta(seconds=5)
    s2 = Sighting(
        camera_id=cam6.id,
        plate_number=plate,
        raw_plate_text=plate,
        ocr_confidence=0.97,
        vehicle_class=VehicleClass.passenger_car,
        track_id=2,
        timestamp=t2,
        frames_voted=10,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(s2, session)
        assert res.tier == "exact"
        assert res.flag == "suspicious_duplicate_plate"
        assert s2.flag == "suspicious_duplicate_plate"
        assert res.speed_kmh is not None
        assert res.speed_kmh > 150.0


@pytest.mark.asyncio
async def test_matcher_tier_2_one_character_ocr_error_accepted_when_speed_plausible():
    """Tier 2: One-character OCR error accepted when kinematic speed is plausible (<= 150 km/h)."""
    t0 = datetime(2026, 10, 1, 14, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:3].upper()
    true_plate = f"TN09A{tag}1"
    read_plate = f"TN09A{tag}I"  # '1' misread as 'I' (Levenshtein = 1)

    async with AsyncSession() as session:
        cam1 = await session.get(Camera, 1)
        cam2 = await session.get(Camera, 2)
        assert cam1 is not None and cam2 is not None

        v = Vehicle(
            plate_number=true_plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t0,
            sighting_count=1,
        )
        session.add(v)
        await session.flush()

        s1 = Sighting(
            vehicle_id=v.id,
            camera_id=cam1.id,
            plate_number=true_plate,
            raw_plate_text=true_plate,
            ocr_confidence=0.94,
            vehicle_class=VehicleClass.passenger_car,
            track_id=11,
            timestamp=t0,
            frames_voted=10,
            job_id=1,
        )
        session.add(s1)
        await session.commit()
        v_id = v.id

    # Sighting 2 at camera 2 after 3 minutes (dist ~1.2 km, speed ~24 km/h <= 150 km/h)
    t1 = t0 + timedelta(minutes=3)
    s2 = Sighting(
        camera_id=cam2.id,
        plate_number=read_plate,
        raw_plate_text=read_plate,
        ocr_confidence=0.92,
        vehicle_class=VehicleClass.passenger_car,
        track_id=12,
        timestamp=t1,
        frames_voted=9,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(s2, session)
        assert res.tier == "fuzzy"
        assert res.vehicle.id == v_id
        assert res.vehicle.plate_number == true_plate
        assert s2.vehicle_id == v_id
        assert res.speed_kmh is not None
        assert res.speed_kmh <= 150.0


@pytest.mark.asyncio
async def test_matcher_tier_2_rejected_when_impossible_speed_creates_tier_3_new():
    """Tier 2: The same one-character-different plate REJECTED when requiring 500 km in 10 minutes.

    Falls back to Tier 3 creating a new vehicle.
    """
    t0 = datetime(2026, 10, 1, 15, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:3].upper()
    base_plate = f"TN09B{tag}8"
    noisy_plate = f"TN09B{tag}B"  # Levenshtein = 1

    async with AsyncSession() as session:
        # Create candidate vehicle in Chennai
        v = Vehicle(
            plate_number=base_plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t0,
            sighting_count=1,
        )
        session.add(v)
        await session.flush()

        cam1 = await session.get(Camera, 1)
        s1 = Sighting(
            vehicle_id=v.id,
            camera_id=cam1.id,
            plate_number=base_plate,
            raw_plate_text=base_plate,
            ocr_confidence=0.95,
            vehicle_class=VehicleClass.passenger_car,
            track_id=20,
            timestamp=t0,
            frames_voted=10,
            job_id=1,
        )
        session.add(s1)

        # Create a distant camera ~500 km away (e.g. Hyderabad lat 17.3850, lon 78.4867)
        dist_cam = Camera(
            name=f"Distant Highway Camera {tag}",
            latitude=17.3850,
            longitude=78.4867,
            intersection_name="Distant Junction",
            heading_deg=180.0,
        )
        session.add(dist_cam)
        await session.commit()
        await session.refresh(dist_cam)
        dist_cam_id = dist_cam.id

    # Sighting appears 10 minutes later at the distant camera (500 km away => ~3000 km/h)
    t_10m = t0 + timedelta(minutes=10)
    s2 = Sighting(
        camera_id=dist_cam_id,
        plate_number=noisy_plate,
        raw_plate_text=noisy_plate,
        ocr_confidence=0.90,
        vehicle_class=VehicleClass.passenger_car,
        track_id=21,
        timestamp=t_10m,
        frames_voted=10,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(s2, session)
        # MUST BE REJECTED from Tier 2 due to speed > 150 km/h, and fall back to Tier 3 New!
        assert res.tier == "new"
        assert res.vehicle.plate_number == noisy_plate
        assert s2.vehicle_id == res.vehicle.id


@pytest.mark.asyncio
async def test_matcher_tier_3_unseen_plate_creates_new_vehicle():
    """Tier 3: Unseen plate creates a brand new vehicle row."""
    t0 = datetime(2026, 10, 1, 16, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    new_plate = f"KA05ZZ{tag}"

    sighting = Sighting(
        camera_id=1,
        plate_number=new_plate,
        raw_plate_text=new_plate,
        ocr_confidence=0.91,
        vehicle_class=VehicleClass.two_wheeler,
        track_id=301,
        timestamp=t0,
        frames_voted=7,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(sighting, session)
        assert res.tier == "new"
        assert res.vehicle.plate_number == new_plate
        assert res.vehicle.vehicle_class == VehicleClass.two_wheeler
        assert res.vehicle.sighting_count == 1
        assert sighting.vehicle_id == res.vehicle.id


@pytest.mark.asyncio
async def test_matcher_triggers_active_alert():
    """Verify active alert triggers AlertTrigger record during matching."""
    t0 = datetime(2026, 10, 1, 17, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    alert_plate = f"DL01AL{tag}"

    async with AsyncSession() as session:
        # Create an active alert for this plate
        alert = Alert(
            plate_number=alert_plate,
            reason="Stolen vehicle bulletin",
            created_by=1,
            is_active=True,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        alert_id = alert.id

    sighting = Sighting(
        camera_id=1,
        plate_number=alert_plate,
        raw_plate_text=alert_plate,
        ocr_confidence=0.98,
        vehicle_class=VehicleClass.passenger_car,
        track_id=401,
        timestamp=t0,
        frames_voted=12,
        job_id=1,
    )

    async with AsyncSession() as session:
        res = await match(sighting, session)
        assert res.triggers_created >= 1

        # Check alert_triggers table in DB
        trig_stmt = select(AlertTrigger).where(
            AlertTrigger.alert_id == alert_id,
            AlertTrigger.sighting_id == sighting.id,
        )
        trig_res = await session.execute(trig_stmt)
        trigger = trig_res.scalar_one_or_none()
        assert trigger is not None
        assert trigger.triggered_at is not None


@pytest.mark.asyncio
async def test_matching_service_ingest_sighting_wrapper():
    """Verify matching_service.ingest_sighting wrapper returns expected dictionary."""
    t0 = datetime(2026, 10, 1, 18, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    plate = f"MH02CD{tag}"

    sighting = Sighting(
        camera_id=1,
        plate_number=plate,
        raw_plate_text=plate,
        ocr_confidence=0.93,
        vehicle_class=VehicleClass.passenger_car,
        track_id=501,
        timestamp=t0,
        frames_voted=8,
        job_id=1,
    )

    result_dict = await matching_service.ingest_sighting(sighting)
    assert result_dict["status"] == "ingested"
    assert result_dict["plate_number"] == plate
    assert result_dict["tier"] in ("exact", "fuzzy", "new")
    assert result_dict["vehicle_id"] is not None
