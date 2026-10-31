"""生理周期页面路由：GET /cycle。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.constants import PHASE_INFO, PHASE_LABELS, SPORT_LABELS
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
    today = request.app.state.today
    calendar_data = service.calendar_month(db, user.id, today.year, today.month)
    return render_page(
        request,
        "cycle/index.html",
        {
            "active": "cycle",
            "calendar": calendar_data,
            "settings": {
                "cycle_length": calendar_data["overview"]["cycle_length"],
                "period_length": calendar_data["overview"]["period_length"],
            },
            "phase_info": {k: {**v, "label": PHASE_LABELS[k], "level_label": SPORT_LABELS[v["level"]]} for k, v in PHASE_INFO.items()},
        },
    )
