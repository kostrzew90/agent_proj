from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tresrv.models import Base, UserProfile, WeightLog, Meal, PendingParse


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_user_profile_rejects_invalid_plec(session):
    session.add(UserProfile(
        chat_id=1, plec="x", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
        updated_at=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_weight_logs_unique_per_chat_and_day(session):
    session.add(WeightLog(chat_id=1, waga_kg=80.0,
                           logged_at=datetime.now(timezone.utc), local_date=date(2026, 8, 23)))
    session.commit()
    session.add(WeightLog(chat_id=1, waga_kg=80.5,
                           logged_at=datetime.now(timezone.utc), local_date=date(2026, 8, 23)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meal_rejects_invalid_status(session):
    now = datetime.now(timezone.utc)
    session.add(Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=5, status="not_a_real_status", created_at=now,
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meal_corrected_from_id_links_to_previous_meal(session):
    now = datetime.now(timezone.utc)
    original = Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=5, status="superseded", created_at=now,
    )
    session.add(original)
    session.commit()

    correction = Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=320, protein_g=22,
        fat_g=10, carbs_g=5, status="corrected", value_source="user",
        corrected_from_id=original.id, created_at=now,
    )
    session.add(correction)
    session.commit()

    assert correction.corrected_from_id == original.id


def test_pending_parse_rejects_invalid_status(session):
    now = datetime.now(timezone.utc)
    session.add(PendingParse(
        chat_id=1, raw_input_type="text", raw_text="jajka",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="not_real", created_at=now,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
