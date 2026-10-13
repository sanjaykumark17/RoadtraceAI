from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SyncSession
from app.models.camera import Camera
from app.models.enums import CameraStatus, UserRole
from app.models.user import User

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
        # Seed 1 admin user
        admin_email = "admin@roadtrace.ai"
        existing_user = session.scalar(
            select(User).where(User.email == admin_email)
        )
        if not existing_user:
            admin = User(
                email=admin_email,
                password_hash=hash_password("admin123"),
                role=UserRole.admin,
                is_active=True,
            )
            session.add(admin)

        # Seed 12 sample cameras
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


if __name__ == "__main__":
    seed_database()
    print("Database seeded successfully: 1 admin user + 12 cameras.")
