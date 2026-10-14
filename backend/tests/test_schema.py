from sqlalchemy import create_engine, inspect, text

from app.core.config import settings
from app.core.security import verify_password
from app.db.seed import seed_database
from app.db.session import SyncSession
from app.models import (
    Base,
    Camera,
    User,
    UserRole,
)

EXPECTED_TABLES = {
    "users",
    "cameras",
    "vehicles",
    "sightings",
    "alerts",
    "alert_triggers",
    "audit_logs",
    "processing_jobs",
}


def test_exactly_eight_tables():
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    app_tables = db_tables.intersection(EXPECTED_TABLES)
    assert app_tables == EXPECTED_TABLES, f"Missing tables: {EXPECTED_TABLES - app_tables}"
    assert len(app_tables) == 8


def test_models_registered_in_base_metadata():
    model_table_names = set(Base.metadata.tables.keys())
    assert model_table_names == EXPECTED_TABLES


def test_composite_index_exists():
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)
    indexes = insp.get_indexes("sightings")
    composite = next(
        (idx for idx in indexes if idx["name"] == "ix_sightings_plate_timestamp"),
        None,
    )
    assert composite is not None
    assert composite["column_names"] == ["plate_number", "timestamp"]
    assert composite.get("column_sorting", {}).get("timestamp") == ("desc",)


def test_gist_indexes_exist():
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)

    sightings_indexes = insp.get_indexes("sightings")
    sightings_gist = any(
        idx.get("dialect_options", {}).get("postgresql_using") == "gist"
        and "location" in idx["column_names"]
        for idx in sightings_indexes
    )
    assert sightings_gist

    cameras_indexes = insp.get_indexes("cameras")
    cameras_gist = any(
        idx.get("dialect_options", {}).get("postgresql_using") == "gist"
        and "location" in idx["column_names"]
        for idx in cameras_indexes
    )
    assert cameras_gist


def test_camera_timestamp_and_vehicle_indexes():
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)

    sightings_indexes = insp.get_indexes("sightings")
    cam_ts_idx = next(
        (idx for idx in sightings_indexes if idx["name"] == "ix_sightings_camera_timestamp"),
        None,
    )
    assert cam_ts_idx is not None
    assert cam_ts_idx["column_names"] == ["camera_id", "timestamp"]

    vehicle_indexes = insp.get_indexes("vehicles")
    plate_idx = next(
        (idx for idx in vehicle_indexes if "plate_number" in idx["column_names"]),
        None,
    )
    assert plate_idx is not None


from tests.conftest import TEST_ADMIN_PASSWORD


def test_seed_admin_and_twelve_cameras():
    seed_database()

    with SyncSession() as session:
        admin = session.query(User).filter_by(email="admin@roadtrace.ai").first()
        assert admin is not None
        assert admin.role == UserRole.admin
        assert verify_password(TEST_ADMIN_PASSWORD, admin.password_hash)

        cameras = session.query(Camera).all()
        assert len(cameras) >= 12

        gst_cams = [c for c in cameras if "GST" in c.name]
        orr_cams = [c for c in cameras if "ORR" in c.name]
        assert len(gst_cams) >= 8
        assert len(orr_cams) >= 4


def test_explain_uses_composite_index():
    with SyncSession() as session:
        query = text(
            "EXPLAIN SELECT * FROM sightings "
            "WHERE plate_number = :plate "
            "ORDER BY timestamp DESC LIMIT 100"
        )
        result = session.execute(query, {"plate": "TN01AB1234"}).fetchall()
        plan_lines = [row[0] for row in result]
        plan_text = "\n".join(plan_lines)

        assert "ix_sightings_plate_timestamp" in plan_text
        assert "Index Scan" in plan_text
        assert "Seq Scan" not in plan_text


def test_foreign_key_and_no_duplicate_indexes():
    engine = create_engine(settings.database_url_sync)
    insp = inspect(engine)

    sightings_idx_names = {idx["name"] for idx in insp.get_indexes("sightings")}
    assert "ix_sightings_vehicle_id" in sightings_idx_names
    assert "ix_sightings_job_id" in sightings_idx_names

    alert_triggers_idx_names = {idx["name"] for idx in insp.get_indexes("alert_triggers")}
    assert "ix_alert_triggers_alert_id" in alert_triggers_idx_names
    assert "ix_alert_triggers_sighting_id" in alert_triggers_idx_names

    # Check connection pool is real pool (not NullPool)
    from app.db.session import async_engine, sync_engine

    assert sync_engine.pool.__class__.__name__ != "NullPool"
    assert async_engine.pool.__class__.__name__ != "NullPool"
