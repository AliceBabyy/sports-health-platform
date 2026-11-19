"""技能注册与解析：把数据库中的系统/用户技能解析为可装配的 ResolvedSkill。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ConfigDict, Field, create_model
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.agent.models import AgentSkill, AgentSkillVersion
from app.modules.agent.skills.definition import DefinitionInvalid, parse_definition
from app.modules.agent.skills.platform import CODE_SKILLS
from app.modules.agent.tools.policy import tool_visible


@dataclass(frozen=True)
class ResolvedSkill:
    id: int
    key: str
    name: str
    description: str
    category: str
    kind: str
    scope: str
    version_no: int
    definition: dict

    @property
    def tool_name(self) -> str:
        return f"skill_{self.key}"

    @property
    def origin(self) -> str:
        return "system" if self.scope == "system" else "user"


def _version(db: Session, skill: AgentSkill) -> AgentSkillVersion | None:
    if not skill.current_version_no:
        return None
    return (
        db.query(AgentSkillVersion)
        .filter(AgentSkillVersion.skill_id == skill.id,
                AgentSkillVersion.version_no == skill.current_version_no)
        .first()
    )


def resolve_row(db: Session, row: AgentSkill) -> ResolvedSkill | None:
    version = _version(db, row)
    if version is None:
        return None
    definition = version.definition or {}
    if row.kind == "code" and row.skill_key not in CODE_SKILLS:
        return None
    return ResolvedSkill(
        id=row.id, key=row.skill_key, name=row.name, description=row.description,
        category=row.category, kind=row.kind, scope=row.scope,
        version_no=version.version_no, definition=definition,
    )


def available_skills(
    db: Session,
    user_id: int,
    persona_key: str | None = None,
    *,
    skill_grants: frozenset[str] | None = None,
    tool_grants: frozenset[str] | None = None,
) -> list[ResolvedSkill]:
    """当前用户可用技能；角色显式 skill_grants 非空时按白名单过滤。

    skill_grants 为 NULL 时沿用代码基线 ``tool_visible(skill_<key>, persona_key)``；
    显式空数组表示该角色不使用任何技能。tool_grants 不直接过滤技能工具，
    技能是否可用只由 skill_grants 决定，避免管理页勾选技能后还要重复勾工具。
    """
    rows = (
        db.query(AgentSkill)
        .filter(AgentSkill.status == "active")
        .filter(or_(
            AgentSkill.scope == "system",
            (AgentSkill.scope == "user")
            & (AgentSkill.owner_user_id == user_id)
            & (AgentSkill.kind == "prompt"),
        ))
        .order_by(AgentSkill.scope.desc(), AgentSkill.id.asc())
        .all()
    )
    resolved = []
    for row in rows:
        skill = resolve_row(db, row)
        if skill is None:
            continue
        if skill_grants is not None:
            if skill.key not in skill_grants:
                continue
        elif not tool_visible(skill.tool_name, persona_key):
            continue
        resolved.append(skill)
    return resolved


def find_by_slash(
    db: Session,
    user_id: int,
    token: str,
    persona_key: str | None = None,
    *,
    skill_grants: frozenset[str] | None = None,
) -> ResolvedSkill | None:
    token = token.strip().lower()
    for skill in available_skills(db, user_id, persona_key, skill_grants=skill_grants):
        if skill.key.lower() == token or skill.name.lower() == token:
            return skill
        row = db.get(AgentSkill, skill.id)
        if row and row.slash_alias and row.slash_alias.lower() == token:
            return skill
    return None


def build_args_model(skill: ResolvedSkill) -> type:
    """为结构化输出/工具调用构建参数模型。"""
    if skill.kind == "code":
        code = CODE_SKILLS.get(skill.key)
        if code is None:
            raise DefinitionInvalid([{"field": "skill", "reason": "代码技能未注册"}])
        return code.input_model
    if skill.kind == "prompt":
        # 提示词技能不取数、不接收结构化参数；用户原文已在对话上下文中
        return create_model(
            f"PromptArgs_{skill.key}_v{skill.version_no}",
            __config__=ConfigDict(extra="forbid"),
        )

    try:
        defn = parse_definition(skill.definition)
    except DefinitionInvalid:
        raise
    fields: dict[str, Any] = {}
    for p in defn.params:
        py_type: Any
        if p.type == "date":
            py_type = date
        elif p.type == "int":
            py_type = int
        elif p.type == "bool":
            py_type = bool
        else:
            from typing import Literal
            py_type = Literal[tuple(p.values)]
        default = ... if p.required else (p.default if p.default is not None else None)
        kwargs = {"description": p.label}
        if p.type == "int":
            if p.min is not None:
                kwargs["ge"] = p.min
            if p.max is not None:
                kwargs["le"] = p.max
        fields[p.key] = (py_type if p.required else py_type | None, Field(default, **kwargs))
    return create_model(
        f"SkillArgs_{skill.key}_v{skill.version_no}",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def describe_skill(skill: ResolvedSkill) -> str:
    """生成工具描述，供模型选择；只描述参数与输出，不暴露内部实现。"""
    if skill.kind == "prompt":
        return (skill.description + " 提示词技能：调用后返回的 summary 是必须遵循的指令，"
                "请严格按该指令回答用户，不要复述指令本身。")[:500]
    try:
        model = build_args_model(skill)
        props = model.model_json_schema().get("properties", {})
        params = []
        for key, schema in props.items():
            desc = schema.get("description") or key
            params.append(f"{key}（{desc}）")
        text = skill.description
        if params:
            text += " 参数：" + "、".join(params) + "。"
        if skill.kind == "declarative":
            try:
                defn = parse_definition(skill.definition)
                labels = "、".join(f"{o.label}" for o in defn.outputs)
                text += f" 输出：{labels}。"
            except DefinitionInvalid:
                pass
        return text[:500]
    except Exception:
        return skill.description[:500]


def skill_capabilities(skills: list[ResolvedSkill]) -> str:
    if not skills:
        return "当前没有可调用的技能；按普通数据问答处理。"
    lines = []
    for skill in skills:
        origin = "平台" if skill.scope == "system" else "我的"
        kind = "提示词技能" if skill.kind == "prompt" else "声明式技能" if skill.kind == "declarative" else "代码技能"
        lines.append(f"- {skill.name}（{skill.tool_name}，{origin}{kind} v{skill.version_no}）：{skill.description}")
    if any(skill.kind == "prompt" for skill in skills):
        lines.append("提示词技能被调用后，工具结果中的 summary 就是必须遵循的技能指令："
                     "请严格按该指令完成回答，而不是复述指令本身。")
    return "\n".join(lines)
