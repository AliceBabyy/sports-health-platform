"""定时任务入参契约：只接受任务键、表达式与参数，不接受函数名或任意可执行内容。"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobCreateIn(BaseModel):
    """新建任务：job_key 必须存在于代码注册表。"""

    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=64, description="任务键，如 report.weekly")
    name: str | None = Field(default=None, max_length=64, description="显示名；空则取注册表默认名")
    trigger_type: Literal["cron", "date", "interval"] = Field(description="触发类型")
    trigger_expr: str = Field(min_length=1, max_length=128, description="触发表达式")
    timezone: str | None = Field(default=None, max_length=48, description="时区；空则用全局默认")
    params: dict[str, Any] = Field(default_factory=dict, description="任务参数，结构与注册表一致")
    enabled: bool = True
    misfire_grace_seconds: int | None = Field(
        default=None, ge=0, le=86400, description="错过宽限秒数；空则用全局默认"
    )


class JobUpdateIn(BaseModel):
    """更新任务：只改传入字段；表达式与参数会重新校验。"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=64)
    trigger_type: Literal["cron", "date", "interval"] | None = None
    trigger_expr: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str | None = Field(default=None, max_length=48)
    params: dict[str, Any] | None = None
    enabled: bool | None = None
    misfire_grace_seconds: int | None = Field(default=None, ge=0, le=86400)
