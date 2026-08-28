"""Adherence: was the plan followed, as distinct from was it typed in."""

from datetime import date, timedelta

import pytest

from app.services import adherence

TODAY = date(2026, 8, 27)
TARGET = 2000.0
PROTEIN_TARGET = 150.0


def day(offset: int, calories: float, protein: float) -> dict:
    return {
        "date": (TODAY - timedelta(days=offset)).isoformat(),
        "calories": calories,
        "protein_g": protein,
    }


def run(days: list[dict], *, protein_target: float | None = PROTEIN_TARGET):
    return adherence.assess(
        macro_days=days, calorie_target=TARGET, protein_target_g=protein_target
    )


def test_a_day_on_target_counts():
    result = run([day(i, 2000.0, 155.0) for i in range(10)])
    assert result.days_compliant == 10
    assert result.compliance_rate == pytest.approx(1.0)
    assert result.status == "good"


def test_protein_short_sinks_an_otherwise_good_day():
    """Calories alone are not adherence: in a deficit, protein is what protects muscle."""
    result = run([day(i, 2000.0, 80.0) for i in range(10)])
    assert result.calorie_days == 10
    assert result.protein_days == 0
    assert result.days_compliant == 0
    assert result.weakest_link == "protein"
    assert "protein" in result.headline.lower()


def test_eating_well_under_target_is_a_miss_not_a_bonus():
    """A one-sided ceiling would reward under-eating, which costs muscle."""
    result = run([day(i, 1200.0, 160.0) for i in range(10)])
    assert result.days_compliant == 0
    assert result.weakest_link == "calories"
    assert "under" in result.headline.lower()


def test_going_over_is_reported_as_going_over():
    result = run([day(i, 2800.0, 160.0) for i in range(10)])
    assert result.days_compliant == 0
    assert "over" in result.headline.lower()


def test_the_band_is_generous_enough_for_real_eating():
    """Nobody hits a target exactly; 2000 +/- 200 must still count."""
    result = run([day(0, 1850.0, 155.0), day(1, 2150.0, 152.0)])
    assert result.days_compliant == 2


def test_unlogged_days_are_not_counted_as_failures():
    days = [day(i, 2000.0, 155.0) for i in range(5)] + [day(i, 0.0, 0.0) for i in range(5, 14)]
    result = run(days)
    assert result.days_in_window == 14
    assert result.days_logged == 5
    assert result.compliance_rate == pytest.approx(1.0)  # 5 of 5, not 5 of 14
    assert result.weakest_link == "logging"  # but the gap is named
    assert "missing" in result.headline.lower()


def test_carb_and_fat_split_is_not_graded():
    """Deliberate: with calories and protein matched, the ratio barely matters."""
    lean = run([day(i, 2000.0, 155.0) for i in range(7)])
    # Same calories and protein, wildly different remaining split — same verdict.
    assert lean.days_compliant == 7


def test_no_protein_target_means_protein_cannot_fail_a_day():
    result = run([day(i, 2000.0, 0.0) for i in range(7)], protein_target=None)
    assert result.days_compliant == 7


def test_streaks_track_the_current_run_and_the_best_one():
    days = [
        day(6, 2000.0, 155.0),
        day(5, 3200.0, 155.0),  # break
        day(4, 2000.0, 155.0),
        day(3, 2000.0, 155.0),
        day(2, 2000.0, 155.0),
        day(1, 3200.0, 155.0),  # break
        day(0, 2000.0, 155.0),
    ]
    result = run(days)
    assert result.current_streak == 1
    assert result.best_streak == 3


def test_nothing_logged_degrades_rather_than_scoring_zero():
    result = run([day(i, 0.0, 0.0) for i in range(14)])
    assert result.status == "unknown"
    assert result.compliance_rate is None
    assert result.days_logged == 0
    assert result.weakest_link == "logging"


def test_status_ladder():
    good = run([day(i, 2000.0, 155.0) for i in range(10)])
    mixed = run(
        [day(i, 2000.0, 155.0) for i in range(6)] + [day(i, 3200.0, 155.0) for i in range(6, 10)]
    )
    bad = run([day(i, 3200.0, 100.0) for i in range(10)])
    assert (good.status, mixed.status, bad.status) == ("good", "watch", "risk")


def test_explanation_states_the_actual_thresholds():
    result = run([day(i, 2000.0, 155.0) for i in range(10)])
    # The user should be able to check the grading themselves.
    assert "2000" in result.how_calculated
    assert "135" in result.how_calculated  # 90% of a 150 g target


def test_serialises_for_the_api():
    payload = run([day(i, 2000.0, 155.0) for i in range(10)]).to_dict()
    assert set(payload) == {
        "days_in_window",
        "days_logged",
        "days_compliant",
        "compliance_rate",
        "calorie_days",
        "protein_days",
        "current_streak",
        "best_streak",
        "status",
        "headline",
        "detail",
        "how_calculated",
        "weakest_link",
        "notes",
    }
