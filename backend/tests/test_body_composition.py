"""Telling fat loss from muscle loss.

These assertions guard the honesty of the feature as much as the arithmetic: it
must never claim to have measured body composition, must refuse to judge on thin
data, and must name one fix rather than reciting every rule.
"""

from app.services import body_composition as bc


def strength(n: int) -> list[dict[str, str]]:
    return [{"activity_type": "weights"} for _ in range(n)]


BASE = {
    "weight_kg": 80.0,
    "span_days": 28,
    "logged_days": 24,
    "maintenance_calories": 2400.0,
}


def test_slow_loss_with_protein_and_lifting_reads_as_fat_loss():
    result = bc.assess(
        **BASE,
        weekly_change_kg=-0.5,  # 0.63% of bodyweight
        avg_protein_g=140.0,  # 1.75 g/kg
        avg_calories_in=1950.0,  # 19% deficit
        workout_rows=strength(8),
    )
    assert result.verdict == "mostly_fat"
    assert result.lean_risk_score == 0
    assert {s.status for s in result.signals} == {"good"}
    assert "nothing to change" in result.focus.lower()


def test_crash_deficit_without_protein_or_lifting_flags_muscle_loss():
    result = bc.assess(
        **BASE,
        weekly_change_kg=-1.4,  # 1.75% of bodyweight
        avg_protein_g=60.0,  # 0.75 g/kg
        avg_calories_in=1300.0,  # 46% deficit
        workout_rows=[{"activity_type": "running"}] * 6,
    )
    assert result.verdict == "high_lean_risk"
    assert "muscle" in result.headline.lower()
    statuses = {s.key: s.status for s in result.signals}
    assert statuses == {"rate": "risk", "protein": "risk", "training": "risk", "deficit": "risk"}
    # protein outranks the rest because it is the biggest lever
    assert "protein" in result.focus.lower()


def test_cardio_only_does_not_count_as_resistance_training():
    """Crediting a run as strength work would hide the exact gap this reveals."""
    result = bc.assess(
        **BASE,
        weekly_change_kg=-0.5,
        avg_protein_g=140.0,
        avg_calories_in=1950.0,
        workout_rows=[{"activity_type": "running"}] * 10 + [{"activity_type": "yoga"}] * 4,
    )
    training = next(s for s in result.signals if s.key == "training")
    assert training.status == "risk"
    assert training.value == 0.0
    assert "resistance" in result.focus.lower() or "strength" in result.focus.lower()


def test_thin_history_refuses_to_guess():
    result = bc.assess(
        weight_kg=80.0,
        weekly_change_kg=-2.0,
        span_days=4,
        logged_days=2,
        avg_protein_g=50.0,
        avg_calories_in=1200.0,
        maintenance_calories=2400.0,
        workout_rows=[],
    )
    assert result.verdict == "insufficient_data"
    assert result.lean_risk_score == 0
    assert "two weeks" in result.focus
    assert "muscle loss" in result.headline


def test_gaining_and_maintaining_are_not_reported_as_fat_loss():
    gaining = bc.assess(
        **BASE, weekly_change_kg=0.4, avg_protein_g=140.0,
        avg_calories_in=2800.0, workout_rows=strength(8),
    )
    assert gaining.verdict == "gaining"

    steady = bc.assess(
        **BASE, weekly_change_kg=0.0, avg_protein_g=140.0,
        avg_calories_in=2400.0, workout_rows=strength(8),
    )
    assert steady.verdict == "maintaining"


def test_never_claims_to_have_measured_body_composition():
    result = bc.assess(
        **BASE, weekly_change_kg=-0.6, avg_protein_g=130.0,
        avg_calories_in=1900.0, workout_rows=strength(6),
    )
    caveat = result.caveat.lower()
    assert "not a body-composition measurement" in caveat
    assert "dexa" in caveat
    assert "water" in caveat and "glycogen" in caveat, "early drops must be explained"

    # no signal may pretend to a precision the data cannot support
    for signal in result.signals:
        assert "body fat" not in signal.detail.lower()
        assert "%" not in signal.detail or signal.key in {"rate", "deficit"}


def test_missing_inputs_degrade_to_unknown_rather_than_zero():
    result = bc.assess(
        weight_kg=80.0, weekly_change_kg=None, span_days=30, logged_days=20,
        avg_protein_g=None, avg_calories_in=None, maintenance_calories=2400.0,
        workout_rows=strength(4),
    )
    by_key = {s.key: s for s in result.signals}
    assert by_key["rate"].status == "unknown"
    assert by_key["protein"].status == "unknown"
    assert by_key["deficit"].status == "unknown"
    assert by_key["rate"].value is None, "absent data must not read as 0"


def test_serialises_for_the_api():
    payload = bc.assess(
        **BASE, weekly_change_kg=-0.5, avg_protein_g=140.0,
        avg_calories_in=1950.0, workout_rows=strength(8),
    ).to_dict()
    assert set(payload) == {
        "verdict", "headline", "focus", "caveat", "signals", "lean_risk_score",
        "zone_note", "in_fat_loss_zone",
    }
    assert isinstance(payload["signals"], list)
    assert set(payload["signals"][0]) == {"key", "label", "status", "value", "detail"}
