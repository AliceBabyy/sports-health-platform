"""dance_records 表（需求 6 章；与游泳同构，字段替换为舞种/星级/风格/双心率；2026-11 支持计划态）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DanceRecord(Base):
    __tablename__ = "dance_records"
    __table_args__ = {"comment": "舞蹈记录/计划（含课程起止时间；2026-11 支持计划态）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    record_date: Mapped[date] = mapped_column(Date, nullable=False, comment="记录日期")
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="课程开始时间（含日期与时分）")  # 课程开始时间（含日期与时分）
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="课程结束时间")    # 课程结束时间
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recorded", comment="planned|recorded（计划态=舞种+星级，记录态=舞种+星级+时长）")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注（计划/记录均可填）")  # 备注（计划/记录均可填）
    dance_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="舞种（可自由输入，计划/记录态必填，接口校验）")  # 舞种，可自由输入（记录态必填）
    stars: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="完成度星级 1~5（计划/记录态必填，接口校验）")  # 1~5（记录态必填）
    teacher: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="舞蹈老师")  # 舞蹈老师
    style: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="舞蹈风格自由文本")  # 舞蹈风格自由文本
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="时长（秒，记录态必填；默认由 start_time/end_time 推导）")  # 存秒（记录态必填；默认由起止时间推导）
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="平均心率")
    max_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最高心率")
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True, comment="消耗 kcal")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")

    note: Mapped["DanceNote | None"] = relationship(
        back_populates="record", cascade="all, delete-orphan", uselist=False
    )


class DanceNote(Base):
    """舞蹈练后心得：与一条舞蹈记录 1:1。"""
    __tablename__ = "dance_notes"
    __table_args__ = {"comment": "舞蹈练后心得（一条舞蹈记录 1:1）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    dance_id: Mapped[int] = mapped_column(ForeignKey("dance_records.id", ondelete="CASCADE"), unique=True, nullable=False, comment="所属舞蹈记录 FK，唯一（CASCADE）")
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="自我评估星级 1~5")  # 自我评估 1~5 星
    video_effect: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="视频效果星级 1~5")  # 视频效果 1~5 星
    insight: Mapped[str | None] = mapped_column(Text, nullable=True, comment="感悟")  # 感悟

    record: Mapped[DanceRecord] = relationship(back_populates="note")
