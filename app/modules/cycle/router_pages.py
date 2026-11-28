"""生理周期页面路由：GET /cycle（非女性账号重定向回身材页）。"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.access import is_female
from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.cycle import service
from database import get_db

router = APIRouter()


@router.get("/cycle")
def cycle_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not is_female(user.gender):
        return RedirectResponse("/body", status_code=303)
    today = date.today()  # 每次请求取当天，避免服务长跑后仍用启动日
    calendar_data = service.calendar_month(db, user.id, today.year, today.month)
    return render_page(
        request,
        "cycle/index.html",
        {
            "active": "cycle",
            "calendar": calendar_data,
            "settings": {
                "cycle_length": calendar_data["overview"]["reference_cycle_length"],
                "period_length": calendar_data["overview"]["reference_period_length"],
            },
        },
    )
