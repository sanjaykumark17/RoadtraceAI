"""Phase 5 regression tests.

Each test covers a specific bug fix from Phases 1-4 and *must* fail on the old code.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import jwt
import numpy as np
import pytest
from httpx import ASGITransport
from sqlalchemy import select, text
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings, Settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.seed import seed_database
from app.db.session import AsyncSession, SyncSession
from app.inference.detector import VEHICLE_CLASS_IDS, YOLODetector, get_detector
from app.inference.preprocess import enhance_plate
from app.main import app
from app.matching.matcher import match
from app.models.camera import Camera
from app.models.enums import JobStatus, UserRole, VehicleClass
from app.models.processing_job import ProcessingJob
from app.models.sighting import Sighting
from app.models.user import User
from app.models.vehicle import Vehicle
from tests.conftest import TEST_ADMIN_PASSWORD, TEST_OPERATOR_PASSWORD, TEST_VIEWER_PASSWORD


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="module")
def setup_seed():
    seed_database()


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


# ══════════════════════════════════════════════════════════════════
# 1. DOUBLE-COUNTING: duplicate sighting for same track must be rejected
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_emit_sighting_deduplicates_track_id(tmp_path):
    """emit_sighting must never create two sightings for the same track_id in one job."""
    from app.inference.plate_ocr import VoteResult
    from app.workers.inference_worker import emit_sighting

    snapshots_dir = tmp_path / "snap"
    snapshots_dir.mkdir()

    with patch.object(settings, "snapshots_dir", str(snapshots_dir)):
        async with AsyncSession() as session:
            camera = await session.get(Camera, 1)
            job = ProcessingJob(
                camera_id=1,
                source_uri="dedup_test.mp4",
                status=JobStatus.running,
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            vote = VoteResult(
                plate_number="TN99ZZ9999",
                agreement_fraction=0.9,
                total_confidence=8.0,
                frames_voted=10,
                winning_frames=9,
                is_final=True,
            )
            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            meta = {
                "best_conf": 0.95,
                "best_frame": dummy_frame,
                "best_ts": datetime.now(timezone.utc),
                "vehicle_class": VehicleClass.passenger_car,
            }
            emitted = set()

            s1 = await emit_sighting(
                track_id=777, vote_result=vote, track_meta=meta,
                job=job, camera=camera, session=session, emitted_tracks=emitted,
            )
            assert s1 is not None

            # Second emission for the same track_id → must return None (no double-count)
            s2 = await emit_sighting(
                track_id=777, vote_result=vote, track_meta=meta,
                job=job, camera=camera, session=session, emitted_tracks=emitted,
            )
            assert s2 is None, "Double-counting: duplicate track_id should be rejected"


# ══════════════════════════════════════════════════════════════════
# 2. TIER 2 REACHABLE THROUGH WORKER (fuzzy match via full pipeline)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_tier2_fuzzy_match_works_via_matcher():
    """Tier 2 fuzzy matching must be reachable and working, not short-circuited."""
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:3].upper()
    true_plate = f"TN09A{tag}1"
    read_plate = f"TN09A{tag}I"  # Levenshtein = 1

    async with AsyncSession() as session:
        cam1 = await session.get(Camera, 1)
        cam2 = await session.get(Camera, 2)
        v = Vehicle(
            plate_number=true_plate,
            vehicle_class=VehicleClass.passenger_car,
            first_seen=t0, last_seen=t0, sighting_count=1,
        )
        session.add(v)
        await session.flush()
        s1 = Sighting(
            vehicle_id=v.id, camera_id=cam1.id,
            plate_number=true_plate, raw_plate_text=true_plate,
            ocr_confidence=0.94, vehicle_class=VehicleClass.passenger_car,
            track_id=500, timestamp=t0, frames_voted=10, job_id=1,
        )
        session.add(s1)
        await session.commit()
        v_id = v.id

    t1 = t0 + timedelta(minutes=3)
    s2 = Sighting(
        camera_id=cam2.id, plate_number=read_plate, raw_plate_text=read_plate,
        ocr_confidence=0.92, vehicle_class=VehicleClass.passenger_car,
        track_id=501, timestamp=t1, frames_voted=9, job_id=1,
    )
    async with AsyncSession() as session:
        res = await match(s2, session)
        assert res.tier == "fuzzy", "Tier 2 must be reachable via matcher"
        assert res.vehicle.id == v_id


# ══════════════════════════════════════════════════════════════════
# 3. NAIVE TIMESTAMP normalization
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_matcher_normalizes_naive_timestamp():
    """A sighting with naive (no-tz) timestamp must be normalized to UTC, not 500."""
    t_naive = datetime(2026, 10, 1, 18, 0, 0)
    assert t_naive.tzinfo is None

    tag = uuid4().hex[:4].upper()
    plate = f"KA01NV{tag}"
    sighting = Sighting(
        camera_id=1, plate_number=plate, raw_plate_text=plate,
        ocr_confidence=0.9, vehicle_class=VehicleClass.passenger_car,
        track_id=601, timestamp=t_naive, frames_voted=5, job_id=1,
    )
    async with AsyncSession() as session:
        res = await match(sighting, session)
        assert sighting.timestamp.tzinfo is not None, "Naive timestamp should be normalized to UTC"
        assert res.tier == "new"


# ══════════════════════════════════════════════════════════════════
# 4. OUT-OF-ORDER SIGHTING: inserted sighting with earlier timestamp must still work
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_out_of_order_sighting_accepted():
    """An out-of-order sighting (earlier ts than last_seen) must be accepted and vehicle stats updated."""
    t_early = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
    t_later = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
    tag = uuid4().hex[:4].upper()
    plate = f"TN01OO{tag}"

    async with AsyncSession() as session:
        # Create vehicle with a later first sighting
        v = Vehicle(
            plate_number=plate, vehicle_class=VehicleClass.passenger_car,
            first_seen=t_later, last_seen=t_later, sighting_count=1,
        )
        session.add(v)
        await session.flush()
        s1 = Sighting(
            vehicle_id=v.id, camera_id=1, plate_number=plate, raw_plate_text=plate,
            ocr_confidence=0.95, vehicle_class=VehicleClass.passenger_car,
            track_id=700, timestamp=t_later, frames_voted=10, job_id=1,
        )
        session.add(s1)
        await session.commit()
        v_id = v.id

    # Insert out-of-order sighting with earlier timestamp
    s2 = Sighting(
        camera_id=2, plate_number=plate, raw_plate_text=plate,
        ocr_confidence=0.90, vehicle_class=VehicleClass.passenger_car,
        track_id=701, timestamp=t_early, frames_voted=8, job_id=1,
    )
    async with AsyncSession() as session:
        res = await match(s2, session)
        assert res.tier == "exact"
        assert res.vehicle.id == v_id
        assert res.vehicle.sighting_count == 2


# ══════════════════════════════════════════════════════════════════
# 5. MISSING CAMERA → ValueError, not KeyError/500
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_missing_camera_raises_value_error():
    """match() with non-existent camera_id must raise ValueError, not crash with 500."""
    tag = uuid4().hex[:4].upper()
    plate = f"MH01MC{tag}"
    s = Sighting(
        camera_id=99999, plate_number=plate, raw_plate_text=plate,
        ocr_confidence=0.9, vehicle_class=VehicleClass.passenger_car,
        track_id=800, timestamp=datetime.now(timezone.utc), frames_voted=5, job_id=1,
    )
    async with AsyncSession() as session:
        with pytest.raises(ValueError, match="Camera with id 99999 not found"):
            await match(s, session)


# ══════════════════════════════════════════════════════════════════
# 6. WEBSOCKET WITHOUT TOKEN → 1008 close
# ══════════════════════════════════════════════════════════════════

def test_ws_without_token_rejected():
    """WebSocket /ws/trajectory/{plate} without a token must close with 1008."""
    import asyncio
    from app.db.session import async_engine

    asyncio.run(async_engine.dispose())
    try:
        with TestClient(app) as tc:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with tc.websocket_connect("/ws/trajectory/TEST1234"):
                    pass
            assert exc_info.value.code == 1008
    finally:
        asyncio.run(async_engine.dispose())


# ══════════════════════════════════════════════════════════════════
# 7. VIEWER ON /SIGHTINGS → 403
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_viewer_blocked_from_sightings(client: httpx.AsyncClient, viewer_token: str):
    """Viewer role must get 403 on GET /sightings, not 200."""
    headers = {"Authorization": f"Bearer {viewer_token}"}
    resp = await client.get("/api/v1/sightings?plate=ANYTHING", headers=headers)
    assert resp.status_code == 403, f"Viewer should be blocked from sightings, got {resp.status_code}"


# ══════════════════════════════════════════════════════════════════
# 8. REFRESH TOKEN USED AS ACCESS TOKEN → 401
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_token_rejected_as_access(client: httpx.AsyncClient):
    """Using a refresh token as an Authorization Bearer must return 401."""
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@roadtrace.ai", "password": TEST_ADMIN_PASSWORD},
    )
    refresh_tok = login_resp.json()["refresh_token"]
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refresh_tok}"},
    )
    assert resp.status_code == 401, "Refresh token must not be accepted as access token"


# ══════════════════════════════════════════════════════════════════
# 9. MISSING SUB in refresh → 401, not 500
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_missing_sub_returns_401(client: httpx.AsyncClient):
    """Refresh with a token missing 'sub' claim must return 401, not 500."""
    payload = {
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "iat": datetime.now(timezone.utc),
    }
    bad_token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": bad_token},
    )
    assert resp.status_code == 401
    assert "missing sub" in resp.json()["detail"].lower()


# ══════════════════════════════════════════════════════════════════
# 10. BAD DATETIME → 422 not 500
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sighting_bad_datetime_returns_422(client: httpx.AsyncClient, operator_token: str):
    """Posting a sighting with naive datetime must return 422, not 500."""
    headers = {"Authorization": f"Bearer {operator_token}"}
    resp = await client.post(
        "/api/v1/sightings",
        json={
            "plate_number": "TN01XX0001",
            "camera_id": 1,
            "latitude": 13.0,
            "longitude": 80.0,
            "timestamp": "2026-10-13T10:00:00",  # NO timezone
        },
        headers=headers,
    )
    assert resp.status_code == 422, f"Expected 422 for naive datetime, got {resp.status_code}"


# ══════════════════════════════════════════════════════════════════
# 11. LONG PLATE → 422 not 500
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sighting_long_plate_rejected(client: httpx.AsyncClient, operator_token: str):
    """Plate_number > 20 chars must be rejected with 422."""
    headers = {"Authorization": f"Bearer {operator_token}"}
    resp = await client.post(
        "/api/v1/sightings",
        json={
            "plate_number": "A" * 25,
            "camera_id": 1,
            "latitude": 13.0,
            "longitude": 80.0,
            "timestamp": "2026-10-13T10:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 422, f"Expected 422 for long plate, got {resp.status_code}"


# ══════════════════════════════════════════════════════════════════
# 12. DELETE CAMERA WITH SIGHTINGS → 409
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_delete_camera_with_sightings_returns_409(client: httpx.AsyncClient, admin_token: str):
    """Deleting a camera that has sightings must return 409, not 500."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create a camera, then a sighting referencing it
    cam_resp = await client.post(
        "/api/v1/cameras",
        json={
            "name": f"CAM-409-TEST-{uuid4().hex[:4]}",
            "latitude": 13.0, "longitude": 80.0,
            "intersection_name": "Test", "heading_deg": 0.0,
        },
        headers=headers,
    )
    assert cam_resp.status_code == 201
    cam_id = cam_resp.json()["id"]

    # Seed a sighting referencing this camera directly in DB
    with SyncSession() as session:
        session.execute(text(f"""
            INSERT INTO vehicles (plate_number, vehicle_class, first_seen, last_seen, sighting_count)
            VALUES ('DEL409TEST', 'passenger_car', NOW(), NOW(), 1)
            ON CONFLICT (plate_number) DO NOTHING
        """))
        session.commit()
        vid = session.execute(text("SELECT id FROM vehicles WHERE plate_number='DEL409TEST'")).scalar()
        session.execute(text(f"""
            INSERT INTO sightings (vehicle_id, camera_id, plate_number, raw_plate_text,
                ocr_confidence, vehicle_class, track_id, timestamp, frames_voted, job_id)
            VALUES ({vid}, {cam_id}, 'DEL409TEST', 'DEL409TEST', 0.9, 'passenger_car',
                1, NOW(), 1, 1)
        """))
        session.commit()

    del_resp = await client.delete(f"/api/v1/cameras/{cam_id}", headers=headers)
    assert del_resp.status_code == 409, f"Expected 409 for camera with sightings, got {del_resp.status_code}"

    # Cleanup
    with SyncSession() as session:
        session.execute(text(f"DELETE FROM sightings WHERE camera_id = {cam_id}"))
        session.execute(text(f"DELETE FROM cameras WHERE id = {cam_id}"))
        session.commit()


