from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import VehicleClass


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_plate_number", "plate_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plate_number: Mapped[str] = mapped_column(String(20), unique=True)
    vehicle_class: Mapped[VehicleClass] = mapped_column(
        SAEnum(VehicleClass, name="vehicle_class")
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sighting_count: Mapped[int] = mapped_column(Integer, default=0)
