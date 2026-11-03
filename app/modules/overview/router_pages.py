"""运动训练/计划 总览页路由：GET /overview（登录门禁，active=overview 高亮侧栏分组头）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from database import get_db

router = APIRouter()


@router.get("/overview")
def overview_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "overview/index.html",
        {"active": "overview"},
    )
