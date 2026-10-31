"""健身训练 schemas。"""
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
    items: list[PlanItemIn] = Field(default_factory=list)


class StartIn(BaseModel):
    mode: Literal["edit", "training"]


class NoteIn(BaseModel):
    status_text: str | None = Field(default=None, max_length=2000)  # 心得文本可空
    rating: int | None = Field(default=None, ge=1, le=5)
