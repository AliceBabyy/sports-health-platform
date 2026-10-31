"""生理周期 API 路由（/api/cycle 系列，MC-01~05、MC-10~12）。"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.cycle import service
from app.modules.cycle.schemas import PainIn, PeriodIn, PeriodUpdateIn, SettingsIn
from database import get_db

router = APIRouter(prefix="/api/cycle", tags=["cycle"])


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = service.get_settings(db, user.id)
    return {"cycle_length": s.cycle_length, "period_length": s.period_length}


@router.put("/settings")
def update_settings(
    payload: SettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = service.update_settings(db, user.id, payload.cycle_length, payload.period_length)
    return {"cycle_length": s.cycle_length, "period_length": s.period_length}


@router.get("/periods")
def list_periods(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"list": service.list_periods(db, user.id)}


@router.post("/periods")
def create_period(
    payload: PeriodIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = service.create_period(db, user.id, payload.start_date, payload.end_date, payload.cycle_length, payload.period_length)
    return {"id": row.id, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat() if row.end_date else None}


@router.put("/periods/{record_id}")
def update_period(
    record_id: int,
    payload: PeriodUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = service.update_period(db, user.id, record_id, payload.start_date, payload.end_date)
    if row is None:
        raise AppError(404, "记录不存在")
    return {"id": row.id, "start_date": row.start_date.isoformat(), "end_date": row.end_date.isoformat() if row.end_date else None}


@router.delete("/periods/{record_id}")
def delete_period(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_period(db, user.id, record_id):
        raise AppError(404, "记录不存在")
    return {"ok": True}


@router.put("/pain/{log_date}")
def set_pain(
    log_date: date,
    payload: PainIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.set_pain(db, user.id, log_date, payload.pain_level)
    return {"ok": True, "log_date": log_date.isoformat(), "pain_level": payload.pain_level}


@router.get("/calendar")
def calendar(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    year, month_num = month.split("-")
    return service.calendar_month(db, user.id, int(year), int(month_num))
