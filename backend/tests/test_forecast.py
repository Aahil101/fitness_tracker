from datetime import date, timedelta

from app.services.forecast import (
    DayEnergy,
    WeightPoint,
    forecast,
    linear_slope,
    observed_weekly_change,
    project_weight_series,
)

TODAY = date(2026, 8, 27)


def make_days(count: int, calories_in: float, burn: float = 0.0, *, logged: bool = True):
    return [
        DayEnergy(
            day=TODAY - timedelta(days=offset),
            calories_in=calories_in if logged else 0.0,
            calories_out=burn,
            food_entries=3 if logged else 0,
        )
        for offset in range(count)
    ]


def test_net_balance_counts_maintenance_and_exercise():
    day = DayEnergy(day=TODAY, calories_in=2000, calories_out=300, food_entries=2)
    assert day.net_balance(2500) == -800


def test_projection_converts_net_balance_at_7700_kcal_per_kg():
    result = forecast(days=make_days(7, 2000, 300), maintenance_calories=2500, today=TODAY)
    assert result.avg_daily_net_kcal == -800
    # -800 * 7 / 7700
    assert result.projected_weekly_change_kg == -0.727
    assert result.projected_monthly_change_kg == -3.117
    assert result.confidence == "high"


def test_unlogged_days_are_excluded_not_treated_as_fasting():
    # Three logged days followed by four days the user forgot to log.
    days = [
        DayEnergy(day=TODAY - timedelta(days=offset), calories_in=2200, food_entries=3)
        for offset in range(3)
    ] + [
        DayEnergy(day=TODAY - timedelta(days=offset), calories_in=0, food_entries=0)
        for offset in range(3, 7)
    ]
    result = forecast(days=days, maintenance_calories=2200, window_days=7, today=TODAY)
    assert result.days_with_data == 3
    assert result.avg_daily_net_kcal == 0  # only the logged days counted
    assert result.confidence == "low"
    assert any("3 of 7 days" in note for note in result.notes)


def test_empty_window_is_reported_rather_than_projecting_zero_silently():
    result = forecast(days=[], maintenance_calories=2200, today=TODAY)
    assert result.days_with_data == 0
    assert result.projected_weekly_change_kg == 0
    assert result.confidence == "low"
    assert any("No food logged" in note for note in result.notes)


def test_linear_slope_recovers_a_known_gradient():
    assert linear_slope([0, 1, 2, 3], [10, 12, 14, 16]) == 2.0
    assert linear_slope([1, 1, 1], [5, 6, 7]) is None
    assert linear_slope([1], [5]) is None


def test_observed_weekly_change_from_the_scale():
    points = [
        WeightPoint(day=TODAY - timedelta(days=14 - i), weight_kg=80.0 - i * 0.1)
        for i in range(15)
    ]
    weekly, span = observed_weekly_change(points)
    assert span == 14
    assert weekly is not None
    assert abs(weekly - (-0.7)) < 0.01


def test_observed_change_needs_a_meaningful_span():
    points = [
        WeightPoint(day=TODAY - timedelta(days=1), weight_kg=80.0),
        WeightPoint(day=TODAY, weight_kg=79.5),
    ]
    weekly, _ = observed_weekly_change(points)
    assert weekly is None


def test_measured_trend_takes_over_for_time_to_goal():
    days = make_days(14, 2000, 0)
    points = [
        WeightPoint(day=TODAY - timedelta(days=20 - i), weight_kg=85.0 - i * 0.05)
        for i in range(21)
    ]
    result = forecast(
        days=days,
        maintenance_calories=2500,
        window_days=14,
        weight_points=points,
        goal_weight_kg=80.0,
        today=TODAY,
    )
    assert result.observed_weekly_change_kg is not None
    assert result.effective_weekly_change_kg == result.observed_weekly_change_kg
    assert result.days_to_goal and result.days_to_goal > 0
    assert result.goal_date and result.goal_date > TODAY


def test_no_eta_when_the_trend_points_away_from_the_goal():
    days = make_days(7, 3200)
    points = [WeightPoint(day=TODAY - timedelta(days=i), weight_kg=85.0) for i in range(3)]
    result = forecast(
        days=days,
        maintenance_calories=2500,
        window_days=7,
        weight_points=points,
        goal_weight_kg=80.0,
        today=TODAY,
    )
    assert result.projected_weekly_change_kg > 0
    assert result.days_to_goal is None


def test_projected_weights_are_anchored_to_the_latest_weigh_in():
    points = [WeightPoint(day=TODAY, weight_kg=90.0)]
    result = forecast(
        days=make_days(7, 2000, 200),
        maintenance_calories=2600,
        weight_points=points,
        today=TODAY,
    )
    assert result.current_weight_kg == 90.0
    assert result.projected_weight_7d_kg == round(90.0 + result.projected_weekly_change_kg, 2)


def test_projection_series_is_a_straight_line_from_the_last_point():
    series = project_weight_series(
        start_weight_kg=80.0, weekly_change_kg=-0.7, start_day=TODAY, days=14, step_days=7
    )
    assert [p["date"] for p in series] == [
        TODAY.isoformat(),
        (TODAY + timedelta(days=7)).isoformat(),
        (TODAY + timedelta(days=14)).isoformat(),
    ]
    assert series[1]["projected_kg"] == 79.3
    assert series[2]["projected_kg"] == 78.6
