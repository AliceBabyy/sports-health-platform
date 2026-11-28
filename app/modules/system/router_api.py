"""系统管理区 API 命名空间（/api/system）：管理员功能的统一挂载点。

子模块只声明自身相对前缀的 router，在此聚合注册；后续新增管理员接口（用户管理、
操作日志等）只需 include 进来，main.py 与 URL 前缀边界均无需改动。
"""
from fastapi import APIRouter

from app.modules.system.scheduler.router_api import router as scheduler_api
from app.modules.system.personas.router_api import router as personas_api
from app.modules.system.skills.router_api import router as skills_api
from app.modules.system.ai_config.router_api import router as ai_config_api

router = APIRouter(prefix="/api/system", tags=["system"])
router.include_router(scheduler_api)
router.include_router(personas_api)
router.include_router(skills_api)
router.include_router(ai_config_api)
