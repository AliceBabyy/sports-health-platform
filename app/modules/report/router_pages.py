"""报告页路由：GET /reports（周报/月报单页，active=reports 高亮侧栏子项）。"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.report.facts import resolve_period
from config import settings
from database import get_db

router = APIRouter()


@router.get("/reports")
def reports_page(
    request: Request,
    type: str = "weekly",
    anchor: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    period_type = type if type in ("weekly", "monthly") else "weekly"
    period = resolve_period(period_type, anchor)
    if period.start > period.as_of:
        period = resolve_period(period_type)
    return render_page(
        request,
        "report/index.html",
        {
            "active": "reports",
            "report_type": period_type,
            "report_anchor": period.start.isoformat(),
            "auto_enabled": settings.report_auto_enabled,
        },
    )
