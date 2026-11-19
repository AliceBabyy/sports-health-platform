"""角色运行时：把会话绑定的角色版本解析为人设段，交给 Agent 节点渲染。

角色提示词影响 system prompt；角色级 tool_grants / skill_grants 参与工具与技能装配；
每轮从会话行读取快照，不写入 checkpointer。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.prompts.loader import load_system_prompt
from app.modules.agent.models import AgentConversation, AgentPersona, AgentPersonaVersion
from app.modules.agent.personas.definition import PersonaInvalid, parse_persona_definition

DEFAULT_PERSONA_BLOCK = "未启用角色设定，按平台默认健康助手风格回答。"
HEALTH_PROFILE_TEST_KEY = "health_profile_test"
HEALTH_PROFILE_TEST_GUARD_PROMPT = "persona_health_profile_test_guard.v2"


@dataclass(frozen=True)
class ResolvedPersona:
    id: int
    key: str
    name: str
    description: str
    scope: str
    version_no: int
    prompt: str
    tool_grants: frozenset[str] | None = None
    skill_grants: frozenset[str] | None = None


def _version(db: Session, persona_id: int, version_no: int) -> AgentPersonaVersion | None:
    return (
        db.query(AgentPersonaVersion)
        .filter(AgentPersonaVersion.persona_id == persona_id,
                AgentPersonaVersion.version_no == version_no)
        .first()
    )


def resolve_for_conversation(
    db: Session, conversation: AgentConversation, user_id: int
) -> ResolvedPersona | None:
    """按会话绑定的版本取角色；普通会话、越权、版本缺失均返回 None（回退默认基座）。"""
    if not conversation.persona_id:
        return None
    row = db.get(AgentPersona, conversation.persona_id)
    if row is None:
        return None
    if row.scope == "user" and row.owner_user_id != user_id:
        return None

    version_no = conversation.persona_version_no or row.current_version_no
    if not version_no:
        return None
    version = _version(db, row.id, version_no)
    if version is None:
        return None
    try:
        definition = parse_persona_definition(version.definition)
    except PersonaInvalid:
        return None
    return ResolvedPersona(
        id=row.id, key=row.persona_key, name=row.name, description=row.description or "",
        scope=row.scope, version_no=version.version_no, prompt=definition.prompt,
        tool_grants=(
            frozenset(str(item) for item in row.tool_grants)
            if row.tool_grants is not None else None
        ),
        skill_grants=(
            frozenset(str(item) for item in row.skill_grants)
            if row.skill_grants is not None else None
        ),
    )


def render_persona_block(persona: ResolvedPersona | None) -> str:
    if persona is None:
        return DEFAULT_PERSONA_BLOCK
    lines = [f"当前角色：{persona.name}（v{persona.version_no}）。"]
    if persona.description:
        lines.append(f"角色定位：{persona.description}")
    lines.append(persona.prompt)
    if persona.key == HEALTH_PROFILE_TEST_KEY:
        # 独立于角色版本的运行约束：老会话仍用旧版角色提示词，也强制受此约束。
        lines.append(load_system_prompt(HEALTH_PROFILE_TEST_GUARD_PROMPT))
    return "\n".join(lines)


def persona_summary(persona: ResolvedPersona | None) -> dict | None:
    if persona is None:
        return None
    return {
        "id": persona.id,
        "key": persona.key,
        "name": persona.name,
        "version_no": persona.version_no,
    }
