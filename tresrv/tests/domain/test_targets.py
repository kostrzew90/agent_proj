import pytest

from tresrv.domain.targets import bmr_mifflin_st_jeor, daily_target


def test_bmr_male():
    bmr = bmr_mifflin_st_jeor("m", waga_kg=80, wzrost_cm=180, wiek=30)
    assert bmr == pytest.approx(10 * 80 + 6.25 * 180 - 5 * 30 + 5)


def test_bmr_female():
    bmr = bmr_mifflin_st_jeor("k", waga_kg=65, wzrost_cm=165, wiek=28)
    assert bmr == pytest.approx(10 * 65 + 6.25 * 165 - 5 * 28 - 161)


def test_bmr_rejects_unknown_plec():
    with pytest.raises(ValueError):
        bmr_mifflin_st_jeor("x", waga_kg=80, wzrost_cm=180, wiek=30)


@pytest.mark.parametrize("cel,expected_modifier", [
    ("reduction", -0.20),
    ("mass", 0.15),
    ("maintenance", 0.0),
])
def test_daily_target_applies_goal_modifier(cel, expected_modifier):
    bmr = bmr_mifflin_st_jeor("m", waga_kg=80, wzrost_cm=180, wiek=30)
    tdee = bmr * 1.55  # moderate
    target = daily_target("m", 80, 180, 30, "moderate", cel)
    assert target.kcal == pytest.approx(tdee * (1 + expected_modifier), abs=1)


def test_daily_target_protein_is_1_8_per_kg():
    target = daily_target("m", 80, 180, 30, "moderate", "reduction")
    assert target.protein_g == pytest.approx(80 * 1.8, abs=0.1)
