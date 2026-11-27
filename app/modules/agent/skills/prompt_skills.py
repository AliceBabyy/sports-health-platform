"""平台提示词技能的代码侧元数据。

提示词技能的定义（prompt）仍存放在数据库版本中；这里只放稳定键、展示信息和
提示词 ID，供种子脚本幂等写入，避免把大段提示词硬编码在 Python 里。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformPromptSkill:
    key: str
    name: str
    description: str
    category: str
    prompt_id: str
    slash_alias: str | None = None


PLATFORM_PROMPT_SKILLS: dict[str, PlatformPromptSkill] = {
    "custom_fitness_plan": PlatformPromptSkill(
        key="custom_fitness_plan",
        name="定制健身计划",
        description="结合健身档案、形体矫正与训练数据，定制一次今日健身计划；先输出文字方案，用户确认后再保存。",
        category="fitness",
        prompt_id="skill_custom_fitness_plan.v1",
        slash_alias="定制健身计划",
    ),
}
