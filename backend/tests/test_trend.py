"""Trend weight: does it reject noise, and does it recover a known rate?"""

from datetime import date, timedelta

import pytest

from app.services import trend
from app.services.trend import WeightPoint

TODAY = date(2026, 8, 27)


def linear(days: int, start_kg: float, per_day: float, *, end: date = TODAY) -> list[WeightPoint]:
    """A clean ramp: the rate is known exactly, so the fit can be checked."""
    return [
        WeightPoint(day=end - timedelta(days=days - 1 - i), weight_kg=start_kg + per_day * i)
        for i in range(days)
    ]


def noisy(days: int, base_kg: float, swing_kg: float, *, end: date = TODAY) -> list[WeightPoint]:
    """Flat underneath, with a large alternating water swing on top."""
    return [
        WeightPoint(
            day=end - timedelta(days=days - 1 - i),
            weight_kg=base_kg + (swing_kg if i % 2 else -swing_kg),
        )
        for i in range(days)
    ]


def test_recovers_a_known_rate_of_loss():
    # 0.1 kg/day is 0.7 kg/week. The trend must say so, not something shallower:
    # a smoother that understates progress tells the user their diet is failing.
    result = trend.analyse(points=linear(30, 90.0, -0.1))
    assert result.weekly_change_kg == pytest.approx(-0.7, abs=0.05)


def test_rate_is_not_dragged_down_by_the_smoother_starting_cold():
    """The start-up transient used to cost a quarter of the measured rate."""
    short = trend.analyse(points=linear(21, 83.0, -0.08))
    assert short.weekly_change_kg == pytest.approx(-0.56, abs=0.05)


def test_trend_ignores_a_swing_the_raw_readings_cannot():
    result = trend.analyse(points=noisy(30, 80.0, 1.0))
    # Underlying weight is flat, so the trend must be flat despite 2 kg of swing.
    assert result.trend_kg == pytest.approx(80.0, abs=0.35)
    assert abs(result.weekly_change_kg) < 0.15
    assert result.rate_status == "holding"
    # And it should tell the user how big their own noise is.
    assert result.noise_kg == pytest.approx(1.0, abs=0.35)


def test_one_heavy_morning_barely_moves_the_trend():
    points = linear(20, 80.0, 0.0)
    baseline = trend.analyse(points=points).trend_kg
    points[-1] = WeightPoint(day=TODAY, weight_kg=82.0)  # a salty dinner
    after = trend.analyse(points=points).trend_kg
    # A 2 kg reading may not move the trend by more than a fraction of that.
    assert abs(after - baseline) < 0.7


def test_trend_sits_where_the_readings_are_rather_than_lagging_behind():
    """A trend reading a kilogram above the scale looks broken, so it is de-lagged."""
    result = trend.analyse(points=linear(40, 95.0, -0.1))
    assert result.scale_kg is not None
    assert result.trend_kg == pytest.approx(result.scale_kg, abs=0.2)


def test_gaps_are_interpolated_so_a_day_is_worth_a_day():
    sparse = [
        WeightPoint(day=TODAY - timedelta(days=20), weight_kg=82.0),
        WeightPoint(day=TODAY - timedelta(days=10), weight_kg=81.0),
        WeightPoint(day=TODAY, weight_kg=80.0),
    ]
    result = trend.analyse(points=sparse)
    assert result.days_of_data == 3
    assert result.interpolated_days == 18  # 21 days spanned, 3 measured
    assert len(result.series) == 21


def test_a_long_silence_is_not_bridged_with_invented_readings():
    stale = [
        WeightPoint(day=TODAY - timedelta(days=200), weight_kg=95.0),
        WeightPoint(day=TODAY, weight_kg=80.0),
    ]
    result = trend.analyse(points=stale)
    # Two measured points, and no fabricated run between them.
    assert result.interpolated_days == 0
    assert len(result.series) == 2


def test_rate_needs_a_span_not_just_a_count():
    """Three weigh-ins in three days cannot establish a weekly rate."""
    result = trend.analyse(points=linear(3, 80.0, -0.3))
    assert result.weekly_change_kg is None
    assert result.rate_status == "unknown"
    assert "more" in result.rate_detail.lower() or "weigh" in result.rate_detail.lower()


def test_no_weigh_ins_degrades_rather_than_raising():
    result = trend.analyse(points=[])
    assert result.trend_kg is None
    assert result.rate_status == "unknown"
    assert result.to_dict()["series"] == []


def test_percentage_is_relative_to_bodyweight():
    """The same kilogram means different things at different sizes."""
    light = trend.analyse(points=linear(30, 55.0, -0.1))
    heavy = trend.analyse(points=linear(30, 110.0, -0.1))
    assert light.weekly_change_pct is not None and heavy.weekly_change_pct is not None
    # Same absolute rate, roughly double the relative cost for the lighter person.
    assert abs(light.weekly_change_pct) > abs(heavy.weekly_change_pct) * 1.8


class TestRateBands:
    """The band is the guidance a coach would apply, so it must be labelled."""

    def test_inside_the_band_is_on_target(self):
        status, label, detail = trend.classify_rate(-0.75, "lose")
        assert status == "on_target"
        assert label and detail  # never a colour without words

    def test_below_the_band_is_gentle_not_a_failure(self):
        status, _, _ = trend.classify_rate(-0.3, "lose")
        assert status == "gentle"

    def test_above_the_band_flags_lean_mass_risk(self):
        status, _, detail = trend.classify_rate(-1.6, "lose")
        assert status == "rapid"
        assert "muscle" in detail.lower()

    def test_flat_is_holding_whichever_way_the_goal_points(self):
        assert trend.classify_rate(0.02, "lose")[0] == "holding"
        assert trend.classify_rate(-0.02, "maintain")[0] == "holding"

    def test_moving_away_from_the_goal_is_called_out(self):
        assert trend.classify_rate(0.6, "lose")[0] == "wrong_way"
        assert trend.classify_rate(-0.6, "gain")[0] == "wrong_way"

    def test_gaining_has_a_tighter_band_than_losing(self):
        # 0.75%/week is fine when cutting and too fast when bulking.
        assert trend.classify_rate(-0.75, "lose")[0] == "on_target"
        assert trend.classify_rate(0.75, "gain")[0] == "rapid"

    def test_unknown_when_there_is_no_rate(self):
        status, label, detail = trend.classify_rate(None, "lose")
        assert status == "unknown"
        assert label and detail


def test_direction_comes_from_the_goal_weight():
    losing = trend.analyse(points=linear(30, 90.0, -0.1), goal_weight_kg=80.0)
    assert losing.rate_status in {"gentle", "on_target", "rapid"}
    # Same data, but the user wants to gain: the identical rate is now wrong-way.
    gaining = trend.analyse(points=linear(30, 90.0, -0.1), goal_weight_kg=95.0)
    assert gaining.rate_status == "wrong_way"


def test_serialises_for_the_api():
    payload = trend.analyse(points=linear(20, 80.0, -0.05)).to_dict()
    assert set(payload) == {
        "trend_kg",
        "scale_kg",
        "deviation_kg",
        "noise_kg",
        "weekly_change_kg",
        "weekly_change_pct",
        "rate_status",
        "rate_label",
        "rate_detail",
        "days_of_data",
        "span_days",
        "interpolated_days",
        "how_calculated",
        "series",
    }
    assert payload["series"][0].keys() == {"date", "trend_kg", "scale_kg"}
    assert payload["how_calculated"]
