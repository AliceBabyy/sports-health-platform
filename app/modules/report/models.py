"""AI 运动报告表（周报/月报）：事实快照 + AI 叙事 + 生成元信息。

一份报告 = 一个周期一行，同一用户同一周期唯一；周报按周一、月报按自然月。
删除采用软删除（status=deleted），避免定时任务把用户主动删掉的报告重新生成回来。
报告是独立归档产物：不写 agent_conversations，也不进 LangGraph checkpointer。
"""
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

REPORT_TYPE_WEEKLY = "weekly"
REPORT_TYPE_MONTHLY = "monthly"
REPORT_TYPES = (REPORT_TYPE_WEEKLY, REPORT_TYPE_MONTHLY)
REPORT_TYPE_LABELS = {
    REPORT_TYPE_WEEKLY: "周报",
    REPORT_TYPE_MONTHLY: "月报",
}

STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"
REPORT_STATUSES = (STATUS_GENERATING, STATUS_READY, STATUS_FAILED, STATUS_DELETED)

MODE_AI = "ai"
MODE_RULE = "rule"
REPORT_MODES = (MODE_AI, MODE_RULE)


class Report(Base):
    """周报/月报主表：一份周期报告一行。"""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("user_id", "period_type", "period_start", name="uq_reports_user_period"),
        CheckConstraint("period_type IN ('weekly', 'monthly')", name="ck_reports_type"),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed', 'deleted')", name="ck_reports_status"
        ),
        CheckConstraint("mode IN ('ai', 'rule')", name="ck_reports_mode"),
        Index("ix_reports_user_period", "user_id", "period_type", text("period_start DESC")),
        {"comment": "AI 运动报告（周报/月报；事实快照 + 叙事 + 生成元信息）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户 FK，删除账号时级联删除",
    )
    period_type: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="周期类型：weekly（周报）/ monthly（月报）"
    )
    period_start: Mapped[date] = mapped_column(
        Date, nullable=False, comment="周期起始日（周报=周一，月报=1 日）"
    )
    period_end: Mapped[date] = mapped_column(
        Date, nullable=False, comment="周期结束日（周报=周日，月报=月末）"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=STATUS_GENERATING,
        server_default=STATUS_GENERATING,
        comment="状态：generating / ready / failed / deleted",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MODE_AI,
        server_default=MODE_AI,
        comment="生成方式：ai（模型叙事）/ rule（无数据规则文案，不调模型）",
    )
    headline: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="一句话主题（列表展示冗余）"
    )
    facts: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="生成时的事实快照（确定性计算，含指标字典）"
    )
    narrative: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="AI 结构化叙事（headline/summary/highlights 等）"
    )
    data_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="facts 的 SHA-256，用于过期检测"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成所用模型"
    )
    prompt_version: Mapped[str | None] = mapped_column(
        String(48), nullable=True, comment="提示词版本 ID（如 weekly_report.v1）"
    )
    generation_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="生成耗时 ms"
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="自动生成尝试次数（定时任务重试上限用）",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(48), nullable=True, comment="失败错误码"
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="失败信息"
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="生成完成时间"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="软删除时间；NULL 表示未删除"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间（ORM onupdate 自动刷新；也用于判断 generating 是否卡死）",
    )
