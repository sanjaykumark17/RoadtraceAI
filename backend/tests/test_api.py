from datetime import datetime, timedelta, timezone

import httpx
from httpx import ASGITransport
from jose import jwt
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.seed import seed_database
from app.db.session import AsyncSession
from app.main import app
from app.models.audit_log import AuditLog
from app.models.enums import UserRole


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
        json={"email": "admin@roadtrace.ai", "password": "admin123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def operator_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@roadtrace.ai", "password": "operator123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
async def viewer_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@roadtrace.ai", "password": "viewer123"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def test_health_and_cors(client: httpx.AsyncClient):
    resp = await client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers.get("access-control-allow-origin") in (
        "*",
        "http://localhost:5173",
    )


def test_token_expiration_paper_targets():
    # Paper requirement: decode a fresh token and assert access exp = 15 min and refresh exp = 7 days
    access_tok = create_access_token(user_id=1, role="admin")
    refresh_tok = create_refresh_token(user_id=1)

    payload_acc = decode_token(access_tok)
    payload_ref = decode_token(refresh_tok)

    assert payload_acc["type"] == "access"
    assert payload_ref["type"] == "refresh"

    acc_duration_seconds = payload_acc["exp"] - payload_acc["iat"]
    ref_duration_seconds = payload_ref["exp"] - payload_ref["iat"]

    assert acc_duration_seconds == 15 * 60, f"Expected 900s, got {acc_duration_seconds}s"
    assert (
        ref_duration_seconds == 7 * 86400
    ), f"Expected 604800s, got {ref_duration_seconds}s"


def test_exactly_three_roles():
    assert len(settings.roles) == 3
    assert set(settings.roles) == {"admin", "operator", "viewer"}
    assert len(UserRole) == 3
    assert {r.value for r in UserRole} == {"admin", "operator", "viewer"}


async def test_auth_login_success(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@roadtrace.ai", "password": "admin123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_auth_login_bad_credentials(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@roadtrace.ai", "password": "wrongpassword"},
    )
    assert resp.status_code == 401
    assert "bad credentials" in resp.json()["detail"]


async def test_auth_refresh(client: httpx.AsyncClient):
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "operator@roadtrace.ai", "password": "operator123"},
    )
    refresh_tok = login_resp.json()["refresh_token"]

    refresh_resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_tok},
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


async def test_auth_refresh_invalid_token(client: httpx.AsyncClient):
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not.a.valid.jwt"},
    )
    assert resp.status_code == 401


async def test_auth_me(client: httpx.AsyncClient, admin_token: str):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    user_data = resp.json()
    assert user_data["email"] == "admin@roadtrace.ai"
    assert user_data["role"] == "admin"
    assert user_data["is_active"] is True


async def test_expired_token_rejected(client: httpx.AsyncClient):
    past_now = datetime.now(timezone.utc) - timedelta(hours=2)
    past_exp = past_now + timedelta(minutes=15)
    expired_payload = {
        "sub": "1",
        "role": "admin",
        "type": "access",
        "exp": past_exp,
        "iat": past_now,
    }
    expired_token = jwt.encode(
        expired_payload, settings.secret_key, algorithm=settings.algorithm
    )

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
    assert "invalid or expired token" in resp.json()["detail"]


async def test_viewer_gets_403_on_write_routes(
    client: httpx.AsyncClient, viewer_token: str
):
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # 1. Camera write: POST /cameras
    resp = await client.post(
        "/api/v1/cameras",
        json={
            "name": "CAM-TEST-VIEWER",
            "latitude": 13.0,
            "longitude": 80.0,
            "intersection_name": "Test Intersection",
            "heading_deg": 90.0,
        },
        headers=headers,
    )
    assert resp.status_code == 403, f"Camera create expected 403, got {resp.status_code}"

    # 2. Camera write: PUT /cameras/1
    resp = await client.put(
        "/api/v1/cameras/1",
        json={"name": "CAM-UPDATED-NAME"},
        headers=headers,
    )
    assert resp.status_code == 403, f"Camera update expected 403, got {resp.status_code}"

    # 3. Camera write: DELETE /cameras/1
    resp = await client.delete("/api/v1/cameras/1", headers=headers)
    assert resp.status_code == 403, f"Camera delete expected 403, got {resp.status_code}"

    # 4. Job write: POST /jobs
    resp = await client.post(
        "/api/v1/jobs",
        json={"camera_id": 1, "source_uri": "rtsp://camera1/stream"},
        headers=headers,
    )
    assert resp.status_code == 403, f"Job create expected 403, got {resp.status_code}"

    # 5. Sighting write: POST /sightings
    resp = await client.post(
        "/api/v1/sightings",
        json={
            "plate_number": "TN01AB1234",
            "camera_id": 1,
            "latitude": 13.0,
            "longitude": 80.0,
            "timestamp": "2026-10-13T10:00:00Z",
        },
        headers=headers,
    )
    assert resp.status_code == 403, f"Sighting create expected 403, got {resp.status_code}"

    # 6. Alert write: POST /alerts
    resp = await client.post(
        "/api/v1/alerts",
        json={"plate_number": "TN01AB1234", "reason": "Test Alert"},
        headers=headers,
    )
    assert resp.status_code == 403, f"Alert create expected 403, got {resp.status_code}"

    # 7. Alert write: PUT /alerts/1
    resp = await client.put(
        "/api/v1/alerts/1",
        json={"reason": "Updated Reason"},
        headers=headers,
    )
    assert resp.status_code == 403, f"Alert update expected 403, got {resp.status_code}"

    # 8. Alert write: DELETE /alerts/1
    resp = await client.delete("/api/v1/alerts/1", headers=headers)
    assert resp.status_code == 403, f"Alert delete expected 403, got {resp.status_code}"

    # 9. Trace run: GET /vehicles/{plate}/trajectory (run traces is operator/admin)
    resp = await client.get("/api/v1/vehicles/TN01AB1234/trajectory", headers=headers)
    assert resp.status_code == 403, f"Trajectory trace expected 403, got {resp.status_code}"


