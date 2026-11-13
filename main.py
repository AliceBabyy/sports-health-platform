"""应用入口：app 创建、SessionMiddleware、静态/模板目录、路由注册、全局异常处理、启动端口 8010。"""
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.exceptions import register_exception_handlers
from app.core.templating import templates
from config import settings

# Windows 下 psycopg 异步驱动要求 SelectorEventLoop（默认 ProactorEventLoop 不兼容），
# 必须在 uvicorn 启动事件循环前切换；非 Windows 保持默认。
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建 checkpointer 连接池/框架表并编译图，挂到 app.state 供路由取用
    from app.modules.agent.runtime import close_agent_runtime, init_agent_runtime

    app.state.agent_runtime = await init_agent_runtime()
    try:
        yield
    finally:
        await close_agent_runtime(app.state.agent_runtime)


app = FastAPI(title="个人健康管理平台 · 体序 BODY ALMANAC", lifespan=lifespan)

# 会话中间件（SameSite=Lax 防 CSRF；Secure 由配置控制）
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)

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
from app.modules.state_record.router_pages import router as state_record_pages
from app.modules.state_record.router_api import router as state_record_api
from app.modules.profile.router_pages import router as profile_pages
from app.modules.profile.router_api import router as profile_api
from app.modules.overview.router_pages import router as overview_pages
from app.modules.overview.router_api import router as overview_api
from app.modules.electronic_trainer.router_api import router as electronic_trainer_api
from app.modules.agent.router_pages import router as agent_pages
from app.modules.agent.router_api import router as agent_api

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
_include(state_record_pages)
_include(state_record_api)
_include(profile_pages)
_include(profile_api)
_include(overview_pages)
_include(overview_api)
_include(electronic_trainer_api)
_include(agent_pages)
_include(agent_api)


@app.get("/", include_in_schema=False)
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/body", status_code=303)
    return RedirectResponse("/login", status_code=303)


if __name__ == "__main__":
    import asyncio

    import uvicorn

    # 命令行 `uvicorn main:app` 会在 import 本模块前用默认 ProactorEventLoop 建好 loop，
    # 顶层 policy 来不及生效。这里显式按当前 policy（Windows 下为 Selector）新建 loop 运行。
    config = uvicorn.Config("main:app", host=settings.host, port=settings.port, reload=False)
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())
