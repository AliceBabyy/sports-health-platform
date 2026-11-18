"""定时任务表：任务定义（scheduled_jobs）与执行记录（job_runs）。

scheduled_jobs 是调度器的唯一事实源：进程启动时据此 reconcile 重建内存作业，
不使用 APScheduler 自带的 SQLAlchemyJobStore，避免任务定义出现两套状态互相覆盖。
错过执行窗口不补跑（misfire 超时记为 skipped），由用户在管理页手动执行。
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

TRIGGER_CRON = "cron"
TRIGGER_DATE = "date"
TRIGGER_INTERVAL = "interval"
TRIGGER_TYPES = (TRIGGER_CRON, TRIGGER_DATE, TRIGGER_INTERVAL)

RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"
RUN_SKIPPED = "skipped"
RUN_STATUSES = (RUN_RUNNING, RUN_SUCCESS, RUN_FAILED, RUN_SKIPPED)

SOURCE_SCHEDULE = "schedule"
SOURCE_MANUAL = "manual"
SOURCE_CLI = "cli"
RUN_SOURCES = (SOURCE_SCHEDULE, SOURCE_MANUAL, SOURCE_CLI)
SOURCE_LABELS = {SOURCE_SCHEDULE: "定时", SOURCE_MANUAL: "手动", SOURCE_CLI: "命令行"}
STATUS_LABELS = {
    RUN_RUNNING: "执行中",
    RUN_SUCCESS: "成功",
    RUN_FAILED: "失败",
    RUN_SKIPPED: "已跳过",
}


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    """把常量元组渲染成 CHECK 用的 IN 子句，避免约束与常量各写一份。"""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ScheduledJob(Base):
    """一条定时任务定义：job_key 指向代码注册表，表达式决定何时触发。"""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        CheckConstraint(
            _in_clause("trigger_type", TRIGGER_TYPES), name="ck_scheduled_jobs_trigger"
        ),
        Index("ix_scheduled_jobs_key", "job_key"),
        {"comment": "定时任务定义（job_key 指向代码注册表；表达式为本表唯一事实源）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    job_key: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="任务键，对应 app/modules/scheduler/registry.py"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务显示名")
    trigger_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="触发类型：cron / date / interval"
    )
    trigger_expr: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="触发表达式（cron 五段式 / interval 如 10m / date 如 2026-11-20 15:40）",
    )
    timezone: Mapped[str] = mapped_column(
        String(48), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai",
        comment="触发时区（默认 Asia/Shanghai，避免服务器 UTC 时区错位）",
    )
    params: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
        comment="任务参数 JSON（结构由 registry 的参数 schema 约束）",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="是否启用；禁用时不注册内存作业",
    )
    misfire_grace_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="错过宽限秒数；可空，空则用全局 settings.scheduler_misfire_grace_seconds",
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="下次触发时间（由调度器回写，服务未运行时为空）"
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近一次执行时间"
    )
    last_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="最近一次结果：running / success / failed / skipped"
    )
    last_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="最近一次结果摘要或失败原因"
    )
    last_duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="最近一次耗时 ms"
    )
    run_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="累计执行次数（含手动）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )


class JobRun(Base):
    """一次执行记录：定时触发、页面手动执行、命令行补跑都落一行。"""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            _in_clause("status", RUN_STATUSES), name="ck_job_runs_status"
        ),
        CheckConstraint(
            _in_clause("source", RUN_SOURCES), name="ck_job_runs_source"
        ),
        Index("ix_job_runs_job", "job_id", "started_at"),
        {"comment": "定时任务执行记录（触发来源、结果、耗时与摘要）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scheduled_jobs.id", ondelete="CASCADE"),
        nullable=True,
        comment="所属任务 FK，可空（命令行执行未挂任务定义时为空）",
    )
    job_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务键")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="触发来源：schedule / manual / cli"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="结果：running / success / failed / skipped"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="开始时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="结束时间"
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="耗时 ms"
    )
    message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="结果摘要或失败原因"
    )
    detail: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="执行明细 JSON（如生成份数、失败条目）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
