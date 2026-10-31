"""游泳 API 路由（/api/swim-records，SW-01/02）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.constants import SWIM_STROKES
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.swim import service
from app.modules.swim.schemas import SwimRecordIn
from database import get_db

router = APIRouter(prefix="/api/swim-records", tags=["swim"])


@router.get("")
def list_swim(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.list_records(db, user.id, page, page_size)
    return {**result, "list": [service.to_dict(r) for r in result["list"]]}


@router.post("")
def create_swim(
    payload: SwimRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.create_record(db, user.id, payload)
    return service.to_dict(row)


@router.put("/{record_id}")
def update_swim(
    record_id: int,
    payload: SwimRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate(payload)
    row = service.update_record(db, user.id, record_id, payload)
    if row is None:
        raise AppError(404, "记录不存在")
    return service.to_dict(row)


@router.delete("/{record_id}")
def delete_swim(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_record(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


@router.get("/stats")
def swim_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.stats(db, user.id)


def _validate(payload: SwimRecordIn):
    if payload.main_stroke not in SWIM_STROKES:
        raise AppError(400, "主泳姿不合法")
