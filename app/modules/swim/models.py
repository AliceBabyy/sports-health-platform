"""swim_records 表（需求 5 章；配速/平均划频为派生字段不落库；2026-11 支持计划态）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SwimRecord(Base):
    __tablename__ = "swim_records"
    __table_args__ = {"comment": "游泳记录/计划（配速/划频为派生值不落库；2026-11 支持计划态）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户（逻辑外键，归属校验在应用层）")
    record_date: Mapped[date] = mapped_column(Date, nullable=False, comment="记录日期")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recorded", comment="planned|recorded（计划态=距离/时长/主泳姿，记录态=距离/时长）")  # planned | recorded
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注（计划/记录均可填）")  # 备注（计划/记录均可填）
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="距离（米，计划/记录态必填，接口校验）")  # 距离（记录态必填）
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="时长（秒，界面按分钟录入，计划/记录态必填，接口校验）")  # 存秒，界面按分钟录入（记录态必填）
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="平均心率")
    total_strokes: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总划次")
    main_stroke: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="主泳姿（计划态必填，记录态可空，界面默认\"未填写\"）")  # 主泳姿，可空
    laps: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="趟数")
    calories: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True, comment="消耗 kcal")
    avg_stroke_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均划频（记录态可手填，未填时仍由 total_strokes/duration 派生）")  # 平均划频（可手填；未填时由 total_strokes/duration 派生）
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间（ORM onupdate 自动刷新）")

    note: Mapped["SwimNote | None"] = relationship(
        back_populates="record", cascade="all, delete-orphan", uselist=False
    )


class SwimNote(Base):
    """游泳练后心得：与一条游泳记录 1:1。"""
    __tablename__ = "swim_notes"
    __table_args__ = {"comment": "游泳练后心得（一条游泳记录 1:1）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="主键")
    swim_id: Mapped[int] = mapped_column(ForeignKey("swim_records.id", ondelete="CASCADE"), unique=True, nullable=False, comment="所属游泳记录 FK，唯一（CASCADE）")
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, comment="自我评估星级 1~5")  # 自我评估 1~5 星
    stroke_insight: Mapped[str | None] = mapped_column(Text, nullable=True, comment="泳姿是否有感悟/进步")  # 泳姿是否有感悟/进步
    other: Mapped[str | None] = mapped_column(Text, nullable=True, comment="其他")  # 其他

    record: Mapped[SwimRecord] = relationship(back_populates="note")
