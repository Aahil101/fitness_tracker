"""Maintenance measured from logs: the arithmetic, and the guards around it."""

from datetime import date, timedelta

import pytest

from app.services import expenditure
from app.services.energy import KCAL_PER_KG
from app.services.trend import TrendDay

TODAY = date(2026, 8, 27)
FORMULA = 2300.0


def series(days: int, start_kg: float, end_kg: float) -> list[TrendDay]:
    """A straight trend from start to end, one entry per day."""
    step = (end_kg - start_kg) / (days - 1)
    return [
        TrendDay(day=TODAY - timedelta(days=days - 1 - i), trend_kg=start_kg + step * i, scale_kg=None)
        for i in range(days)
    ]


def flat_intake(trend_series: list[TrendDay], kcal: float) -> dict:
    return {d.day: kcal for d in trend_series}


def logged_all(trend_series: list[TrendDay]) -> set:
    return {d.day for d in trend_series}


def test_backs_maintenance_out_of_intake_and_weight_change():
    """The core inversion: expenditure = intake - stored energy change."""
    trend_series = series(28, 80.0, 79.0)  # 1 kg down over 27 days of span
    result = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 2000.0),
        logged_days=logged_all(trend_series),
    )
    expected = 2000.0 + (1.0 * KCAL_PER_KG / 27)
    assert result.measured_kcal == pytest.approx(expected, abs=1.0)
    assert result.source == "measured"
    assert result.confidence == "high"


def test_exercise_is_subtracted_so_workouts_are_not_counted_twice():
    """The subtle one.

    Energy balance yields *total* expenditure, which includes exercise. But this
    app adds logged workout burn on top of maintenance everywhere else, so
    handing the total over as maintenance would count every session twice and
    inflate the user's target by exactly their training.
    """
    trend_series = series(28, 80.0, 79.0)
    common = {
        "formula_maintenance": FORMULA,
        "trend_series": trend_series,
        "intake_by_day": flat_intake(trend_series, 2000.0),
        "logged_days": logged_all(trend_series),
    }
    without = expenditure.estimate(**common)
    with_training = expenditure.estimate(
        **common, exercise_by_day={d.day: 300.0 for d in trend_series}
    )
    assert without.measured_kcal is not None and with_training.measured_kcal is not None
    assert without.measured_kcal - with_training.measured_kcal == pytest.approx(300.0, abs=0.5)


def test_a_surplus_reads_as_a_lower_expenditure():
    """Gaining while eating 3000 means burning less than 3000."""
    trend_series = series(28, 80.0, 81.0)
    result = expenditure.estimate(
        formula_maintenance=3000.0,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 3000.0),
        logged_days=logged_all(trend_series),
    )
    assert result.measured_kcal is not None
    assert result.measured_kcal < 3000.0


def test_sparse_logging_falls_back_to_the_formula():
    trend_series = series(28, 80.0, 79.0)
    only_a_few = {d.day for d in trend_series[:6]}
    result = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 2000.0),
        logged_days=only_a_few,
    )
    assert result.source == "formula"
    assert result.maintenance_kcal == FORMULA
    assert result.measured_kcal is None
    assert result.notes  # tells the user what would unlock it


def test_no_weight_history_falls_back_to_the_formula():
    result = expenditure.estimate(
        formula_maintenance=FORMULA, trend_series=[], intake_by_day={}, logged_days=set()
    )
    assert result.source == "formula"
    assert result.maintenance_kcal == FORMULA
    assert "weigh" in result.notes[0].lower()


def test_an_absurd_estimate_is_clamped_rather_than_handed_to_the_user():
    """A mistyped weigh-in must not be able to rewrite someone's target."""
    trend_series = series(28, 85.0, 80.0)  # 5 kg in four weeks while eating 2000
    result = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 2000.0),
        logged_days=logged_all(trend_series),
    )
    ceiling = FORMULA * (1 + expenditure.MAX_DIVERGENCE_FRACTION)
    assert result.measured_kcal == pytest.approx(ceiling, abs=0.5)
    assert any("capped" in note for note in result.notes)


def test_thin_history_is_blended_towards_the_formula_not_trusted_outright():
    trend_series = series(12, 80.0, 79.6)
    result = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 2000.0),
        logged_days=logged_all(trend_series),
    )
    assert result.source == "blended"
    assert 0.0 < result.trust < 0.75
    # The reported figure sits between the two inputs.
    low, high = sorted([FORMULA, result.measured_kcal])
    assert low <= result.maintenance_kcal <= high


def test_trust_grows_with_history():
    short = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=(s := series(12, 80.0, 79.6)),
        intake_by_day=flat_intake(s, 2000.0),
        logged_days=logged_all(s),
    )
    long = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=(t := series(28, 80.0, 79.0)),
        intake_by_day=flat_intake(t, 2000.0),
        logged_days=logged_all(t),
    )
    assert long.trust > short.trust


def test_unlogged_days_are_not_read_as_zero_calorie_days():
    """Intake must be averaged over logged days, not over the whole window."""
    trend_series = series(28, 80.0, 79.0)
    every_other = {d.day for i, d in enumerate(trend_series) if i % 2 == 0}
    intake = {d: 2000.0 for d in every_other}
    result = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=intake,
        logged_days=every_other,
    )
    # 14 logged days at 2000 kcal. Averaging over 28 would halve it to 1000 and
    # report a wildly low expenditure.
    assert result.measured_kcal is not None
    assert result.measured_kcal > 2000.0


def test_explanation_is_always_present_and_names_its_source():
    trend_series = series(28, 80.0, 79.0)
    measured = expenditure.estimate(
        formula_maintenance=FORMULA,
        trend_series=trend_series,
        intake_by_day=flat_intake(trend_series, 2000.0),
        logged_days=logged_all(trend_series),
    )
    assert "measured" in measured.how_calculated.lower()
    fallback = expenditure.estimate(
        formula_maintenance=FORMULA, trend_series=[], intake_by_day={}, logged_days=set()
    )
    assert "estimated" in fallback.how_calculated.lower()


def test_serialises_for_the_api():
    payload = expenditure.estimate(
        formula_maintenance=FORMULA, trend_series=[], intake_by_day={}, logged_days=set()
    ).to_dict()
    assert set(payload) == {
        "maintenance_kcal",
        "formula_kcal",
        "measured_kcal",
        "source",
        "confidence",
        "divergence_kcal",
        "days_used",
        "days_logged",
        "logged_fraction",
        "trust",
        "how_calculated",
        "notes",
    }
