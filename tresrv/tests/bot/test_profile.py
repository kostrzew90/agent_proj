import pytest
from datetime import datetime, timezone

from tresrv.bot.profile import parse_cel_command, format_profile
from tresrv.models import UserProfile


def test_parse_cel_command_valid():
    assert parse_cel_command(["reduction"]) == "reduction"


def test_parse_cel_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_cel_command([])


def test_parse_cel_command_invalid_value_raises():
    with pytest.raises(ValueError):
        parse_cel_command(["bulk"])


def test_format_profile_includes_all_fields():
    profile = UserProfile(
        chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
        updated_at=datetime.now(timezone.utc),
    )
    text = format_profile(profile)
    assert "180" in text
    assert "80" in text
    assert "reduction" in text
