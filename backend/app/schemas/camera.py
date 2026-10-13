from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import CameraStatus


class CameraCreate(BaseModel):
    name: str = Field(max_length=255)
    latitude: float
    longitude: float
    intersection_name: str = Field(max_length=255)
    heading_deg: float
    status: CameraStatus = CameraStatus.active


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    intersection_name: Optional[str] = Field(default=None, max_length=255)
    heading_deg: Optional[float] = None
    status: Optional[CameraStatus] = None


class CameraOut(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    intersection_name: str
    heading_deg: float
    status: CameraStatus
    created_at: datetime

    model_config = {"from_attributes": True}
