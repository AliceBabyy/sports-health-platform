"""总览 API 路由（/api/overview）：三颗粒度聚合 + 单日详情（2026-11 新增）。"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.overview import service
from database import get_db

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("")
def overview(
    granularity: Literal["day", "week", "month"] = "week",
    day: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """日/周/月聚合总览；date 缺省为今天。"""
    from app.core.constants import today_local

    anchor = day or today_local()
    return service.aggregate(db, user.id, granularity, anchor)


@router.get("/day")
def overview_day(
    day: date = Query(..., alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """单日详情（三运动全部条目），供总览弹窗与详情页。"""
    return service.day_detail(db, user.id, day)
