"""系统内置角色 API（相对前缀 /system-personas，由 system 模块挂载为 /api/system/system-personas）。

全部接口落在 /api/system 下，自动受 AdminGateMiddleware 管理员门禁保护，不再单独写鉴权依赖。
"""
from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.modules.agent.personas.management import PersonaValidationError
from app.modules.auth.models import User
from app.modules.system.personas import service
from app.modules.system.personas.schemas import SystemPersonaIn, SystemPersonaUpdateIn
from database import get_db

router = APIRouter(prefix="/system-personas", tags=["system-personas"])


def _validation_response(exc: PersonaValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "code": "SYSTEM_PERSONA_INVALID",
            "error": "内置角色定义或配置不合法",
            "errors": exc.errors,
            "warnings": exc.warnings,
        },
    )


@router.get("")
def list_system_personas(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"list": service.list_system_personas(db)}


@router.get("/options")
def system_persona_options(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "tools": service.tool_options(),
        "skills": service.skill_options(db),
    }


@router.post("", status_code=201)
def create_system_persona(
    payload: SystemPersonaIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.create_system_persona(db, payload.model_dump(), user.id)
    except PersonaValidationError as exc:
        return _validation_response(exc)


@router.get("/{persona_id}")
def get_system_persona(
    persona_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.get_system_persona(db, persona_id)


@router.put("/{persona_id}")
def update_system_persona(
    persona_id: int,
    payload: SystemPersonaUpdateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.save_system_persona(db, persona_id, payload.model_dump(), user.id)
    except PersonaValidationError as exc:
        return _validation_response(exc)


@router.delete("/{persona_id}")
def delete_system_persona(
    persona_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.delete_system_persona(db, persona_id)
    return {"ok": True}
