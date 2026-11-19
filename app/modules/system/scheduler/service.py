"""定时任务服务层：任务 CRUD、启动 reconcile、下次执行回写、执行历史。

所有写操作完成后都会把该任务同步到内存调度器，保证页面改动即时生效，不需要重启服务。
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.pagination import paginate
from app.modules.system.scheduler import engine as sched
from app.modules.system.scheduler.models import (
    RUN_SKIPPED,
    SOURCE_LABELS,
    SOURCE_MANUAL,
    STATUS_LABELS,
    JobRun,
    ScheduledJob,
)
from app.modules.system.scheduler.registry import REGISTRY, get_spec, validate_params
from app.modules.system.scheduler.triggers import describe, parse_trigger
from config import settings
from database import SessionLocal

logger = logging.getLogger("scheduler")


# ---------- 启动重建 ----------

def bootstrap() -> None:
    """服务启动时调用：补默认任务 + 重建内存作业。"""
    db = SessionLocal()
    try:
        seed_defaults(db)
    except Exception:
        logger.exception("初始化默认任务失败")
        db.rollback()
    finally:
        db.close()
    reconcile()


def seed_defaults(db: Session) -> int:
    """注册表里带默认排期的任务，库里没有就补一条（幂等）。"""
    created = 0
    for spec in REGISTRY.values():
        if not spec.default_trigger_type:
            continue
        if db.query(ScheduledJob).filter(ScheduledJob.job_key == spec.key).first():
            continue
        db.add(
            ScheduledJob(
                job_key=spec.key,
                name=spec.name,
                trigger_type=spec.default_trigger_type,
                trigger_expr=spec.default_trigger_expr or "",
                timezone=settings.scheduler_timezone,
            )
        )
        created += 1
    if created:
        db.commit()
        logger.info("已补默认定时任务 %d 条", created)
    return created


def reconcile() -> int:
    """按数据库全量重建内存作业，并移除库里已不存在的作业。返回注册条数。"""
    sched_obj = sched.get_scheduler()
    if sched_obj is None:
        return 0
    db = SessionLocal()
    try:
        rows = db.query(ScheduledJob).order_by(ScheduledJob.id).all()
        wanted = set()
        for row in rows:
            if row.enabled:
                sched.sync_job(row, sched_obj)
                wanted.add(sched.job_id(row.id))
            else:
                sched.remove_job(row.id, sched_obj)
        for job in sched_obj.get_jobs():
            if job.id not in wanted:
                sched_obj.remove_job(job.id)
        for row in rows:
            row.next_run_at = sched.next_run_time(row.id, sched_obj)
        db.commit()
        logger.info("调度任务已重建：%d 条启用", len(wanted))
        return len(wanted)
    except Exception:
        logger.exception("重建调度任务失败")
        db.rollback()
        return 0
    finally:
        db.close()


def refresh_schedule(job_pk: int) -> None:
    """执行完成后回写下次触发时间。"""
    db = SessionLocal()
    try:
        row = db.get(ScheduledJob, job_pk)
        if row is not None:
            row.next_run_at = sched.next_run_time(job_pk)
            db.commit()
    except Exception:
        logger.exception("回写下次执行时间失败 job_id=%s", job_pk)
        db.rollback()
    finally:
        db.close()


def mark_missed(job_pk: int) -> None:
    """错过执行窗口：不补跑，只记一条 skipped 记录并更新任务状态。"""
    started_at = datetime.now()
    db = SessionLocal()
    try:
        row = db.get(ScheduledJob, job_pk)
        if row is None:
            return
        message = "错过执行窗口，未补跑（可在页面手动执行）"
        db.add(
            JobRun(
                job_id=row.id,
                job_key=row.job_key,
                source="schedule",
                status=RUN_SKIPPED,
                started_at=started_at,
                finished_at=started_at,
                message=message,
            )
        )
        row.last_run_at = started_at
        row.last_status = RUN_SKIPPED
        row.last_message = message
        row.next_run_at = sched.next_run_time(job_pk)
        db.commit()
        logger.warning("任务错过执行窗口 job_id=%s", job_pk)
    except Exception:
        logger.exception("记录错过事件失败 job_id=%s", job_pk)
        db.rollback()
    finally:
        db.close()


# ---------- 查询 ----------

def _payload(row: ScheduledJob) -> dict:
    spec = REGISTRY.get(row.job_key)
    next_run = sched.next_run_time(row.id) or row.next_run_at
    return {
        "id": row.id,
        "job_key": row.job_key,
        "name": row.name,
        "job_desc": spec.desc if spec else "代码中已移除该任务键",
        "available": spec is not None,
        "trigger_type": row.trigger_type,
        "trigger_expr": row.trigger_expr,
        "trigger_display": describe(row.trigger_type, row.trigger_expr),
        "timezone": row.timezone,
        "params": row.params or {},
        "enabled": row.enabled,
        "misfire_grace_seconds": row.misfire_grace_seconds,
        "next_run_at": next_run.isoformat(timespec="minutes") if next_run else None,
        "last_run_at": row.last_run_at.isoformat(timespec="seconds") if row.last_run_at else None,
        "last_status": row.last_status,
        "last_status_label": STATUS_LABELS.get(row.last_status or "", "未执行"),
        "last_message": row.last_message,
        "last_duration_ms": row.last_duration_ms or 0,
        "run_count": row.run_count or 0,
    }


def list_jobs(db: Session) -> dict:
    rows = db.query(ScheduledJob).order_by(ScheduledJob.id).all()
    items = [_payload(row) for row in rows]
    return {"list": items, "total": len(items)}


def history(db: Session, job_pk: int | None = None, page: int = 1, page_size: int = 20) -> dict:
    query = db.query(JobRun)
    if job_pk is not None:
        query = query.filter(JobRun.job_id == job_pk)
    result = paginate(query, page, page_size, JobRun.started_at.desc())
    names = {row.id: row.name for row in db.query(ScheduledJob).all()}
    result["list"] = [
        {
            "id": run.id,
            "job_id": run.job_id,
            "job_key": run.job_key,
            "job_name": names.get(run.job_id) or run.job_key,
            "source": run.source,
            "source_label": SOURCE_LABELS.get(run.source, run.source),
            "status": run.status,
            "status_label": STATUS_LABELS.get(run.status, run.status),
            "started_at": run.started_at.isoformat(timespec="seconds") if run.started_at else None,
            "duration_ms": run.duration_ms or 0,
            "message": run.message,
        }
        for run in result["list"]
    ]
    return result


# ---------- 写操作 ----------

def _validate(spec, trigger_type: str, trigger_expr: str, timezone: str, params: dict) -> None:
    parse_trigger(trigger_type, trigger_expr, timezone)
    validate_params(spec, params)


def create_job(db: Session, payload) -> dict:
    spec = get_spec(payload.job_key)
    timezone = payload.timezone or settings.scheduler_timezone
    _validate(spec, payload.trigger_type, payload.trigger_expr, timezone, payload.params)
    row = ScheduledJob(
        job_key=spec.key,
        name=payload.name or spec.name,
        trigger_type=payload.trigger_type,
        trigger_expr=payload.trigger_expr.strip(),
        timezone=timezone,
        params=payload.params or {},
        enabled=payload.enabled,
        misfire_grace_seconds=payload.misfire_grace_seconds,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    sched.sync_job(row)
    _refresh_after_write(db, row)
    return _payload(row)


def update_job(db: Session, job_pk: int, payload) -> dict:
    row = db.get(ScheduledJob, job_pk)
    if row is None:
        raise AppError(404, "任务不存在")
    spec = REGISTRY.get(row.job_key)
    if spec is None:
        raise AppError(400, "该任务键已从代码中移除，无法修改")

    trigger_type = payload.trigger_type or row.trigger_type
    trigger_expr = payload.trigger_expr if payload.trigger_expr is not None else row.trigger_expr
    timezone = payload.timezone or row.timezone
    params = payload.params if payload.params is not None else (row.params or {})
    _validate(spec, trigger_type, trigger_expr, timezone, params)

    row.name = payload.name or row.name
    row.trigger_type = trigger_type
    row.trigger_expr = trigger_expr.strip()
    row.timezone = timezone
    row.params = params
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.misfire_grace_seconds is not None:
        row.misfire_grace_seconds = payload.misfire_grace_seconds
    db.commit()
    db.refresh(row)
    sched.sync_job(row)
    _refresh_after_write(db, row)
    return _payload(row)


def delete_job(db: Session, job_pk: int) -> dict:
    row = db.get(ScheduledJob, job_pk)
    if row is None:
        raise AppError(404, "任务不存在")
    sched.remove_job(job_pk)
    db.delete(row)
    db.commit()
    return {"ok": True}


def run_now(job_pk: int) -> dict:
    """页面「立即执行」：同步跑一次（HTTP 层放线程池，避免阻塞事件循环）。"""
    db = SessionLocal()
    try:
        row = db.get(ScheduledJob, job_pk)
        if row is None:
            raise AppError(404, "任务不存在")
        job_key, params = row.job_key, dict(row.params or {})
    finally:
        db.close()

    from app.modules.system.scheduler.runner import run_task

    result = run_task(job_key, params, source=SOURCE_MANUAL, job_id=job_pk)

    db = SessionLocal()
    try:
        row = db.get(ScheduledJob, job_pk)
        if row is not None:
            row.next_run_at = sched.next_run_time(job_pk)
            db.commit()
    finally:
        db.close()
    return result


def _refresh_after_write(db: Session, row: ScheduledJob) -> None:
    """写操作后同步 next_run_at，页面立刻能看到新时间。"""
    row.next_run_at = sched.next_run_time(row.id)
    db.commit()
