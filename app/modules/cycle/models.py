"""生理周期三表（需求 9.1）：cycle_settings / period_records / daily_pain_logs。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CycleSetting(Base):
    """周期设置（单用户单行）。"""

    __tablename__ = "cycle_settings"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    cycle_length: Mapped[int] = mapped_column(Integer, nullable=False, default=28)
    period_length: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PeriodRecord(Base):
    """月经记录：start_date 为推算锚点。"""

    __tablename__ = "period_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyPainLog(Base):
    """每日疼痛（0~3），user+date 唯一。"""

    __tablename__ = "daily_pain_logs"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="uq_pain_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    pain_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
