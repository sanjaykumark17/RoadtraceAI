from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertTrigger(Base):
    __tablename__ = "alert_triggers"
    __table_args__ = (
        Index("ix_alert_triggers_alert_id", "alert_id"),
        Index("ix_alert_triggers_sighting_id", "sighting_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"))
    sighting_id: Mapped[int] = mapped_column(ForeignKey("sightings.id"))
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acknowledged_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
