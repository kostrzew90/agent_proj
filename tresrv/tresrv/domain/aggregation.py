from dataclasses import dataclass


@dataclass(frozen=True)
class MealRow:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    status: str


@dataclass(frozen=True)
class DaySummary:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    meal_count: int


def aggregate_day(meals: list[MealRow]) -> DaySummary:
    active = [m for m in meals if m.status != "superseded"]
    return DaySummary(
        kcal=sum(m.kcal for m in active),
        protein_g=sum(m.protein_g for m in active),
        fat_g=sum(m.fat_g for m in active),
        carbs_g=sum(m.carbs_g for m in active),
        meal_count=len(active),
    )
