"""每日训练建议的结构化输出与接口入参。"""
from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DailyAdvice(BaseModel):
    """模型结构化输出：四件事 + 一段正文。extra=forbid 防止模型自造字段。"""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["适合", "克制", "休息"] = Field(description="今天适不适合运动")
    focus: Literal["有氧", "无氧", "有氧+无氧", "恢复"] = Field(description="训练方向")
    intensity: Literal["低", "中", "高"] = Field(description="建议强度")
    body_parts: list[str] = Field(default_factory=list, description="健身部位，最多 2 个")
    text: str = Field(
        description="侧栏三段要点：今日建议（≤20 字）/ 健身建议（≤20 字）/ 依据（≤40 字），每行以「- 」开头、行间换行、句末不写句号"
    )


class AdviceRegenerateIn(BaseModel):
    """手动刷新入参：默认今天，force 强制重算。"""

    model_config = ConfigDict(extra="forbid")

    date: date_type | None = None
    force: bool = False
