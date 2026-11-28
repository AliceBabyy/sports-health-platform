"""AI Agent 页面路由：GET /agent（对话）、GET /agent/skills（技能管理）、GET /agent/personas（角色管理）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.models.registry import chat_model_names, current_alias
from app.core.access import is_female
from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.agent import service
from app.modules.agent.personas.management import list_personas
from app.modules.agent.skills.management import list_skills
from app.modules.agent.tools.policy import TOOL_PERSONA_SCOPES
from app.modules.agent.tools.web_search import web_search_available
from app.modules.auth.models import User
from app.modules.profile.aspect_skills import skill_female_only
from config import settings
from database import get_db

router = APIRouter()


def _selectable_personas(db: Session, user_id: int) -> list[dict]:
    """对话页「新建角色对话」可选项：启用且已发布的平台/我的角色。"""
    items = []
    for row, version in list_personas(db, user_id):
        if row.status != "active" or version is None or version.published_at is None:
            continue
        items.append({
            "id": row.id, "name": row.name, "description": row.description, "scope": row.scope,
        })
    return items


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
            "model_options": chat_model_names(),
            "default_model": current_alias("agent.chat"),
            "personas": _selectable_personas(db, user.id),
            "web_search_available": web_search_available(),
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
        if is_female(user.gender) or not skill_female_only(row.skill_key)
    ]
    return render_page(
        request,
        "agent/skills.html",
        {"active": "agent_skills", "skills": skills},
    )


@router.get("/agent/personas")
def agent_personas_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    personas = [
        {
            "id": row.id, "scope": row.scope, "key": row.persona_key, "name": row.name,
            "description": row.description, "status": row.status, "sort_order": row.sort_order,
            "current_version_no": row.current_version_no,
            "version_no": version.version_no if version else None,
            "published": bool(version and version.published_at),
            "can_edit": row.scope == "user" and row.owner_user_id == user.id,
            "can_delete": row.scope == "user" and row.owner_user_id == user.id,
            "definition": version.definition if version else None,
        }
        for row, version in list_personas(db, user.id)
    ]
    return render_page(
        request,
        "agent/personas.html",
        {
            "active": "agent_personas",
            "personas": personas,
            "persona_max": settings.agent_persona_max_per_user,
            "persona_max_chars": settings.agent_persona_max_chars,
            "tool_scoping_active": bool(TOOL_PERSONA_SCOPES),
        },
    )
