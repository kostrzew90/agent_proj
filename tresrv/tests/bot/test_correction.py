from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.domain.aggregation import MealRow, aggregate_day
from tresrv.bot.correction import parse_popraw_command


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_parse_popraw_command_kcal():
    assert parse_popraw_command(["kcal", "740"]) == {"kcal": 740.0}


def test_parse_popraw_command_protein():
    assert parse_popraw_command(["protein_g", "48"]) == {"protein_g": 48.0}


def test_parse_popraw_command_unknown_field_raises():
    with pytest.raises(ValueError):
        parse_popraw_command(["kalorie", "740"])


def test_parse_popraw_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_popraw_command([])


def test_parse_popraw_command_non_numeric_value_raises():
    with pytest.raises(ValueError):
        parse_popraw_command(["kcal", "dużo"])


def test_correction_then_daily_aggregate_counts_once(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="kanapka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=30, opis="kanapka", status="parsed", created_at=now,
    )

    repo.correct_meal(session, original.id, kcal=600)

    meals = repo.get_active_meals_for_day(session, 1, today)
    rows = [MealRow(kcal=float(m.kcal), protein_g=float(m.protein_g),
                     fat_g=float(m.fat_g), carbs_g=float(m.carbs_g), status=m.status)
            for m in meals]
    summary = aggregate_day(rows)
    assert summary.kcal == 600  # not 900 — the superseded original must not double-count
