"""每日训练建议表（一天一条）：事实快照 + 一句判断 + 生成元信息。

与 AI 运动报告同属「离线单次结构化调用」：不写 agent_conversations，也不进 LangGraph checkpointer。
不设软删除：侧栏只展示当天一条，没有历史页与删除入口。
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
ADVICE_STATUSES = (STATUS_GENERATING, STATUS_READY, STATUS_FAILED)

MODE_AI = "ai"
MODE_RULE = "rule"
ADVICE_MODES = (MODE_AI, MODE_RULE)

VERDICT_SUITABLE = "适合"
VERDICT_MODERATE = "克制"
VERDICT_REST = "休息"
VERDICTS = (VERDICT_SUITABLE, VERDICT_MODERATE, VERDICT_REST)
# 结论 → 侧栏四档标签色（复用 base.css 的 tag-good / tag-average / tag-rest）
VERDICT_TAGS = {
    VERDICT_SUITABLE: "good",
    VERDICT_MODERATE: "average",
    VERDICT_REST: "rest",
}

FOCUS_AEROBIC = "有氧"
FOCUS_ANAEROBIC = "无氧"
FOCUS_MIXED = "有氧+无氧"
FOCUS_RECOVERY = "恢复"
FOCUSES = (FOCUS_AEROBIC, FOCUS_ANAEROBIC, FOCUS_MIXED, FOCUS_RECOVERY)

INTENSITY_LOW = "低"
INTENSITY_MID = "中"
INTENSITY_HIGH = "高"
INTENSITIES = (INTENSITY_LOW, INTENSITY_MID, INTENSITY_HIGH)


class DailyAdvice(Base):
    """每日训练建议主表：同一用户同一天一行。"""

    __tablename__ = "daily_advice"
    __table_args__ = (
        UniqueConstraint("user_id", "advice_date", name="uq_daily_advice_user_date"),
        CheckConstraint("status IN ('generating', 'ready', 'failed')", name="ck_daily_advice_status"),
        CheckConstraint("mode IN ('ai', 'rule')", name="ck_daily_advice_mode"),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('适合', '克制', '休息')", name="ck_daily_advice_verdict"
        ),
        CheckConstraint(
            "intensity IS NULL OR intensity IN ('低', '中', '高')", name="ck_daily_advice_intensity"
        ),
        {"comment": "每日训练建议（侧栏常驻；一天一条，事实快照 + 一句话判断）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="用户 FK，删除账号时级联删除",
    )
    advice_date: Mapped[date] = mapped_column(Date, nullable=False, comment="建议所属日（一天一条）")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=STATUS_GENERATING,
        server_default=STATUS_GENERATING,
        comment="状态：generating / ready / failed",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MODE_AI,
        server_default=MODE_AI,
        comment="生成方式：ai（模型生成）/ rule（无数据规则文案，不调模型）",
    )
    verdict: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="今日判断：适合 / 克制 / 休息（决定标签配色）"
    )
    focus: Mapped[str | None] = mapped_column(
        String(24), nullable=True, comment="训练方向：有氧 / 无氧 / 有氧+无氧 / 恢复"
    )
    intensity: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="建议强度：低 / 中 / 高"
    )
    body_parts: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="建议的健身部位数组（最多 2 个）"
    )
    text: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="侧栏三句正文（≤124 字）"
    )
    facts: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="生成时的事实快照（确定性计算，含硬约束）"
    )
    data_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="facts 的 SHA-256，用于同日重算判断"
    )
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="生成所用模型")
    prompt_version: Mapped[str | None] = mapped_column(
        String(48), nullable=True, comment="提示词版本 ID（如 daily_advice.v3）"
    )
    generation_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="模型耗时 ms"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="当天尝试次数（失败重试上限用）"
    )
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True, comment="失败错误码")
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="失败信息"
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="生成完成时间"
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
