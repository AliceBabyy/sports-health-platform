"""系统内置角色管理：管理员侧的增删改查与工具/技能白名单。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agent.chat_defaults import (
    default_chat_dict,
    save_default_chat as save_chat_default,
)
from app.modules.agent.models import AgentConversation, AgentPersona, AgentPersonaVersion
from app.modules.agent.personas.definition import validate_definition
from app.modules.agent.personas.management import (
    KEY_RE,
    MAX_DESCRIPTION,
    NAME_RE,
    PersonaValidationError,
    current_version,
    definition_hash,
    latest_version,
)
from app.modules.agent.skills.registry import available_skills
from app.modules.agent.tools.catalog import tool_names
from app.modules.agent.tools.catalog import tool_options as catalog_tool_options

SYSTEM_SCOPE = "system"
MAX_SORT_ORDER = 9999


def _normalise_grants(
    payload: dict,
    field: str,
    allowed: set[str],
    errors: list[dict],
) -> list[str] | None:
    raw = payload.get(field)
    if raw is None:
        return None
    if not isinstance(raw, list):
        errors.append({"field": field, "reason": "必须是字符串数组或 null"})
        return None
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            errors.append({"field": field, "reason": "数组元素必须是字符串"})
            continue
        value = item.strip()
        if not value:
            continue
        if value not in allowed:
            errors.append({"field": field, "reason": f"未知项：{value}"})
            continue
        values.append(value)
    return sorted(set(values))


def _basic_errors(
    db: Session,
    *,
    name: str,
    key: str,
    description: str,
    sort_order: int,
    exclude_id: int | None,
) -> list[dict]:
    errors: list[dict] = []
    if not 1 <= len(name) <= 48:
        errors.append({"field": "name", "reason": "角色名需为 1~48 字"})
    elif not NAME_RE.fullmatch(name):
        errors.append({"field": "name", "reason": "角色名不能包含空格或斜杠"})
    if not KEY_RE.fullmatch(key):
        errors.append({"field": "key", "reason": "角色键需为小写字母开头的 1~48 位字母数字下划线"})
    if len(description) > MAX_DESCRIPTION:
        errors.append({"field": "description", "reason": f"角色定位最多 {MAX_DESCRIPTION} 字"})
    if not 0 <= sort_order <= MAX_SORT_ORDER:
        errors.append({"field": "sort_order", "reason": f"排序需在 0~{MAX_SORT_ORDER} 之间"})

    q = db.query(AgentPersona).filter(AgentPersona.scope == SYSTEM_SCOPE)
    if exclude_id is not None:
        q = q.filter(AgentPersona.id != exclude_id)
    if q.filter(AgentPersona.persona_key == key).first():
        errors.append({"field": "key", "reason": "内置角色键已存在"})
    if q.filter(AgentPersona.name == name).first():
        errors.append({"field": "name", "reason": "内置角色名已存在"})
    return errors


def _system_persona(db: Session, persona_id: int) -> AgentPersona:
    persona = db.get(AgentPersona, persona_id)
    if persona is None:
        raise AppError(404, "内置角色不存在")
    if persona.scope != SYSTEM_SCOPE:
        raise AppError(404, "内置角色不存在")
    return persona


def _validate_payload(
    db: Session,
    payload: dict,
    *,
    exclude_id: int,
) -> tuple[list[str] | None, list[str] | None]:
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    sort_order = payload.get("sort_order")
    if sort_order is None:
        sort_order = 0
    status = payload.get("status") or "active"
    errors = _basic_errors(
        db, name=name, key=(payload.get("key") or "").strip().lower(),
        description=description, sort_order=sort_order, exclude_id=exclude_id,
    )
    if status not in ("active", "disabled"):
        errors.append({"field": "status", "reason": "状态只能是 active 或 disabled"})
    definition_errors, _ = validate_definition(payload.get("definition"))
    errors.extend(definition_errors)
    tools = _normalise_grants(payload, "tool_grants", tool_names(), errors)
    available_skill_keys = {
        skill.key for skill in available_skills(db, 0, include_restricted=True)
    }
    skills = _normalise_grants(payload, "skill_grants", available_skill_keys, errors)
    if tools is not None:
        for name_ in tools:
            if name_.startswith("skill_"):
                errors.append({
                    "field": "tool_grants",
                    "reason": f"{name_} 属于技能，请使用 skill_grants 管理",
                })
    if errors:
        raise PersonaValidationError(errors)
    return tools, skills


def _default_tools(persona_key: str) -> list[str]:
    return sorted(tool_names())


def _default_skills(db: Session, persona_key: str) -> list[str]:
    return sorted(
        skill.key for skill in available_skills(db, 0, persona_key)
        if skill.scope == SYSTEM_SCOPE
    )


def _available_skill_keys(db: Session) -> set[str]:
    return {
        skill.key for skill in available_skills(db, 0, include_restricted=True)
        if skill.scope == SYSTEM_SCOPE
    }


def persona_dict(db: Session, persona: AgentPersona) -> dict:
    version = current_version(db, persona) or latest_version(db, persona)
    default_tools = _default_tools(persona.persona_key)
    default_skills = _default_skills(db, persona.persona_key)
    known_tools = tool_names()
    known_skills = _available_skill_keys(db)
    explicit_tools = persona.tool_grants
    explicit_skills = persona.skill_grants
    effective_tools = (
        sorted(set(explicit_tools) & known_tools)
        if explicit_tools is not None else default_tools
    )
    effective_skills = (
        sorted(set(explicit_skills) & known_skills)
        if explicit_skills is not None else default_skills
    )
    conversation_count = db.query(AgentConversation).filter(
        AgentConversation.persona_id == persona.id
    ).count()
    return {
        "id": persona.id,
        "scope": persona.scope,
        "key": persona.persona_key,
        "name": persona.name,
        "description": persona.description or "",
        "status": persona.status,
        "sort_order": persona.sort_order,
        "current_version_no": persona.current_version_no,
        "version_no": version.version_no if version else None,
        "published": bool(version and version.published_at),
        "definition": version.definition if version else None,
        "tool_grants": explicit_tools,
        "skill_grants": explicit_skills,
        "default_tools": default_tools,
        "default_skills": default_skills,
        "effective_tools": effective_tools,
        "effective_skills": effective_skills,
        "tool_count": len(effective_tools),
        "skill_count": len(effective_skills),
        "conversation_count": conversation_count,
        "can_edit": True,
        "can_delete": conversation_count == 0,
        "updated_at": persona.updated_at.isoformat() if persona.updated_at else None,
    }


def list_system_personas(db: Session) -> list[dict]:
    rows = (
        db.query(AgentPersona)
        .filter(AgentPersona.scope == SYSTEM_SCOPE)
        .order_by(AgentPersona.sort_order.asc(), AgentPersona.id.asc())
        .all()
    )
    return [persona_dict(db, row) for row in rows]


def get_system_persona(db: Session, persona_id: int) -> dict:
    return persona_dict(db, _system_persona(db, persona_id))


def create_system_persona(db: Session, payload: dict, actor_id: int | None) -> dict:
    key = (payload.get("key") or "").strip().lower()
    tools, skills = _validate_payload(db, payload, exclude_id=None)
    sort_order = payload.get("sort_order")
    if sort_order is None:
        sort_order = 0
    persona = AgentPersona(
        scope=SYSTEM_SCOPE,
        owner_user_id=None,
        persona_key=key,
        name=payload["name"].strip(),
        description=(payload.get("description") or "").strip(),
        status=payload.get("status") or "active",
        sort_order=sort_order,
        current_version_no=1,
        tool_grants=tools,
        skill_grants=skills,
    )
    db.add(persona)
    db.flush()
    definition = payload["definition"]
    db.add(AgentPersonaVersion(
        persona_id=persona.id,
        version_no=1,
        definition=definition,
        definition_hash=definition_hash(definition),
        created_by=actor_id,
        published_at=datetime.now(),
    ))
    db.commit()
    db.refresh(persona)
    return persona_dict(db, persona)


def save_system_persona(db: Session, persona_id: int, payload: dict, actor_id: int | None) -> dict:
    persona = _system_persona(db, persona_id)
    requested_key = payload.get("key")
    if requested_key is not None and requested_key.strip().lower() != persona.persona_key:
        raise PersonaValidationError([{
            "field": "key", "reason": "内置角色键创建后不可修改；需要新键请新建角色",
        }])
    tools, skills = _validate_payload(
        db, payload, exclude_id=persona.id,
    )
    persona.name = payload["name"].strip()
    persona.description = (payload.get("description") or "").strip()
    persona.status = payload.get("status") or persona.status
    sort_order = payload.get("sort_order")
    persona.sort_order = persona.sort_order if sort_order is None else sort_order
    persona.tool_grants = tools
    persona.skill_grants = skills

    definition = payload["definition"]
    latest = latest_version(db, persona)
    new_hash = definition_hash(definition)
    if latest is None or latest.definition_hash != new_hash:
        next_no = (latest.version_no + 1) if latest else 1
        db.add(AgentPersonaVersion(
            persona_id=persona.id,
            version_no=next_no,
            definition=definition,
            definition_hash=new_hash,
            created_by=actor_id,
            published_at=datetime.now(),
        ))
        persona.current_version_no = next_no
    db.commit()
    db.refresh(persona)
    return persona_dict(db, persona)


def delete_system_persona(db: Session, persona_id: int) -> None:
    persona = _system_persona(db, persona_id)
    used = db.query(AgentConversation).filter(
        AgentConversation.persona_id == persona.id
    ).count()
    if used:
        raise AppError(409, f"该内置角色已有 {used} 个角色会话，请先删除相关会话")
    db.delete(persona)
    db.commit()


def tool_options() -> list[dict]:
    """工具选项；角色限制已取消，所有已注册工具都可自由勾选。"""
    options = catalog_tool_options()
    for option in options:
        option["restricted"] = False
    return options


def skill_options(db: Session) -> list[dict]:
    skills = [
        skill for skill in available_skills(db, 0, include_restricted=True)
        if skill.scope == SYSTEM_SCOPE
    ]
    order = {"code": 0, "declarative": 1, "prompt": 2}
    return sorted([
        {
            "key": skill.key,
            "label": skill.name,
            "kind": skill.kind,
            "scope": skill.scope,
            "description": skill.description,
            "version": skill.version_no,
            "restricted": False,
        }
        for skill in skills
    ], key=lambda item: (order.get(item["kind"], 99), item["key"]))


def get_default_chat(db: Session) -> dict:
    return default_chat_dict(db)


def save_default_chat_config(db: Session, payload: dict, actor_id: int | None) -> dict:
    """保存通用对话配置；只校验选项是否存在，不做任何角色范围限制。"""
    errors: list[dict] = []
    tools = _normalise_grants(payload, "tool_grants", tool_names(), errors)
    available_skill_keys = {
        skill.key for skill in available_skills(db, 0, include_restricted=True)
        if skill.scope == SYSTEM_SCOPE
    }
    skills = _normalise_grants(payload, "skill_grants", available_skill_keys, errors)
    if tools is not None:
        for name_ in tools:
            if name_.startswith("skill_"):
                errors.append({
                    "field": "tool_grants",
                    "reason": f"{name_} 属于技能，请使用 skill_grants 管理",
                })
    if errors:
        raise PersonaValidationError(errors)
    return save_chat_default(
        db, tool_grants=tools, skill_grants=skills, actor_id=actor_id,
    )


def page_context(db: Session) -> dict:
    return {
        "personas": list_system_personas(db),
        "default_chat": get_default_chat(db),
        "tool_options": tool_options(),
        "skill_options": skill_options(db),
    }
