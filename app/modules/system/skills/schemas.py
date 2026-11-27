"""系统内置技能管理请求模型：平台提示词/声明式技能可完整编辑，代码技能可编辑元数据。"""
from typing import Any, Literal

from pydantic import BaseModel, Field


class SystemSkillCreateIn(BaseModel):
    key: str = Field(min_length=1, max_length=48)
    name: str = Field(min_length=1, max_length=48)
    slash_alias: str | None = Field(default=None, max_length=24)
    description: str = Field(default="", max_length=200)
    category: str = Field(default="custom", max_length=16)
    kind: Literal["prompt", "declarative"] = "prompt"
    definition: dict[str, Any]
    status: Literal["active", "disabled"] = "active"


class SystemSkillUpdateIn(BaseModel):
    key: str | None = Field(default=None, max_length=48)
    name: str = Field(min_length=1, max_length=48)
    slash_alias: str | None = Field(default=None, max_length=24)
    description: str = Field(default="", max_length=200)
    category: str = Field(max_length=16)
    kind: Literal["code", "prompt", "declarative"] | None = None
    definition: dict[str, Any] | None = None
    status: Literal["active", "disabled"]


class SystemSkillStatusIn(BaseModel):
    status: Literal["active", "disabled"]


class SystemSkillValidateIn(BaseModel):
    kind: Literal["prompt", "declarative"] = "prompt"
    definition: dict[str, Any]


class SystemSkillTestIn(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
