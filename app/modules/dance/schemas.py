"""舞蹈记录 schemas。"""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class DanceRecordIn(BaseModel):
    record_date: date
    dance_type: str = Field(min_length=1, max_length=32)
    stars: int = Field(ge=1, le=5)
    style: str | None = Field(default=None, max_length=64)
    duration_s: int = Field(ge=1)
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    max_heart_rate: int | None = Field(default=None, ge=1, le=300)
    calories: Decimal | None = None
