"""dance_records 表（需求 6 章；与游泳同构，字段替换为舞种/星级/风格/双心率）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DanceRecord(Base):
    __tablename__ = "dance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    dance_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 舞种，可自由输入
    stars: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1~5
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 舞蹈风格自由文本
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)  # 存秒
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
