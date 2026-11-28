"""个人信息页面路由：GET /profile（账号资料）与 GET /profile/health-profile（健康档案）。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.access import is_female
from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.aspect_skills import ASPECT_SKILLS, skill_name
from app.modules.profile.questionnaire import answered_count, question_count
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
    """展示全部专项卡；已建立的展示最近一套，未建立的直接提供新增入口。"""
    row = service.get_health_profile(db, user.id)
    latest_by_skill = {
        item["skill_key"]: item for item in (row.sets if row else [])
    }
    cards = []
    visible_skills = [
        skill for skill in ASPECT_SKILLS
        if not skill["female_only"] or is_female(user.gender)
    ]
    for index, skill in enumerate(visible_skills, start=1):
        question_set = latest_by_skill.get(skill["key"])
        cards.append({
            "skill_key": skill["key"],
            "name": skill_name(skill["key"]),
            "description": skill["description"],
            "aspects": list(skill["aspects"]),
            "sort_order": skill["sort_order"],
            "index": index,
            "filled": question_set is not None,
            "set": _page_set(question_set) if question_set else None,
            "question_count": question_count(question_set) if question_set else 0,
            "answered_count": answered_count(question_set) if question_set else 0,
        })

    total_questions = sum(card["question_count"] for card in cards)
    total_answers = sum(card["answered_count"] for card in cards)
    filled_count = sum(1 for card in cards if card["filled"])
    latest_at = max(
        (card["set"]["generated_at"] for card in cards if card["set"]),
        default="—",
    )
    return render_page(
        request,
        "profile/health_profile.html",
        {
            "active": "health_profile",
            "filled": filled_count > 0,
            "cards": cards,
            "filled_count": filled_count,
            "total_questions": total_questions,
            "total_answers": total_answers,
            "latest_at": latest_at,
        },
    )
