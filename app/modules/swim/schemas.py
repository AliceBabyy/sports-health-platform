"""游泳记录 schemas：配速/划频只读派生字段不接收前端提交。"""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class SwimRecordIn(BaseModel):
    record_date: date
    distance_m: int = Field(ge=1)
    duration_s: int = Field(ge=1)  # 前端分钟转秒后提交
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    total_strokes: int | None = Field(default=None, ge=0)
    main_stroke: str
    laps: int | None = Field(default=None, ge=0)
    calories: Decimal | None = None
