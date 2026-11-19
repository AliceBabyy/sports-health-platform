"""系统内置角色页面路由：GET /system/personas（列表 + 编辑 + 工具/技能勾选）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.system.personas import service
from config import settings
from database import get_db

router = APIRouter(prefix="/personas")


@router.get("")
def personas_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "system/personas.html",
        {
            "active": "system_personas",
            "persona_max_chars": settings.agent_persona_max_chars,
            **service.page_context(db),
        },
    )
