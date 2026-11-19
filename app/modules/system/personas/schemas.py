"""系统内置角色管理请求模型。"""
from typing import Any, Literal

from pydantic import BaseModel, Field


class SystemPersonaIn(BaseModel):
    key: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=48)
    description: str = Field(default="", max_length=200)
    definition: dict[str, Any]
    status: Literal["active", "disabled"] = "active"
    sort_order: int = Field(default=0, ge=0, le=9999)
    tool_grants: list[str] | None = None
    skill_grants: list[str] | None = None


class SystemPersonaUpdateIn(BaseModel):
    key: str | None = Field(default=None, max_length=48)
    name: str = Field(min_length=1, max_length=48)
    description: str = Field(default="", max_length=200)
    definition: dict[str, Any]
    status: Literal["active", "disabled"] = "active"
    sort_order: int = Field(default=0, ge=0, le=9999)
    tool_grants: list[str] | None = None
    skill_grants: list[str] | None = None
