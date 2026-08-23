from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tresrv.models import UserProfile, WeightLog, Meal, PendingParse

_MEAL_COPY_FIELDS = (
    "chat_id", "logged_at", "consumed_at", "consumed_date", "raw_input_type",
    "raw_text", "storage_path", "telegram_file_id", "opis", "kcal",
    "protein_g", "fat_g", "carbs_g", "confidence", "llm_model",
)


def get_profile(session: Session, chat_id: int) -> UserProfile | None:
    return session.get(UserProfile, chat_id)


def upsert_profile(session: Session, chat_id: int, **fields) -> UserProfile:
    profile = session.get(UserProfile, chat_id)
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = UserProfile(chat_id=chat_id, updated_at=now, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
        profile.updated_at = now
    session.commit()
    return profile


def upsert_weight_log(session: Session, chat_id: int, waga_kg: float,
                       logged_at: datetime, local_date) -> WeightLog:
    existing = session.execute(
        select(WeightLog).where(
            WeightLog.chat_id == chat_id, WeightLog.local_date == local_date
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = WeightLog(chat_id=chat_id, waga_kg=waga_kg,
                              logged_at=logged_at, local_date=local_date)
        session.add(existing)
    else:
        existing.waga_kg = waga_kg
        existing.logged_at = logged_at
    session.commit()
    return existing


def save_meal(session: Session, **fields) -> Meal:
    meal = Meal(**fields)
    session.add(meal)
    session.commit()
    return meal


def save_pending_parse(session: Session, **fields) -> PendingParse:
    pending = PendingParse(**fields)
    session.add(pending)
    session.commit()
    return pending


def get_active_meals_for_day(session: Session, chat_id: int, consumed_date) -> list[Meal]:
    return list(session.execute(
        select(Meal).where(
            Meal.chat_id == chat_id,
            Meal.consumed_date == consumed_date,
            Meal.status != "superseded",
        )
    ).scalars())


def get_last_active_meal(session: Session, chat_id: int) -> Meal | None:
    return session.execute(
        select(Meal)
        .where(Meal.chat_id == chat_id, Meal.status != "superseded")
        .order_by(Meal.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def correct_meal(session: Session, meal_id: int, **new_values) -> Meal:
    original = session.get(Meal, meal_id)
    if original is None:
        raise ValueError(f"Meal {meal_id} nie istnieje")

    data = {field: getattr(original, field) for field in _MEAL_COPY_FIELDS}
    data.update(new_values)
    data["value_source"] = "user"
    data["status"] = "corrected"
    data["needs_confirmation"] = False
    data["corrected_from_id"] = original.id
    data["created_at"] = datetime.now(timezone.utc)

    corrected = Meal(**data)
    original.status = "superseded"
    session.add(corrected)
    session.commit()
    return corrected


def fetch_due_pending(session: Session, now: datetime) -> list[PendingParse]:
    return list(session.execute(
        select(PendingParse).where(
            PendingParse.status == "pending",
            PendingParse.next_attempt_at <= now,
        )
    ).scalars())


def mark_pending_resolved(session: Session, pending: PendingParse, meal_id: int) -> None:
    pending.status = "resolved"
    pending.meal_id = meal_id
    session.commit()


def mark_pending_retry(session: Session, pending: PendingParse, error: str,
                        next_attempt_at: datetime) -> None:
    pending.attempts += 1
    pending.last_attempt_at = datetime.now(timezone.utc)
    pending.last_error = error
    pending.next_attempt_at = next_attempt_at
    session.commit()


def mark_pending_failed_permanently(session: Session, pending: PendingParse, error: str) -> None:
    pending.attempts += 1
    pending.last_attempt_at = datetime.now(timezone.utc)
    pending.last_error = error
    pending.status = "failed_permanently"
    session.commit()
