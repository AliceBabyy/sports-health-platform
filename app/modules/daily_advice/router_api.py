"""每日训练建议 API（/api/daily-advice）：读取当天建议、手动重新生成。"""
from datetime import date

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.constants import today_local
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.daily_advice import service
from app.modules.daily_advice.schemas import AdviceRegenerateIn
from database import get_db

router = APIRouter(prefix="/api/daily-advice", tags=["daily_advice"])


@router.get("")
def read_advice(
    advice_date: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取某天的建议（缺省今天）；只返回当前用户自己的行，无行 status=none。"""
    return service.read(db, user.id, advice_date)


@router.post("/regenerate")
def regenerate_advice(
    payload: AdviceRegenerateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新生成今天的建议；跨天返回 400，生成中返回 409。"""
    today = today_local()
    day = payload.date or today
    if day != today:
        raise AppError(400, "只能重新生成今天的建议")
    return service.generate(db, user, day, force=payload.force)
