"""系统 AI 配置页面：GET /system/ai（来源 + 模型 + 功能路由）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.system.ai_config import service
from database import get_db

router = APIRouter(prefix="/ai")


@router.get("")
def ai_config_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "system/ai.html",
        {"active": "system_ai", **service.page_context(db)},
    )
