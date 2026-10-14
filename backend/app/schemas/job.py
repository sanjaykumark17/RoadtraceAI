from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from app.models.enums import JobStatus


class JobCreate(BaseModel):
    camera_id: int
    source_uri: str = Field(max_length=500)
    recorded_start_at: Optional[datetime] = None


class JobOut(BaseModel):
    id: int
    camera_id: int
    source_uri: str
    status: JobStatus
    started_at: Optional[datetime] = None
    recorded_start_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    frames_processed: int
    error: Optional[str] = None

    @computed_field
    @property
    def job_id(self) -> int:
        return self.id

    model_config = {"from_attributes": True}
