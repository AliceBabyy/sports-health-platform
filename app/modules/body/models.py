"""身材数据 4 表模型（拆分重构：基础 / 期望指标 / 围度 / 目标围度）。

表名约定：基础 body_basic_records、期望 body_basic_goal、
围度 body_dimensions_records、目标围度 body_dimensions_goal。
每表按 (user_id, record_date) 唯一（同日同组重复添加=覆盖当日该组）；
BMI 为派生值实时计算不落库。新增记录时未填字段沿用该字段最近一次非空值（service 层）。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class _BodyRowBase(Base):
    """公共列：id / user_id / record_date / 时间戳；每表 UNIQUE(user_id, record_date)。"""
    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    record_date: Mapped[date] = mapped_column(Date, nullable=False, comment="记录日期（一日一行）")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")


def _col(comment: str, precision: int = 6, scale: int = 2) -> Mapped[Decimal | None]:
    return mapped_column(Numeric(precision, scale), nullable=True, comment=comment)


class BodyBasicRecord(_BodyRowBase):
    """表1：身高 / 体重 / 体脂率。"""
    __tablename__ = "body_basic_records"
    __table_args__ = (
        UniqueConstraint("user_id", "record_date", name="uq_body_basic_user_date"),
        {"comment": "身材基础记录（身高/体重/体脂率）"},
    )

    height_cm: Mapped[Decimal | None] = _col("身高")     # 身高
    weight_kg: Mapped[Decimal | None] = _col("体重", 10, 2)     # 体重（任意数值、保留两位小数）
    body_fat_pct: Mapped[Decimal | None] = _col("体脂率 %")  # 体脂率 %


class BodyBasicGoalRecord(_BodyRowBase):
    """表2：期望体重 / 期望体脂率。"""
    __tablename__ = "body_basic_goal"
    __table_args__ = (
        UniqueConstraint("user_id", "record_date", name="uq_body_basic_goal_user_date"),
        {"comment": "身材期望指标（目标体重/目标体脂率）"},
    )

    target_weight_kg: Mapped[Decimal | None] = _col("目标体重", 10, 2)    # 目标体重（任意数值、保留两位小数）
    target_body_fat_pct: Mapped[Decimal | None] = _col("目标体脂率 %") # 目标体脂率 %


class BodyDimensionsRecord(_BodyRowBase):
    """表3：颈围 / 肩宽 / 臂围 / 胸围 / 腰围 / 臀围 / 大腿围 / 小腿围。"""
    __tablename__ = "body_dimensions_records"
    __table_args__ = (
        UniqueConstraint("user_id", "record_date", name="uq_body_dimensions_records_user_date"),
        {"comment": "身材围度记录（颈/肩/臂/胸/腰/臀/大腿/小腿围）"},
    )

    neck_cm: Mapped[Decimal | None] = _col("颈围")           # 颈围
    shoulder_width_cm: Mapped[Decimal | None] = _col("肩宽") # 肩宽
    arm_circ_cm: Mapped[Decimal | None] = _col("臂围")       # 臂围
    chest_circ_cm: Mapped[Decimal | None] = _col("胸围")     # 胸围
    waist_circ_cm: Mapped[Decimal | None] = _col("腰围")     # 腰围
    hip_circ_cm: Mapped[Decimal | None] = _col("臀围")       # 臀围
    thigh_circ_cm: Mapped[Decimal | None] = _col("大腿围")   # 大腿围
    calf_circ_cm: Mapped[Decimal | None] = _col("小腿围")    # 小腿围


class BodyDimensionsGoalRecord(_BodyRowBase):
    """表4：目标臂围 / 目标胸围 / 目标腰围 / 目标臀围 / 目标大腿围 / 目标小腿围。"""
    __tablename__ = "body_dimensions_goal"
    __table_args__ = (
        UniqueConstraint("user_id", "record_date", name="uq_body_dimensions_goal_user_date"),
        {"comment": "身材目标围度（目标臂/胸/腰/臀/大腿/小腿围）"},
    )

    target_arm_circ_cm: Mapped[Decimal | None] = _col("目标臂围")    # 目标臂围
    target_chest_circ_cm: Mapped[Decimal | None] = _col("目标胸围")  # 目标胸围
    target_waist_circ_cm: Mapped[Decimal | None] = _col("目标腰围")  # 目标腰围
    target_hip_circ_cm: Mapped[Decimal | None] = _col("目标臀围")    # 目标臀围
    target_thigh_circ_cm: Mapped[Decimal | None] = _col("目标大腿围")  # 目标大腿围
    target_calf_circ_cm: Mapped[Decimal | None] = _col("目标小腿围")  # 目标小腿围
