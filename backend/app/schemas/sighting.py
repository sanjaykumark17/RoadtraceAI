from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import VehicleClass


class SightingCreate(BaseModel):
    plate_number: str = Field(max_length=20)
    camera_id: int
    latitude: float
    longitude: float
    timestamp: datetime


class SightingOut(BaseModel):
    id: int
    vehicle_id: int
    camera_id: int
    plate_number: str
    raw_plate_text: str
    ocr_confidence: float
    vehicle_class: VehicleClass
    track_id: int
    timestamp: datetime
    frames_voted: int
    snapshot_path: Optional[str] = None
    job_id: int
    flag: Optional[str] = None

    model_config = {"from_attributes": True}


class SightingQuery(BaseModel):
    plate: Optional[str] = None
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
