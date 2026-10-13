from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    desc,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import VehicleClass


class Sighting(Base):
    __tablename__ = "sightings"
    __table_args__ = (
        Index("ix_sightings_plate_timestamp", "plate_number", desc("timestamp")),
        Index("ix_sightings_camera_timestamp", "camera_id", "timestamp"),
        Index("ix_sightings_location", "location", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    plate_number: Mapped[str] = mapped_column(String(20))
    raw_plate_text: Mapped[str] = mapped_column(String(50))
    ocr_confidence: Mapped[float] = mapped_column(Float)
    vehicle_class: Mapped[VehicleClass] = mapped_column(
        SAEnum(VehicleClass, name="vehicle_class", create_type=False)
    )
    track_id: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False), nullable=True
    )
    frames_voted: Mapped[int] = mapped_column(Integer)
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("processing_jobs.id"))
    flag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
