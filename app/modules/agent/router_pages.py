"""AI Agent 页面路由：GET /agent（会话列表 + 对话区）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.models.registry import MODELS
from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.agent import service
from app.modules.auth.models import User
from config import settings
from database import get_db

router = APIRouter()


@router.get("/agent")
def agent_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render_page(
        request,
        "agent/index.html",
        {
            "active": "agent",
            "conversations": service.list_conversations(db, user.id),
            "model_options": list(MODELS.keys()),
            "default_model": settings.ai_default_model,
        },
    )
