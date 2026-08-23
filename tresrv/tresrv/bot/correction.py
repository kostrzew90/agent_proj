from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.meals import format_meal_reply

CORRECTABLE_FIELDS = {"kcal", "protein_g", "fat_g", "carbs_g"}

_FIELD_LABELS = {
    "kcal": "Kalorie", "protein_g": "Białko", "fat_g": "Tłuszcz", "carbs_g": "Węgle",
}


def parse_popraw_command(args: list[str]) -> dict:
    if len(args) < 2:
        raise ValueError(
            "Użycie: /popraw <kcal|protein_g|fat_g|carbs_g> <wartość>"
        )
    field, raw_value = args[0], args[1]
    if field not in CORRECTABLE_FIELDS:
        raise ValueError(f"Nieznane pole. Wybierz jedno z: {', '.join(sorted(CORRECTABLE_FIELDS))}")
    try:
        value = float(raw_value.replace(",", "."))
    except ValueError as exc:
        raise ValueError("Wartość musi być liczbą.") from exc
    return {field: value}


async def popraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.bot_data["session_factory"]()
    try:
        if context.args:
            try:
                changes = parse_popraw_command(context.args)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
            meal = repo.get_last_active_meal(session, update.effective_chat.id)
            if meal is None:
                await update.message.reply_text("Brak posiłków do poprawienia.")
                return
            corrected = repo.correct_meal(session, meal.id, **changes)
            await update.message.reply_text(format_meal_reply({
                "kcal": corrected.kcal, "protein_g": corrected.protein_g,
                "fat_g": corrected.fat_g, "carbs_g": corrected.carbs_g,
                "value_source": corrected.value_source,
            }))
            return

        meal = repo.get_last_active_meal(session, update.effective_chat.id)
        if meal is None:
            await update.message.reply_text("Brak posiłków do poprawienia.")
            return
        await update.message.reply_text(
            f"Ostatni posiłek: {meal.opis}\n"
            f"{meal.kcal} kcal, B {meal.protein_g}g / T {meal.fat_g}g / W {meal.carbs_g}g\n"
            "Co poprawić?",
            reply_markup=build_correction_keyboard(meal),
        )
    finally:
        session.close()


def build_correction_keyboard(meal) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"popraw:{meal.id}:{field}")]
        for field, label in _FIELD_LABELS.items()
    ]
    return InlineKeyboardMarkup(buttons)


async def correction_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, meal_id_str, field = query.data.split(":")
    context.user_data["correction_meal_id"] = int(meal_id_str)
    context.user_data["correction_field"] = field
    await query.message.reply_text(f"Podaj nową wartość dla: {_FIELD_LABELS[field]}")


async def correction_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    meal_id = context.user_data.get("correction_meal_id")
    field = context.user_data.get("correction_field")
    if meal_id is None or field is None:
        return  # not mid-correction; let other handlers process this message

    try:
        value = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Wartość musi być liczbą, spróbuj ponownie.")
        return

    session = context.bot_data["session_factory"]()
    try:
        corrected = repo.correct_meal(session, meal_id, **{field: value})
    finally:
        session.close()

    context.user_data.pop("correction_meal_id", None)
    context.user_data.pop("correction_field", None)
    await update.message.reply_text(format_meal_reply({
        "kcal": corrected.kcal, "protein_g": corrected.protein_g,
        "fat_g": corrected.fat_g, "carbs_g": corrected.carbs_g,
        "value_source": corrected.value_source,
    }))
