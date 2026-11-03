"""舞蹈记录 schemas。

2026-11 计划态字段化：status=planned 时需 舞种/星级（由 API 校验）；
status=recorded 时需舞种/星级/时长。remark 计划/记录均可填。
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class DanceRecordIn(BaseModel):
    record_date: date
    status: Literal["planned", "recorded"] = "recorded"
    dance_type: str | None = Field(default=None, min_length=1, max_length=32)  # 舞种（计划/记录态必填）
    stars: int | None = Field(default=None, ge=1, le=5)  # 星级（计划/记录态必填）
    remark: str | None = Field(default=None, max_length=255)  # 备注
    style: str | None = Field(default=None, max_length=64)
    duration_s: int | None = Field(default=None, ge=1)
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    max_heart_rate: int | None = Field(default=None, ge=1, le=300)
    calories: Decimal | None = None