# ══════════════════════════════════════════════════════════════════
# 13. DEFAULT SECRET KEY REFUSED OUTSIDE DEV
# ══════════════════════════════════════════════════════════════════

def test_default_secret_key_refused_in_production():
    """Settings(environment='production', secret_key='change-me-in-production') must raise ValueError."""
    with pytest.raises(ValueError, match="Default secret key is not allowed"):
        Settings(environment="production", secret_key="change-me-in-production")


# ══════════════════════════════════════════════════════════════════
# 14. detect_vehicles CALLED WITH MOCK MODEL: assert conf/iou/classes
# ══════════════════════════════════════════════════════════════════

def test_detect_vehicles_passes_conf_iou_classes():
    """detect_vehicles must call the model with conf=vehicle_conf, iou=nms_iou, classes=VEHICLE_CLASS_IDS."""
    mock_model = MagicMock()
    mock_results = MagicMock()
    mock_results.boxes = None  # No detections
    mock_model.return_value = [mock_results]

    detector = get_detector()
    original_model = detector.model
    try:
        YOLODetector.set_model(mock_model)
        frame = np.zeros((640, 640, 3), dtype=np.uint8)
        detector.detect_vehicles(frame)

        call_kwargs = mock_model.call_args
        assert call_kwargs is not None, "Model was not called"
        _, kwargs = call_kwargs
        assert kwargs["conf"] == settings.vehicle_conf, f"conf should be {settings.vehicle_conf}"
        assert kwargs["iou"] == settings.nms_iou, f"iou should be {settings.nms_iou}"
        assert kwargs["classes"] == VEHICLE_CLASS_IDS, f"classes should be {VEHICLE_CLASS_IDS}"
    finally:
        YOLODetector.set_model(original_model)


