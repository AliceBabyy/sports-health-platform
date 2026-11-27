"""用户技能管理：创建、保存草稿、校验、发布、停用、删除与运行记录。"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agent.models import AgentSkill, AgentSkillRun, AgentSkillVersion, USER_SKILL_KINDS
from app.modules.agent.skills.definition import DefinitionInvalid, parse_any_definition
from app.modules.agent.skills.registry import ResolvedSkill

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
NAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,48}$")
ALIAS_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,24}$")


class SkillValidationError(ValueError):
    def __init__(self, errors: list[dict], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("技能校验未通过")


def _hash(definition: dict) -> str:
    import json
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_definition_payload(kind: str, definition: Any) -> tuple[list[dict], list[str]]:
    try:
        parse_any_definition(kind, definition)
        return [], []
    except DefinitionInvalid as exc:
        return exc.errors, []


def _check_basic(payload: dict, db: Session, user_id: int, exclude_id: int | None = None) -> list[dict]:
    errors = []
    name = (payload.get("name") or "").strip()
    key = (payload.get("key") or "").strip().lower()
    alias = (payload.get("slash_alias") or "").strip() or None
    description = (payload.get("description") or "").strip()
    category = (payload.get("category") or "custom").strip()
    kind = (payload.get("kind") or "prompt").strip()
    if not 1 <= len(name) <= 48:
        errors.append({"field": "name", "reason": "技能名需为 1~48 字"})
    elif not NAME_RE.fullmatch(name):
        errors.append({"field": "name", "reason": "技能名不能包含空格或斜杠"})
    if not KEY_RE.fullmatch(key):
        errors.append({"field": "key", "reason": "技能键需为小写字母开头的 1~48 位字母数字下划线"})
    if alias and not ALIAS_RE.fullmatch(alias):
        errors.append({"field": "slash_alias", "reason": "斜杠别名需为 1~24 位文字、字母、数字、下划线或短横线"})
    if len(description) > 200:
        errors.append({"field": "description", "reason": "描述最多 200 字"})
    if category not in ("body", "swim", "fitness", "dance", "profile", "custom"):
        errors.append({"field": "category", "reason": "分类不合法"})
    if kind not in USER_SKILL_KINDS:
        errors.append({"field": "kind", "reason": "用户技能只支持提示词类型"})

    # 平台技能保留 key/name/alias，用户技能不得遮蔽平台技能。
    platform_rows = db.query(AgentSkill).filter(AgentSkill.scope == "system").all()
    if any(row.skill_key.lower() == key for row in platform_rows):
        errors.append({"field": "key", "reason": "技能键与平台技能冲突"})
    if any(row.name.lower() == name.lower() for row in platform_rows):
        errors.append({"field": "name", "reason": "技能名与平台技能冲突"})
    if alias and any(
        (row.slash_alias or "").lower() == alias.lower() or row.name.lower() == alias.lower()
        for row in platform_rows
    ):
        errors.append({"field": "slash_alias", "reason": "斜杠别名与平台技能冲突"})

    q = db.query(AgentSkill).filter(AgentSkill.scope == "user", AgentSkill.owner_user_id == user_id)
    if exclude_id:
        q = q.filter(AgentSkill.id != exclude_id)
    if q.filter(AgentSkill.skill_key == key).first():
        errors.append({"field": "key", "reason": "技能键已存在"})
    if q.filter(AgentSkill.name == name).first():
        errors.append({"field": "name", "reason": "技能名已存在"})
    if alias:
        q2 = db.query(AgentSkill).filter(AgentSkill.scope == "user", AgentSkill.owner_user_id == user_id)
        if exclude_id:
            q2 = q2.filter(AgentSkill.id != exclude_id)
        if q2.filter(AgentSkill.slash_alias == alias).first():
            errors.append({"field": "slash_alias", "reason": "斜杠别名已存在"})
    return errors


def create_skill(db: Session, user_id: int, payload: dict) -> AgentSkill:
    kind = (payload.get("kind") or "prompt").strip()
    errors = _check_basic(payload, db, user_id)
    definition = payload.get("definition")
    def_errors, _ = validate_definition_payload(kind, definition)
    errors.extend(def_errors)
    if errors:
        raise SkillValidationError(errors)

    skill = AgentSkill(
        scope="user", owner_user_id=user_id,
        skill_key=payload["key"].strip().lower(), name=payload["name"].strip(),
        description=(payload.get("description") or "").strip(),
        category=(payload.get("category") or "custom").strip(),
        kind=kind, status="draft",
        slash_alias=(payload.get("slash_alias") or "").strip() or None,
        current_version_no=None,
    )
    db.add(skill)
    db.flush()
    version = AgentSkillVersion(
        skill_id=skill.id, version_no=1, definition=definition,
        definition_hash=_hash(definition), created_by=user_id,
    )
    db.add(version)
    db.commit()
    db.refresh(skill)
    return skill


def save_skill(db: Session, user_id: int, skill_id: int, payload: dict) -> AgentSkill:
    skill = _own_skill(db, user_id, skill_id)
    kind = (payload.get("kind") or skill.kind or "prompt").strip()
    if kind != skill.kind and skill.status != "draft":
        raise SkillValidationError([{"field": "kind", "reason": "技能类型只能在草稿状态修改"}])
    errors = _check_basic(payload, db, user_id, skill.id)
    definition = payload.get("definition")
    def_errors, _ = validate_definition_payload(kind, definition)
    errors.extend(def_errors)
    if errors:
        raise SkillValidationError(errors)

    skill.name = payload["name"].strip()
    skill.skill_key = payload["key"].strip().lower()
    skill.description = (payload.get("description") or "").strip()
    skill.category = (payload.get("category") or "custom").strip()
    skill.slash_alias = (payload.get("slash_alias") or "").strip() or None
    skill.kind = kind
    latest = db.query(AgentSkillVersion).filter(AgentSkillVersion.skill_id == skill.id).order_by(
        AgentSkillVersion.version_no.desc()).first()
    new_hash = _hash(definition)
    if latest is not None and latest.definition_hash == new_hash:
        # 定义未变时只更新元信息，避免每次“保存/发布”都无意义地递增版本。
        db.commit()
        db.refresh(skill)
        return skill
    next_no = (latest.version_no + 1) if latest else 1
    version = AgentSkillVersion(
        skill_id=skill.id, version_no=next_no, definition=definition,
        definition_hash=new_hash, created_by=user_id,
    )
    db.add(version)
    db.commit()
    db.refresh(skill)
    return skill


def publish_skill(db: Session, user_id: int, skill_id: int) -> AgentSkill:
    skill = _own_skill(db, user_id, skill_id)
    if skill.kind not in USER_SKILL_KINDS:
        raise SkillValidationError([{"field": "kind", "reason": "用户技能只支持提示词类型"}])
    latest = db.query(AgentSkillVersion).filter(AgentSkillVersion.skill_id == skill.id).order_by(
        AgentSkillVersion.version_no.desc()).first()
    if latest is None:
        raise AppError(400, "没有可发布的定义")
    try:
        parse_any_definition(skill.kind, latest.definition)
    except DefinitionInvalid as exc:
        raise SkillValidationError(exc.errors)
    latest.published_at = datetime.now()
    skill.current_version_no = latest.version_no
    skill.status = "active"
    db.commit()
    db.refresh(skill)
    return skill


def set_status(db: Session, user_id: int, skill_id: int, status: str) -> AgentSkill:
    if status not in ("disabled", "active", "archived"):
        raise AppError(400, "状态不合法")
    skill = _own_skill(db, user_id, skill_id)
    if status == "active" and skill.kind not in USER_SKILL_KINDS:
        raise AppError(400, "用户技能只支持提示词类型")
    if status == "active" and not skill.current_version_no:
        raise AppError(400, "技能尚未发布，不能启用")
    skill.status = status
    db.commit()
    db.refresh(skill)
    return skill


def delete_skill(db: Session, user_id: int, skill_id: int) -> None:
    skill = _own_skill(db, user_id, skill_id)
    db.delete(skill)
    db.commit()


def _own_skill(db: Session, user_id: int, skill_id: int) -> AgentSkill:
    skill = db.get(AgentSkill, skill_id)
    if skill is None:
        raise AppError(404, "技能不存在")
    if skill.scope != "user" or skill.owner_user_id != user_id:
        raise AppError(403, "无权操作该技能")
    return skill


def latest_version(db: Session, skill: AgentSkill) -> AgentSkillVersion | None:
    return db.query(AgentSkillVersion).filter(AgentSkillVersion.skill_id == skill.id).order_by(
        AgentSkillVersion.version_no.desc()).first()


def current_or_latest_version(db: Session, skill: AgentSkill) -> AgentSkillVersion | None:
    if skill.current_version_no:
        version = db.query(AgentSkillVersion).filter(
            AgentSkillVersion.skill_id == skill.id,
            AgentSkillVersion.version_no == skill.current_version_no).first()
        if version:
            return version
    return latest_version(db, skill)


def resolved_from_version(skill: AgentSkill, version: AgentSkillVersion) -> ResolvedSkill:
    return ResolvedSkill(
        id=skill.id, key=skill.skill_key, name=skill.name, description=skill.description,
        category=skill.category, kind=skill.kind, scope=skill.scope,
        version_no=version.version_no, definition=version.definition,
    )


def list_skills(db: Session, user_id: int) -> list[tuple[AgentSkill, AgentSkillVersion | None]]:
    rows = (
        db.query(AgentSkill)
        .filter(or_(AgentSkill.scope == "system",
                    (AgentSkill.scope == "user") & (AgentSkill.owner_user_id == user_id)))
        .order_by(AgentSkill.scope.asc(), AgentSkill.id.asc())
        .all()
    )
    return [(row, latest_version(db, row) if row.scope == "user" else current_or_latest_version(db, row))
            for row in rows]


def list_runs(db: Session, user_id: int, skill_id: int | None = None, limit: int = 20) -> list[AgentSkillRun]:
    q = db.query(AgentSkillRun).filter(AgentSkillRun.user_id == user_id)
    if skill_id:
        q = q.filter(AgentSkillRun.skill_id == skill_id)
    return q.order_by(AgentSkillRun.created_at.desc(), AgentSkillRun.id.desc()).limit(min(limit, 100)).all()
