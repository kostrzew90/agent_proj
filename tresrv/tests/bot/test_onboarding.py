import asyncio
import datetime
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Chat, Message, MessageEntity, Update, User
from telegram.ext import (
    Application, ApplicationHandlerStop, MessageHandler, filters,
)

from tresrv.bot.onboarding import (
    parse_plec, parse_wiek, parse_wzrost, parse_waga, parse_aktywnosc, parse_cel,
    build_onboarding_handler, receive_plec, PLEC,
)


def test_parse_plec_accepts_m_and_k():
    assert parse_plec("M") == "m"
    assert parse_plec("k") == "k"


def test_parse_plec_rejects_other():
    with pytest.raises(ValueError):
        parse_plec("inne")


def test_parse_wiek_accepts_reasonable_range():
    assert parse_wiek("30") == 30


@pytest.mark.parametrize("text", ["0", "150", "abc"])
def test_parse_wiek_rejects_out_of_range_or_non_numeric(text):
    with pytest.raises(ValueError):
        parse_wiek(text)


def test_parse_wzrost_accepts_cm():
    assert parse_wzrost("180") == 180.0


@pytest.mark.parametrize("text", ["50", "260", "abc"])
def test_parse_wzrost_rejects_out_of_range(text):
    with pytest.raises(ValueError):
        parse_wzrost(text)


def test_parse_waga_accepts_kg():
    assert parse_waga("80.5") == 80.5


@pytest.mark.parametrize("text", ["10", "400", "abc"])
def test_parse_waga_rejects_out_of_range(text):
    with pytest.raises(ValueError):
        parse_waga(text)


def test_parse_aktywnosc_accepts_known_levels():
    assert parse_aktywnosc("moderate") == "moderate"


def test_parse_aktywnosc_rejects_unknown():
    with pytest.raises(ValueError):
        parse_aktywnosc("super_active")


def test_parse_cel_accepts_known_goals():
    assert parse_cel("reduction") == "reduction"


def test_parse_cel_rejects_unknown():
    with pytest.raises(ValueError):
        parse_cel("bulk")


def _make_update_context(text):
    update = AsyncMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_chat.id = 1
    context = AsyncMock()
    context.user_data = {}
    context.bot_data = {}
    return update, context


def test_receive_plec_raises_application_handler_stop_on_success():
    update, context = _make_update_context("M")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(receive_plec(update, context))


def test_receive_plec_raises_application_handler_stop_on_validation_failure():
    update, context = _make_update_context("inne")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(receive_plec(update, context))


def test_onboarding_reply_is_not_also_processed_as_a_meal_by_a_later_group():
    """Regression test for C1: registering the onboarding ConversationHandler and a
    free-text meal-logging handler in different `Application` groups does NOT, by
    itself, stop the later group from also seeing the same update — only raising
    `ApplicationHandlerStop` does. This builds a real `telegram.ext.Application` with
    the actual onboarding handler at group 0 and a stand-in meal handler at group 1,
    dispatches a real `/start` then a real text reply ("M") through
    `Application.process_update`, and asserts the meal handler was never invoked.
    """
    async def scenario():
        app = Application.builder().token(
            "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        ).build()
        # Avoid a real network call in Application/Bot initialization.
        app.bot._bot_user = User(id=999, first_name="bot", is_bot=True, username="testbot")
        app.bot._bot_initialized = True
        app.bot._requests_initialized = True
        app._initialized = True
        app.bot_data["session_factory"] = None  # unused: validation fails before DB access

        meal_handler = AsyncMock()

        app.add_handler(build_onboarding_handler(), group=0)
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, meal_handler), group=1
        )

        chat = Chat(id=1, type="private")
        user = User(id=1, first_name="a", is_bot=False)

        start_entity = MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0, length=6)
        start_msg = Message(
            message_id=0, date=datetime.datetime.now(), chat=chat, from_user=user,
            text="/start", entities=[start_entity],
        )
        start_msg.set_bot(app.bot)
        start_update = Update(update_id=0, message=start_msg)

        reply_msg = Message(
            message_id=1, date=datetime.datetime.now(), chat=chat, from_user=user, text="M",
        )
        reply_msg.set_bot(app.bot)
        reply_update = Update(update_id=1, message=reply_msg)

        # Avoid real network calls from reply_text() inside start()/receive_plec().
        with patch.object(app.bot.__class__, "send_message", AsyncMock()):
            await app.process_update(start_update)
            await app.process_update(reply_update)

        meal_handler.assert_not_called()

    asyncio.run(scenario())
