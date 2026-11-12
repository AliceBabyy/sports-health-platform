"""健身训练页面路由：GET /training（单日视图 + 前后翻页，?date= 指定某日；默认今天）。

2026-11 改版：支持从总览页按 ?date= 跳转到任意一日；「完成训练」仅对当日开放（后端强校验，2026-11-03 移除记录模式）。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.constants import today_local
from app.core.deps import get_current_user
from app.core.templating import WEEKDAY_CN, render_page
from app.modules.auth.models import User
from app.modules.training import service as training_service
from database import get_db

router = APIRouter()


@router.get("/training")
def training_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    day: date | None = Query(None, alias="date"),  # 前端链接统一 ?date=（2026-11-03 修：参数名与链接不一致致翻页失效）
):
    today = today_local()
    selected = day or today
    selected_plans = training_service.get_plans_by_date(db, user.id, selected)
    return render_page(
        request,
        "training/index.html",
        {
            "active": "training",
            "today": today,
            "selected_date": selected,
            "selected_date_str": selected.strftime("%m月%d日"),
            "selected_weekday": WEEKDAY_CN[selected.weekday()],
            "is_today": selected == today,
            "prev_date": (selected - timedelta(days=1)).isoformat(),
            "next_date": (selected + timedelta(days=1)).isoformat(),
            "today_plans": [training_service.plan_to_dict(p) for p in selected_plans],
            "stats": training_service.stats(db, user.id),
        },
    )
