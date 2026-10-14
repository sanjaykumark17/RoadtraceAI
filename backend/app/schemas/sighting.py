from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import VehicleClass


class SightingCreate(BaseModel):
    plate_number: str = Field(min_length=1, max_length=20)
    camera_id: int
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    timestamp: datetime
    raw_plate_text: Optional[str] = Field(default=None, max_length=50)
    ocr_confidence: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    vehicle_class: Optional[VehicleClass] = Field(default=VehicleClass.passenger_car)
    track_id: Optional[int] = Field(default=1)
    frames_voted: Optional[int] = Field(default=1)
    job_id: Optional[int] = Field(default=1)
    snapshot_path: Optional[str] = Field(default=None, max_length=500)

    @field_validator("plate_number")
    @classmethod
    def normalize_plate(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("plate_number cannot be empty")
        v = v.strip().upper()
        if len(v) > 20:
            raise ValueError("plate_number exceeds 20 characters")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("timestamp must include timezone offset")
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data):
        if isinstance(data, dict):
            for k in ("plate_number", "camera_id", "latitude", "longitude", "timestamp"):
                if k in data and data[k] is None:
                    raise ValueError(f"{k} cannot be null")
        return data


class SightingOut(BaseModel):
    id: int
    vehicle_id: Optional[int] = None
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

