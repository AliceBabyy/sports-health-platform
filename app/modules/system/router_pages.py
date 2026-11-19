"""系统管理区页面命名空间（/system）：管理员页面的统一挂载点。

子模块只声明自身相对前缀的 router，在此聚合注册，保证页面与 API 前缀同构。
"""
from fastapi import APIRouter

from app.modules.system.scheduler.router_pages import router as scheduler_pages
from app.modules.system.personas.router_pages import router as personas_pages

router = APIRouter(prefix="/system")
router.include_router(scheduler_pages)
router.include_router(personas_pages)
