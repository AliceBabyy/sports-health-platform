"""状态记录 API 路由（/api/state-record 系列）：三类记录增删改查、分页、批量删除、当日聚合、月历。"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.state_record import service
from app.modules.state_record.schemas import StateBatchDeleteIn, StateRecordIn
from database import get_db

router = APIRouter(prefix="/api/state-record", tags=["state-record"])


@router.get("")
def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.list_records(db, user.id, page, page_size, type)


@router.get("/daily")
def daily_records(
    day: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """某日三类记录：{type: dict|None}。"""
    return {"date": day.isoformat(), "records": service.get_by_date(db, user.id, day)}


@router.get("/calendar")
def calendar(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    year, month_num = month.split("-")
    if not 1 <= int(month_num) <= 12 or int(year) < 1:
        raise AppError(422, "月份格式无效")
    return service.calendar_with_records(db, user, int(year), int(month_num))


@router.post("")
def create_record(
    payload: StateRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.create_record(db, user.id, payload)


@router.post("/batch-delete")
def batch_delete_records(
    payload: StateBatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = [{"id": item.id, "type": item.type} for item in payload.items]
    return service.batch_delete(db, user.id, items)


@router.put("/{record_id}")
def update_record(
    record_id: int,
    payload: StateRecordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = service.update_record(db, user.id, record_id, payload)
    if row is None:
        raise AppError(404, "记录不存在")
    return row


@router.delete("/{record_id}")
def delete_record(
    record_id: int,
    type: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_record(db, user.id, type, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}
