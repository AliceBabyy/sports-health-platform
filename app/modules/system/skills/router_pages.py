"""系统内置技能页面路由：GET /system/skills（列表 + 编辑 + 定义校验 + 试运行）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.system.skills import service
from database import get_db

router = APIRouter(prefix="/skills")


@router.get("")
def skills_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "system/skills.html",
        {
            "active": "system_skills",
            **service.page_context(db),
        },
    )
