from datetime import datetime, timezone, date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_upsert_profile_creates_then_updates(session):
    now = datetime.now(timezone.utc)
    repo.upsert_profile(
        session, chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
    )
    repo.upsert_profile(session, chat_id=1, cel="maintenance")

    profile = repo.get_profile(session, 1)
    assert profile.cel == "maintenance"
    assert profile.waga_kg == 80  # untouched field survives partial update


def test_upsert_weight_log_is_idempotent_per_day(session):
    d = date(2026, 8, 23)
    repo.upsert_weight_log(session, chat_id=1, waga_kg=80.0,
                            logged_at=datetime.now(timezone.utc), local_date=d)
    repo.upsert_weight_log(session, chat_id=1, waga_kg=80.5,
                            logged_at=datetime.now(timezone.utc), local_date=d)

    logs = session.query(repo.WeightLog).filter_by(chat_id=1, local_date=d).all()
    assert len(logs) == 1
    assert logs[0].waga_kg == 80.5


def test_get_active_meals_for_day_excludes_superseded(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    m1 = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="a", kcal=300, protein_g=20, fat_g=10,
        carbs_g=30, status="superseded", created_at=now,
    )
    repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="b", kcal=320, protein_g=22, fat_g=10,
        carbs_g=30, status="corrected", corrected_from_id=m1.id, created_at=now,
    )

    active = repo.get_active_meals_for_day(session, 1, today)
    assert len(active) == 1
    assert active[0].kcal == 320


def test_correct_meal_supersedes_old_and_creates_new(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="kanapka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=30, opis="kanapka", status="parsed", created_at=now,
    )

    corrected = repo.correct_meal(session, original.id, kcal=600)

    session.refresh(original)
    assert original.status == "superseded"
    assert corrected.status == "corrected"
    assert corrected.value_source == "user"
    assert corrected.corrected_from_id == original.id
    assert corrected.kcal == 600
    assert corrected.protein_g == 20  # untouched field copied from original


def test_fetch_due_pending_only_returns_due_and_pending(session):
    now = datetime.now(timezone.utc)
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="b",
        logged_at=now, consumed_at=now, next_attempt_at=now + timedelta(hours=1),
        status="pending", created_at=now,
    )
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="c",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="resolved", created_at=now,
    )

    due = repo.fetch_due_pending(session, now)
    assert len(due) == 1
    assert due[0].raw_text == "a"


def test_mark_pending_retry_increments_attempts_and_sets_next_attempt(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="pending", created_at=now,
    )

    next_attempt = now + timedelta(seconds=120)
    repo.mark_pending_retry(session, pending, "429 rate limited", next_attempt)

    assert pending.attempts == 1
    assert pending.last_error == "429 rate limited"
    assert pending.next_attempt_at == next_attempt
    assert pending.status == "pending"


def test_mark_pending_failed_permanently_sets_status(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="pending", created_at=now,
    )

    repo.mark_pending_failed_permanently(session, pending, "nieparsowalny JSON x2")

    assert pending.status == "failed_permanently"
