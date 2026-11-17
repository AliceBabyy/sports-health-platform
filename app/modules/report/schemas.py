"""AI 报告叙事输出契约：形状由 pydantic 约束，数字真值由 facts 与 evidence 校验兜底。

模型只负责解释与建议；所有数字来自服务端事实快照，evidence 只能引用指标字典中的键。
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReportGenerateIn(BaseModel):
    """生成入参：周期类型 + 锚点日（缺省今天）+ 是否强制重生成。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["weekly", "monthly"] = "weekly"
    anchor: date | None = None
    force: bool = False


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="短标题，不超过 14 个字")
    detail: str = Field(description="基于 facts 的 2~3 句说明，可引用指标数字")
    evidence: list[str] = Field(
        default_factory=list,
        description="引用的指标键列表，只能取 facts.metrics 中存在的键，最多 3 个",
    )


class ReportNarrative(BaseModel):
    """周报与月报共用同一叙事结构，前端渲染逻辑复用。"""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(description="一句话主题，不超过 24 个字")
    summary: str = Field(description="2~3 句总览，包含关键数字")
    highlights: list[EvidenceItem] = Field(default_factory=list, description="做得好的地方 2~4 条")
    watchouts: list[EvidenceItem] = Field(default_factory=list, description="需要留意的地方 1~3 条，可为空")
    next_actions: list[EvidenceItem] = Field(default_factory=list, description="下一周期可执行建议 2~3 条")
    caveats: list[str] = Field(default_factory=list, description="数据不足或口径说明")
    cycle_note: str = Field(
        default="",
        description="生理周期与训练安排的观察；无周期数据时返回空字符串",
    )
