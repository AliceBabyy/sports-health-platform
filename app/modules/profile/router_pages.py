"""个人信息页面路由：GET /profile（账号资料）与 GET /profile/health-profile（健康档案）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.aspect_skills import skill_name
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


def _page_set(question_set: dict) -> dict:
    generated_at = question_set.get("generated_at")
    return {
        "set_id": question_set["set_id"],
        "skill_key": question_set["skill_key"],
        "name": skill_name(question_set["skill_key"]),
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M") if generated_at else "—",
        "items": question_set["questions"],
    }


@router.get("/profile/health-profile")
def health_profile_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """只展示已存储的专项档案；直接编辑，不再有查看/编辑两态。"""
    row = service.get_health_profile(db, user.id)
    return render_page(
        request,
        "profile/health_profile.html",
        {
            "active": "health_profile",
            "filled": row is not None,
            "sets": [_page_set(item) for item in (row.sets if row else [])],
        },
    )
