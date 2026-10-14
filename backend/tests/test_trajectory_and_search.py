"""Tests for Trajectory GeoJSON endpoint, Search with fuzzy suggestions, and WebSocket live feed."""

import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from app.core.config import settings
from app.core.security import create_access_token
from app.db.seed import seed_database
from app.db.session import AsyncSession, SyncSession
from app.main import app
from app.matching.haversine import est_speed_kmh
from app.models.audit_log import AuditLog
from app.models.camera import Camera
from app.models.enums import UserRole, VehicleClass
from app.models.processing_job import ProcessingJob
from app.models.sighting import Sighting
from app.models.user import User
from app.models.vehicle import Vehicle
from httpx import ASGITransport
from sqlalchemy import select, text
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tests.conftest import TEST_ADMIN_PASSWORD, TEST_OPERATOR_PASSWORD, TEST_VIEWER_PASSWORD


@pytest.fixture(autouse=True, scope="module")
def setup_seed():
    seed_database()
    with SyncSession() as session:
        # Ensure job 1 exists for test sightings
        job = session.query(ProcessingJob).filter_by(id=1).first()
        if not job:
            job = ProcessingJob(
                id=1,
                camera_id=1,
                source_uri="test://default",
                status="done",
            )
            session.add(job)
            session.commit()


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
async def admin_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@roadtrace.ai", "password": TEST_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def operator_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@roadtrace.ai", "password": TEST_OPERATOR_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def viewer_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@roadtrace.ai", "password": TEST_VIEWER_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_trajectory_geojson_format_and_properties(
    client: httpx.AsyncClient, operator_token: str
):
    """Verify GET /api/v1/vehicles/{plate}/trajectory returns GeoJSON FeatureCollection.

    - Point features: camera name, lat/lon, timestamp, plate, ocr_confidence, snapshot url, dwell seconds
    - One LineString for the full path
    - Per-segment estimated speed using Haversine / delta t
    - Chronologically ordered by timestamp
    """
    tag = uuid4().hex[:6].upper()
    test_plate = f"TN01TJ{tag}"
    t0 = datetime(2026, 10, 10, 8, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=5)
    t2 = t1 + timedelta(minutes=10)

    # Seed 3 sightings across cameras 1, 2, 3
    async with AsyncSession() as session:
        v = Vehicle(
            plate_number=test_plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t2,
            sighting_count=3,
        )
        session.add(v)
        await session.flush()

        cam1 = await session.get(Camera, 1)
        cam2 = await session.get(Camera, 2)
        cam3 = await session.get(Camera, 3)

        s1 = Sighting(
            vehicle_id=v.id,
            camera_id=cam1.id,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.96,
            vehicle_class=VehicleClass.passenger_car,
            track_id=101,
            timestamp=t0,
            snapshot_path="snapshots/s1.jpg",
            frames_voted=10,
            job_id=1,
        )
        s2 = Sighting(
            vehicle_id=v.id,
            camera_id=cam2.id,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.92,
            vehicle_class=VehicleClass.passenger_car,
            track_id=102,
            timestamp=t1,
            snapshot_path=None,
            frames_voted=8,
            job_id=1,
        )
        s3 = Sighting(
            vehicle_id=v.id,
            camera_id=cam3.id,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.98,
            vehicle_class=VehicleClass.passenger_car,
            track_id=103,
            timestamp=t2,
            snapshot_path="snapshots/s3.jpg",
            frames_voted=12,
            job_id=1,
        )
        session.add_all([s1, s2, s3])
        await session.commit()

    headers = {"Authorization": f"Bearer {operator_token}"}
    resp = await client.get(
        f"/api/v1/vehicles/{test_plate}/trajectory",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["type"] == "FeatureCollection"
    assert data["plate"] == test_plate

    features = data["features"]
    assert len(features) == 4  # 3 Points + 1 LineString

    points = [f for f in features if f["geometry"]["type"] == "Point"]
    linestrings = [f for f in features if f["geometry"]["type"] == "LineString"]

    assert len(points) == 3
    assert len(linestrings) == 1

    # Verify chronological ordering
    ts0 = datetime.fromisoformat(points[0]["properties"]["timestamp"])
    ts1 = datetime.fromisoformat(points[1]["properties"]["timestamp"])
    ts2 = datetime.fromisoformat(points[2]["properties"]["timestamp"])
    assert ts0 < ts1 < ts2
    assert ts0 == t0
    assert ts1 == t1
    assert ts2 == t2

    # Verify Point properties
    # Point 0
    p0_props = points[0]["properties"]
    assert p0_props["camera_name"] == cam1.name
    assert p0_props["latitude"] == pytest.approx(cam1.latitude, 0.0001)
    assert p0_props["longitude"] == pytest.approx(cam1.longitude, 0.0001)
    assert points[0]["geometry"]["coordinates"] == [
        pytest.approx(cam1.longitude, 0.0001),
        pytest.approx(cam1.latitude, 0.0001),
    ]
    assert p0_props["ocr_confidence"] == pytest.approx(0.96, 0.01)
    assert p0_props["snapshot_url"] == "/snapshots/s1.jpg"
    assert p0_props["dwell_seconds"] == pytest.approx(300.0, 0.1)  # 5 minutes = 300s

    # Point 1
    p1_props = points[1]["properties"]
    assert p1_props["camera_name"] == cam2.name
    assert p1_props["snapshot_url"] is None
    assert p1_props["dwell_seconds"] == pytest.approx(600.0, 0.1)  # 10 minutes = 600s

    # Point 2 (last sighting: dwell_seconds should be None)
    p2_props = points[2]["properties"]
    assert p2_props["camera_name"] == cam3.name
    assert p2_props["dwell_seconds"] is None
    assert p2_props["snapshot_url"] == "/snapshots/s3.jpg"

    # Verify LineString geometry and segment speeds
    ls = linestrings[0]
    coords = ls["geometry"]["coordinates"]
    assert len(coords) == 3
    assert coords[0] == [pytest.approx(cam1.longitude, 0.0001), pytest.approx(cam1.latitude, 0.0001)]
    assert coords[1] == [pytest.approx(cam2.longitude, 0.0001), pytest.approx(cam2.latitude, 0.0001)]
    assert coords[2] == [pytest.approx(cam3.longitude, 0.0001), pytest.approx(cam3.latitude, 0.0001)]

    segment_speeds = ls["properties"]["segment_speeds"]
    assert len(segment_speeds) == 2

    # Check speeds match the matcher's est_speed_kmh
    expected_spd_0 = round(
        est_speed_kmh(cam1.latitude, cam1.longitude, t0, cam2.latitude, cam2.longitude, t1, radius_km=settings.earth_radius_km),
        2,
    )
    expected_spd_1 = round(
        est_speed_kmh(cam2.latitude, cam2.longitude, t1, cam3.latitude, cam3.longitude, t2, radius_km=settings.earth_radius_km),
        2,
    )
    assert segment_speeds[0] == pytest.approx(expected_spd_0, 0.05)
    assert segment_speeds[1] == pytest.approx(expected_spd_1, 0.05)


@pytest.mark.asyncio
async def test_trajectory_time_range_filter(
    client: httpx.AsyncClient, operator_token: str
):
    """Verify from= and to= query params filter the trajectory correctly."""
    tag = uuid4().hex[:6].upper()
    test_plate = f"KA04FL{tag}"
    t0 = datetime(2026, 10, 11, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    t2 = t0 + timedelta(hours=2)

    async with AsyncSession() as session:
        v = Vehicle(
            plate_number=test_plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0,
            last_seen=t2,
            sighting_count=3,
        )
        session.add(v)
        await session.flush()

        s1 = Sighting(
            vehicle_id=v.id,
            camera_id=1,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.9,
            vehicle_class=VehicleClass.passenger_car,
            track_id=201,
            timestamp=t0,
            frames_voted=10,
            job_id=1,
        )
        s2 = Sighting(
            vehicle_id=v.id,
            camera_id=2,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.9,
            vehicle_class=VehicleClass.passenger_car,
            track_id=202,
            timestamp=t1,
            frames_voted=10,
            job_id=1,
        )
        s3 = Sighting(
            vehicle_id=v.id,
            camera_id=3,
            plate_number=test_plate,
            raw_plate_text=test_plate,
            ocr_confidence=0.9,
            vehicle_class=VehicleClass.passenger_car,
            track_id=203,
            timestamp=t2,
            frames_voted=10,
            job_id=1,
        )
        session.add_all([s1, s2, s3])
        await session.commit()

    headers = {"Authorization": f"Bearer {operator_token}"}

    # Filter including only t1 (between t0 + 30m and t0 + 90m)
    from_str = (t0 + timedelta(minutes=30)).isoformat()
    to_str = (t0 + timedelta(minutes=90)).isoformat()

    resp = await client.get(
        f"/api/v1/vehicles/{test_plate}/trajectory?from={from_str}&to={to_str}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    points = [f for f in data["features"] if f["geometry"]["type"] == "Point"]
    assert len(points) == 1
    assert datetime.fromisoformat(points[0]["properties"]["timestamp"]) == t1


@pytest.mark.asyncio
async def test_search_fuzzy_levenshtein(
    client: httpx.AsyncClient, operator_token: str
):
    """Verify GET /api/v1/search?plate= returns fuzzy suggestions (Levenshtein <= 2)."""
    tag = uuid4().hex[:4].upper()
    exact_plate = f"TN07FZ{tag}"
    fuzzy_dist1 = f"TN07F2{tag}"  # 'Z' -> '2' (Levenshtein = 1)
    fuzzy_dist2 = f"TN0712{tag}"  # 'F' -> '1', 'Z' -> '2' (Levenshtein = 2)
    far_plate = f"MH12XX{tag}"    # Levenshtein > 2

    t0 = datetime.now(UTC)
    async with AsyncSession() as session:
        v1 = Vehicle(plate_number=exact_plate, vehicle_class=VehicleClass.passenger_car, first_seen=t0, last_seen=t0, sighting_count=5)
        v2 = Vehicle(plate_number=fuzzy_dist1, vehicle_class=VehicleClass.passenger_car, first_seen=t0, last_seen=t0, sighting_count=3)
        v3 = Vehicle(plate_number=fuzzy_dist2, vehicle_class=VehicleClass.passenger_car, first_seen=t0, last_seen=t0, sighting_count=1)
        v4 = Vehicle(plate_number=far_plate, vehicle_class=VehicleClass.passenger_car, first_seen=t0, last_seen=t0, sighting_count=2)
        session.add_all([v1, v2, v3, v4])
        await session.commit()

    headers = {"Authorization": f"Bearer {operator_token}"}
    resp = await client.get(f"/api/v1/search?plate={exact_plate}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "suggestions" in data
    found_plates = [s["plate_number"] for s in data["suggestions"]]
    assert exact_plate in found_plates
    assert fuzzy_dist1 in found_plates
    assert fuzzy_dist2 in found_plates
    assert far_plate not in found_plates

    # Check distances recorded
    for s in data["suggestions"]:
        if s["plate_number"] == exact_plate:
            assert s["distance"] == 0
        elif s["plate_number"] == fuzzy_dist1:
            assert s["distance"] == 1
        elif s["plate_number"] == fuzzy_dist2:
            assert s["distance"] == 2


@pytest.mark.asyncio
async def test_search_and_trajectory_audit_logging(
    client: httpx.AsyncClient, operator_token: str
):
    """Verify that every search and trajectory call records a row in audit_logs."""
    headers = {"Authorization": f"Bearer {operator_token}"}
    plate_audit = f"AUDIT{uuid4().hex[:4].upper()}"

    # 1. Search call
    search_resp = await client.get(f"/api/v1/search?plate={plate_audit}", headers=headers)
    assert search_resp.status_code == 200

    # 2. Trajectory call
    traj_resp = await client.get(f"/api/v1/vehicles/{plate_audit}/trajectory", headers=headers)
    assert traj_resp.status_code == 200

    # Verify audit log rows in database
    async with AsyncSession() as session:
        search_logs = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "search",
                    AuditLog.resource_id == plate_audit,
                )
            )
        ).all()
        assert len(search_logs) >= 1

        trace_logs = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "trace",
                    AuditLog.resource_id == plate_audit,
                )
            )
        ).all()
        assert len(trace_logs) >= 1


