"""生理周期三表（需求 9.1）：cycle_settings / period_records / daily_pain_logs。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CycleSetting(Base):
    """周期设置（单用户单行）。"""

    __tablename__ = "cycle_settings"
    __table_args__ = {"comment": "生理周期设置（单用户单行）"}

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True, comment="主键 + FK → users.id")
    cycle_length: Mapped[int] = mapped_column(Integer, nullable=False, default=28, comment="周期长度（天）")
    period_length: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="经期长度（天）")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")


class PeriodRecord(Base):
    """月经记录：start_date 为推算锚点。"""

    __tablename__ = "period_records"
    __table_args__ = {"comment": "月经记录（start_date 为推算锚点）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="月经开始日（推算锚点）")
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="结束日（可后补）")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")


class DailyPainLog(Base):
    """每日疼痛（0~3），user+date 唯一。"""

    __tablename__ = "daily_pain_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_pain_user_date"),
        {"comment": "每日疼痛记录（0~3，一天一行）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    log_date: Mapped[date] = mapped_column(Date, nullable=False, comment="记录日期（一天一行）")
    pain_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="疼痛等级 0无/1轻/2中/3重")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
