"""角色管理：用户私有角色的创建、保存、启停、删除，以及平台内置角色的读取。

用户角色没有草稿态：保存即生成新版本并立即生效，历史角色会话仍固定旧版本。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.agent.models import AgentConversation, AgentPersona, AgentPersonaVersion
from app.modules.agent.personas.definition import PersonaInvalid, validate_definition
from config import settings

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
NAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,48}$")
MAX_DESCRIPTION = 200


class PersonaValidationError(ValueError):
    def __init__(self, errors: list[dict], warnings: list[str] | None = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__("角色定义或基本信息不合法")


def _hash(definition: dict) -> str:
    payload = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_basic(payload: dict, db: Session, user_id: int, exclude_id: int | None = None) -> list[dict]:
    errors: list[dict] = []
    name = (payload.get("name") or "").strip()
    key = (payload.get("key") or "").strip().lower()
    description = (payload.get("description") or "").strip()

    if not 1 <= len(name) <= 48:
        errors.append({"field": "name", "reason": "角色名需为 1~48 字"})
    elif not NAME_RE.fullmatch(name):
        errors.append({"field": "name", "reason": "角色名不能包含空格或斜杠"})
    if not KEY_RE.fullmatch(key):
        errors.append({"field": "key", "reason": "角色键需为小写字母开头的 1~48 位字母数字下划线"})
    if len(description) > MAX_DESCRIPTION:
        errors.append({"field": "description", "reason": f"角色定位最多 {MAX_DESCRIPTION} 字"})

    # 平台角色保留 key/name，用户角色不得遮蔽。
    platform_rows = db.query(AgentPersona).filter(AgentPersona.scope == "system").all()
    if any(row.persona_key.lower() == key for row in platform_rows):
        errors.append({"field": "key", "reason": "角色键与平台内置角色冲突"})
    if any(row.name.lower() == name.lower() for row in platform_rows):
        errors.append({"field": "name", "reason": "角色名与平台内置角色冲突"})

    q = db.query(AgentPersona).filter(
        AgentPersona.scope == "user", AgentPersona.owner_user_id == user_id
    )
    if exclude_id:
        q = q.filter(AgentPersona.id != exclude_id)
    if q.filter(AgentPersona.persona_key == key).first():
        errors.append({"field": "key", "reason": "角色键已存在"})
    if q.filter(AgentPersona.name == name).first():
        errors.append({"field": "name", "reason": "角色名已存在"})

    if exclude_id is None:
        total = db.query(AgentPersona).filter(
            AgentPersona.scope == "user", AgentPersona.owner_user_id == user_id
        ).count()
        if total >= settings.agent_persona_max_per_user:
            errors.append({
                "field": "name",
                "reason": f"每个账号最多创建 {settings.agent_persona_max_per_user} 个角色",
            })
    return errors


def latest_version(db: Session, persona: AgentPersona) -> AgentPersonaVersion | None:
    return db.query(AgentPersonaVersion).filter(
        AgentPersonaVersion.persona_id == persona.id
    ).order_by(AgentPersonaVersion.version_no.desc()).first()


def current_version(db: Session, persona: AgentPersona) -> AgentPersonaVersion | None:
    if not persona.current_version_no:
        return None
    return db.query(AgentPersonaVersion).filter(
        AgentPersonaVersion.persona_id == persona.id,
        AgentPersonaVersion.version_no == persona.current_version_no,
    ).first()


def current_or_latest_version(db: Session, persona: AgentPersona) -> AgentPersonaVersion | None:
    return current_version(db, persona) or latest_version(db, persona)


def _own_persona(db: Session, user_id: int, persona_id: int) -> AgentPersona:
    persona = db.get(AgentPersona, persona_id)
    if persona is None:
        raise AppError(404, "角色不存在")
    if persona.scope != "user" or persona.owner_user_id != user_id:
        raise AppError(403, "平台内置角色只读，无权操作该角色")
    return persona


def create_persona(db: Session, user_id: int, payload: dict) -> AgentPersona:
    errors = _check_basic(payload, db, user_id)
    errors.extend(validate_definition(payload.get("definition"))[0])
    if errors:
        raise PersonaValidationError(errors)

    persona = AgentPersona(
        scope="user", owner_user_id=user_id,
        persona_key=payload["key"].strip().lower(), name=payload["name"].strip(),
        description=(payload.get("description") or "").strip(),
        status="active", current_version_no=1,
    )
    db.add(persona)
    db.flush()
    definition = payload["definition"]
    version = AgentPersonaVersion(
        persona_id=persona.id, version_no=1, definition=definition,
        definition_hash=_hash(definition), created_by=user_id, published_at=datetime.now(),
    )
    db.add(version)
    db.commit()
    db.refresh(persona)
    return persona


def save_persona(db: Session, user_id: int, persona_id: int, payload: dict) -> AgentPersona:
    persona = _own_persona(db, user_id, persona_id)
    errors = _check_basic(payload, db, user_id, persona.id)
    errors.extend(validate_definition(payload.get("definition"))[0])
    if errors:
        raise PersonaValidationError(errors)

    persona.name = payload["name"].strip()
    persona.persona_key = payload["key"].strip().lower()
    persona.description = (payload.get("description") or "").strip()

    definition = payload["definition"]
    latest = latest_version(db, persona)
    new_hash = _hash(definition)
    if latest is not None and latest.definition_hash == new_hash:
        db.commit()
        db.refresh(persona)
        return persona

    next_no = (latest.version_no + 1) if latest else 1
    version = AgentPersonaVersion(
        persona_id=persona.id, version_no=next_no, definition=definition,
        definition_hash=new_hash, created_by=user_id, published_at=datetime.now(),
    )
    db.add(version)
    persona.current_version_no = next_no
    db.commit()
    db.refresh(persona)
    return persona


def set_status(db: Session, user_id: int, persona_id: int, status: str) -> AgentPersona:
    if status not in ("active", "disabled"):
        raise AppError(400, "状态不合法")
    persona = _own_persona(db, user_id, persona_id)
    if status == "active" and not persona.current_version_no:
        raise AppError(400, "角色尚未发布，不能启用")
    persona.status = status
    db.commit()
    db.refresh(persona)
    return persona


def delete_persona(db: Session, user_id: int, persona_id: int) -> None:
    persona = _own_persona(db, user_id, persona_id)
    used = db.query(AgentConversation).filter(
        AgentConversation.persona_id == persona.id
    ).count()
    if used:
        raise AppError(409, f"该角色已有 {used} 个角色会话，请先删除相关会话")
    db.delete(persona)
    db.commit()


def bindable_persona(db: Session, user_id: int, persona_id: int) -> AgentPersona:
    """新建角色会话前的校验：可见、启用、有生效版本。"""
    persona = db.get(AgentPersona, persona_id)
    if persona is None:
        raise AppError(404, "角色不存在")
    if persona.scope == "user" and persona.owner_user_id != user_id:
        raise AppError(403, "无权使用该角色")
    if persona.status != "active":
        raise AppError(400, "角色已停用，不能新建角色会话")
    version = current_version(db, persona)
    if version is None or version.published_at is None:
        raise AppError(400, "角色尚未发布，不能新建角色会话")
    return persona


def list_personas(db: Session, user_id: int) -> list[tuple[AgentPersona, AgentPersonaVersion | None]]:
    rows = (
        db.query(AgentPersona)
        .filter(or_(
            AgentPersona.scope == "system",
            (AgentPersona.scope == "user") & (AgentPersona.owner_user_id == user_id),
        ))
        .order_by(AgentPersona.scope.asc(), AgentPersona.sort_order.asc(), AgentPersona.id.asc())
        .all()
    )
    return [(row, current_or_latest_version(db, row)) for row in rows]


def get_persona(db: Session, user_id: int, persona_id: int) -> tuple[AgentPersona, AgentPersonaVersion | None]:
    persona = db.get(AgentPersona, persona_id)
    if persona is None:
        raise AppError(404, "角色不存在")
    if persona.scope == "user" and persona.owner_user_id != user_id:
        raise AppError(403, "无权查看该角色")
    return persona, current_or_latest_version(db, persona)
