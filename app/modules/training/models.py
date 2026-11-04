"""健身训练三表（需求 9.1）：training_plans / training_plan_items / training_notes。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TrainingPlan(Base):
    """训练计划/记录主表：一日可多个计划（TR-03 整改，按 id 区分，无 (user_id, plan_date) 唯一约束）。"""
    __tablename__ = "training_plans"
    __table_args__ = (Index("ix_training_plans_user_date", "user_id", "plan_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 备注（计划/记录均可填）
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 开始训练时刻（2026-11-03 起不再写入，仅历史 recorded 时长计算用）
    saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 完成训练时刻
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["TrainingPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="TrainingPlanItem.sort"
    )
    note: Mapped["TrainingNote | None"] = relationship(
        back_populates="plan", cascade="all, delete-orphan", uselist=False
    )


class TrainingPlanItem(Base):
    __tablename__ = "training_plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exercise_name: Mapped[str] = mapped_column(String(128), nullable=False)
    body_part: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 部位，可空
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)  # 重量 kg，可空
    sets: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 组数，可空
    reps: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 每组个数，字符串，可空
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)  # 期望突破重量，计划/记录均可填
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    plan: Mapped[TrainingPlan] = relationship(back_populates="items")


class TrainingNote(Base):
    """练后心得（2026-11 重构：结构化四字段；status_text 为旧版自由文本，保留列兼容历史数据）。"""
    __tablename__ = "training_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), unique=True, nullable=False)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 自我评估 1~5 星
    best_movement: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 最佳动作（最有感觉的动作）
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)  # 复盘/反思（发力感/质量/体能状态）
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True)  # 下一步想法（动作改动/重量突破）
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 旧版心得文本（2026-11-03 前），仅历史数据用

    plan: Mapped[TrainingPlan] = relationship(back_populates="note")
