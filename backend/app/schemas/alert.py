from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class AlertCreate(BaseModel):
    plate_number: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("plate_number")
    @classmethod
    def normalize_plate(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("plate_number cannot be empty")
        v = v.strip().upper()
        if len(v) > 20:
            raise ValueError("plate_number exceeds 20 characters")
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data):
        if isinstance(data, dict):
            for k in ("plate_number", "reason"):
                if k in data and data[k] is None:
                    raise ValueError(f"{k} cannot be null")
        return data


class AlertUpdate(BaseModel):
    plate_number: Optional[str] = Field(default=None, min_length=1, max_length=20)
    reason: Optional[str] = Field(default=None, min_length=1, max_length=500)
    is_active: Optional[bool] = None

    @field_validator("plate_number")
    @classmethod
    def normalize_plate(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().upper()
            if not v:
                raise ValueError("plate_number cannot be empty")
            if len(v) > 20:
                raise ValueError("plate_number exceeds 20 characters")
        return v

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, data):
        if isinstance(data, dict):
            for k in ("plate_number", "reason", "is_active"):
                if k in data and data[k] is None:
                    raise ValueError(f"{k} cannot be null")
        return data


class AlertOut(BaseModel):
    id: int
    plate_number: str
    reason: str
    created_by: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
