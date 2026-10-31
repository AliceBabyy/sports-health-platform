"""身材数据 schemas（宽表：values 为字段 key→数值）。"""
from datetime import date

from pydantic import BaseModel, Field


class MetricUpsertIn(BaseModel):
    record_date: date
    values: dict[str, float] = Field(default_factory=dict)


class MetricUpdateIn(BaseModel):
    values: dict[str, float] = Field(default_factory=dict)
