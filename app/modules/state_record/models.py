"""状态记录三表：食欲 / 肌肉疼痛 / 炎症（按天记录，每类每天一行）。

本模块不是运动模块，不套用 SportRecordMixin（无计划态、起止时间、心率、热量等字段）；
统一字段：id / user_id / date / star（1~5，可空）/ remark（可空）/ created_at / updated_at。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# ---------- 记录类型（模块专属枚举） ----------
TYPE_APPETITE = "appetite"
TYPE_MYALGIA = "myalgia"
TYPE_INFLAMMATION = "inflammation"

STATE_TYPES = (TYPE_APPETITE, TYPE_MYALGIA, TYPE_INFLAMMATION)
STATE_TYPE_LABELS = {
    TYPE_APPETITE: "食欲",
    TYPE_MYALGIA: "肌肉疼痛",
    TYPE_INFLAMMATION: "炎症",
}


class _StateRecordMixin:
    """三表共用字段（模块内私有；与运动记录契约无关）。"""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        comment="用户 FK，删除账号时级联删除",
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, comment="记录日期（同类一天一行）")
    star: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="星级 1~5，可空")
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="描述")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）"
    )


class AppetiteRecord(_StateRecordMixin, Base):
    """食欲记录（user + date 唯一）。"""

    __tablename__ = "appetite_record"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_appetite_user_date"),
        Index("ix_appetite_record_user_date_id", "user_id", "date", "id"),
        {"comment": "食欲状态记录（按天，每类每天一行）"},
    )


class MyalgiaRecord(_StateRecordMixin, Base):
    """肌肉疼痛记录（user + date 唯一）。"""

    __tablename__ = "myalgia_record"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_myalgia_user_date"),
        Index("ix_myalgia_record_user_date_id", "user_id", "date", "id"),
        {"comment": "肌肉疼痛状态记录（按天，每类每天一行）"},
    )


class InflammationRecord(_StateRecordMixin, Base):
    """炎症记录（user + date 唯一）。"""

    __tablename__ = "inflammation_record"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_inflammation_user_date"),
        Index("ix_inflammation_record_user_date_id", "user_id", "date", "id"),
        {"comment": "炎症状态记录（按天，每类每天一行）"},
    )


STATE_MODELS = {
    TYPE_APPETITE: AppetiteRecord,
    TYPE_MYALGIA: MyalgiaRecord,
    TYPE_INFLAMMATION: InflammationRecord,
}
