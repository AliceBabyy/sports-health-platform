"""Dance records and notes."""
from sqlalchemy import ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.sport_contract import SportNoteMixin, SportRecordMixin
from database import Base


class DanceRecord(SportRecordMixin, Base):
    __tablename__ = "dance_records"
    __table_args__ = (Index("ix_dance_records_user_date_id", "user_id", "date", "id"),)

    dance_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stars: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    teacher: Mapped[str | None] = mapped_column(String(64), nullable=True)
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)

    note: Mapped["DanceNote | None"] = relationship(back_populates="record", cascade="all, delete-orphan", uselist=False)


class DanceNote(SportNoteMixin, Base):
    __tablename__ = "dance_notes"

    dance_id: Mapped[int] = mapped_column(ForeignKey("dance_records.id", ondelete="CASCADE"), unique=True, nullable=False)
    video_effect: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    record: Mapped[DanceRecord] = relationship(back_populates="note")
