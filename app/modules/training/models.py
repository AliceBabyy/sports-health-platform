"""健身训练三表（需求 9.1）：training_plans / training_plan_items / training_notes。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TrainingPlan(Base):
    __tablename__ = "training_plans"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", name="uq_training_plan_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")  # planned | recorded
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 开始训练时刻（仅计时路径）
    saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 保存记录时刻
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
    __tablename__ = "training_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), unique=True, nullable=False)
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 心得文本，可空
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1~5

    plan: Mapped[TrainingPlan] = relationship(back_populates="note")
