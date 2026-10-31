"""舞蹈 API 路由（/api/dance-records，DA-01）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.dance import service
from app.modules.dance.schemas import DanceRecordIn
from database import get_db

router = APIRouter(prefix="/api/dance-records", tags=["dance"])


@router.get("")
def list_dance(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    dance_type: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.list_records(db, user.id, page, page_size, dance_type)
    return {**result, "list": [service.to_dict(r) for r in result["list"]]}


@router.post("")
def create_dance(
    payload: DanceRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = service.create_record(db, user.id, payload)
    return service.to_dict(row)


@router.put("/{record_id}")
def update_dance(
    record_id: int,
    payload: DanceRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = service.update_record(db, user.id, record_id, payload)
    if row is None:
        raise AppError(404, "记录不存在")
    return service.to_dict(row)


@router.delete("/{record_id}")
def delete_dance(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_record(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


@router.get("/stats")
def dance_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.stats(db, user.id)
