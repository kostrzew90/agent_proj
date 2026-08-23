from datetime import date, datetime, timezone

from tresrv.bot.meals import build_meal_fields, resolve_photo_storage, format_meal_reply
from tresrv.llm import ParsedMeal


def test_build_meal_fields_defaults_consumed_at_to_logged_at():
    logged_at = datetime(2026, 8, 23, 19, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="kurczak z ryzem", confidence=0.9, when_hint=None)

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="kurczak z ryzem",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["consumed_at"] == logged_at
    assert fields["consumed_date"] == logged_at.date()
    assert fields["kcal"] == 450
    assert fields["needs_confirmation"] is False
    assert fields["value_source"] == "llm"
    assert fields["status"] == "parsed"


def test_build_meal_fields_uses_warsaw_local_date_not_utc_date():
    # 2026-08-23 22:30 UTC is 2026-08-24 00:30 in Warsaw (CEST, UTC+2) —
    # this crosses the day boundary, so consumed_date must be the Warsaw date.
    logged_at = datetime(2026, 8, 23, 22, 30, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="kurczak z ryzem", confidence=0.9, when_hint=None)

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="kurczak z ryzem",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["consumed_date"] == date(2026, 8, 24)


def test_build_meal_fields_applies_when_hint():
    logged_at = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="pizza", confidence=0.9, when_hint="yesterday")

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="wczoraj jadlem pizze",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["consumed_at"] < logged_at


def test_build_meal_fields_low_confidence_needs_confirmation():
    logged_at = datetime(2026, 8, 23, 19, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="cos", confidence=0.4, when_hint=None)

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="cos",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["needs_confirmation"] is True


def test_resolve_photo_storage_download_succeeded():
    path, file_id = resolve_photo_storage(True, "/data/meals/abc.jpg", "tg_file_1")
    assert path == "/data/meals/abc.jpg"
    assert file_id == "tg_file_1"


def test_resolve_photo_storage_download_failed_keeps_file_id_only():
    path, file_id = resolve_photo_storage(False, None, "tg_file_1")
    assert path is None
    assert file_id == "tg_file_1"


def test_format_meal_reply_labels_as_estimate():
    fields = {"kcal": 740, "protein_g": 48, "fat_g": 22, "carbs_g": 73, "value_source": "llm"}
    text = format_meal_reply(fields)
    assert "Szacunek" in text
    assert "740" in text


def test_format_meal_reply_labels_as_user_correction():
    fields = {"kcal": 740, "protein_g": 48, "fat_g": 22, "carbs_g": 73, "value_source": "user"}
    text = format_meal_reply(fields)
    assert "Twoja korekta" in text
