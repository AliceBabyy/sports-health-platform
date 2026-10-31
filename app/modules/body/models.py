"""body_metric_records 表（需求 9.1；BD-02 唯一索引支撑 upsert）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class BodyMetricRecord(Base):
    __tablename__ = "body_metric_records"
    __table_args__ = (
        UniqueConstraint("user_id", "metric_key", "record_date", name="uq_body_metric_user_key_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
