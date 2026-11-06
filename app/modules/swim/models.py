"""Swimming records and notes."""
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.sport_contract import SportNoteMixin, SportRecordMixin
from database import Base


class SwimRecord(SportRecordMixin, Base):
    __tablename__ = "swim_records"
    __table_args__ = (Index("ix_swim_records_user_date_id", "user_id", "date", "id"),)

    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_strokes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_stroke: Mapped[str | None] = mapped_column(String(16), nullable=True)
    laps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_stroke_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    note: Mapped["SwimNote | None"] = relationship(back_populates="record", cascade="all, delete-orphan", uselist=False)


class SwimNote(SportNoteMixin, Base):
    __tablename__ = "swim_notes"

    swim_id: Mapped[int] = mapped_column(ForeignKey("swim_records.id", ondelete="CASCADE"), unique=True, nullable=False)
    stroke_insight: Mapped[str | None] = mapped_column(Text, nullable=True)

    record: Mapped[SwimRecord] = relationship(back_populates="note")
