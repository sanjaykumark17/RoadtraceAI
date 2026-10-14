import os
import secrets
from datetime import UTC, datetime, timedelta
from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SyncSession
from app.models.camera import Camera
from app.models.enums import CameraStatus, JobStatus, UserRole, VehicleClass
from app.models.processing_job import ProcessingJob
from app.models.sighting import Sighting
from app.models.user import User
from app.models.vehicle import Vehicle


def get_or_generate_seed_password(env_var: str, role_name: str) -> str:
    pwd = os.environ.get(env_var)
    if not pwd:
        pwd = secrets.token_urlsafe(16)
        print(f"Generated initial {role_name} password ({env_var}): {pwd}")
    return pwd

SAMPLE_CAMERAS = [
    {
        "name": "CAM-GST-01",
        "latitude": 13.0067,
        "longitude": 80.2030,
        "intersection_name": "Kathipara Urban Interchange",
        "heading_deg": 210.0,
    },
    {
        "name": "CAM-GST-02",
        "latitude": 12.9806,
        "longitude": 80.1634,
        "intersection_name": "Chennai Airport Southbound",
        "heading_deg": 215.0,
    },
    {
        "name": "CAM-GST-03",
        "latitude": 12.9675,
        "longitude": 80.1491,
        "intersection_name": "Pallavaram Sandhai Junction",
        "heading_deg": 215.0,
    },
    {
        "name": "CAM-GST-04",
        "latitude": 12.9516,
        "longitude": 80.1412,
        "intersection_name": "Chromepet MIT Gate Flyover",
        "heading_deg": 220.0,
    },
    {
        "name": "CAM-GST-05",
        "latitude": 12.9360,
        "longitude": 80.1305,
        "intersection_name": "Tambaram Sanatorium Signal",
        "heading_deg": 210.0,
    },
    {
        "name": "CAM-GST-06",
        "latitude": 12.9249,
        "longitude": 80.1188,
        "intersection_name": "Tambaram MEPZ Junction",
        "heading_deg": 205.0,
    },
    {
        "name": "CAM-GST-07",
        "latitude": 12.9056,
        "longitude": 80.0917,
        "intersection_name": "Perungalathur Bypass Entry",
        "heading_deg": 210.0,
    },
    {
        "name": "CAM-GST-08",
        "latitude": 12.8797,
        "longitude": 80.0822,
        "intersection_name": "Vandalur Zoo Junction",
        "heading_deg": 200.0,
    },
    {
        "name": "CAM-ORR-01",
        "latitude": 12.8912,
        "longitude": 80.0754,
        "intersection_name": "ORR Vandalur Cloverleaf",
        "heading_deg": 320.0,
    },
    {
        "name": "CAM-ORR-02",
        "latitude": 12.9972,
        "longitude": 80.0945,
        "intersection_name": "ORR Kundrathur Toll Plaza",
        "heading_deg": 345.0,
    },
    {
        "name": "CAM-ORR-03",
        "latitude": 13.0489,
        "longitude": 80.0701,
        "intersection_name": "ORR Nazarathpet NH4 Junction",
        "heading_deg": 10.0,
    },
    {
        "name": "CAM-ORR-04",
        "latitude": 13.1147,
        "longitude": 80.0652,
        "intersection_name": "ORR Nemilichery CTH Flyover",
        "heading_deg": 15.0,
    },
]


