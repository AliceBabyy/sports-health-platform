"""健身训练 schemas。"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PlanItemIn(BaseModel):
    exercise_name: str = Field(min_length=1, max_length=128)
    body_part: str | None = Field(default=None, max_length=32)   # 部位可空
    weight_kg: float | None = Field(default=None, ge=0, le=999)  # 重量可空
    sets: int | None = Field(default=None, ge=1, le=99)          # 组数可空
    reps: str | None = Field(default=None, max_length=32)        # 每组个数，字符串，可空
    target_weight_kg: float | None = Field(default=None, ge=0, le=999)  # 期望突破重量，计划/记录均可填
    checked: bool = False


class PlanSaveIn(BaseModel):
    """编辑计划/记录（2026-11-04 起可改归属日期：计划挪期、记录补录/改期均支持）。

    起止时间与训练时长计划态/记录态均可填（均可空）；填了起止时间且未手填时长时，后端自动推导时长。
    """
    date: date
    items: list[PlanItemIn] = Field(default_factory=list)
    remark: str | None = Field(default=None, max_length=255)  # 备注（计划/记录均可填）
    start_time: datetime | None = None      # 开始训练时刻（ISO，计划/记录均可填、可空）
    end_time: datetime | None = None         # 结束训练时刻（ISO，计划/记录均可填、可空）
    duration_s: int | None = Field(default=None, ge=0, le=24 * 3600)  # 训练时长秒，可空
    avg_heart_rate: int | None = Field(default=None, ge=1, le=300)
    max_heart_rate: int | None = Field(default=None, ge=1, le=300)
    calories: Decimal | None = Field(default=None, ge=0)


class PlanCreateIn(PlanSaveIn):
    """新建计划/记录（2026-11-04 起 status 可指定：前端「＋ 新建记录」直接落 recorded）。"""
    date: date
    status: Literal["planned", "recorded"] = "planned"


class JsonImportPlanIn(BaseModel):
    """JSON 导入：一个计划对象（2026-11-04 新增；2026-11-07 起支持起止时间）。"""

    date: date
    start_time: datetime | None = None                         # 训练开始（ISO，可空）
    end_time: datetime | None = None                           # 训练结束（ISO，可空）
    remark: str | None = Field(default=None, max_length=255)  # 备注可空
    items: list[PlanItemIn] = Field(min_length=1)             # 动作至少 1 条


class JsonImportIn(BaseModel):
    """JSON 导入：整体请求体 {plans: [...]}。"""

    plans: list[JsonImportPlanIn] = Field(min_length=1, max_length=200)


class TrainingNoteIn(BaseModel):
    """健身练后心得：自我评估星级 + 最佳动作 + 复盘反思 + 下一步想法。"""
    rating: int | None = Field(default=None, ge=1, le=5)
    best_movement: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None)
    next_steps: str | None = Field(default=None)
