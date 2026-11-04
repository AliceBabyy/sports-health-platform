"""dance_records 表（需求 6 章；与游泳同构，字段替换为舞种/星级/风格/双心率；2026-11 支持计划态）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DanceRecord(Base):
    __tablename__ = "dance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 课程开始时间（含日期与时分）
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)    # 课程结束时间
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recorded")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 备注（计划/记录均可填）
    dance_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 舞种，可自由输入（记录态必填）
    stars: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1~5（记录态必填）
    teacher: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 舞蹈老师
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 舞蹈风格自由文本
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 存秒（记录态必填；默认由起止时间推导）
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    note: Mapped["DanceNote | None"] = relationship(
        back_populates="record", cascade="all, delete-orphan", uselist=False
    )


class DanceNote(Base):
    """舞蹈练后心得：与一条舞蹈记录 1:1。"""
    __tablename__ = "dance_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dance_id: Mapped[int] = mapped_column(ForeignKey("dance_records.id", ondelete="CASCADE"), unique=True, nullable=False)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 自我评估 1~5 星
    video_effect: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 视频效果 1~5 星
    insight: Mapped[str | None] = mapped_column(Text, nullable=True)  # 感悟

    record: Mapped[DanceRecord] = relationship(back_populates="note")
