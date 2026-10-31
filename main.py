"""应用入口：app 创建、SessionMiddleware、静态/模板目录、路由注册、全局异常处理、启动端口 8010。"""
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.exceptions import register_exception_handlers
from app.core.templating import templates
from config import settings

app = FastAPI(title="个人健康管理平台 · 体序 BODY ALMANAC")

# 会话中间件（SameSite=Lax 防 CSRF；Secure 由配置控制）
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)

app.state.today = date.today()  # 页面共享“今天”基准

# 静态资源
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 注册全局异常处理
register_exception_handlers(app, templates)


# ---------- 路由注册 ----------
def _include(router, **kwargs):
    app.include_router(router, **kwargs)


from app.modules.auth.router_pages import router as auth_pages
from app.modules.auth.router_api import router as auth_api
from app.modules.body.router_pages import router as body_pages
from app.modules.body.router_api import router as body_api
from app.modules.training.router_pages import router as training_pages
from app.modules.training.router_api import router as training_api
from app.modules.swim.router_pages import router as swim_pages
from app.modules.swim.router_api import router as swim_api
from app.modules.dance.router_pages import router as dance_pages
from app.modules.dance.router_api import router as dance_api
from app.modules.cycle.router_pages import router as cycle_pages
from app.modules.cycle.router_api import router as cycle_api

_include(auth_pages)
_include(auth_api)
_include(body_pages)
_include(body_api)
_include(training_pages)
_include(training_api)
_include(swim_pages)
_include(swim_api)
_include(dance_pages)
_include(dance_api)
_include(cycle_pages)
_include(cycle_api)


@app.get("/", include_in_schema=False)
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/body", status_code=303)
    return RedirectResponse("/login", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=settings.port, reload=False)
