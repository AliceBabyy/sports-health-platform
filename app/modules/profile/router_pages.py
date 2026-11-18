"""个人信息页面路由：GET /profile（账号资料）与 GET /profile/health-profile（健康/运动档案）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.questions import grouped_questions
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
            "active": "profile_basic",
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else "—",
            "updated_at": user.updated_at.strftime("%Y-%m-%d %H:%M") if user.updated_at else "—",
        },
    )


@router.get("/profile/health-profile")
def health_profile_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """健康/运动档案：未填写直接展示问卷，已填写展示答案并支持编辑/清空。"""
    row = service.get_health_profile(db, user.id)
    answers = dict(row.answers or {}) if row else {}
    return render_page(
        request,
        "profile/health_profile.html",
        {
            "active": "health_profile",
            "filled": row is not None,
            "answers": answers,
            "groups": grouped_questions(),
            "completed_at": row.completed_at.strftime("%Y-%m-%d %H:%M")
            if row and row.completed_at
            else "—",
        },
    )
