"""报告 API 路由（/api/reports）：读取、生成、历史、软删除。"""
from datetime import date

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.modules.auth.models import User
from app.modules.report import service
from app.modules.report.schemas import ReportGenerateIn
from database import get_db

router = APIRouter(prefix="/api/reports", tags=["report"])


@router.get("")
def read_report(
    type: str = Query("weekly"),
    anchor: date | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取某周期报告：事实快照 + 已生成的叙事（无则 report=null）。"""
    return service.read(db, user, type, anchor)


@router.post("/generate")
def generate_report(
    payload: ReportGenerateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成（或复用）报告；已 ready 且数据未变时直接返回，force=true 强制重生成。"""
    return service.generate(db, user, payload.type, payload.anchor, force=payload.force)


@router.get("/history")
def report_history(
    type: str | None = Query(None),
    page: int = Query(1),
    page_size: int = Query(10),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """历史报告列表（软删除的不返回），按周期倒序分页。"""
    return service.history(db, user.id, type, page, page_size)


@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """软删除一条报告：扫描任务不会重新生成已删除的周期。"""
    return service.delete(db, user.id, report_id)
