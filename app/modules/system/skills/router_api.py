"""系统内置技能 API（相对前缀 /system-skills，由 system 模块挂载为 /api/system/system-skills）。

全部接口落在 /api/system 下，自动受 AdminGateMiddleware 管理员门禁保护，不再单独写鉴权依赖。
"""
import logging

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.modules.agent.runtime import refresh_system_graph
from app.modules.agent.skills.management import SkillValidationError
from app.modules.auth.models import User
from app.modules.system.skills import service
from app.modules.system.skills.schemas import (
    SystemSkillCreateIn,
    SystemSkillStatusIn,
    SystemSkillTestIn,
    SystemSkillUpdateIn,
    SystemSkillValidateIn,
)
from database import get_db

router = APIRouter(prefix="/system-skills", tags=["system-skills"])
logger = logging.getLogger("system_skills")


def _validation_response(exc: SkillValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "code": "SYSTEM_SKILL_INVALID",
            "error": "内置技能定义或配置不合法",
            "errors": exc.errors,
            "warnings": exc.warnings,
        },
    )


def _refresh_runtime(request: Request) -> None:
    """平台技能写入后重建常驻系统图并清空按用户图缓存，让变更立即生效。"""
    runtime = getattr(request.app.state, "agent_runtime", None)
    if not runtime:
        return
    try:
        refresh_system_graph(runtime)
    except Exception:  # 图重建失败不影响已落库的管理操作，下次重启仍会加载最新技能
        logger.exception("刷新 Agent 系统技能图失败")


def _run_dict(run) -> dict:
    return {
        "id": run.id,
        "version_no": run.version_no,
        "trigger": run.trigger,
        "status": run.status,
        "args": run.args,
        "parse": run.parse,
        "sample_size": run.sample_size,
        "duration_ms": run.duration_ms,
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("")
def list_system_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"list": service.list_system_skills(db)}


@router.post("/validate")
def validate_system_skill(
    payload: SystemSkillValidateIn = Body(...),
    user: User = Depends(get_current_user),
):
    return service.validate_definition(payload.definition)


@router.post("", status_code=201)
def create_system_skill(
    request: Request,
    payload: SystemSkillCreateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        created = service.create_system_skill(db, payload.model_dump(), user.id)
    except SkillValidationError as exc:
        return _validation_response(exc)
    _refresh_runtime(request)
    return created


@router.get("/{skill_id}")
def get_system_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.get_system_skill(db, skill_id)


@router.put("/{skill_id}")
def update_system_skill(
    skill_id: int,
    request: Request,
    payload: SystemSkillUpdateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        saved = service.save_system_skill(db, skill_id, payload.model_dump(), user.id)
    except SkillValidationError as exc:
        return _validation_response(exc)
    _refresh_runtime(request)
    return saved


@router.post("/{skill_id}/status")
def set_system_skill_status(
    skill_id: int,
    request: Request,
    payload: SystemSkillStatusIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.set_system_skill_status(db, skill_id, payload.status)
    _refresh_runtime(request)
    return result


@router.delete("/{skill_id}")
def delete_system_skill(
    skill_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.delete_system_skill(db, skill_id)
    _refresh_runtime(request)
    return {"ok": True}


@router.post("/{skill_id}/test")
def test_system_skill(
    skill_id: int,
    payload: SystemSkillTestIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.test_system_skill(db, user.id, skill_id, payload.args)


@router.get("/{skill_id}/runs")
def list_system_skill_runs(
    skill_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    runs = service.list_platform_runs(db, skill_id, limit)
    return {"list": [_run_dict(run) for run in runs]}
