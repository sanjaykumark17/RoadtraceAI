"""add recorded_start_at to processing_jobs and allow nullable vehicle_id in sightings

Revision ID: 003_phase2_pipeline_updates
Revises: 002_sightings_notify_trigger
Create Date: 2026-10-14 15:45:00
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_phase2_pipeline_updates"
down_revision: Union[str, None] = "002_sightings_notify_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("recorded_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "sightings",
        "vehicle_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "sightings",
        "vehicle_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("processing_jobs", "recorded_start_at")
