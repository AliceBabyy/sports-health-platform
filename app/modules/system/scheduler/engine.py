"""进程内调度器：BackgroundScheduler + 内存作业，启动时按 scheduled_jobs 重建。

设计取舍：
- 不用 APScheduler 自带的 SQLAlchemyJobStore：任务定义以 scheduled_jobs 为唯一事实源，
  启动 reconcile 重建内存作业，避免 job store 与业务表两套状态互相覆盖。
- 错过不补：misfire_grace_time 默认 300 秒；超出宽限的触发由 EVENT_JOB_MISSED 记为 skipped，
  由用户在管理页「立即执行」手动补齐。
"""
import logging
from datetime import datetime, timedelta

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.exceptions import AppError
from app.modules.system.scheduler.runner import run_task
from app.modules.system.scheduler.triggers import get_tz
from config import settings

logger = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler | None = None
ADVICE_CATCHUP_JOB_ID = "advice-catchup"


def job_id(job_pk: int) -> str:
    """内存作业 id：与表主键一一对应，便于事件回写。"""
    return f"job-{job_pk}"


def pk_of(aps_job_id: str) -> int | None:
    try:
        return int(str(aps_job_id).split("-", 1)[1])
    except (IndexError, ValueError):
        return None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def start_scheduler() -> BackgroundScheduler | None:
    """启动调度器并重建作业；scheduler_enabled=false（测试/排障）时不启动。"""
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("调度器未启用（scheduler_enabled=false）")
        return None
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(
        timezone=get_tz(settings.scheduler_timezone),
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": settings.scheduler_misfire_grace_seconds,
        },
    )
    sched.add_listener(_on_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    sched.start()
    _scheduler = sched

    from app.modules.system.scheduler import service

    service.bootstrap()
    _schedule_advice_catchup(sched)
    logger.info("调度器已启动，时区 %s", settings.scheduler_timezone)
    return sched


def _schedule_advice_catchup(sched: BackgroundScheduler) -> None:
    """启动补跑：延迟一段时间补齐当天缺失的每日训练建议。

    这是对「错过不补」的显式例外——侧栏常驻位空着没有价值。
    只补当天缺 ready 行的账号，直接调 service（不经过 run_task，故不写 job_runs）。
    """
    if not settings.advice_auto_enabled:
        return
    delay = settings.advice_startup_catchup_seconds
    if delay <= 0:
        return
    run_date = datetime.now(get_tz(settings.scheduler_timezone)) + timedelta(seconds=delay)
    try:
        sched.add_job(
            _advice_catchup,
            trigger="date",
            run_date=run_date,
            id=ADVICE_CATCHUP_JOB_ID,
            replace_existing=True,
            misfire_grace_time=settings.scheduler_misfire_grace_seconds,
        )
    except Exception:
        logger.exception("每日训练建议启动补跑注册失败")


def _advice_catchup() -> None:
    from app.modules.daily_advice.service import generate_due
    from database import SessionLocal

    db = SessionLocal()
    try:
        result = generate_due(db)
        logger.info("每日训练建议启动补跑完成：%s", result)
    except Exception:
        logger.exception("每日训练建议启动补跑失败")
    finally:
        db.close()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("调度器已停止")


def sync_job(row, sched: BackgroundScheduler | None = None) -> None:
    """按一行任务定义注册/更新内存作业；禁用则移除。表达式非法时只记日志不注册。"""
    sched = sched or _scheduler
    if sched is None:
        return
    if not row.enabled:
        remove_job(row.id, sched)
        return
    try:
        trigger = _trigger(row)
    except AppError as exc:
        logger.warning("任务表达式非法，未注册 job_id=%s：%s", row.id, exc.message)
        remove_job(row.id, sched)
        return
    sched.add_job(
        run_task,
        trigger=trigger,
        id=job_id(row.id),
        name=row.name,
        replace_existing=True,
        kwargs={
            "job_key": row.job_key,
            "params": dict(row.params or {}),
            "source": "schedule",
            "job_id": row.id,
        },
        misfire_grace_time=row.misfire_grace_seconds
        if row.misfire_grace_seconds is not None
        else settings.scheduler_misfire_grace_seconds,
    )


def _trigger(row):
    from app.modules.system.scheduler.triggers import parse_trigger

    return parse_trigger(row.trigger_type, row.trigger_expr, row.timezone)


def remove_job(job_pk: int, sched: BackgroundScheduler | None = None) -> None:
    sched = sched or _scheduler
    if sched is None:
        return
    try:
        sched.remove_job(job_id(job_pk))
    except Exception:  # 作业不存在属正常
        pass


def next_run_time(job_pk: int, sched: BackgroundScheduler | None = None):
    """内存作业的下次触发时间；调度器未启动返回 None。"""
    sched = sched or _scheduler
    if sched is None:
        return None
    job = sched.get_job(job_id(job_pk))
    return getattr(job, "next_run_time", None) if job is not None else None


def _on_event(event) -> None:
    """执行完成/错过事件：回写 next_run_at，并把错过记为 skipped 留痕。"""
    job_pk = pk_of(event.job_id)
    if job_pk is None:
        return
    try:
        from app.modules.system.scheduler import service

        if event.code == EVENT_JOB_MISSED:
            service.mark_missed(job_pk)
        else:
            service.refresh_schedule(job_pk)
    except Exception:
        logger.exception("调度事件回写失败 job_id=%s", event.job_id)
