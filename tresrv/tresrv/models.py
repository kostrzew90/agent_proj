from datetime import datetime, date

from sqlalchemy import (
    BigInteger, String, Numeric, Boolean, DateTime, Date, Integer,
    ForeignKey, CheckConstraint, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plec: Mapped[str] = mapped_column(String(1))
    wiek: Mapped[int] = mapped_column(Integer)
    wzrost_cm: Mapped[float] = mapped_column(Numeric(5, 1))
    waga_kg: Mapped[float] = mapped_column(Numeric(5, 1))
    poziom_aktywnosci: Mapped[str] = mapped_column(String(20))
    cel: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("plec IN ('m','k')", name="ck_user_profile_plec"),
        CheckConstraint(
            "poziom_aktywnosci IN ('sedentary','light','moderate','active','very_active')",
            name="ck_user_profile_activity",
        ),
        CheckConstraint("cel IN ('reduction','mass','maintenance')", name="ck_user_profile_cel"),
    )


class WeightLog(Base):
    __tablename__ = "weight_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    waga_kg: Mapped[float] = mapped_column(Numeric(5, 1))
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("chat_id", "local_date", name="uq_weight_logs_chat_date"),
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_date: Mapped[date] = mapped_column(Date)
    raw_input_type: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    opis: Mapped[str | None] = mapped_column(String, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    value_source: Mapped[str] = mapped_column(String(10), default="llm")
    llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="parsed")
    corrected_from_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("meals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("raw_input_type IN ('text','photo')", name="ck_meals_input_type"),
        CheckConstraint("value_source IN ('llm','user')", name="ck_meals_value_source"),
        CheckConstraint("status IN ('parsed','corrected','superseded')", name="ck_meals_status"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_meals_confidence_range",
        ),
        Index("meals_day_idx", "chat_id", "consumed_date"),
    )


class PendingParse(Base):
    __tablename__ = "pending_parse"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    raw_input_type: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    meal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("meals.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("raw_input_type IN ('text','photo')", name="ck_pending_input_type"),
        CheckConstraint(
            "status IN ('pending','failed_permanently','resolved')", name="ck_pending_status"
        ),
        Index("pending_parse_due_idx", "next_attempt_at"),
    )
