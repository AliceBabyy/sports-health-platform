"""定时任务页面路由：GET /system/scheduler（任务列表 + 新建/编辑 + 执行历史）。

前缀 /scheduler 为相对前缀，由 system 模块的 /system 命名空间聚合。
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.templating import render_page
from app.modules.auth.models import User
from app.modules.system.scheduler import service
from app.modules.system.scheduler.registry import catalog
from config import settings
from database import get_db

router = APIRouter(prefix="/scheduler")


@router.get("")
def scheduler_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    jobs = service.list_jobs(db)
    runs = service.history(db, None, 1, 12)
    return render_page(
        request,
        "system/scheduler.html",
        {
            "active": "scheduler",
            "jobs": jobs["list"],
            "catalog": catalog(),
            "runs": runs["list"],
            "default_timezone": settings.scheduler_timezone,
            "scheduler_enabled": settings.scheduler_enabled,
            "grace_seconds": settings.scheduler_misfire_grace_seconds,
        },
    )
