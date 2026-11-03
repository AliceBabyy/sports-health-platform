"""健身训练页面路由：GET /training（单日视图 + 前后翻页，?date= 指定某日；默认今天）。

2026-11 改版：支持从总览页按 ?date= 跳转到任意一日；记录模式仍仅对当日开放（后端强校验）。
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.constants import (
    PHASE_INFO,
    SPORT_GOOD,
    SPORT_HIGH,
    SPORT_REST,
    today_local,
)
from app.core.deps import get_current_user
from app.core.templating import WEEKDAY_CN, render_page
from app.modules.auth.models import User
from app.modules.cycle.service import get_today_summary
from app.modules.training import service as training_service
from database import get_db

router = APIRouter()


@router.get("/training")
def training_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    day: date | None = Query(None),
):
    today = today_local()
    selected = day or today
    selected_plans = training_service.get_plans_by_date(db, user.id, selected)
    # 周期联动：今日阶段 + 运动等级 + 建议（男性账号不显示）
    cycle_link = None
    if user.gender != "男":
        cyc = get_today_summary(user.id)
        info = PHASE_INFO.get(cyc.get("phase_key", ""), {})
        level = cyc.get("sport_level", SPORT_REST)
        chips = []
        if level == SPORT_HIGH:
            chips = ["建议负荷 +5%", "可冲击 PR"]
        elif level == SPORT_GOOD:
            chips = ["维持常规负荷", "注意补水"]
        else:
            chips = ["以拉伸 / 有氧为主", "保证睡眠"]
        cycle_link = {
            "phase_label": cyc.get("phase_label", "—"),
            "sport_label": cyc.get("sport_label", "—"),
            "sport_level": level,
            "advice": info.get("advice", ""),
            "chips": chips,
        }
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
            "cycle_link": cycle_link,
        },
    )