def seed_database() -> None:
    with SyncSession() as session:
        # Seed or update admin user
        admin_email = "admin@roadtrace.ai"
        admin_pass = get_or_generate_seed_password("RT_ADMIN_PASSWORD", "admin")
        existing_admin = session.scalar(
            select(User).where(User.email == admin_email)
        )
        if existing_admin:
            existing_admin.password_hash = hash_password(admin_pass)
        else:
            admin = User(
                email=admin_email,
                password_hash=hash_password(admin_pass),
                role=UserRole.admin,
                is_active=True,
            )
            session.add(admin)

        # Seed or update operator user
        operator_email = "operator@roadtrace.ai"
        operator_pass = get_or_generate_seed_password("RT_OPERATOR_PASSWORD", "operator")
        existing_operator = session.scalar(
            select(User).where(User.email == operator_email)
        )
        if existing_operator:
            existing_operator.password_hash = hash_password(operator_pass)
        else:
            operator = User(
                email=operator_email,
                password_hash=hash_password(operator_pass),
                role=UserRole.operator,
                is_active=True,
            )
            session.add(operator)

        # Seed or update viewer user
        viewer_email = "viewer@roadtrace.ai"
        viewer_pass = get_or_generate_seed_password("RT_VIEWER_PASSWORD", "viewer")
        existing_viewer = session.scalar(
            select(User).where(User.email == viewer_email)
        )
        if existing_viewer:
            existing_viewer.password_hash = hash_password(viewer_pass)
        else:
            viewer = User(
                email=viewer_email,
                password_hash=hash_password(viewer_pass),
                role=UserRole.viewer,
                is_active=True,
            )
            session.add(viewer)

        # Seed sample cameras
        for cam_data in SAMPLE_CAMERAS:
            existing_cam = session.scalar(
                select(Camera).where(Camera.name == cam_data["name"])
            )
            if not existing_cam:
                point_wkt = WKTElement(
                    f"POINT({cam_data['longitude']} {cam_data['latitude']})",
                    srid=4326,
                )
                camera = Camera(
                    name=cam_data["name"],
                    latitude=cam_data["latitude"],
                    longitude=cam_data["longitude"],
                    intersection_name=cam_data["intersection_name"],
                    heading_deg=cam_data["heading_deg"],
                    status=CameraStatus.active,
                    location=point_wkt,
                )
                session.add(camera)

        session.commit()

        # Seed sample processing job if not present
        job = session.query(ProcessingJob).filter_by(id=1).first()
        if not job:
            job = ProcessingJob(
                id=1,
                camera_id=1,
                source_uri="corridor://gst-road-surveillance.mp4",
                status=JobStatus.done,
                frames_processed=1500,
            )
            session.add(job)
            session.commit()

        # Seed sample vehicle TN01TJ2026 trajectory
        test_plate = "TN01TJ2026"
        existing_vehicle = session.scalar(
            select(Vehicle).where(Vehicle.plate_number == test_plate)
        )
        if not existing_vehicle:
            base_time = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)
            t1 = base_time
            t2 = t1 + timedelta(minutes=10)        # ~31.6 km/h (<40 green)
            t3 = t2 + timedelta(seconds=150)       # ~50.9 km/h (40-80 amber)
            t4 = t3 + timedelta(seconds=72)        # ~97.5 km/h (>80 red)
            t5 = t4 + timedelta(seconds=150)       # ~49.9 km/h (40-80 amber)

            v = Vehicle(
                plate_number=test_plate,
                vehicle_class=VehicleClass.passenger_car,
                first_seen=t1,
                last_seen=t5,
                sighting_count=5,
            )
            session.add(v)
            session.flush()

            cams = session.execute(
                select(Camera).order_by(Camera.id).limit(5)
            ).scalars().all()

            if len(cams) >= 5:
                timestamps = [t1, t2, t3, t4, t5]
                confidences = [0.98, 0.94, 0.99, 0.91, 0.96]
                for idx, (cam, ts, conf) in enumerate(zip(cams, timestamps, confidences, strict=False)):
                    sighting = Sighting(
                        vehicle_id=v.id,
                        camera_id=cam.id,
                        plate_number=test_plate,
                        raw_plate_text=test_plate,
                        ocr_confidence=conf,
                        vehicle_class=VehicleClass.passenger_car,
                        track_id=200 + idx,
                        timestamp=ts,
                        snapshot_path=f"snapshots/s{idx + 1}.jpg",
                        frames_voted=10,
                        job_id=job.id,
                    )
                    session.add(sighting)

            session.commit()


if __name__ == "__main__":
    seed_database()
    print("Database seeded successfully: admin, operator, viewer users + 12 cameras + TN01TJ2026 trajectory.")
