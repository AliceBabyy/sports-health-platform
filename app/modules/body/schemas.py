"""身材数据 schemas。"""
from datetime import date

from pydantic import BaseModel, Field


class MetricUpsertIn(BaseModel):
    record_date: date
    values: dict[str, float] = Field(default_factory=dict)


class MetricUpdateIn(BaseModel):
    value: float | None = None
    record_date: date | None = None
