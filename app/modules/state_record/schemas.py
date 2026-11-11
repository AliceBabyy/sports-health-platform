"""状态记录 schemas：三类共用一套字段（日期 / 类型 / 星级 / 描述）。"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.state_record.models import STATE_TYPES


class StateRecordIn(BaseModel):
    """新增 / 编辑入参：type 定位落在哪张表；star 可空（null 表示未评星）。"""

    date: date
    type: Literal[tuple(STATE_TYPES)]  # type: ignore[valid-type]
    star: int | None = Field(default=None, ge=1, le=5)
    remark: str | None = Field(default=None, max_length=255)


class StateBatchItem(BaseModel):
    id: int = Field(ge=1)
    type: Literal[tuple(STATE_TYPES)]  # type: ignore[valid-type]


class StateBatchDeleteIn(BaseModel):
    """跨三表批量删除：每条记录自带类型定位表。"""

    items: list[StateBatchItem] = Field(min_length=1, max_length=200)
