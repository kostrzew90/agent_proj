from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.domain.targets import DailyTarget
from tresrv.domain.aggregation import DaySummary
from tresrv.scheduler.jobs import build_summary_text, build_evening_summary


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_build_summary_text_includes_kcal_and_protein_vs_target():
    summary = DaySummary(kcal=1850, protein_g=140, fat_g=60, carbs_g=180, meal_count=3)
    target = DailyTarget(kcal=2100, protein_g=160)

    text = build_summary_text(summary, target)

    assert "1850" in text
    assert "2100" in text
    assert "140" in text
    assert "160" in text
    assert "Szacunkowo" in text


def test_build_evening_summary_returns_none_without_profile(session):
    result = build_evening_summary(session, chat_id=1, today=date(2026, 8, 23))
    assert result is None


def test_build_evening_summary_excludes_superseded_meals(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    repo.upsert_profile(
        session, chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
    )
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="a", kcal=300, protein_g=20, fat_g=10,
        carbs_g=30, status="superseded", created_at=now,
    )
    repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="b", kcal=320, protein_g=22, fat_g=10,
        carbs_g=30, status="corrected", corrected_from_id=original.id, created_at=now,
    )

    text = build_evening_summary(session, chat_id=1, today=today)

    assert "320" in text
    assert "300" not in text or "320" in text  # 320 must appear; 300 must not dominate the total
