"""游泳记录 schemas：配速/划频只读派生字段不接收前端提交。

2026-11 计划态字段化：status=planned 时需 距离/时长/主泳姿（由 API 校验）；
status=recorded 时需距离/时长。remark 计划/记录均可填。
"""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class SwimRecordIn(BaseModel):
    record_date: date
    status: Literal["planned", "recorded"] = "recorded"
    distance_m: int | None = Field(default=None, ge=1)
    duration_s: int | None = Field(default=None, ge=1)  # 前端分钟转秒后提交
    main_stroke: str | None = Field(default=None)  # 主泳姿（计划态必填，记录态可空）
    remark: str | None = Field(default=None, max_length=255)  # 备注
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    total_strokes: int | None = Field(default=None, ge=0)
    laps: int | None = Field(default=None, ge=0)
    calories: Decimal | None = None
    avg_stroke_rate: float | None = Field(default=None, ge=0, le=200)  # 平均划频（记录态可手填，次/分）
