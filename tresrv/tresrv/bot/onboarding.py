_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
_GOALS = {"reduction", "mass", "maintenance"}


def parse_plec(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in ("m", "k"):
        raise ValueError("Podaj 'M' (mężczyzna) lub 'K' (kobieta).")
    return normalized


def parse_wiek(text: str) -> int:
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError("Wiek musi być liczbą całkowitą.") from exc
    if not (10 <= value <= 100):
        raise ValueError("Podaj realny wiek (10-100 lat).")
    return value


def parse_wzrost(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Wzrost musi być liczbą (w cm).") from exc
    if not (100 <= value <= 250):
        raise ValueError("Podaj realny wzrost w cm (100-250).")
    return value


def parse_waga(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Waga musi być liczbą (w kg).") from exc
    if not (30 <= value <= 300):
        raise ValueError("Podaj realną wagę w kg (30-300).")
    return value


def parse_aktywnosc(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in _ACTIVITY_LEVELS:
        raise ValueError(
            "Wybierz jeden z: sedentary, light, moderate, active, very_active."
        )
    return normalized


def parse_cel(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in _GOALS:
        raise ValueError("Wybierz jeden z: reduction, mass, maintenance.")
    return normalized


from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters,
)

from tresrv import repo
from tresrv.domain.daytime import local_date

PLEC, WIEK, WZROST, WAGA, AKTYWNOSC, CEL = range(6)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Zaczynamy onboarding. Podaj płeć (M/K):")
    return PLEC


async def receive_plec(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["plec"] = parse_plec(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return PLEC
    await update.message.reply_text("Podaj wiek (lata):")
    return WIEK


async def receive_wiek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["wiek"] = parse_wiek(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WIEK
    await update.message.reply_text("Podaj wzrost (cm):")
    return WZROST


async def receive_wzrost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["wzrost_cm"] = parse_wzrost(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WZROST
    await update.message.reply_text("Podaj wagę (kg):")
    return WAGA


async def receive_waga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["waga_kg"] = parse_waga(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WAGA
    await update.message.reply_text(
        "Poziom aktywności (sedentary/light/moderate/active/very_active):"
    )
    return AKTYWNOSC


async def receive_aktywnosc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["poziom_aktywnosci"] = parse_aktywnosc(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return AKTYWNOSC
    await update.message.reply_text("Cel (reduction/mass/maintenance):")
    return CEL


async def receive_cel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cel = parse_cel(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return CEL

    chat_id = update.effective_chat.id
    now = datetime.now(timezone.utc)
    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_profile(
            session, chat_id=chat_id,
            plec=context.user_data["plec"], wiek=context.user_data["wiek"],
            wzrost_cm=context.user_data["wzrost_cm"], waga_kg=context.user_data["waga_kg"],
            poziom_aktywnosci=context.user_data["poziom_aktywnosci"], cel=cel,
        )
        repo.upsert_weight_log(
            session, chat_id=chat_id, waga_kg=context.user_data["waga_kg"],
            logged_at=now, local_date=local_date(now),
        )
    finally:
        session.close()

    await update.message.reply_text("Profil zapisany. Możesz teraz logować posiłki i wagę.")
    return ConversationHandler.END


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PLEC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plec)],
            WIEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wiek)],
            WZROST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wzrost)],
            WAGA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_waga)],
            AKTYWNOSC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_aktywnosc)],
            CEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cel)],
        },
        fallbacks=[],
    )
