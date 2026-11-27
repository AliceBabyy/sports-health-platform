"""Agent 受控写工具：保存某个健康档案专项 skill 生成的一套问题与答案。

仅通过 TOOL_PERSONA_SCOPES 授权给 health_profile_test 角色；普通会话与其他角色不可见。
边界由代码强制：
- user_id 从 RunnableConfig 注入，模型不可填；
- skill_key 必须是九个专项之一，题目 aspect 必须属于该专项；
- 一套 3~6 题、题号 q1~q6、答案 key 必须与题目对应、至少 1 题有答案；
- 复用 profile.service 的落库逻辑，不直接写 SQL。
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import AppError
from app.modules.profile import service as profile_service
from app.modules.profile.aspect_skills import PROFILE_SKILL_KEYS
from app.modules.profile.aspects import ASPECTS
from database import SessionLocal

_ASPECT_HELP = "；".join(f"{item['key']}={item['label']}" for item in ASPECTS)
_SKILL_HELP = "、".join(sorted(PROFILE_SKILL_KEYS))


class AspectQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^q[1-6]$", description="题号，使用 q1~q6")
    aspect: str = Field(
        min_length=1,
        max_length=32,
        description=f"档案方面，必须属于当前专项：{_ASPECT_HELP}",
    )
    label: str = Field(min_length=1, max_length=48, description="问题标题")
    hint: str = Field(default="", max_length=120, description="填写提示，可空")
    placeholder: str = Field(default="", max_length=120, description="占位文案，可空")
    max_length: int = Field(default=200, ge=50, le=255, description="答案最大字数")


class SaveHealthProfileAspectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_key: str = Field(
        min_length=1, max_length=48,
        description=f"档案专项 skill key，只能是：{_SKILL_HELP}",
    )
    questions: list[AspectQuestionIn] = Field(
        min_length=3, max_length=6, description="本次生成的 3~6 个问题"
    )
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="用户已回答内容：q1~q6 → 文本，至少 1 题，只填用户实际说出的答案",
    )


def _user_id(config: RunnableConfig | None) -> int:
    uid = (config or {}).get("configurable", {}).get("user_id")
    if not uid:
        raise AppError(400, "缺少用户身份，无法保存健康档案")
    return uid


async def _save_health_profile_aspect(
    skill_key: str,
    questions: list[AspectQuestionIn],
    answers: dict[str, str],
    config: RunnableConfig = None,
) -> dict:
    user_id = _user_id(config)
    payload = [
        q.model_dump() if hasattr(q, "model_dump") else dict(q)
        for q in questions
    ]
    with SessionLocal() as db:
        return profile_service.save_health_profile_aspect(
            db, user_id, skill_key, payload, answers
        )


save_health_profile_aspect = StructuredTool.from_function(
    coroutine=_save_health_profile_aspect,
    name="save_health_profile_aspect",
    description=(
        "保存健康档案测试中某个专项 skill 生成的一套问题与用户已回答内容（仅该角色可用）。"
        "只在用户明确确认写入健康档案后调用；questions 为 3~6 个，key 用 q1~q6，"
        "每题 aspect 必须属于 skill_key 对应的专项（不能自造），不要混入其他专项；"
        "answers 的 key 必须与 questions 对应，只填用户实际说出的答案，至少 1 题，"
        "不要推断或补写。同一套题再次保存只更新答案；题目变化会新增一套，"
        "同一专项只保留最近 3 套。不要传 user_id、日期、set_id 或表名。"
    ),
    args_schema=SaveHealthProfileAspectIn,
)