# ══════════════════════════════════════════════════════════════════
# 15. enhance_plate ORDER: CLAHE → Bilateral → Otsu
# ══════════════════════════════════════════════════════════════════

def test_enhance_plate_pipeline_order():
    """enhance_plate must apply CLAHE → bilateral → Otsu in that exact order."""
    import cv2

    # Create test plate image
    plate = np.full((60, 200, 3), 200, dtype=np.uint8)
    cv2.putText(plate, "TEST1234", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2)

    call_order = []
    original_clahe = cv2.createCLAHE
    original_bilateral = cv2.bilateralFilter
    original_threshold = cv2.threshold

    def mock_clahe(*args, **kwargs):
        call_order.append("CLAHE")
        return original_clahe(*args, **kwargs)

    def mock_bilateral(*args, **kwargs):
        call_order.append("bilateral")
        return original_bilateral(*args, **kwargs)

    def mock_threshold(*args, **kwargs):
        call_order.append("Otsu")
        return original_threshold(*args, **kwargs)

    with patch("app.inference.preprocess.cv2.createCLAHE", side_effect=mock_clahe):
        with patch("app.inference.preprocess.cv2.bilateralFilter", side_effect=mock_bilateral):
            with patch("app.inference.preprocess.cv2.threshold", side_effect=mock_threshold):
                enhance_plate(plate)

    assert call_order == ["CLAHE", "bilateral", "Otsu"], (
        f"Expected order [CLAHE, bilateral, Otsu], got {call_order}"
    )