async def test_viewer_allowed_on_read_routes(
    client: httpx.AsyncClient, viewer_token: str
):
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # List cameras
    resp = await client.get("/api/v1/cameras", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 12

    # Search sightings
    resp = await client.get("/api/v1/sightings?plate=TN01AB1234", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_operator_permissions(
    client: httpx.AsyncClient, operator_token: str
):
    headers = {"Authorization": f"Bearer {operator_token}"}

    # Operator cannot manage cameras (admin only)
    resp = await client.post(
        "/api/v1/cameras",
        json={
            "name": "CAM-OPERATOR-FAIL",
            "latitude": 13.0,
            "longitude": 80.0,
            "intersection_name": "Op Intersection",
            "heading_deg": 90.0,
        },
        headers=headers,
    )
    assert resp.status_code == 403

    # Operator can create jobs
    resp = await client.post(
        "/api/v1/jobs",
        json={"camera_id": 1, "source_uri": "rtsp://live.stream/1"},
        headers=headers,
    )
    assert resp.status_code == 201
    job_data = resp.json()
    assert job_data["id"] is not None
    assert job_data["status"] == "queued"

    # Operator can create alerts
    resp = await client.post(
        "/api/v1/alerts",
        json={"plate_number": "KA01AB9999", "reason": "Wanted vehicle"},
        headers=headers,
    )
    assert resp.status_code == 201
    alert_id = resp.json()["id"]

    # Operator can run traces
    resp = await client.get("/api/v1/vehicles/KA01AB9999/trajectory", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["plate"] == "KA01AB9999"

    # Operator can delete alert
    resp = await client.delete(f"/api/v1/alerts/{alert_id}", headers=headers)
    assert resp.status_code == 204


async def test_admin_permissions(client: httpx.AsyncClient, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin can create cameras
    resp = await client.post(
        "/api/v1/cameras",
        json={
            "name": "CAM-ADMIN-TEST",
            "latitude": 13.05,
            "longitude": 80.25,
            "intersection_name": "Admin Junction",
            "heading_deg": 180.0,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    cam_id = resp.json()["id"]

    # Admin can delete camera
    del_resp = await client.delete(f"/api/v1/cameras/{cam_id}", headers=headers)
    assert del_resp.status_code == 204


async def test_audit_logging_for_login_search_and_trace(
    client: httpx.AsyncClient, operator_token: str
):
    headers = {"Authorization": f"Bearer {operator_token}"}

    # 1. Search sightings
    search_resp = await client.get("/api/v1/sightings?plate=AUDITTEST", headers=headers)
    assert search_resp.status_code == 200

    # 2. Trace vehicle trajectory
    trace_resp = await client.get(
        "/api/v1/vehicles/AUDITTEST/trajectory", headers=headers
    )
    assert trace_resp.status_code == 200

    # Verify audit log rows in database
    async with AsyncSession() as session:
        login_logs = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "login")
            )
        ).all()
        assert len(login_logs) >= 1

        search_logs = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "search",
                    AuditLog.resource_id == "AUDITTEST",
                )
            )
        ).all()
        assert len(search_logs) >= 1

        trace_logs = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "trace",
                    AuditLog.resource_id == "AUDITTEST",
                )
            )
        ).all()
        assert len(trace_logs) >= 1
