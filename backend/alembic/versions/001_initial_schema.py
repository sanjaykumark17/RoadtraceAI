"""create postgis schema with 8 tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-10-13 15:35:00
"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure postgis extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "operator", "viewer", name="user_role"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    # cameras
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("intersection_name", sa.String(length=255), nullable=False),
        sa.Column("heading_deg", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "maintenance", name="camera_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cameras_location",
        "cameras",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )

    # vehicles
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plate_number", sa.String(length=20), nullable=False),
        sa.Column(
            "vehicle_class",
            sa.Enum(
                "passenger_car",
                "commercial_truck",
                "public_bus",
                "two_wheeler",
                name="vehicle_class",
            ),
            nullable=False,
        ),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "sighting_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plate_number"),
    )
    op.create_index(
        "ix_vehicles_plate_number", "vehicles", ["plate_number"], unique=False
    )

    # processing_jobs
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("source_uri", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "done", "failed", name="job_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "frames_processed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # sightings
    op.create_table(
        "sightings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("plate_number", sa.String(length=20), nullable=False),
        sa.Column("raw_plate_text", sa.String(length=50), nullable=False),
        sa.Column("ocr_confidence", sa.Float(), nullable=False),
        sa.Column(
            "vehicle_class",
            postgresql.ENUM(
                "passenger_car",
                "commercial_truck",
                "public_bus",
                "two_wheeler",
                name="vehicle_class",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("frames_voted", sa.Integer(), nullable=False),
        sa.Column("snapshot_path", sa.String(length=500), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("flag", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["processing_jobs.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sightings_camera_timestamp",
        "sightings",
        ["camera_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_sightings_location",
        "sightings",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "ix_sightings_plate_timestamp",
        "sightings",
        ["plate_number", sa.text("timestamp DESC")],
        unique=False,
    )

    # alerts
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plate_number", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_plate_number", "alerts", ["plate_number"], unique=False)

    # alert_triggers
    op.create_table(
        "alert_triggers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("sighting_id", sa.Integer(), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"]),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("alert_triggers")
    op.drop_table("alerts")
    op.drop_table("sightings")
    op.drop_table("processing_jobs")
    op.drop_table("vehicles")
    op.drop_table("cameras")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS vehicle_class")
    op.execute("DROP TYPE IF EXISTS camera_status")
    op.execute("DROP TYPE IF EXISTS user_role")