# ══════════════════════════════════════════════════════════════════
# 16. OCR blur threshold is 100 (paper spec)
# ══════════════════════════════════════════════════════════════════

def test_ocr_blur_threshold_is_100():
    """blur_tau setting must be 100 per the paper specification."""
    assert settings.blur_tau == 100, f"Expected blur_tau=100, got {settings.blur_tau}"


# ══════════════════════════════════════════════════════════════════
# 17. test_exactly_eight_tables is exact (no extra tables)
# ══════════════════════════════════════════════════════════════════

def test_exactly_eight_tables_exact():
    """DB must have exactly 8 application tables – no fewer, no more (aside from system/extension tables)."""
    from sqlalchemy import create_engine, inspect

    EXPECTED = {
        "users", "cameras", "vehicles", "sightings",
        "alerts", "alert_triggers", "audit_logs", "processing_jobs",
    }
    # PostGIS extension installs geocoder and topology tables in public schema;
    # Alembic and spatial_ref_sys are also system tables.
    SYSTEM_TABLES = {"alembic_version", "spatial_ref_sys"}

    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())

    # Filter out known PostGIS extension tables (geocoder, topology, tiger)
    POSTGIS_PREFIXES = (
        "pagc_", "geocode_", "loader_", "zip_", "addr",
        "county", "cousub", "direction_", "edges", "faces",
        "featnames", "layer", "place", "secondary_unit_",
        "state", "street_type_", "tabblock", "topology", "tract",
        "bg", "zcta5",
    )
    app_tables = {
        t for t in db_tables
        if t not in SYSTEM_TABLES and not any(t.startswith(p) or t == p.rstrip("_") for p in POSTGIS_PREFIXES)
    }
    # Also remove tables whose name contains "lookup" (PostGIS geocoder lookup tables)
    app_tables = {t for t in app_tables if "lookup" not in t}
    assert app_tables == EXPECTED, (
        f"Extra tables: {app_tables - EXPECTED}, Missing: {EXPECTED - app_tables}"
    )