def test_websocket_trajectory_live_feed():
    """Verify WebSocket /ws/trajectory/{plate} rejects unauthorized connections, rejects plate '*', and receives live sighting when authorized."""
    ws_plate = f"WSFEED{uuid4().hex[:4].upper()}"

    with SyncSession() as s:
        op_user = s.query(User).filter_by(role=UserRole.operator).first()
        viewer_user = s.query(User).filter_by(role=UserRole.viewer).first()
        assert op_user is not None
        assert viewer_user is not None
        op_token = create_access_token(user_id=op_user.id, role="operator")
        viewer_token = create_access_token(user_id=viewer_user.id, role="viewer")

    import asyncio
    from app.db.session import async_engine

    asyncio.run(async_engine.dispose())
    try:
        with TestClient(app) as test_c:
            # 1. Connection without token fails with 1008
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_c.websocket_connect(f"/ws/trajectory/{ws_plate}"):
                    pass
            assert exc_info.value.code == 1008

            # 2. Connection with plate="*" fails with 1008
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_c.websocket_connect(f"/ws/trajectory/*?token={op_token}"):
                    pass
            assert exc_info.value.code == 1008

            # 3. Connection with viewer role fails with 1008
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with test_c.websocket_connect(f"/ws/trajectory/{ws_plate}?token={viewer_token}"):
                    pass
            assert exc_info.value.code == 1008

            # 4. Valid operator connection receives sighting
            def insert_sighting_delayed():
                time.sleep(0.5)
                with SyncSession() as s:
                    veh = s.query(Vehicle).first()
                    if not veh:
                        veh = Vehicle(
                            plate_number=ws_plate,
                            vehicle_class=VehicleClass.passenger_car,
                            first_seen=datetime.now(UTC),
                            last_seen=datetime.now(UTC),
                            sighting_count=1,
                        )
                        s.add(veh)
                        s.commit()
                    veh_id = veh.id
                    s.execute(text(f"""
                        INSERT INTO sightings (
                            vehicle_id, camera_id, plate_number, raw_plate_text,
                            ocr_confidence, vehicle_class, track_id, timestamp,
                            frames_voted, job_id
                        ) VALUES (
                            {veh_id}, 1, '{ws_plate}', '{ws_plate}',
                            0.99, 'passenger_car', 888, NOW(),
                            10, 1
                        );
                    """))
                    s.commit()

            thread = threading.Thread(target=insert_sighting_delayed)
            thread.start()

            with test_c.websocket_connect(f"/ws/trajectory/{ws_plate}?token={op_token}") as ws:
                msg = ws.receive_json()
                assert msg["plate_number"] == ws_plate
                assert msg["type"] == "Feature"
                assert msg["geometry"]["type"] == "Point"
                assert msg["properties"]["plate_number"] == ws_plate
                assert msg["properties"]["camera_name"] == "CAM-GST-01"
                assert msg["properties"]["ocr_confidence"] == pytest.approx(0.99, 0.01)

            thread.join()
    finally:
        asyncio.run(async_engine.dispose())
        with SyncSession() as s:
            s.execute(text(f"DELETE FROM sightings WHERE plate_number = '{ws_plate}'"))
            s.commit()
