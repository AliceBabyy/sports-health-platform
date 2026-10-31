"""swim_records 表（需求 5 章；配速/平均划频为派生字段不落库）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SwimRecord(Base):
    __tablename__ = "swim_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)  # 存秒，界面按分钟录入
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_stroke: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 主泳姿，可空
    laps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
