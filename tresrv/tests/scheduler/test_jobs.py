import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.llm import ParsedMeal, ParseError, NotFoodError, TransientLLMError
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

    result = asyncio.run(drain_pending_parse(session, FakeLLMSucceeds(), now, max_attempts=5))

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

    result = asyncio.run(drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5))

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

    result = asyncio.run(drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5))

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

    result = asyncio.run(drain_pending_parse(session, FlakyLLM(), now, max_attempts=5))

    assert result["failed_permanently"] == 1
    session.refresh(pending)
    assert pending.status == "failed_permanently"


class FakeLLMFailsWithTransientError:
    model_name = "fake-model"

    def parse_text(self, text):
        raise TransientLLMError("429 rate limited")


def test_drain_retries_transient_llm_error_even_with_prior_error(session):
    # A prior last_error is present (as it would be after one retry), but a
    # TransientLLMError must NOT trigger the ParseError "repeated error" fast-fail path.
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=1, last_error="429 rate limited",
    )

    result = asyncio.run(
        drain_pending_parse(session, FakeLLMFailsWithTransientError(), now, max_attempts=5)
    )

    assert result == {"resolved": 0, "retried": 1, "failed_permanently": 0}
    session.refresh(pending)
    assert pending.status == "pending"
    assert pending.attempts == 2


def test_drain_fails_transient_llm_error_permanently_after_max_attempts_and_notifies(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=42, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=4,
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()

    result = asyncio.run(
        drain_pending_parse(session, FakeLLMFailsWithTransientError(), now, max_attempts=5, bot=bot)
    )

    assert result == {"resolved": 0, "retried": 0, "failed_permanently": 1}
    session.refresh(pending)
    assert pending.status == "failed_permanently"
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 42


def test_drain_not_food_notifies_user(session):
    now = datetime.now(timezone.utc)

    class FakeLLMNotFood:
        model_name = "fake-model"

        def parse_text(self, text):
            raise NotFoodError()

    repo.save_pending_parse(
        session, chat_id=7, raw_input_type="text", raw_text="stol",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()

    result = asyncio.run(drain_pending_parse(session, FakeLLMNotFood(), now, max_attempts=5, bot=bot))

    assert result == {"resolved": 0, "retried": 0, "failed_permanently": 1}
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 7


def test_drain_unexpected_exception_does_not_poison_the_whole_tick(session):
    # A pending photo row with storage_path=None and no telegram_file_id would previously
    # crash parse_photo(None) with an uncaught AttributeError/TypeError, aborting the loop
    # for every other due row behind it. It must instead be retried/failed like any other
    # row, and the row behind it must still get processed in the same tick.
    now = datetime.now(timezone.utc)
    poison = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="photo", storage_path=None, telegram_file_id=None,
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=0,
    )
    healthy = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )

    class LLMThatCrashesOnNonePath:
        model_name = "fake-model"

        def parse_text(self, text):
            return ParsedMeal(kcal=400, protein_g=25, fat_g=10, carbs_g=40,
                               opis=text, confidence=0.9, when_hint=None)

        def parse_photo(self, image_path):
            # Simulates PIL.Image.open(None) raising when storage_path is None.
            raise AttributeError("'NoneType' object has no attribute 'read'")

    result = asyncio.run(
        drain_pending_parse(session, LLMThatCrashesOnNonePath(), now, max_attempts=5)
    )

    assert result == {"resolved": 1, "retried": 1, "failed_permanently": 0}
    session.refresh(poison)
    session.refresh(healthy)
    assert poison.status == "pending"
    assert poison.attempts == 1
    assert healthy.status == "resolved"


def test_drain_retries_photo_download_before_parsing_when_storage_path_missing(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="photo", storage_path=None,
        telegram_file_id="tg_file_1", logged_at=now, consumed_at=now,
        next_attempt_at=now - timedelta(minutes=1), status="pending", created_at=now,
    )

    downloaded_paths = []

    class FakeTelegramFile:
        async def download_to_drive(self, path):
            downloaded_paths.append(path)

    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=FakeTelegramFile())

    class FakeLLMPhoto:
        model_name = "fake-model"

        def parse_photo(self, image_path):
            assert image_path == downloaded_paths[0]
            return ParsedMeal(kcal=500, protein_g=30, fat_g=20, carbs_g=40,
                               opis="zdjecie", confidence=0.9, when_hint=None)

    result = asyncio.run(
        drain_pending_parse(session, FakeLLMPhoto(), now, max_attempts=5, bot=bot)
    )

    assert result == {"resolved": 1, "retried": 0, "failed_permanently": 0}
    bot.get_file.assert_awaited_once_with("tg_file_1")
    session.refresh(pending)
    assert pending.status == "resolved"
    assert pending.storage_path == downloaded_paths[0]


def test_drain_retries_when_photo_redownload_fails_again(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="photo", storage_path=None,
        telegram_file_id="tg_file_1", logged_at=now, consumed_at=now,
        next_attempt_at=now - timedelta(minutes=1), status="pending", created_at=now,
    )

    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=Exception("network error"))

    result = asyncio.run(drain_pending_parse(session, FakeLLMSucceeds(), now, max_attempts=5, bot=bot))

    assert result == {"resolved": 0, "retried": 1, "failed_permanently": 0}
    session.refresh(pending)
    assert pending.status == "pending"
    assert pending.storage_path is None
    assert pending.attempts == 1
