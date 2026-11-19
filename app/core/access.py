"""系统管理区访问控制（2026-11-19）：角色常量、路径判定与 `/system` 前缀门禁中间件。

边界口径：页面前缀 `/system` 与 API 前缀 `/api/system` 一律仅 `管理员` 可访问。
门禁放在中间件而非逐个 router，新增管理员功能只要落在这两个前缀下即自动受保护。
"""
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.modules.auth.models import User

ADMIN_ROLE = "管理员"
USER_ROLE = "普通用户"
ROLES = (ADMIN_ROLE, USER_ROLE)

ADMIN_PATH_PREFIXES = ("/system", "/api/system")


def is_admin_path(path: str) -> bool:
    """是否落在管理员区前缀内；按路径段匹配，避免 `/systematic` 这类误判。"""
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ADMIN_PATH_PREFIXES)


def is_admin(user: User | None) -> bool:
    return user is not None and user.role == ADMIN_ROLE


def _deny(request: Request, status: int, message: str):
    """中间件内直接构造响应：Starlette 的全局异常处理器包不到中间件，不能抛 AppError。"""
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=status,
            content={"code": {401: "UNAUTHORIZED", 403: "FORBIDDEN"}.get(status, "REQUEST_FAILED"), "error": message},
        )
    if status == 401:
        return RedirectResponse("/login", status_code=303)
    from app.core.templating import templates  # 延迟 import，避免与应用装配顺序耦合

    return templates.TemplateResponse(
        request, "error.html", {"error_code": status, "error_message": message}, status_code=status
    )


class AdminGateMiddleware(BaseHTTPMiddleware):
    """管理员区门禁：未登录 401/303，非管理员 403，停用账号按未登录处理。

    必须注册在 SessionMiddleware 之前（add_middleware 后加先执行），保证本中间件运行时
    会话已解析完毕。
    """

    def __init__(self, app, session_factory):
        super().__init__(app)
        self.session_factory = session_factory

    async def dispatch(self, request: Request, call_next):
        if not is_admin_path(request.url.path):
            return await call_next(request)

        user_id = request.session.get("user_id")
        if not user_id:
            return _deny(request, 401, "未登录或会话已过期")

        db: Session = self.session_factory()
        try:
            user = db.get(User, user_id)
            active = user is not None and user.status == "启用"
            role = user.role if user is not None else None
        finally:
            db.close()

        if not active:
            request.session.clear()
            return _deny(request, 401, "未登录或会话已过期")
        if role != ADMIN_ROLE:
            return _deny(request, 403, "需要管理员权限，当前账号为普通用户")
        return await call_next(request)
