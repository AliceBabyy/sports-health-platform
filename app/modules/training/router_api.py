"""健身训练 API 路由（TR-01~03、TR-10~17、TR-22、TR-24；2026-11 整改：id 维度 CRUD）。

一日可多个训练计划/记录，接口一律按 plan_id 定位：
- GET  /plans?plan_date=      某日全部计划列表
- POST /plans                  新建计划（body: plan_date + items）
- GET/PUT/DELETE /plans/{plan_id}  单个计划查询/编辑/删除（已记录锁定）
- POST /plans/batch-delete     批量删除（仅 planned，已记录的跳过）
- POST /plans/{plan_id}/start|save|cancel|note  状态机与心得
注意：/plans/batch-delete 必须在 /plans/{plan_id} 之前声明。
周/月跨运动总览已迁移至 /api/overview（2026-11），本模块不再提供 /plans/week。
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.training import service
from app.modules.training.schemas import BatchDeleteIn, NoteIn, PlanCreateIn, PlanSaveIn, StartIn
from database import get_db

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/plans")
def list_plans(
    plan_date: date = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {
        "plan_date": plan_date.isoformat(),
        "plans": [service.plan_to_dict(p) for p in service.get_plans_by_date(db, user.id, plan_date)],
    }


@router.post("/plans")
def create_plan(
    payload: PlanCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.create_plan(db, user.id, payload.plan_date, payload.items, payload.remark)
    return {"plan": service.plan_to_dict(plan)}


@router.post("/plans/batch-delete")
def batch_delete(
    payload: BatchDeleteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.batch_delete_plans(db, user.id, payload.ids)


@router.get("/plans/{plan_id}")
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"plan": service.plan_to_dict(service.get_plan_or_404(db, user.id, plan_id))}


@router.put("/plans/{plan_id}")
def update_plan(
    plan_id: int,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.items:
        raise AppError(400, "计划至少包含一条训练动作")
    plan = service.update_plan(db, user.id, plan_id, payload.items, payload.remark)
    return {"plan": service.plan_to_dict(plan)}


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not service.delete_plan(db, user.id, plan_id):
        raise AppError(404, "训练计划不存在")
    return {"ok": True}


@router.post("/plans/{plan_id}/start")
def start_record(
    plan_id: int,
    payload: StartIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.start_record(db, user.id, plan_id, payload.mode)
    return {"plan": service.plan_to_dict(plan), "mode": payload.mode}


@router.post("/plans/{plan_id}/save")
def save_record(
    plan_id: int,
    payload: PlanSaveIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.save_record(db, user.id, plan_id, payload.items, payload.remark)


@router.post("/plans/{plan_id}/note")
def save_note(
    plan_id: int,
    payload: NoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.save_note(db, user.id, plan_id, payload.status_text, payload.rating)
    return {"ok": True}


@router.post("/plans/{plan_id}/cancel")
def cancel_record(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = service.cancel_record(db, user.id, plan_id)
    if plan is None:
        raise AppError(404, "训练计划不存在")
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
