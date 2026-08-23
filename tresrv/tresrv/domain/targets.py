from dataclasses import dataclass

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_MODIFIERS = {
    "reduction": -0.20,
    "mass": 0.15,
    "maintenance": 0.0,
}


@dataclass(frozen=True)
class DailyTarget:
    kcal: float
    protein_g: float


def bmr_mifflin_st_jeor(plec: str, waga_kg: float, wzrost_cm: float, wiek: int) -> float:
    base = 10 * waga_kg + 6.25 * wzrost_cm - 5 * wiek
    if plec == "m":
        return base + 5
    if plec == "k":
        return base - 161
    raise ValueError(f"Nieznana płeć: {plec}")


def daily_target(
    plec: str, waga_kg: float, wzrost_cm: float, wiek: int,
    poziom_aktywnosci: str, cel: str,
) -> DailyTarget:
    bmr = bmr_mifflin_st_jeor(plec, waga_kg, wzrost_cm, wiek)
    tdee = bmr * ACTIVITY_MULTIPLIERS[poziom_aktywnosci]
    kcal = tdee * (1 + GOAL_MODIFIERS[cel])
    protein_g = waga_kg * 1.8
    return DailyTarget(kcal=round(kcal, 1), protein_g=round(protein_g, 1))
