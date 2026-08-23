from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.llm import ParsedMeal, ParseError, NotFoodError
from tresrv.scheduler.jobs import next_backoff_seconds, drain_pending_parse


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class FakeLLMSucceeds:
    model_name = "fake-model"

    def parse_text(self, text):
        return ParsedMeal(kcal=400, protein_g=25, fat_g=10, carbs_g=40,
                           opis=text, confidence=0.9, when_hint=None)


class FakeLLMFailsWithParseError:
    model_name = "fake-model"

    def parse_text(self, text):
        raise ParseError("still garbage")


@pytest.mark.parametrize("attempts,expected", [(0, 60), (1, 120), (2, 300), (3, 300), (10, 300)])
def test_next_backoff_seconds(attempts, expected):
    assert next_backoff_seconds(attempts) == expected


def test_drain_resolves_pending_on_success(session):
    now = datetime.now(timezone.utc)
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )

    result = drain_pending_parse(session, FakeLLMSucceeds(), now, max_attempts=5)

    assert result == {"resolved": 1, "retried": 0, "failed_permanently": 0}
    active_meals = repo.get_active_meals_for_day(session, 1, now.date())
    assert len(active_meals) == 1
    pending_rows = session.query(repo.PendingParse).all()
    assert pending_rows[0].status == "resolved"


def test_drain_retries_on_parse_error_below_two_attempts(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=0,
    )

    result = drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5)

    assert result == {"resolved": 0, "retried": 1, "failed_permanently": 0}
    session.refresh(pending)
    assert pending.status == "pending"
    assert pending.attempts == 1


def test_drain_fails_permanently_after_two_parse_errors(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=1,
        last_error="nieparsowalny JSON",
    )

    result = drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5)

    assert result == {"resolved": 0, "retried": 0, "failed_permanently": 1}
    session.refresh(pending)
    assert pending.status == "failed_permanently"


def test_drain_fails_permanently_after_max_attempts(session):
    now = datetime.now(timezone.utc)

    class FlakyLLM:
        model_name = "fake-model"

        def parse_text(self, text):
            raise ParseError("temporary-looking but keeps failing")

    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=4,
    )

    result = drain_pending_parse(session, FlakyLLM(), now, max_attempts=5)

    assert result["failed_permanently"] == 1
    session.refresh(pending)
    assert pending.status == "failed_permanently"