# ══════════════════════════════════════════════════════════════════
# 18. Low-confidence tracker score between 0.1 and 0.45
# ══════════════════════════════════════════════════════════════════

def test_low_conf_tracker_score_between_0_1_and_0_45():
    """ByteTrack's second association pass uses a low score between track_low_thresh (0.1) and track_high_thresh (0.45)."""
    import torch
    from ultralytics.engine.results import Boxes
    from app.inference.tracker import VehicleTracker

    tracker = VehicleTracker(camera_id="test_lowconf")

    # Frame 1: Vehicle at conf 0.85 (above 0.45)
    b1 = Boxes(
        torch.tensor([[100.0, 100.0, 200.0, 200.0, 0.85, 2.0]]),
        orig_shape=(640, 640),
    )
    t1 = tracker.update(b1.cpu().numpy(), frame_index=0)
    assert len(t1) == 1
    track_id = t1[0].track_id

    # Frame 2: Vehicle at conf 0.25 (between 0.1 and 0.45 → used in 2nd association but filtered from output)
    low_conf = 0.25
    assert 0.1 <= low_conf <= 0.45, "Low confidence must be in ByteTrack's second pass range"
    b2 = Boxes(
        torch.tensor([[103.0, 102.0, 203.0, 202.0, low_conf, 2.0]]),
        orig_shape=(640, 640),
    )
    t2 = tracker.update(b2.cpu().numpy(), frame_index=1)
    assert len(t2) == 0, "Low-conf detection should be filtered from output"

    # Frame 3: Vehicle returns at conf 0.80 → track ID must be preserved
    b3 = Boxes(
        torch.tensor([[106.0, 104.0, 206.0, 204.0, 0.80, 2.0]]),
        orig_shape=(640, 640),
    )
    t3 = tracker.update(b3.cpu().numpy(), frame_index=2)
    assert len(t3) == 1
    assert t3[0].track_id == track_id, "Track ID should be preserved through low-conf occlusion"
