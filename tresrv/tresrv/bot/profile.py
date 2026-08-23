from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.onboarding import parse_cel
from tresrv.models import UserProfile


def parse_cel_command(args: list[str]) -> str:
    if not args:
        raise ValueError("Użycie: /cel reduction|mass|maintenance")
    return parse_cel(args[0])


def format_profile(profile: UserProfile) -> str:
    return (
        f"Płeć: {profile.plec}\n"
        f"Wiek: {profile.wiek}\n"
        f"Wzrost: {profile.wzrost_cm} cm\n"
        f"Waga: {profile.waga_kg} kg\n"
        f"Aktywność: {profile.poziom_aktywnosci}\n"
        f"Cel: {profile.cel}"
    )


async def profil_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.bot_data["session_factory"]()
    try:
        profile = repo.get_profile(session, update.effective_chat.id)
    finally:
        session.close()

    if profile is None:
        await update.message.reply_text("Brak profilu. Użyj /start.")
        return
    await update.message.reply_text(format_profile(profile))


async def cel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        cel = parse_cel_command(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_profile(session, chat_id=update.effective_chat.id, cel=cel)
    finally:
        session.close()
    await update.message.reply_text(f"Cel ustawiony na: {cel}")
