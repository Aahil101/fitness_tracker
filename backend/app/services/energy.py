"""Energy expenditure and macro-target maths.

Everything here is a pure function so it can be unit tested and reused by both
the goals endpoint and the forecasting engine. Classical equations only — no
models, no fitted parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# 1 kg of body fat ≈ 7700 kcal. Used for every weight <-> energy conversion.
KCAL_PER_KG = 7700.0

# Mifflin-St Jeor activity multipliers -> TDEE.
ACTIVITY_MULTIPLIERS: dict[str, float] = {
    "sedentary": 1.2,   # desk job, little deliberate movement
    "light": 1.375,     # light exercise 1-3 days/week
    "moderate": 1.55,   # moderate exercise 3-5 days/week
    "active": 1.725,    # hard exercise 6-7 days/week
}

# Guard rails. Aggressive deficits are the single most common way these apps
# produce harmful advice, so the floor is enforced in code, not in the UI.
MIN_SAFE_CALORIES = 1200
MAX_DAILY_DEFICIT_FRACTION = 0.30  # never cut more than 30% below maintenance

DEFAULT_AGE_YEARS = 30
PROTEIN_G_PER_KG = 1.8
FAT_FRACTION_OF_KCAL = 0.25
FIBER_G_PER_1000_KCAL = 14.0


@dataclass
class MacroTargets:
    protein_g: float
    carb_g: float
    fat_g: float
    fiber_g: float


@dataclass
class GoalComputation:
    maintenance_calories: int
    daily_calorie_target: int
    bmr: int
    target_weekly_deficit_kcal: int
    projected_weekly_change_kg: float
    macros: MacroTargets
    warnings: list[str] = field(default_factory=list)


def age_from_birth_date(birth_date: date | None, today: date | None = None) -> int:
    if birth_date is None:
        return DEFAULT_AGE_YEARS
    today = today or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(13, min(100, years))


def bmr_mifflin_st_jeor(
    weight_kg: float,
    height_cm: float,
    age_years: int,
    sex: str | None,
) -> float:
    """Mifflin-St Jeor resting energy expenditure in kcal/day.

    ``sex`` of None/'other' uses the midpoint of the male and female constants
    (-78) rather than defaulting to one, which keeps the error symmetric.
    """
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_years
    constant = {"male": 5.0, "female": -161.0}.get((sex or "").lower(), -78.0)
    return max(800.0, base + constant)


def tdee(bmr: float, activity_level: str | None) -> float:
    multiplier = ACTIVITY_MULTIPLIERS.get((activity_level or "sedentary").lower(), 1.2)
    return bmr * multiplier


def macro_targets(calorie_target: float, weight_kg: float) -> MacroTargets:
    """Protein-first split: fixed g/kg protein, 25% fat, carbohydrate remainder."""
    protein_g = PROTEIN_G_PER_KG * weight_kg
    fat_g = (FAT_FRACTION_OF_KCAL * calorie_target) / 9.0

    # If protein + fat already exceed the budget (very low targets, heavy user),
    # scale both down proportionally so carbs never go negative.
    locked_kcal = protein_g * 4.0 + fat_g * 9.0
    min_carb_kcal = 0.10 * calorie_target
    if locked_kcal > calorie_target - min_carb_kcal:
        scale = max(0.1, (calorie_target - min_carb_kcal) / locked_kcal)
        protein_g *= scale
        fat_g *= scale

    carb_kcal = max(0.0, calorie_target - (protein_g * 4.0 + fat_g * 9.0))
    return MacroTargets(
        protein_g=round(protein_g, 1),
        carb_g=round(carb_kcal / 4.0, 1),
        fat_g=round(fat_g, 1),
        fiber_g=round(FIBER_G_PER_1000_KCAL * calorie_target / 1000.0, 1),
    )


def weekly_kcal_for_weight_change(weekly_change_kg: float) -> int:
    """Energy balance needed per week for a target weight change.

    Negative ``weekly_change_kg`` (losing weight) yields a negative kcal figure,
    matching the ``goals.target_weekly_deficit_kcal`` sign convention.
    """
    return int(round(weekly_change_kg * KCAL_PER_KG))


def compute_goal(
    *,
    weight_kg: float,
    height_cm: float,
    age_years: int,
    sex: str | None,
    activity_level: str | None,
    weekly_change_kg: float | None = None,
    target_weekly_deficit_kcal: int | None = None,
    maintenance_override: int | None = None,
) -> GoalComputation:
    """Derive maintenance calories, the deficit-adjusted target, and macros.

    Exactly one of ``weekly_change_kg`` / ``target_weekly_deficit_kcal`` is
    needed; the kcal figure wins if both are supplied. Both use the same sign
    convention: negative means losing weight.
    """
    warnings: list[str] = []

    bmr = bmr_mifflin_st_jeor(weight_kg, height_cm, age_years, sex)
    maintenance = float(maintenance_override) if maintenance_override else tdee(bmr, activity_level)

    if target_weekly_deficit_kcal is None:
        change = -0.5 if weekly_change_kg is None else weekly_change_kg
        target_weekly_deficit_kcal = weekly_kcal_for_weight_change(change)

    daily_delta = target_weekly_deficit_kcal / 7.0
    target = maintenance + daily_delta

    # Cap the deficit as a fraction of maintenance.
    floor_by_fraction = maintenance * (1.0 - MAX_DAILY_DEFICIT_FRACTION)
    if target < floor_by_fraction:
        target = floor_by_fraction
        warnings.append(
            f"Deficit capped at {int(MAX_DAILY_DEFICIT_FRACTION * 100)}% below maintenance "
            "to keep the plan sustainable."
        )

    # Absolute floor.
    if target < MIN_SAFE_CALORIES:
        target = float(MIN_SAFE_CALORIES)
        warnings.append(
            f"Daily target raised to the {MIN_SAFE_CALORIES} kcal safety floor."
        )

    # Recompute the achievable weekly change after clamping so the UI never
    # promises a rate the target cannot deliver.
    effective_weekly_kcal = (target - maintenance) * 7.0
    projected_weekly_change_kg = effective_weekly_kcal / KCAL_PER_KG

    if (activity_level or "").lower() != "sedentary":
        warnings.append(
            "Your activity multiplier already includes exercise. Logged workouts are "
            "shown separately and will overlap with it — pick 'sedentary' if you plan "
            "to log every workout."
        )

    return GoalComputation(
        maintenance_calories=int(round(maintenance)),
        daily_calorie_target=int(round(target)),
        bmr=int(round(bmr)),
        target_weekly_deficit_kcal=int(round(effective_weekly_kcal)),
        projected_weekly_change_kg=round(projected_weekly_change_kg, 3),
        macros=macro_targets(target, weight_kg),
        warnings=warnings,
    )
