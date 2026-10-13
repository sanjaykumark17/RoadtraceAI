"""add sightings notify trigger for real-time postgres LISTEN/NOTIFY

Revision ID: 002_sightings_notify_trigger
Revises: 001_initial_schema
Create Date: 2026-10-13 19:45:00
"""

from typing import Sequence, Union
from alembic import op

revision: str = "002_sightings_notify_trigger"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION notify_sighting_insert()
RETURNS trigger AS $$
DECLARE
    cam record;
    payload json;
BEGIN
    SELECT name, latitude, longitude INTO cam FROM cameras WHERE id = NEW.camera_id;
    payload = json_build_object(
        'id', NEW.id,
        'plate_number', NEW.plate_number,
        'camera_id', NEW.camera_id,
        'camera_name', cam.name,
        'latitude', cam.latitude,
        'longitude', cam.longitude,
        'timestamp', to_char(NEW.timestamp AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'ocr_confidence', NEW.ocr_confidence,
        'snapshot_path', NEW.snapshot_path,
        'track_id', NEW.track_id,
        'vehicle_id', NEW.vehicle_id,
        'flag', NEW.flag
    );
    PERFORM pg_notify('new_sighting', payload::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_sighting_notify ON sightings;
CREATE TRIGGER trigger_sighting_notify
AFTER INSERT ON sightings
FOR EACH ROW
EXECUTE FUNCTION notify_sighting_insert();
"""

DOWN_SQL = """
DROP TRIGGER IF EXISTS trigger_sighting_notify ON sightings;
DROP FUNCTION IF EXISTS notify_sighting_insert();
"""

def upgrade() -> None:
    op.execute(TRIGGER_SQL)

def downgrade() -> None:
    op.execute(DOWN_SQL)
