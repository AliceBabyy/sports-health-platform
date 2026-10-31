"""身材数据页面路由：GET /body。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.body import service as body_service
from app.modules.body import trend_service
from database import get_db

router = APIRouter()


@router.get("/body")
def body_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    snap = body_service.latest_snapshot(db, user.id)
    initial_trend = trend_service.build_trend(db, user.id, "weight", "month")
    return render_page(
        request,
        "body/index.html",
        {
            "active": "body",
            "snapshot": snap,
            "initial_trend": initial_trend,
        },
    )
