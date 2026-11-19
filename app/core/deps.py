"""请求依赖：数据库会话、当前登录用户（未登录门禁）与管理员依赖。"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.access import ADMIN_ROLE
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
    if user is None or user.status != "启用":
        request.session.clear()
        if request.url.path.startswith("/api"):
            raise AppError(401, "未登录或会话已过期")
        raise RedirectRequest("/login")
    request.state.user = user
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """管理员依赖：已登录但角色非管理员返回 403。

    `/system` 与 `/api/system` 前缀由 `AdminGateMiddleware` 统一拦截，本依赖用于
    前缀之外仍需要管理员权限的个别路由。
    """
    if user.role != ADMIN_ROLE:
        raise AppError(403, "需要管理员权限，当前账号为普通用户")
    return user
