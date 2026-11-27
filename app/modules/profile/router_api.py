"""个人信息 API 路由（/api/profile）：基本资料更新 / 密码修改 / 健康档案。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.aspect_skills import skill_name
from app.modules.profile.schemas import (
    AccountDeleteIn,
    HealthProfileIn,
    PasswordChangeIn,
    ProfileUpdateIn,
)
from database import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _set_payload(question_set: dict) -> dict:
    generated_at = question_set.get("generated_at")
    return {
        "set_id": question_set["set_id"],
        "skill_key": question_set["skill_key"],
        "name": skill_name(question_set["skill_key"]),
        "generated_at": generated_at.isoformat() if generated_at else None,
        "items": [
            {
                "local_key": item["local_key"],
                "aspect": item["aspect"],
                "label": item["label"],
                "hint": item["hint"],
                "placeholder": item["placeholder"],
                "max_length": item["max_length"],
                "answer": item["answer"],
            }
            for item in question_set["questions"]
        ],
    }


def _health_profile_payload(db: Session, user: User) -> dict:
    row = service.get_health_profile(db, user.id)
    return {
        "ok": True,
        "filled": row is not None,
        "sets": [_set_payload(item) for item in (row.sets if row else [])],
    }


@router.post("")
def update_profile(
    payload: ProfileUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新基本资料（昵称/性别/年龄）；返回最新值供前端同步顶栏。"""
    service.update_profile(db, user, payload.display_name, payload.gender, payload.age)
    return {"ok": True, "display_name": user.display_name, "gender": user.gender, "age": user.age}


@router.post("/password")
def change_password(
    payload: PasswordChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改密码：当前密码校验 + 新密码两次一致，成功后保持登录态。"""
    if payload.new_password != payload.confirm_password:
        raise AppError(400, "两次输入的新密码不一致")
    service.change_password(db, user, payload.current_password, payload.new_password)
    return {"ok": True}


@router.delete("/account")
def delete_account(
    payload: AccountDeleteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service.delete_account(db, user, payload.mode, payload.current_password)
    request.session.clear()
    return {"ok": True}


@router.get("/health-profile")
def read_health_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取已存储的专项档案；未填写时 `filled=false`、`sets=[]`。"""
    return _health_profile_payload(db, user)


@router.put("/health-profile")
def save_health_profile(
    payload: HealthProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """逐题保存已存储档案：空串清空该题，但保留该套与题目结构。"""
    service.save_health_profile_items(db, user, payload.items)
    return _health_profile_payload(db, user)


@router.delete("/health-profile")
def clear_health_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """清空档案：删除全部套装行。"""
    service.clear_health_profile(db, user)
    return {"ok": True}
