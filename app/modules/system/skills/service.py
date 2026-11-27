"""系统内置技能管理：平台技能（scope=system）的增删改查、版本、启停、试运行与运行记录。

边界：
- 只管理平台技能，任何接口都不会创建或改写 scope=user 的用户技能。
- 代码技能（kind=code）由 ``app/modules/agent/skills/platform.py`` 实现，
  页面只能查看定义与启停，不能编辑定义或删除；声明式技能（kind=declarative）
  可新建、编辑并被版本化，定义继续走既有 DSL 白名单校验。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agent.models import AgentPersona, AgentSkill, AgentSkillRun, AgentSkillVersion
from app.modules.agent.skills.argument import validate_args
from app.modules.agent.skills.definition import DefinitionInvalid
from app.modules.agent.skills.execution import test_skill
from app.modules.agent.skills.management import (
    ALIAS_RE,
    KEY_RE,
    NAME_RE,
    SkillValidationError,
    current_or_latest_version,
    latest_version,
    resolved_from_version,
    validate_definition_payload,
)
from app.modules.agent.skills.platform import CODE_SKILLS

SYSTEM_SCOPE = "system"
SKILL_CATEGORIES = ("body", "swim", "fitness", "dance", "profile", "custom")
SKILL_STATUSES = ("active", "disabled")
MAX_DESCRIPTION = 200


def _definition_hash(definition: dict) -> str:
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise_key(value: str | None) -> str:
    return (value or "").strip().lower()


def _system_skill(db: Session, skill_id: int) -> AgentSkill:
    skill = db.get(AgentSkill, skill_id)
    if skill is None or skill.scope != SYSTEM_SCOPE:
        raise AppError(404, "内置技能不存在")
    return skill


def _validate_payload(
    db: Session,
    payload: dict,
    *,
    key: str,
    existing: AgentSkill | None = None,
) -> tuple[str, dict[str, Any]]:
    """校验基本信息与声明式定义；返回 (kind, definition)。

    平台技能键/名称/别名按全局唯一处理，避免与用户技能互相遮蔽；
    声明式定义仍由 ``agent.skills.definition`` 的白名单校验器负责。
    """
    creating = existing is None
    errors: list[dict] = []
    name = (payload.get("name") or "").strip()
    alias = (payload.get("slash_alias") or "").strip() or None
    description = (payload.get("description") or "").strip()
    category = (payload.get("category") or "custom").strip()
    status = payload.get("status") or "active"
    kind = payload.get("kind") or ("declarative" if creating else existing.kind)
    definition = payload.get("definition")

    if not 1 <= len(name) <= 48:
        errors.append({"field": "name", "reason": "技能名需为 1~48 字"})
    elif not NAME_RE.fullmatch(name):
        errors.append({"field": "name", "reason": "技能名不能包含空格或斜杠"})
    if not KEY_RE.fullmatch(key):
        errors.append({"field": "key", "reason": "技能键需为小写字母开头的 1~48 位字母数字下划线"})
    if alias and not ALIAS_RE.fullmatch(alias):
        errors.append({"field": "slash_alias", "reason": "斜杠别名需为 1~24 位文字、字母、数字、下划线或短横线"})
    if len(description) > MAX_DESCRIPTION:
        errors.append({"field": "description", "reason": f"能力描述最多 {MAX_DESCRIPTION} 字"})
    if category not in SKILL_CATEGORIES:
        errors.append({"field": "category", "reason": "分类不合法"})
    if status not in SKILL_STATUSES:
        errors.append({"field": "status", "reason": "状态只能是 active 或 disabled"})
    if creating and kind != "declarative":
        errors.append({"field": "kind", "reason": "代码技能只能由代码注册，页面仅可新建声明式技能"})
    if existing is not None and kind != existing.kind:
        errors.append({"field": "kind", "reason": "技能类型创建后不可修改"})

    q = db.query(AgentSkill)
    if existing is not None:
        q = q.filter(AgentSkill.id != existing.id)
    rows = q.all()
    code_names = {code.name.strip().lower() for code in CODE_SKILLS.values()}
    if creating and key in CODE_SKILLS:
        errors.append({"field": "key", "reason": "技能键已被平台代码技能占用"})
    if any(row.skill_key == key for row in rows):
        errors.append({"field": "key", "reason": "技能键已被其他技能占用"})
    if any(row.name.strip().lower() == name.strip().lower() for row in rows):
        errors.append({"field": "name", "reason": "技能名已被其他技能占用"})
    elif creating and name.strip().lower() in code_names:
        errors.append({"field": "name", "reason": "技能名已被平台代码技能占用"})
    elif any(row.skill_key == name.strip().lower() for row in rows):
        errors.append({"field": "name", "reason": "技能名与其他技能的技能键冲突"})
    if alias:
        if any((row.slash_alias or "").strip().lower() == alias.lower() for row in rows):
            errors.append({"field": "slash_alias", "reason": "斜杠别名已被其他技能占用"})
        elif creating and (alias.lower() in CODE_SKILLS or alias.lower() in code_names):
            errors.append({"field": "slash_alias", "reason": "斜杠别名已被平台代码技能占用"})
        elif any(
            row.skill_key == alias.lower() or row.name.strip().lower() == alias.lower()
            for row in rows
        ):
            errors.append({"field": "slash_alias", "reason": "斜杠别名与其他技能的名称或技能键冲突"})

    if kind == "declarative":
        definition_errors, _ = validate_definition_payload("declarative", definition)
        errors.extend(definition_errors)
    if errors:
        raise SkillValidationError(errors)
    return kind, definition


def skill_dict(db: Session, skill: AgentSkill) -> dict:
    version = current_or_latest_version(db, skill)
    definition = version.definition if version else None
    if skill.kind == "code":
        definition = {"kind": "code", "code_key": skill.skill_key}
    run_count = db.query(AgentSkillRun).filter(AgentSkillRun.skill_id == skill.id).count()
    return {
        "id": skill.id,
        "scope": skill.scope,
        "key": skill.skill_key,
        "tool_name": f"skill_{skill.skill_key}",
        "name": skill.name,
        "slash_alias": skill.slash_alias,
        "description": skill.description or "",
        "category": skill.category,
        "kind": skill.kind,
        "status": skill.status,
        "current_version_no": skill.current_version_no,
        "version_no": version.version_no if version else None,
        "published": bool(version and version.published_at),
        "definition": definition,
        "run_count": run_count,
        "can_edit": skill.kind == "declarative",
        "can_delete": skill.kind == "declarative",
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def list_system_skills(db: Session) -> list[dict]:
    rows = (
        db.query(AgentSkill)
        .filter(AgentSkill.scope == SYSTEM_SCOPE)
        .order_by(AgentSkill.kind.asc(), AgentSkill.name.asc(), AgentSkill.id.asc())
        .all()
    )
    return [skill_dict(db, row) for row in rows]


def get_system_skill(db: Session, skill_id: int) -> dict:
    return skill_dict(db, _system_skill(db, skill_id))


def create_system_skill(db: Session, payload: dict, actor_id: int | None) -> dict:
    key = _normalise_key(payload.get("key"))
    kind, definition = _validate_payload(db, payload, key=key)
    skill = AgentSkill(
        scope=SYSTEM_SCOPE,
        owner_user_id=None,
        skill_key=key,
        name=payload["name"].strip(),
        description=(payload.get("description") or "").strip(),
        kind=kind,
        category=(payload.get("category") or "custom").strip(),
        status=payload.get("status") or "active",
        slash_alias=(payload.get("slash_alias") or "").strip() or None,
        current_version_no=1,
    )
    db.add(skill)
    db.flush()
    db.add(AgentSkillVersion(
        skill_id=skill.id,
        version_no=1,
        definition=definition,
        definition_hash=_definition_hash(definition),
        created_by=actor_id,
        published_at=datetime.now(),
    ))
    db.commit()
    db.refresh(skill)
    return skill_dict(db, skill)


def save_system_skill(db: Session, skill_id: int, payload: dict, actor_id: int | None) -> dict:
    skill = _system_skill(db, skill_id)
    if skill.kind == "code":
        raise AppError(400, "代码技能由代码实现，页面只能启停，不能编辑或删除")
    requested_key = payload.get("key")
    if requested_key is not None and _normalise_key(requested_key) != skill.skill_key:
        raise SkillValidationError([{
            "field": "key", "reason": "技能键创建后不可修改；需要新键请新建技能",
        }])
    _, definition = _validate_payload(db, payload, key=skill.skill_key, existing=skill)
    skill.name = payload["name"].strip()
    skill.description = (payload.get("description") or "").strip()
    skill.category = (payload.get("category") or "custom").strip()
    skill.status = payload.get("status") or skill.status
    skill.slash_alias = (payload.get("slash_alias") or "").strip() or None

    latest = latest_version(db, skill)
    new_hash = _definition_hash(definition)
    if latest is None or latest.definition_hash != new_hash:
        next_no = (latest.version_no + 1) if latest else 1
        db.add(AgentSkillVersion(
            skill_id=skill.id,
            version_no=next_no,
            definition=definition,
            definition_hash=new_hash,
            created_by=actor_id,
            published_at=datetime.now(),
        ))
        skill.current_version_no = next_no
    db.commit()
    db.refresh(skill)
    return skill_dict(db, skill)


def set_system_skill_status(db: Session, skill_id: int, status: str) -> dict:
    if status not in SKILL_STATUSES:
        raise AppError(400, "状态不合法")
    skill = _system_skill(db, skill_id)
    if status == "active" and not skill.current_version_no:
        raise AppError(400, "技能尚未发布，不能启用")
    skill.status = status
    db.commit()
    db.refresh(skill)
    return skill_dict(db, skill)


def delete_system_skill(db: Session, skill_id: int) -> None:
    skill = _system_skill(db, skill_id)
    if skill.kind == "code":
        raise AppError(400, "代码技能由代码实现，不能删除；可改为停用")
    referenced = [
        row.name for row in db.query(AgentPersona).all()
        if row.skill_grants and skill.skill_key in row.skill_grants
    ]
    if referenced:
        names = "、".join(referenced[:3]) + ("等" if len(referenced) > 3 else "")
        raise AppError(409, f"该内置技能已被角色「{names}」的可用技能白名单引用，请先取消勾选")
    db.delete(skill)
    db.commit()


def validate_definition(definition: dict) -> dict:
    errors, warnings = validate_definition_payload("declarative", definition)
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def test_system_skill(db: Session, user_id: int, skill_id: int, args: dict) -> dict:
    skill = _system_skill(db, skill_id)
    version = current_or_latest_version(db, skill)
    if version is None:
        raise AppError(400, "技能没有可用定义")
    resolved = resolved_from_version(skill, version)
    try:
        normalized, errors, warnings, missing = validate_args(resolved, args or {}, date.today())
    except DefinitionInvalid:
        raise AppError(400, "技能定义无法执行，请检查定义与参数")
    if errors or missing:
        return {
            "ok": False, "status": "invalid_args",
            "errors": errors, "missing": missing, "warnings": warnings,
        }
    result = test_skill(db, user_id, resolved, normalized)
    db.commit()
    return result


def list_platform_runs(db: Session, skill_id: int, limit: int = 20) -> list[AgentSkillRun]:
    """平台技能的运行记录：管理员视角读取全部用户的运行审计，不返回用户身份。"""
    _system_skill(db, skill_id)
    return (
        db.query(AgentSkillRun)
        .filter(AgentSkillRun.skill_id == skill_id)
        .order_by(AgentSkillRun.created_at.desc(), AgentSkillRun.id.desc())
        .limit(min(max(limit, 1), 100))
        .all()
    )


def page_context(db: Session) -> dict:
    return {"skills": list_system_skills(db)}
