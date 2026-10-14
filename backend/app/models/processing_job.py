from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import JobStatus


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    source_uri: Mapped[str] = mapped_column(String(500))
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, name="job_status"), default=JobStatus.queued
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_start_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
