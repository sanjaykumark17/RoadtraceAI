from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CameraStatus


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        Index("ix_cameras_location", "location", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    location = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False), nullable=True
    )
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    intersection_name: Mapped[str] = mapped_column(String(255))
    heading_deg: Mapped[float] = mapped_column(Float)
    status: Mapped[CameraStatus] = mapped_column(
        SAEnum(CameraStatus, name="camera_status"), default=CameraStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
