from datetime import date

from app.services.energy import (
    KCAL_PER_KG,
    MIN_SAFE_CALORIES,
    age_from_birth_date,
    bmr_mifflin_st_jeor,
    compute_goal,
    macro_targets,
    tdee,
    weekly_kcal_for_weight_change,
)


def test_bmr_matches_published_mifflin_st_jeor_values():
    # 10*80 + 6.25*180 - 5*30 + 5
    assert bmr_mifflin_st_jeor(80, 180, 30, "male") == 1780
    # ...and the female constant is -161
    assert bmr_mifflin_st_jeor(80, 180, 30, "female") == 1614


def test_unknown_sex_sits_between_male_and_female():
    male = bmr_mifflin_st_jeor(70, 170, 35, "male")
    female = bmr_mifflin_st_jeor(70, 170, 35, "female")
    neutral = bmr_mifflin_st_jeor(70, 170, 35, None)
    assert female < neutral < male


def test_tdee_applies_activity_multiplier():
    assert tdee(2000, "sedentary") == 2400
    assert tdee(2000, "active") == 3450
    # Unknown levels fall back to sedentary rather than inflating the ceiling.
    assert tdee(2000, "nonsense") == 2400


def test_macro_split_adds_back_up_to_the_calorie_target():
    macros = macro_targets(2000, 80)
    kcal = macros.protein_g * 4 + macros.carb_g * 4 + macros.fat_g * 9
    assert abs(kcal - 2000) < 5
    assert macros.protein_g == 144.0  # 1.8 g/kg
    assert macros.fiber_g == 28.0  # 14 g per 1000 kcal


def test_macro_split_never_produces_negative_carbs():
    # Heavy user on a very low target: protein alone would blow the budget.
    macros = macro_targets(1200, 150)
    assert macros.carb_g >= 0
    kcal = macros.protein_g * 4 + macros.carb_g * 4 + macros.fat_g * 9
    assert kcal <= 1210


def test_weekly_kcal_conversion_uses_7700_per_kg():
    assert weekly_kcal_for_weight_change(-0.5) == -3850
    assert weekly_kcal_for_weight_change(1.0) == int(KCAL_PER_KG)


def test_compute_goal_subtracts_the_daily_share_of_the_weekly_deficit():
    result = compute_goal(
        weight_kg=80,
        height_cm=180,
        age_years=30,
        sex="male",
        activity_level="sedentary",
        weekly_change_kg=-0.5,
    )
    assert result.maintenance_calories == 2136  # 1780 * 1.2
    assert result.daily_calorie_target == 1586  # 2136 - 3850/7
    assert result.projected_weekly_change_kg == -0.5
    assert result.warnings == []


def test_aggressive_deficit_is_capped_at_30_percent():
    result = compute_goal(
        weight_kg=60,
        height_cm=165,
        age_years=30,
        sex="female",
        activity_level="sedentary",
        weekly_change_kg=-1.5,
    )
    assert result.daily_calorie_target >= result.maintenance_calories * 0.7 - 1
    assert any("capped" in w for w in result.warnings)
    # The promised rate is recomputed after clamping, so it is honest.
    assert result.projected_weekly_change_kg > -1.5


def test_absolute_calorie_floor_is_enforced():
    result = compute_goal(
        weight_kg=45,
        height_cm=150,
        age_years=60,
        sex="female",
        activity_level="sedentary",
        weekly_change_kg=-1.0,
    )
    assert result.daily_calorie_target >= MIN_SAFE_CALORIES


def test_surplus_goals_increase_the_target():
    result = compute_goal(
        weight_kg=65,
        height_cm=178,
        age_years=22,
        sex="male",
        activity_level="moderate",
        weekly_change_kg=0.25,
    )
    assert result.daily_calorie_target > result.maintenance_calories
    assert result.projected_weekly_change_kg > 0


def test_non_sedentary_activity_warns_about_double_counting():
    result = compute_goal(
        weight_kg=80,
        height_cm=180,
        age_years=30,
        sex="male",
        activity_level="active",
        weekly_change_kg=-0.5,
    )
    assert any("already includes exercise" in w for w in result.warnings)


def test_maintenance_override_wins_over_the_equation():
    result = compute_goal(
        weight_kg=80,
        height_cm=180,
        age_years=30,
        sex="male",
        activity_level="sedentary",
        weekly_change_kg=-0.5,
        maintenance_override=2600,
    )
    assert result.maintenance_calories == 2600
    assert result.daily_calorie_target == 2050  # 2600 - 550


def test_age_from_birth_date_handles_pre_birthday():
    assert age_from_birth_date(date(1990, 12, 31), date(2026, 6, 1)) == 35
    assert age_from_birth_date(date(1990, 1, 1), date(2026, 6, 1)) == 36
    assert age_from_birth_date(None) == 30
