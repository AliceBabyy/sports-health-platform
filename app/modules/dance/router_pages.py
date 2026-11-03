"""舞蹈页面路由：GET /dance（单日视图 + 前后翻页，?date= 指定某日；默认今天）。

2026-11 改版：支持从总览页按 ?date= 跳转；当日视图展示计划与记录两态。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.constants import today_local
from app.core.deps import get_current_user
from app.core.templating import WEEKDAY_CN, render_page
from app.modules.auth.models import User
from app.modules.dance import service
from database import get_db

router = APIRouter()


@router.get("/dance")
def dance_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    day: date | None = Query(None),
):
    selected = day or today_local()
    stats = service.stats(db, user.id)
    return render_page(
        request,
        "dance/index.html",
        {
            "active": "dance",
            "stats": stats,
            "selected_date": selected.isoformat(),
            "selected_date_str": selected.strftime("%m月%d日"),
            "selected_weekday": WEEKDAY_CN[selected.weekday()],
            "is_today": selected == today_local(),
            "prev_date": (selected - timedelta(days=1)).isoformat(),
            "next_date": (selected + timedelta(days=1)).isoformat(),
        },
    )
