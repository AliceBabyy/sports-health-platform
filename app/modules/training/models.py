"""Training records, exercise items, and post-training notes."""
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.sport_contract import SportNoteMixin, SportRecordMixin, SportStatus, status_type
from database import Base


class TrainingRecord(SportRecordMixin, Base):
    __tablename__ = "training_records"
    __table_args__ = (Index("ix_training_records_user_date_id", "user_id", "date", "id"),)

    status: Mapped[SportStatus] = mapped_column(status_type, nullable=False, default=SportStatus.PLANNED)
    items: Mapped[list["TrainingRecordItem"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", order_by="TrainingRecordItem.sort"
    )
    note: Mapped["TrainingNote | None"] = relationship(
        back_populates="record", cascade="all, delete-orphan", uselist=False
    )


class TrainingRecordItem(Base):
    __tablename__ = "training_records_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("training_records.id", ondelete="CASCADE"), nullable=False, index=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exercise_name: Mapped[str] = mapped_column(String(128), nullable=False)
    body_part: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    record: Mapped[TrainingRecord] = relationship(back_populates="items")


class TrainingNote(SportNoteMixin, Base):
    __tablename__ = "training_notes"

    training_id: Mapped[int] = mapped_column(ForeignKey("training_records.id", ondelete="CASCADE"), unique=True, nullable=False)
    best_movement: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    record: Mapped[TrainingRecord] = relationship(back_populates="note")
