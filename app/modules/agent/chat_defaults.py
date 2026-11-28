"""普通会话（未绑定角色）的默认工具/技能配置。

单独一行配置，不新增角色、不参与角色选择。运行时用 ``ChatDefaultScope`` 伪装成
与角色同形的 scope，交给现有的 tools_for_persona / available_skills / 图缓存逻辑；
角色会话仍优先使用角色自己的授权。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.agent.models import AgentChatDefault
from app.modules.agent.skills.registry import available_skills
from app.modules.agent.tools.catalog import tool_names

DEFAULT_CHAT_KEY = "default_chat"
DEFAULT_CHAT_NAME = "通用对话"
DEFAULT_CONFIG_ID = 1


@dataclass(frozen=True)
class ChatDefaultScope:
    key: str
    tool_grants: frozenset[str] | None = None
    skill_grants: frozenset[str] | None = None


def _grants(raw) -> frozenset[str] | None:
    if raw is None:
        return None
    return frozenset(str(item) for item in raw)


def get_row(db: Session) -> AgentChatDefault | None:
    return db.get(AgentChatDefault, DEFAULT_CONFIG_ID)


def default_chat_scope(db: Session | None) -> ChatDefaultScope:
    if db is None:
        return ChatDefaultScope(DEFAULT_CHAT_KEY, None, None)
    row = get_row(db)
    return ChatDefaultScope(
        key=DEFAULT_CHAT_KEY,
        tool_grants=_grants(row.tool_grants) if row else None,
        skill_grants=_grants(row.skill_grants) if row else None,
    )


def _known_skills(db: Session) -> list[str]:
    return sorted(
        skill.key
        for skill in available_skills(db, 0, include_restricted=True)
        if skill.scope == "system"
    )


def default_chat_dict(db: Session) -> dict:
    row = get_row(db)
    known_tools = sorted(tool_names())
    known_skills = _known_skills(db)
    explicit_tools = row.tool_grants if row else None
    explicit_skills = row.skill_grants if row else None
    effective_tools = (
        sorted(set(explicit_tools) & set(known_tools))
        if explicit_tools is not None else known_tools
    )
    effective_skills = (
        sorted(set(explicit_skills) & set(known_skills))
        if explicit_skills is not None else known_skills
    )
    return {
        "id": "default",
        "key": DEFAULT_CHAT_KEY,
        "name": DEFAULT_CHAT_NAME,
        "description": "所有未绑定角色的普通会话统一使用本配置",
        "is_default_chat": True,
        "tool_grants": explicit_tools,
        "skill_grants": explicit_skills,
        "default_tools": known_tools,
        "default_skills": known_skills,
        "effective_tools": effective_tools,
        "effective_skills": effective_skills,
        "tool_count": len(effective_tools),
        "skill_count": len(effective_skills),
        "can_edit": True,
        "can_delete": False,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def save_default_chat(
    db: Session,
    *,
    tool_grants: list[str] | None,
    skill_grants: list[str] | None,
    actor_id: int | None,
) -> dict:
    row = get_row(db)
    if row is None:
        row = AgentChatDefault(id=DEFAULT_CONFIG_ID)
        db.add(row)
    row.tool_grants = tool_grants
    row.skill_grants = skill_grants
    row.updated_by = actor_id
    db.commit()
    db.refresh(row)
    return default_chat_dict(db)
