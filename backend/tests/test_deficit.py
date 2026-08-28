"""Today's deficit and the weight projection built from it."""

import pytest

from app.services import deficit
from app.services.energy import KCAL_PER_KG

# Intake sits on the target so the headline figures are final rather than
# still-provisional; the mid-day case is exercised explicitly below.
BASE = {
    "maintenance_calories": 2400.0,
    "target_calories": 1900.0,
    "eaten_calories": 1900.0,
    "exercise_burn": 300.0,
}


def test_deficit_is_food_plus_exercise():
    out = deficit.summarise(**BASE, avg_daily_net_kcal=-600.0, days_with_data=7)

    assert out["food_deficit"] == 500.0, "2400 maintenance - 1900 eaten"
    assert out["exercise_deficit"] == 300.0
    assert out["total_deficit"] == 800.0, "500 from eating under + 300 burned"


def test_deficit_matches_the_forecasts_own_definition():
    """net_balance is intake - (maintenance + burn); this is that, negated."""
    from app.services.forecast import DayEnergy

    day = DayEnergy(day=None, calories_in=1900.0, calories_out=300.0, food_entries=3)  # type: ignore[arg-type]
    net = day.net_balance(2400.0)

    out = deficit.summarise(**BASE, avg_daily_net_kcal=net, days_with_data=7)
    assert out["total_deficit"] == pytest.approx(-net)


def test_projection_uses_the_average_not_today():
    """Today's figure swings with whether lunch is logged yet."""
    out = deficit.summarise(**BASE, avg_daily_net_kcal=-500.0, days_with_data=10)

    assert out["avg_daily_deficit"] == 500.0
    by_days = {p["days"]: p for p in out["projections"]}
    assert set(by_days) == {7, 14, 30}
    assert by_days[7]["loss_kg"] == pytest.approx(500 * 7 / KCAL_PER_KG, abs=0.01)
    assert by_days[30]["loss_kg"] == pytest.approx(500 * 30 / KCAL_PER_KG, abs=0.01)
    # not derived from today's 800
    assert by_days[7]["loss_kg"] != pytest.approx(800 * 7 / KCAL_PER_KG, abs=0.01)


@pytest.mark.parametrize("days", [0, 1, 2])
def test_under_three_days_offers_no_projection(days):
    out = deficit.summarise(**BASE, avg_daily_net_kcal=-600.0, days_with_data=days)

    assert out["has_enough_history"] is False
    assert out["projections"] == []
    assert f"{3 - days} more day" in out["note"]
    # today's numbers are still shown; only the projection waits
    assert out["total_deficit"] == 800.0


def test_three_days_is_enough():
    out = deficit.summarise(**BASE, avg_daily_net_kcal=-600.0, days_with_data=3)
    assert out["has_enough_history"] is True
    assert len(out["projections"]) == 3
    assert "3 logged days" in out["note"]


def test_a_surplus_projects_nothing_rather_than_a_gain():
    """The panel is about deficit; a surplus should say so, not promise loss."""
    out = deficit.summarise(**BASE, avg_daily_net_kcal=+400.0, days_with_data=10)

    assert out["avg_daily_deficit"] == -400.0
    assert out["projections"] == []
    assert "nothing to project" in out["note"]


def test_projected_weight_counts_down_from_the_current_weight():
    out = deficit.summarise(
        **BASE, avg_daily_net_kcal=-770.0, days_with_data=7, current_weight_kg=80.0
    )
    week = next(p for p in out["projections"] if p["days"] == 7)
    # 770 kcal/day for 7 days = 5390 kcal = 0.7 kg
    assert week["loss_kg"] == pytest.approx(0.7, abs=0.01)
    assert week["weight_kg"] == pytest.approx(79.3, abs=0.05)


def test_progress_bar_tracks_the_eating_plan_not_exercise():
    """Exercise is surplus to the plan; counting it pinned the bar past full."""
    out = deficit.summarise(**BASE, avg_daily_net_kcal=-600.0, days_with_data=7)
    assert out["target_deficit"] == 500.0
    assert out["progress_fraction"] == pytest.approx(1.0), "eating on target = full"

    # halfway into the allowance overspend: 2400 - 2150 = 250 of the 500 planned
    half = deficit.summarise(
        maintenance_calories=2400.0, target_calories=1900.0,
        eaten_calories=2150.0, exercise_burn=900.0,
        avg_daily_net_kcal=-250.0, days_with_data=7,
    )
    assert half["food_deficit"] == 250.0
    assert half["progress_fraction"] == pytest.approx(0.5), "900 kcal burned must not fill it"


def test_an_unfinished_day_is_not_counted_as_deficit_earned():
    """The bug: food not yet eaten was being banked as an achievement.

    Reported from the live app — at 8pm with 521 of 1,763 kcal eaten it claimed a
    1,997 kcal food deficit, a 2,432 kcal total and 150% of plan, all of which
    evaporates as dinner is logged.
    """
    out = deficit.summarise(
        maintenance_calories=2518.0, target_calories=1763.0,
        eaten_calories=521.0, exercise_burn=436.0,
        avg_daily_net_kcal=-600.0, days_with_data=1,
    )

    assert out["food_deficit"] == 755.0, "the plan's deficit, not 2518 - 521"
    assert out["total_deficit"] == 1191.0, "not 2432"
    assert out["progress_fraction"] == pytest.approx(1.0)
    assert out["on_plan"] is True, "still provisional: the day can change"
    assert out["remaining_to_eat"] == 1242.0


def test_eating_past_the_target_erodes_the_deficit_honestly():
    out = deficit.summarise(
        maintenance_calories=2518.0, target_calories=1763.0,
        eaten_calories=2600.0, exercise_burn=436.0,
        avg_daily_net_kcal=100.0, days_with_data=5,
    )
    assert out["food_deficit"] == pytest.approx(-82.0), "past maintenance is a surplus"
    assert out["total_deficit"] == pytest.approx(354.0), "exercise still offsets it"
    assert out["progress_fraction"] == 0.0
    assert out["on_plan"] is False


def test_maintaining_does_not_divide_by_zero():
    out = deficit.summarise(
        maintenance_calories=2400.0, target_calories=2400.0,
        eaten_calories=2400.0, exercise_burn=0.0,
        avg_daily_net_kcal=0.0, days_with_data=7,
    )
    assert out["target_deficit"] == 0.0
    assert out["progress_fraction"] == 1.0
