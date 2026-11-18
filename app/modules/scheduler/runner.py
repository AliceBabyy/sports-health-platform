"""任务执行统一入口：定时触发、页面手动执行、命令行补跑都走 run_task。

职责：参数校验 → 同域 advisory lock 互斥 → 写 job_runs → 调注册表里的函数 → 回写任务统计。
任何异常都收敛为失败结果，不抛回调度线程（否则会让 APScheduler 记录大量错误日志）。
"""
import logging
import time
from datetime import datetime

from sqlalchemy import text

from app.core.exceptions import AppError
from app.modules.scheduler.models import (
    RUN_FAILED,
    RUN_RUNNING,
    RUN_SKIPPED,
    RUN_SUCCESS,
    SOURCE_SCHEDULE,
    JobRun,
    ScheduledJob,
)
from app.modules.scheduler.registry import REGISTRY, validate_params
from database import SessionLocal, engine

logger = logging.getLogger("scheduler")
MESSAGE_MAX = 500


def _acquire_lock(conn, scope: str) -> bool:
    """同一 lock_scope 的任务互斥执行；非 PostgreSQL（如测试用 SQLite）直接放行。"""
    if engine.dialect.name != "postgresql":
        return True
    return bool(
        conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:scope))"), {"scope": scope}).scalar()
    )


def _release_lock(conn, scope: str) -> None:
    if engine.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_unlock(hashtext(:scope))"), {"scope": scope})


def _insert_run(job_id: int | None, job_key: str, source: str, started_at: datetime) -> int | None:
    db = SessionLocal()
    try:
        run = JobRun(
            job_id=job_id, job_key=job_key, source=source, status=RUN_RUNNING, started_at=started_at
        )
        db.add(run)
        db.commit()
        return run.id
    except Exception:
        logger.exception("写入执行记录失败 job_key=%s", job_key)
        db.rollback()
        return None
    finally:
        db.close()


def _close_run(
    run_id: int | None,
    job_id: int | None,
    status: str,
    message: str,
    detail: dict | None,
    started_at: datetime,
    duration_ms: int,
) -> None:
    db = SessionLocal()
    try:
        if run_id is not None:
            run = db.get(JobRun, run_id)
            if run is not None:
                run.status = status
                run.finished_at = datetime.now()
                run.duration_ms = duration_ms
                run.message = message[:MESSAGE_MAX]
                run.detail = detail
        if job_id is not None:
            job = db.get(ScheduledJob, job_id)
            if job is not None:
                job.last_run_at = started_at
                job.last_status = status
                job.last_message = message[:MESSAGE_MAX]
                job.last_duration_ms = duration_ms
                job.run_count = (job.run_count or 0) + 1
        db.commit()
    except Exception:
        logger.exception("回写执行结果失败 job_key=%s", job_id)
        db.rollback()
    finally:
        db.close()


def run_task(
    job_key: str,
    params: dict | None = None,
    source: str = SOURCE_SCHEDULE,
    job_id: int | None = None,
) -> dict:
    """执行一个任务并返回 {status, message, duration_ms, detail}。"""
    started_at = datetime.now()
    started = time.monotonic()

    spec = REGISTRY.get(job_key)
    if spec is None:
        message = f"任务不存在：{job_key}"
        logger.error(message)
        return {"status": RUN_FAILED, "message": message, "duration_ms": 0, "detail": None}

    try:
        clean_params = validate_params(spec, params or {})
    except AppError as exc:
        logger.warning("任务参数无效 job_key=%s：%s", job_key, exc.message)
        _close_run(None, job_id, RUN_FAILED, exc.message, None, started_at, 0)
        return {"status": RUN_FAILED, "message": exc.message, "duration_ms": 0, "detail": None}

    scope = spec.lock_scope or job_key
    lock_conn = engine.connect()
    run_id = None
    try:
        if not _acquire_lock(lock_conn, scope):
            message = "同组任务正在执行，本次跳过"
            logger.info("任务互斥跳过 job_key=%s", job_key)
            run_id = _insert_run(job_id, job_key, source, started_at)
            duration = int((time.monotonic() - started) * 1000)
            _close_run(run_id, job_id, RUN_SKIPPED, message, None, started_at, duration)
            return {"status": RUN_SKIPPED, "message": message, "duration_ms": duration, "detail": None}

        run_id = _insert_run(job_id, job_key, source, started_at)

        db = SessionLocal()
        try:
            detail = spec.func(db, clean_params) or {}
        finally:
            db.close()

        duration = int((time.monotonic() - started) * 1000)
        message = _summary(job_key, detail)
        logger.info("任务完成 job_key=%s：%s（%dms）", job_key, message, duration)
        _close_run(run_id, job_id, RUN_SUCCESS, message, detail, started_at, duration)
        return {"status": RUN_SUCCESS, "message": message, "duration_ms": duration, "detail": detail}
    except Exception as exc:
        duration = int((time.monotonic() - started) * 1000)
        message = f"{type(exc).__name__}：{exc}"
        logger.exception("任务失败 job_key=%s", job_key)
        _close_run(run_id, job_id, RUN_FAILED, message, None, started_at, duration)
        return {"status": RUN_FAILED, "message": message, "duration_ms": duration, "detail": None}
    finally:
        try:
            _release_lock(lock_conn, scope)
        finally:
            lock_conn.close()


def _summary(job_key: str, detail: dict) -> str:
    """把任务返回的结构化明细压成一句可读摘要。"""
    if "generated" in detail:
        return (
            f"扫描 {detail.get('scanned', 0)} 个周期，"
            f"生成 {detail.get('generated', 0)} 份，"
            f"失败 {detail.get('failed', 0)} 份"
        )
    keys = "、".join(str(key) for key in detail.keys())
    return f"{job_key} 执行完成" + (f"（{keys}）" if keys else "")
