"""业务异常与全局错误响应：/api 返回 JSON，页面返回错误页。"""
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


class AppError(Exception):
    """业务异常：status 为 HTTP 状态码，message 为对外文案。"""

    def __init__(self, status: int = 400, message: str = "请求处理失败"):
        self.status = status
        self.message = message
        super().__init__(message)


class RedirectRequest(Exception):
    """页面路由内部重定向（如未登录 303 → /login）。"""

    def __init__(self, url: str = "/login"):
        self.url = url
        super().__init__(url)


def register_exception_handlers(app, templates: Jinja2Templates) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if request.url.path.startswith("/api"):
            return JSONResponse(
                status_code=exc.status,
                content={"error": exc.message},
            )
        # 页面错误：渲染轻量错误页
        return templates.TemplateResponse(
            request, "error.html", {"error_code": exc.status, "error_message": exc.message}, status_code=exc.status
        )

    @app.exception_handler(RedirectRequest)
    async def redirect_handler(request: Request, exc: RedirectRequest):
        return RedirectResponse(exc.url, status_code=303)
