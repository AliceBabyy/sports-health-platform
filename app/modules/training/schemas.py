"""健身训练 schemas。"""
from typing import Literal

from pydantic import BaseModel, Field


class PlanItemIn(BaseModel):
    exercise_name: str = Field(min_length=1, max_length=128)
    body_part: str = Field(default="", max_length=32)
    weight_kg: float = Field(default=0, ge=0, le=999)
    sets: int = Field(default=1, ge=1, le=99)
    reps: int = Field(default=1, ge=1, le=999)
    target_weight_kg: float | None = Field(default=None, ge=0, le=999)
    checked: bool = False


class PlanSaveIn(BaseModel):
    items: list[PlanItemIn] = Field(default_factory=list)


class StartIn(BaseModel):
    mode: Literal["edit", "training"]


class NoteIn(BaseModel):
    status_text: str = Field(default="", max_length=2000)
    rating: int | None = Field(default=None, ge=1, le=5)
