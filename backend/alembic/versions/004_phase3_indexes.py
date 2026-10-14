"""add missing foreign key indexes, drop duplicate gist and plate indexes, enable pg_trgm

Revision ID: 004_phase3_indexes
Revises: 003_phase2_pipeline_updates
Create Date: 2026-10-14 16:25:00
"""

from typing import Sequence, Union
from alembic import op


revision: str = "004_phase3_indexes"
down_revision: Union[str, None] = "003_phase2_pipeline_updates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pg_trgm and fuzzystrmatch extensions for SQL fuzzy matching
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;")

    # Add missing foreign key indexes
    op.create_index(
        "ix_sightings_vehicle_id",
        "sightings",
        ["vehicle_id"],
        unique=False,
    )
    op.create_index(
        "ix_sightings_job_id",
        "sightings",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_alert_triggers_alert_id",
        "alert_triggers",
        ["alert_id"],
        unique=False,
    )
    op.create_index(
        "ix_alert_triggers_sighting_id",
        "alert_triggers",
        ["sighting_id"],
        unique=False,
    )

    # Drop duplicate GiST indexes created implicitly by geoalchemy2
    op.execute("DROP INDEX IF EXISTS idx_sightings_location;")
    op.execute("DROP INDEX IF EXISTS idx_cameras_location;")

    # Drop duplicate plate index on vehicles (unique constraint vehicles_plate_number_key already indexes it)
    op.execute("DROP INDEX IF EXISTS ix_vehicles_plate_number;")


def downgrade() -> None:
    op.create_index(
        "ix_vehicles_plate_number",
        "vehicles",
        ["plate_number"],
        unique=False,
    )
    op.drop_index("ix_alert_triggers_sighting_id", table_name="alert_triggers")
    op.drop_index("ix_alert_triggers_alert_id", table_name="alert_triggers")
    op.drop_index("ix_sightings_job_id", table_name="sightings")
    op.drop_index("ix_sightings_vehicle_id", table_name="sightings")
