"""健身训练 API 路由（TR-01~03、TR-10~17、TR-22、TR-24）。"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.training import service
from app.modules.training.schemas import NoteIn, PlanSaveIn, StartIn
from database import get_db

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/plans/{plan_date}")
def get_plan(
    plan_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"plan": service.plan_to_dict(service.get_plan(db, user.id, plan_date))}


@router.post("/plans/{plan_date}")
@router.put("/plans/{plan_date}")
def save_plan(
    plan_date: date,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.save_plan(db, user.id, plan_date, payload.items)
    return {"plan": service.plan_to_dict(plan)}


@router.delete("/plans/{plan_date}")
def delete_plan(
    plan_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_plan(db, user.id, plan_date):
        raise AppError(404, "该日无训练计划")
    return {"ok": True}


@router.get("/plans/week")
def week(
    week_start: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"week_start": week_start.isoformat(), "days": service.week_plans(db, user.id, week_start)}


@router.post("/plans/{plan_date}/start")
def start_record(
    plan_date: date,
    payload: StartIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.start_record(db, user.id, plan_date, payload.mode)
    return {"plan": service.plan_to_dict(plan), "mode": payload.mode}


@router.post("/plans/{plan_date}/save")
def save_record(
    plan_date: date,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.save_record(db, user.id, plan_date, payload.items)


@router.post("/plans/{plan_date}/note")
def save_note(
    plan_date: date,
    payload: NoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.save_note(db, user.id, plan_date, payload.status_text, payload.rating)
    return {"ok": True}


@router.post("/plans/{plan_date}/cancel")
def cancel_record(
    plan_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.cancel_record(db, user.id, plan_date)
    if plan is None:
        raise AppError(404, "该日无训练计划")
    return {"plan": service.plan_to_dict(plan)}


@router.get("/history")
def history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = service.history(db, user.id, page, page_size)
    return {**result, "list": [service.plan_to_dict(p) for p in result["list"]]}
