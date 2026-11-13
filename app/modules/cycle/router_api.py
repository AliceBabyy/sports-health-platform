"""生理周期 API 路由（/api/cycle 系列，MC-01~05、MC-10~12）。"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.cycle import service
from app.modules.cycle.models import PeriodRecord
from app.modules.cycle.schemas import PainIn, PeriodIn, PeriodUpdateIn, SettingsIn
from database import get_db

router = APIRouter(prefix="/api/cycle", tags=["cycle"])


def _female_only(user: User = Depends(get_current_user)) -> User:
    """性别守卫：男性账号不开放生理周期数据接口。"""
    if user.gender == "男":
        raise AppError(403, "男性账号不开放生理周期模块")
    return user


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    s = service.get_settings(db, user.id)
    return {"cycle_length": s.cycle_length, "period_length": s.period_length}


@router.put("/settings")
def update_settings(
    payload: SettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    s = service.update_settings(db, user.id, payload.cycle_length, payload.period_length)
    return {"cycle_length": s.cycle_length, "period_length": s.period_length}


@router.get("/periods")
def list_periods(
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    return {"list": service.list_periods(db, user.id)}


@router.post("/periods")
def create_period(
    payload: PeriodIn,
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    if db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user.id, PeriodRecord.start_date == payload.start_date).first():
        raise AppError(409, "该日期已有月经记录")
    service.validate_period_bounds(db, user.id, payload.start_date, payload.end_date)
    row = service.create_period(db, user.id, payload.start_date, payload.end_date)
    return {"id": row.id, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat() if row.end_date else None}


@router.put("/periods/{record_id}")
def update_period(
    record_id: int,
    payload: PeriodUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    existing = db.query(PeriodRecord).filter(PeriodRecord.id == record_id, PeriodRecord.user_id == user.id).first()
    if existing is None:
        raise AppError(404, "记录不存在")
    start_date = payload.start_date or existing.start_date
    end_date = payload.end_date if "end_date" in payload.model_fields_set else existing.end_date
    if end_date and end_date < start_date:
        raise AppError(422, "结束日期不能早于开始日期")
    if start_date != existing.start_date and db.query(PeriodRecord.id).filter(PeriodRecord.user_id == user.id, PeriodRecord.start_date == start_date, PeriodRecord.id != record_id).first():
        raise AppError(409, "该日期已有月经记录")
    update_end = "end_date" in payload.model_fields_set
    service.validate_period_bounds(db, user.id, start_date, end_date, exclude_id=record_id)
    row = service.update_period(db, user.id, record_id, payload.start_date, payload.end_date, update_end)
    if row is None:
        raise AppError(404, "记录不存在")
    return {"id": row.id, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat() if row.end_date else None}


@router.delete("/periods/{record_id}")
def delete_period(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    if not service.delete_period(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


@router.put("/pain/{log_date}")
def set_pain(
    log_date: date,
    payload: PainIn,
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    service.set_pain(db, user.id, log_date, payload.pain_level)
    return {"ok": True, "log_date": log_date.isoformat(), "pain_level": payload.pain_level}


@router.get("/calendar")
def calendar(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(_female_only),
):
    year, month_num = month.split("-")
    if not 1 <= int(month_num) <= 12 or int(year) < 1:
        raise AppError(422, "月份格式无效")
    return service.calendar_month(db, user.id, int(year), int(month_num))
