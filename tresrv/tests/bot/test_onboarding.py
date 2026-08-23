import pytest

from tresrv.bot.onboarding import (
    parse_plec, parse_wiek, parse_wzrost, parse_waga, parse_aktywnosc, parse_cel,
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
