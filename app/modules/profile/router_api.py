"""个人信息 API 路由（/api/profile）：基本资料更新 / 密码修改 / 健康档案。"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile import probe
from app.modules.profile.schemas import (
    AccountDeleteIn,
    HealthProfileIn,
    PasswordChangeIn,
    ProfileUpdateIn,
)
from database import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _health_profile_payload(db: Session, user: User) -> dict:
    row = service.get_health_profile(db, user.id)
    store = probe.parse_store(row.custom_questions if row else None)
    return {
        "ok": True,
        "filled": row is not None,
        "completed_at": row.completed_at.isoformat() if row and row.completed_at else None,
        "answers": dict(row.answers or {}) if row else {},
        "custom_questions": probe.latest_payload(store),
        "custom_history_count": len(store["sets"]),
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
    """读取健康/运动档案：未填写时 `filled=false`、`answers={}`。"""
    return _health_profile_payload(db, user)


@router.put("/health-profile")
def save_health_profile(
    payload: HealthProfileIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存档案：只更新提交的题目，空串清空该题；全部清空后删除档案行。"""
    row = service.save_health_profile(db, user, payload.answers)
    if row is None:
        return {
            "ok": True, "filled": False, "completed_at": None, "answers": {},
            "custom_questions": None, "custom_history_count": 0,
        }
    return _health_profile_payload(db, user)


@router.delete("/health-profile")
def clear_health_profile(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """清空档案：删除档案行，页面回到问卷态。"""
    service.clear_health_profile(db, user)
    return {"ok": True}
