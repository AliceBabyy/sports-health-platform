"""AI Agent API 路由（/api/agent 系列）：会话 CRUD、消息流式 SSE、技能管理、角色管理。"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.agent import schemas, service
from app.modules.agent.models import AgentSkill
from app.modules.agent.personas.management import (
    PersonaValidationError,
    create_persona,
    delete_persona,
    get_persona,
    list_personas,
    save_persona,
    set_status as set_persona_status,
)
from app.modules.agent.skills.argument import validate_args
from app.modules.agent.skills.execution import test_skill
from app.modules.agent.skills.management import (
    SkillValidationError,
    create_skill,
    current_or_latest_version,
    delete_skill,
    latest_version,
    list_runs,
    list_skills,
    publish_skill,
    resolved_from_version,
    save_skill,
    set_status,
    validate_definition_payload,
)
from app.modules.auth.models import User
from database import get_db

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _runtime(request: Request) -> dict:
    return request.app.state.agent_runtime


@router.get("/conversations")
def list_conversations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"list": service.list_conversations(db, user.id)}


@router.post("/conversations")
def create_conversation(
    payload: schemas.ConversationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.create_conversation(db, user.id, payload.model_name, payload.persona_id)


@router.put("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    payload: schemas.ConversationRenameIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.rename_conversation(db, user.id, conversation_id, payload.title)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await service.delete_conversation(db, user.id, conversation_id, _runtime(request))
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.get_messages(db, user.id, conversation_id, _runtime(request))


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    payload: schemas.MessageIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 前置校验与 slot 预占在响应头发送前完成：400/404/409 由全局处理器返回 JSON。
    row, thread_id = await service.acquire_reply_slot(db, user.id, conversation_id, payload)
    return StreamingResponse(
        service.stream_reply(db, row, thread_id, _runtime(request), payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/conversations/{conversation_id}/messages/regenerate")
async def regenerate_message(
    conversation_id: int,
    payload: schemas.RegenerateIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 回滚最近一轮（移除上一条用户消息及其后的工具/AI 消息）后，用同一原文重新生成并覆盖。
    row, thread_id, human_content = await service.prepare_regenerate(
        db, user.id, conversation_id, _runtime(request), payload
    )
    return StreamingResponse(
        service.stream_reply(db, row, thread_id, _runtime(request), payload, human_content, replay=True),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------- 技能管理 ----------

def _skill_dict(row: AgentSkill, version, user_id: int) -> dict:
    can_delete = row.scope == "user" and row.owner_user_id == user_id
    can_edit = can_delete and row.kind == "prompt"
    definition = None
    if version is not None:
        definition = version.definition if row.kind in ("declarative", "prompt") \
            else {"kind": "code", "code_key": row.skill_key}
    return {
        "id": row.id,
        "scope": row.scope,
        "key": row.skill_key,
        "name": row.name,
        "slash_alias": row.slash_alias,
        "description": row.description,
        "kind": row.kind,
        "category": row.category,
        "status": row.status,
        "current_version_no": row.current_version_no,
        "version_no": version.version_no if version else None,
        "published": bool(version and version.published_at),
        "can_edit": can_edit,
        "can_delete": can_delete,
        "definition": definition,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validation_response(exc: SkillValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "SKILL_DEFINITION_INVALID", "error": "技能定义或基本信息不合法",
                 "errors": exc.errors, "warnings": exc.warnings},
    )


@router.get("/skills")
def list_skills_api(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"list": [_skill_dict(row, version, user.id) for row, version in list_skills(db, user.id)]}


@router.get("/skills/runs")
def all_skill_runs_api(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    runs = list_runs(db, user.id, None, limit)
    return {"list": [{
        "id": r.id, "skill_id": r.skill_id, "trigger": r.trigger, "status": r.status,
        "args": r.args, "parse": r.parse, "sample_size": r.sample_size,
        "duration_ms": r.duration_ms, "error_code": r.error_code,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]}


@router.post("/skills/validate")
def validate_new_skill_api(
    payload: schemas.SkillValidateIn,
    _: User = Depends(get_current_user),
):
    errors, warnings = validate_definition_payload(payload.kind or "prompt", payload.definition or {})
    return {"ok": not errors, "errors": errors, "warnings": warnings}


@router.get("/skills/{skill_id}")
def get_skill_api(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise AppError(404, "技能不存在")
    if row.scope == "user" and row.owner_user_id != user.id:
        raise AppError(403, "无权查看该技能")
    version = current_or_latest_version(db, row)
    return _skill_dict(row, version, user.id)


@router.post("/skills")
def create_skill_api(
    payload: schemas.SkillIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = create_skill(db, user.id, payload.model_dump())
    except SkillValidationError as exc:
        return _validation_response(exc)
    return _skill_dict(row, current_or_latest_version(db, row), user.id)


@router.put("/skills/{skill_id}")
def update_skill_api(
    skill_id: int,
    payload: schemas.SkillIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = save_skill(db, user.id, skill_id, payload.model_dump())
    except SkillValidationError as exc:
        return _validation_response(exc)
    return _skill_dict(row, current_or_latest_version(db, row), user.id)


@router.post("/skills/{skill_id}/validate")
def validate_skill_api(
    skill_id: int,
    payload: schemas.SkillValidateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise AppError(404, "技能不存在")
    if row.scope == "user" and row.owner_user_id != user.id:
        raise AppError(403, "无权查看该技能")
    definition = payload.definition
    if row.kind == "code":
        return {"ok": True, "errors": [], "warnings": ["平台代码技能不可修改定义"]}
    if definition is None:
        version = current_or_latest_version(db, row)
        definition = version.definition if version else {}
    errors, warnings = validate_definition_payload(row.kind, definition)
    return {"ok": not errors, "errors": errors, "warnings": warnings}


@router.post("/skills/{skill_id}/publish")
def publish_skill_api(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = publish_skill(db, user.id, skill_id)
    except SkillValidationError as exc:
        return _validation_response(exc)
    return _skill_dict(row, current_or_latest_version(db, row), user.id)


@router.post("/skills/{skill_id}/status")
def set_skill_status_api(
    skill_id: int,
    payload: schemas.SkillStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = set_status(db, user.id, skill_id, payload.status)
    return _skill_dict(row, current_or_latest_version(db, row), user.id)


@router.delete("/skills/{skill_id}")
def delete_skill_api(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    delete_skill(db, user.id, skill_id)
    return {"ok": True}


@router.post("/skills/{skill_id}/test")
def test_skill_api(
    skill_id: int,
    payload: schemas.SkillTestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise AppError(404, "技能不存在")
    if row.scope == "user" and row.owner_user_id != user.id:
        raise AppError(403, "无权试运行该技能")
    version = latest_version(db, row) if row.scope == "user" else current_or_latest_version(db, row)
    if version is None:
        raise AppError(400, "技能没有可用定义")
    skill = resolved_from_version(row, version)
    args, errors, warnings, missing = validate_args(skill, payload.args, date.today())
    if errors or missing:
        return {"ok": False, "status": "invalid_args", "errors": errors,
                "missing": missing, "warnings": warnings}
    result = test_skill(db, user.id, skill, args)
    db.commit()
    return result


@router.get("/skills/{skill_id}/runs")
def skill_runs_api(
    skill_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.get(AgentSkill, skill_id)
    if row is None:
        raise AppError(404, "技能不存在")
    if row.scope == "user" and row.owner_user_id != user.id:
        raise AppError(403, "无权查看该技能")
    runs = list_runs(db, user.id, skill_id, limit)
    return {"list": [{
        "id": r.id, "trigger": r.trigger, "status": r.status,
        "args": r.args, "parse": r.parse, "sample_size": r.sample_size,
        "duration_ms": r.duration_ms, "error_code": r.error_code,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]}


# ---------- 角色管理 ----------

def _persona_dict(row, version, user_id: int) -> dict:
    can_edit = row.scope == "user" and row.owner_user_id == user_id
    return {
        "id": row.id,
        "scope": row.scope,
        "key": row.persona_key,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "sort_order": row.sort_order,
        "current_version_no": row.current_version_no,
        "version_no": version.version_no if version else None,
        "published": bool(version and version.published_at),
        "can_edit": can_edit,
        "can_delete": can_edit,
        "definition": version.definition if version else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _persona_validation_response(exc: PersonaValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "PERSONA_INVALID", "error": "角色定义或基本信息不合法",
                 "errors": exc.errors, "warnings": exc.warnings},
    )


@router.get("/personas")
def list_personas_api(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"list": [_persona_dict(row, version, user.id) for row, version in list_personas(db, user.id)]}


@router.get("/personas/{persona_id}")
def get_persona_api(
    persona_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row, version = get_persona(db, user.id, persona_id)
    return _persona_dict(row, version, user.id)


@router.post("/personas")
def create_persona_api(
    payload: schemas.PersonaIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = create_persona(db, user.id, payload.model_dump())
    except PersonaValidationError as exc:
        return _persona_validation_response(exc)
    return _persona_dict(row, get_persona(db, user.id, row.id)[1], user.id)


@router.put("/personas/{persona_id}")
def update_persona_api(
    persona_id: int,
    payload: schemas.PersonaIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        row = save_persona(db, user.id, persona_id, payload.model_dump())
    except PersonaValidationError as exc:
        return _persona_validation_response(exc)
    return _persona_dict(row, get_persona(db, user.id, row.id)[1], user.id)


@router.post("/personas/{persona_id}/status")
def set_persona_status_api(
    persona_id: int,
    payload: schemas.PersonaStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = set_persona_status(db, user.id, persona_id, payload.status)
    return _persona_dict(row, get_persona(db, user.id, row.id)[1], user.id)


@router.delete("/personas/{persona_id}")
def delete_persona_api(
    persona_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    delete_persona(db, user.id, persona_id)
    return {"ok": True}
