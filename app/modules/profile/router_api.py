"""个人信息 API 路由（/api/profile）：基本资料更新 / 密码修改。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.modules.auth.models import User
from app.modules.profile import service
from app.modules.profile.schemas import PasswordChangeIn, ProfileUpdateIn
from database import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


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
