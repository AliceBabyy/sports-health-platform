"""定时任务 API（/api/scheduler）：任务列表、新建、更新、删除、立即执行、执行历史。"""
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.deps import get_current_user
from app.modules.auth.models import User
from app.modules.scheduler import service
from app.modules.scheduler.schemas import JobCreateIn, JobUpdateIn
from database import get_db

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """任务列表：表达式、下次执行、上次结果与累计次数。"""
    return service.list_jobs(db)


@router.post("/jobs", status_code=201)
def create_job(
    payload: JobCreateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新建任务；job_key 必须是注册表里存在的任务，表达式在此校验。"""
    return service.create_job(db, payload)


@router.patch("/jobs/{job_id}")
def update_job(
    job_id: int,
    payload: JobUpdateIn = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新任务（改表达式 / 启停 / 改名）；保存后立即同步到内存调度器。"""
    return service.update_job(db, job_id, payload)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除任务定义与其执行记录。"""
    return service.delete_job(db, job_id)


@router.post("/jobs/{job_id}/run")
async def run_job(
    job_id: int,
    user: User = Depends(get_current_user),
):
    """立即执行一次（同步跑在线程池里，返回本次结果摘要）。"""
    return await run_in_threadpool(service.run_now, job_id)


@router.get("/runs")
def list_runs(
    job_id: int | None = Query(None),
    page: int = Query(1),
    page_size: int = Query(20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """执行历史：按开始时间倒序分页，可按任务过滤。"""
    return service.history(db, job_id, page, page_size)
