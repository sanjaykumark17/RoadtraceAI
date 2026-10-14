from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import CameraStatus


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    intersection_name: str = Field(min_length=1, max_length=255)
    heading_deg: float = Field(ge=0.0, le=360.0)
    status: CameraStatus = CameraStatus.active

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data):
        if isinstance(data, dict):
            for k in ("name", "latitude", "longitude", "intersection_name", "heading_deg", "status"):
                if k in data and data[k] is None:
                    raise ValueError(f"{k} cannot be null")
        return data


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    intersection_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    heading_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    status: Optional[CameraStatus] = None

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data):
        if isinstance(data, dict):
            for k in ("name", "latitude", "longitude", "intersection_name", "heading_deg", "status"):
                if k in data and data[k] is None:
                    raise ValueError(f"{k} cannot be null")
        return data


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
