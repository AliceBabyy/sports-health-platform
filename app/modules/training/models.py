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
    __table_args__ = (
        Index("ix_training_plans_user_date", "user_id", "plan_date"),
        {"comment": "健身训练计划/记录主表（状态机 planned|recorded，一日可多计划）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    plan_date: Mapped[date] = mapped_column(Date, nullable=False, comment="计划日期（一日可多计划，按 id 区分）")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned", comment="终态：planned|recorded")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注（计划/记录均可填）")  # 备注（计划/记录均可填）
    starttime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="开始训练时刻（仅记录态填写，2026-11-04 由 started_at 改名）")  # 开始训练时刻（仅记录态填写）
    endtime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="结束训练时刻（仅记录态填写，2026-11-04 由 saved_at 改名）")  # 结束训练时刻（仅记录态填写）
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="训练时长（秒，仅记录态；填了起止时间自动推导，也可手填）")  # 训练时长（秒，仅记录态）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")

    items: Mapped[list["TrainingPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="TrainingPlanItem.sort"
    )
    note: Mapped["TrainingNote | None"] = relationship(
        back_populates="plan", cascade="all, delete-orphan", uselist=False
    )


class TrainingPlanItem(Base):
    __tablename__ = "training_plan_items"
    __table_args__ = {"comment": "健身训练计划明细（动作/负荷/勾选，负荷可空）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属计划 FK（CASCADE）")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="行序")
    exercise_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="动作名称（唯一必填项）")
    body_part: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="部位（可空）")  # 部位，可空
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True, comment="重量 kg（可空）")  # 重量 kg，可空
    sets: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="组数（可空）")  # 组数，可空
    reps: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="每组个数，字符串（如 \"10+8+6\"，可空）")  # 每组个数，字符串，可空
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True, comment="期望突破重量（计划/记录均可填）")  # 期望突破重量，计划/记录均可填
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="完成勾选")

    plan: Mapped[TrainingPlan] = relationship(back_populates="items")


class TrainingNote(Base):
    """练后心得（2026-11 重构：结构化四字段；status_text 为旧版自由文本，保留列兼容历史数据）。"""
    __tablename__ = "training_notes"
    __table_args__ = {"comment": "健身训练心得（一条训练记录 1:1）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    plan_id: Mapped[int] = mapped_column(ForeignKey("training_plans.id", ondelete="CASCADE"), unique=True, nullable=False, comment="所属计划 FK，唯一（CASCADE）")
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="自我评估星级 1~5")  # 自我评估 1~5 星
    best_movement: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="最佳动作（最有感觉的动作）")  # 最佳动作（最有感觉的动作）
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True, comment="复盘/反思：发力感、质量、体能状态")  # 复盘/反思（发力感/质量/体能状态）
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True, comment="下一步想法：动作改动、重量突破")  # 下一步想法（动作改动/重量突破）
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="旧版心得文本（2026-11-03 前数据，新 UI 不读写）")  # 旧版心得文本（2026-11-03 前），仅历史数据用

    plan: Mapped[TrainingPlan] = relationship(back_populates="note")
