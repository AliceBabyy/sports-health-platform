"""舞蹈记录 schemas。

2026-11 计划态字段化：status=planned 时需 舞种/星级/舞蹈老师（由 API 校验）；
status=recorded 时需舞种/星级；duration_s 默认由起止时间推导，也可手动填。
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class DanceRecordIn(BaseModel):
    date: date
    start_time: datetime | None = None  # 课程开始时间（ISO datetime）
    end_time: datetime | None = None   # 课程结束时间
    status: Literal["planned", "recorded"] = "recorded"
    dance_type: str | None = Field(default=None, min_length=1, max_length=32)  # 舞种（计划/记录态必填）
    stars: int | None = Field(default=None, ge=1, le=5)  # 星级（计划/记录态必填）
    teacher: str | None = Field(default=None, max_length=64)  # 舞蹈老师
    remark: str | None = Field(default=None, max_length=255)  # 备注
    style: str | None = Field(default=None, max_length=64)
    duration_s: int | None = Field(default=None, ge=1)
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    max_heart_rate: int | None = Field(default=None, ge=1, le=300)
    calories: Decimal | None = None


class DanceNoteIn(BaseModel):
    """舞蹈练后心得：自我评估 + 视频效果双星级 + 感悟。"""
    rating: int | None = Field(default=None, ge=1, le=5)
    video_effect: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None)
