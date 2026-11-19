"""Agent 专用写工具：保存“健康档案测试”角色生成的定制问题与用户答案。

仅通过 TOOL_PERSONA_SCOPES 授权给 health_profile_test 角色；普通会话与其他角色不可见。
边界由代码强制：
- user_id 从 RunnableConfig 注入，模型不可填；
- 问题 key 只允许 q1~q10，答案必须与问题对应，不允许覆盖固定题；
- 复用 profile.service 的落库逻辑，不直接写 SQL；
- 同套问题更新答案，问题变化新增一套并保留历史（最多 20 套），同内容重复保存不落库。
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import AppError
from app.modules.profile import service as profile_service
from app.modules.profile.aspects import ASPECTS
from database import SessionLocal

_ASPECT_HELP = "；".join(f"{item['key']}={item['label']}" for item in ASPECTS)


class ProbeQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^q(?:[1-9]|10)$", description="问题序号，使用 q1~q10")
    aspect: str = Field(
        min_length=1,
        max_length=32,
        description=f"固定档案方面，只能从以下 key 中选：{_ASPECT_HELP}",
    )
    label: str = Field(min_length=1, max_length=48, description="问题标题")
    hint: str = Field(default="", max_length=120, description="填写提示，可空")
    placeholder: str = Field(default="", max_length=120, description="占位文案，可空")
    max_length: int = Field(default=200, ge=50, le=255, description="答案最大字数")


class SaveHealthProfileProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ProbeQuestionIn] = Field(
        min_length=3, max_length=10, description="本次生成的 3~10 个问题"
    )
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="用户已回答内容：q1~q10 → 文本，至少 1 题，只填用户实际说出的答案",
    )


def _user_id(config: RunnableConfig | None) -> int:
    uid = (config or {}).get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法保存健康档案")
    return uid


async def _save_health_profile_probe(
    questions: list[ProbeQuestionIn],
    answers: dict[str, str],
    config: RunnableConfig = None,
) -> dict:
    user_id = _user_id(config)
    payload = [
        q.model_dump() if hasattr(q, "model_dump") else dict(q)
        for q in questions
    ]
    with SessionLocal() as db:
        return profile_service.save_probe_health_profile(db, user_id, payload, answers)


save_health_profile_probe = StructuredTool.from_function(
    coroutine=_save_health_profile_probe,
    name="save_health_profile_probe",
    description=(
        "保存“健康档案测试”角色生成的一套定制健康问题与用户已回答内容（仅该角色可用）。"
        "只在用户明确确认写入健康档案后调用；questions 为 3~10 个，key 用 q1~q10，"
        "每题必须声明固定 aspect（不能自造），整套至少覆盖 3 个不同 aspect，单 aspect 最多 2 题，"
        "生理周期与其他各最多 1 题；answers 的 key 必须与 questions 对应，只填用户实际说出的答案，"
        "至少 1 题，不要推断或补写。同一套问题再次保存只更新答案；问题变化会新增一套并保留历史。"
        "不要传 user_id、固定题 key、日期或表名。"
    ),
    args_schema=SaveHealthProfileProbeIn,
)
