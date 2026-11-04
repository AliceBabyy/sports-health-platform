"""swim_records 表（需求 5 章；配速/平均划频为派生字段不落库；2026-11 支持计划态）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SwimRecord(Base):
    __tablename__ = "swim_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recorded")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 备注（计划/记录均可填）
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 距离（记录态必填）
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 存秒，界面按分钟录入（记录态必填）
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_stroke: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 主泳姿，可空
    laps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    avg_stroke_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # 平均划频（可手填；未填时由 total_strokes/duration 派生）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    note: Mapped["SwimNote | None"] = relationship(
        back_populates="record", cascade="all, delete-orphan", uselist=False
    )


class SwimNote(Base):
    """游泳练后心得：与一条游泳记录 1:1。"""
    __tablename__ = "swim_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    swim_id: Mapped[int] = mapped_column(ForeignKey("swim_records.id", ondelete="CASCADE"), unique=True, nullable=False)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 自我评估 1~5 星
    stroke_insight: Mapped[str | None] = mapped_column(Text, nullable=True)  # 泳姿是否有感悟/进步
    other: Mapped[str | None] = mapped_column(Text, nullable=True)  # 其他

    record: Mapped[SwimRecord] = relationship(back_populates="note")
