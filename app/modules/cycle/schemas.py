"""生理周期 schemas。"""
from datetime import date

from pydantic import BaseModel, Field


class SettingsIn(BaseModel):
    cycle_length: int = Field(ge=10, le=60)
    period_length: int = Field(ge=1, le=20)


class PeriodIn(BaseModel):
    start_date: date
    end_date: date | None = None
    # 记录月经时可一并更新设置（MC-02）
    cycle_length: int | None = Field(default=None, ge=10, le=60)
    period_length: int | None = Field(default=None, ge=1, le=20)


class PeriodUpdateIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


class PainIn(BaseModel):
    pain_level: int = Field(ge=0, le=3)
