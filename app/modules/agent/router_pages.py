"""AI Agent 页面路由：GET /agent（对话）、GET /agent/skills（技能管理）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.models.registry import MODELS
from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.agent import service
from app.modules.agent.skills.management import list_skills
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
            "active": "agent_chat",
            "conversations": service.list_conversations(db, user.id),
            "model_options": list(MODELS.keys()),
            "default_model": settings.ai_default_model,
        },
    )


@router.get("/agent/skills")
def agent_skills_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    skills = [
        {
            "id": row.id, "scope": row.scope, "key": row.skill_key, "name": row.name,
            "slash_alias": row.slash_alias, "description": row.description,
            "kind": row.kind, "category": row.category, "status": row.status,
            "current_version_no": row.current_version_no,
            "version_no": version.version_no if version else None,
            "published": bool(version and version.published_at),
            "can_edit": row.scope == "user" and row.owner_user_id == user.id and row.kind == "prompt",
            "can_delete": row.scope == "user" and row.owner_user_id == user.id,
            "definition": version.definition if version and row.kind in ("declarative", "prompt") else None,
        }
        for row, version in list_skills(db, user.id)
    ]
    return render_page(
        request,
        "agent/skills.html",
        {"active": "agent_skills", "skills": skills},
    )
