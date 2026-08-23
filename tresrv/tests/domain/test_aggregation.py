from tresrv.domain.aggregation import MealRow, aggregate_day


def test_aggregate_day_sums_active_meals():
    meals = [
        MealRow(kcal=300, protein_g=20, fat_g=10, carbs_g=30, status="parsed"),
        MealRow(kcal=500, protein_g=30, fat_g=15, carbs_g=50, status="parsed"),
    ]
    summary = aggregate_day(meals)
    assert summary.kcal == 800
    assert summary.protein_g == 50
    assert summary.fat_g == 25
    assert summary.carbs_g == 80
    assert summary.meal_count == 2


def test_aggregate_day_excludes_superseded():
    meals = [
        MealRow(kcal=300, protein_g=20, fat_g=10, carbs_g=30, status="superseded"),
        MealRow(kcal=320, protein_g=22, fat_g=10, carbs_g=30, status="corrected"),
    ]
    summary = aggregate_day(meals)
    assert summary.kcal == 320
    assert summary.meal_count == 1


def test_aggregate_day_empty_list():
    summary = aggregate_day([])
    assert summary.kcal == 0
    assert summary.meal_count == 0
