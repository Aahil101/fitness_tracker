"""Today's energy deficit, and what it implies for weight over time.

Two sources combine into one number:

* eating below maintenance — ``maintenance - eaten``
* deliberate exercise — the calories burned on top

which is the same quantity the forecast already tracks as
``DayEnergy.net_balance``, only with the sign flipped so a deficit reads
positive. Sharing the definition matters: a second, subtly different deficit
would contradict the projection shown elsewhere in the app.

Projections deliberately use the *average* deficit across recent logged days
rather than today's, and appear only once there are enough of them. A single
day is dominated by whether lunch was logged yet, so extrapolating from it
would promise a kilogram of loss at 11am and retract it by dinner.
"""

from __future__ import annotations

from typing import Any

from .energy import KCAL_PER_KG

# Below this, an average is still mostly noise, so no projection is offered.
MIN_DAYS_FOR_PROJECTION = 3

# Horizons worth showing: a week, a fortnight, a month.
PROJECTION_HORIZONS = (7, 14, 30)


def summarise(
    *,
    maintenance_calories: float,
    target_calories: float,
    eaten_calories: float,
    exercise_burn: float,
    avg_daily_net_kcal: float,
    days_with_data: int,
    current_weight_kg: float | None = None,
) -> dict[str, Any]:
    """Today's deficit plus projected loss, in the shape the home page needs."""
    # Mid-day, food not yet eaten is not a deficit earned. Measuring against
    # maintenance made an unfinished day look like an achievement: at 8pm with
    # 521 of 1,763 kcal eaten it claimed a 1,997 kcal food deficit and 150% of
    # plan, which then collapses as dinner is logged. Crediting only down to the
    # eating target keeps the figure to what the plan actually asks for, and it
    # still shrinks honestly once intake passes the target.
    effective_intake = max(eaten_calories, target_calories)
    food_deficit = maintenance_calories - effective_intake
    total_deficit = food_deficit + exercise_burn

    # True while the day can still change: the food part is the plan's, not a
    # result, so the UI can label it as on-track rather than banked.
    on_plan = eaten_calories < target_calories
    remaining_to_eat = max(0.0, target_calories - eaten_calories)

    # net_balance is negative for a deficit; flip it so "deficit" reads positive.
    avg_daily_deficit = -avg_daily_net_kcal
    enough = days_with_data >= MIN_DAYS_FOR_PROJECTION

    projections: list[dict[str, Any]] = []
    if enough and avg_daily_deficit > 0:
        for horizon in PROJECTION_HORIZONS:
            change_kg = avg_daily_deficit * horizon / KCAL_PER_KG
            entry: dict[str, Any] = {
                "days": horizon,
                "loss_kg": round(change_kg, 2),
            }
            if current_weight_kg:
                entry["weight_kg"] = round(current_weight_kg - change_kg, 1)
            projections.append(entry)

    if not enough:
        note = (
            f"Log {MIN_DAYS_FOR_PROJECTION - days_with_data} more day"
            f"{'s' if MIN_DAYS_FOR_PROJECTION - days_with_data != 1 else ''} "
            "to project your weight loss."
        )
    elif avg_daily_deficit <= 0:
        note = "No average deficit over recent days, so there is nothing to project yet."
    else:
        note = (
            f"Based on your average {avg_daily_deficit:.0f} kcal deficit "
            f"across {days_with_data} logged days."
        )

    return {
        # The three headline figures, in the order the home page shows them.
        "maintenance_calories": round(maintenance_calories, 1),
        "target_calories": round(target_calories, 1),
        "exercise_burn": round(exercise_burn, 1),
        "eaten_calories": round(eaten_calories, 1),
        "remaining_to_eat": round(remaining_to_eat, 1),
        # Deficit, split so the user can see where it came from.
        "food_deficit": round(food_deficit, 1),
        "exercise_deficit": round(exercise_burn, 1),
        "total_deficit": round(total_deficit, 1),
        "on_plan": on_plan,
        # How much of the day's intended deficit has been achieved, for a bar.
        "target_deficit": round(max(0.0, maintenance_calories - target_calories), 1),
        "progress_fraction": _progress(maintenance_calories, target_calories, food_deficit),
        # Projection, gated on having enough history.
        "tracked_days": days_with_data,
        "min_days_required": MIN_DAYS_FOR_PROJECTION,
        "has_enough_history": enough,
        "avg_daily_deficit": round(avg_daily_deficit, 1),
        "projections": projections,
        "note": note,
    }


def _progress(maintenance: float, target: float, food_deficit: float) -> float:
    """How much of the planned *eating* deficit is intact.

    Measures the food side only. Including exercise pinned the bar past 100% on
    any day with a workout, which says nothing about whether the plan is being
    followed — exercise is surplus to it, and is reported separately. Eating
    within the target reads full; going over eats into the bar.
    """
    intended = maintenance - target
    if intended <= 0:
        # Maintaining or bulking: no deficit to fill, so show it complete rather
        # than dividing by zero and rendering an empty bar forever.
        return 1.0 if food_deficit >= 0 else 0.0
    return round(max(0.0, min(1.0, food_deficit / intended)), 4)
