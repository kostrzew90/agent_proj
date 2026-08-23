from datetime import datetime, timezone

from tresrv.domain.confirmation import needs_confirmation
from tresrv.domain.daytime import local_date, resolve_consumed_at
from tresrv.llm import ParsedMeal


def build_meal_fields(
    chat_id: int, parsed: ParsedMeal, raw_input_type: str,
    raw_text: str | None, storage_path: str | None, telegram_file_id: str | None,
    logged_at: datetime,
) -> dict:
    consumed_at, _time_needs_confirmation = resolve_consumed_at(logged_at, parsed.when_hint)
    confirmation_needed = needs_confirmation(
        parsed.confidence, parsed.kcal, raw_input_type, parsed.opis
    ) or _time_needs_confirmation

    return {
        "chat_id": chat_id,
        "logged_at": logged_at,
        "consumed_at": consumed_at,
        "consumed_date": local_date(consumed_at),
        "raw_input_type": raw_input_type,
        "raw_text": raw_text,
        "storage_path": storage_path,
        "telegram_file_id": telegram_file_id,
        "opis": parsed.opis,
        "kcal": parsed.kcal,
        "protein_g": parsed.protein_g,
        "fat_g": parsed.fat_g,
        "carbs_g": parsed.carbs_g,
        "confidence": parsed.confidence,
        "needs_confirmation": confirmation_needed,
        "value_source": "llm",
        "status": "parsed",
        "created_at": datetime.now(timezone.utc),
    }


def resolve_photo_storage(
    download_succeeded: bool, storage_path: str | None, telegram_file_id: str,
) -> tuple[str | None, str | None]:
    if download_succeeded:
        return storage_path, telegram_file_id
    return None, telegram_file_id


def format_meal_reply(fields: dict) -> str:
    label = "Twoja korekta" if fields["value_source"] == "user" else "Szacunek"
    return (
        f"{label}: {fields['kcal']:.0f} kcal\n"
        f"B: {fields['protein_g']:.0f}g | T: {fields['fat_g']:.0f}g | "
        f"W: {fields['carbs_g']:.0f}g"
    )


import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.llm import NotFoodError, ParseError, TransientLLMError

MEALS_DIR = Path("/data/meals")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    logged_at = datetime.now(timezone.utc)
    llm_client = context.bot_data["llm_client"]
    session = context.bot_data["session_factory"]()
    try:
        try:
            parsed = llm_client.parse_text(text)
        except NotFoodError:
            await update.message.reply_text("To nie wygląda na jedzenie — spróbuj inaczej.")
            return
        except (ParseError, TransientLLMError) as exc:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="text", raw_text=text,
                logged_at=logged_at, consumed_at=logged_at, next_attempt_at=logged_at,
                status="pending", created_at=logged_at, last_error=str(exc),
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        fields = build_meal_fields(
            chat_id=chat_id, parsed=parsed, raw_input_type="text", raw_text=text,
            storage_path=None, telegram_file_id=None, logged_at=logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        repo.save_meal(session, **fields)
        await update.message.reply_text(format_meal_reply(fields))
    finally:
        session.close()


async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logged_at = datetime.now(timezone.utc)
    telegram_photo = update.message.photo[-1]
    telegram_file_id = telegram_photo.file_id

    MEALS_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = str(MEALS_DIR / f"{uuid.uuid4()}.jpg")
    download_succeeded = True
    try:
        telegram_file = await context.bot.get_file(telegram_file_id)
        await telegram_file.download_to_drive(storage_path)
    except Exception:
        download_succeeded = False

    resolved_path, resolved_file_id = resolve_photo_storage(
        download_succeeded, storage_path, telegram_file_id
    )

    llm_client = context.bot_data["llm_client"]
    session = context.bot_data["session_factory"]()
    try:
        if not download_succeeded:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="photo", telegram_file_id=resolved_file_id,
                logged_at=logged_at, consumed_at=logged_at, next_attempt_at=logged_at,
                status="pending", created_at=logged_at, last_error="download failed",
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        try:
            parsed = llm_client.parse_photo(resolved_path)
        except NotFoodError:
            await update.message.reply_text("To nie wygląda na jedzenie — spróbuj inaczej.")
            return
        except (ParseError, TransientLLMError) as exc:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="photo", storage_path=resolved_path,
                telegram_file_id=resolved_file_id, logged_at=logged_at, consumed_at=logged_at,
                next_attempt_at=logged_at, status="pending", created_at=logged_at,
                last_error=str(exc),
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        fields = build_meal_fields(
            chat_id=chat_id, parsed=parsed, raw_input_type="photo", raw_text=None,
            storage_path=resolved_path, telegram_file_id=resolved_file_id, logged_at=logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        repo.save_meal(session, **fields)
        await update.message.reply_text(format_meal_reply(fields))
    finally:
        session.close()
