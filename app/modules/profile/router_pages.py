"""个人信息页面路由：GET /profile（登录门禁，active=profile 高亮侧栏）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from database import get_db

router = APIRouter()


@router.get("/profile")
def profile_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "profile/index.html",
        {
            "active": "profile",
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else "—",
            "updated_at": user.updated_at.strftime("%Y-%m-%d %H:%M") if user.updated_at else "—",
        },
    )
