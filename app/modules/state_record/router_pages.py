"""状态记录页面路由：GET /state-record（月历 + 当日三类记录 + 全部记录列表容器）。"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.state_record import service
from app.modules.state_record.models import STATE_TYPES, STATE_TYPE_LABELS
from database import get_db

router = APIRouter()


@router.get("/state-record")
def state_record_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = date.today()  # 每次请求取当天，避免服务长跑后仍用启动日
    calendar_data = service.calendar_with_records(db, user, today.year, today.month)
    daily = service.get_by_date(db, user.id, today)
    return render_page(
        request,
        "state_record/index.html",
        {
            "active": "state_record",
            "calendar": calendar_data,
            "daily": daily,
            "today_str": today.isoformat(),
            "state_types": STATE_TYPES,
            "state_type_labels": STATE_TYPE_LABELS,
        },
    )
