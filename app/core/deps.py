"""请求依赖：数据库会话、当前登录用户（未登录门禁）。"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, RedirectRequest
from app.modules.auth.models import User
from database import get_db


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """业务路由统一门禁：未登录时 /api 返回 401，页面 303 跳 /login。"""
    user_id = request.session.get("user_id")
    if not user_id:
        if request.url.path.startswith("/api"):
            raise AppError(401, "未登录或会话已过期")
        raise RedirectRequest("/login")
    user = db.get(User, user_id)
    if user is None:
        if request.url.path.startswith("/api"):
            raise AppError(401, "未登录或会话已过期")
        raise RedirectRequest("/login")
    request.state.user = user
    return user
