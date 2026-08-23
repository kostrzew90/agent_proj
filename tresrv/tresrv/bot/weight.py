from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.onboarding import parse_waga
from tresrv.domain.daytime import local_date


def parse_waga_command(args: list[str]) -> float:
    if not args:
        raise ValueError("Użycie: /waga 80.5")
    return parse_waga(args[0])


async def waga_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        waga_kg = parse_waga_command(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    now = datetime.now(timezone.utc)
    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_weight_log(
            session, chat_id=update.effective_chat.id, waga_kg=waga_kg,
            logged_at=now, local_date=local_date(now),
        )
        repo.upsert_profile(session, chat_id=update.effective_chat.id, waga_kg=waga_kg)
    finally:
        session.close()
    await update.message.reply_text(f"Zapisano wagę: {waga_kg} kg")
