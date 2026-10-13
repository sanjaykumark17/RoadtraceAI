from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    plate_number: str = Field(max_length=20)
    reason: str = Field(max_length=500)


class AlertUpdate(BaseModel):
    plate_number: Optional[str] = Field(default=None, max_length=20)
    reason: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class AlertOut(BaseModel):
    id: int
    plate_number: str
    reason: str
    created_by: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
