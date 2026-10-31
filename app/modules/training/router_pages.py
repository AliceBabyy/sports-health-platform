"""健身训练页面路由：GET /training（日/周同页，首屏注入今日计划与整周数据）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.constants import (
    PHASE_INFO,
    SPORT_GOOD,
    SPORT_HIGH,
    SPORT_REST,
    monday_of,
    today_local,
)
from app.core.deps import get_current_user
from app.core.templating import render_page
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
):
    today = today_local()
    today_plan = training_service.get_plan(db, user.id, today)
    week = training_service.week_plans(db, user.id, monday_of(today))
    # 周期联动：今日阶段 + 运动等级 + 建议
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
            "today_plan": training_service.plan_to_dict(today_plan),
            "week": week,
            "can_record": today_plan is not None and today_plan.status != "recorded",
            "cycle_link": cycle_link,
        },
    )
