"""系统 AI 配置 API（相对前缀 /ai-config，由 system 模块挂载为 /api/system/ai-config）。"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.system.ai_config import service
from app.modules.system.ai_config.schemas import ModelIn, ProviderIn, RouteIn, TestIn
from database import get_db

router = APIRouter(prefix="/ai-config", tags=["system-ai"])


def _fail(exc: service.AiConfigError):
    raise AppError(exc.status_code, exc.message) from exc


@router.get("")
def get_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_payload(db)


@router.post("/providers", status_code=201)
def create_provider(
    payload: ProviderIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.save_provider(db, None, payload.model_dump(), user)
    except service.AiConfigError as exc:
        _fail(exc)


@router.put("/providers/{provider_id}")
def update_provider(
    provider_id: int,
    payload: ProviderIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.save_provider(db, provider_id, payload.model_dump(), user)
    except service.AiConfigError as exc:
        _fail(exc)


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        service.delete_provider(db, provider_id)
    except service.AiConfigError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: int,
    payload: TestIn = Body(default_factory=TestIn),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.test_provider(db, provider_id, payload.model_alias)
    except service.AiConfigError as exc:
        _fail(exc)


@router.post("/models", status_code=201)
def create_model(
    payload: ModelIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.save_model(db, None, payload.model_dump(), user)
    except service.AiConfigError as exc:
        _fail(exc)


@router.put("/models/{model_id}")
def update_model(
    model_id: int,
    payload: ModelIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.save_model(db, model_id, payload.model_dump(), user)
    except service.AiConfigError as exc:
        _fail(exc)


@router.delete("/models/{model_id}")
def delete_model(
    model_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        service.delete_model(db, model_id)
    except service.AiConfigError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/models/{model_id}/test")
def test_model(
    model_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return service.test_model(db, model_id)
    except service.AiConfigError as exc:
        _fail(exc)


@router.put("/routes/{feature_key}")
def save_route(
    feature_key: str,
    payload: RouteIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.feature_key != feature_key:
        raise AppError(400, "功能键不一致")
    try:
        return service.save_route(db, feature_key, payload.model_dump(), user)
    except service.AiConfigError as exc:
        _fail(exc)


@router.delete("/routes/{feature_key}")
def delete_route(
    feature_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        service.delete_route(db, feature_key)
    except service.AiConfigError as exc:
        _fail(exc)
    return {"ok": True}


@router.post("/apply")
def apply_config(user: User = Depends(get_current_user)):
    return service.apply_config()
