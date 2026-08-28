"""Maintenance calories measured from the user's own data, not a formula.

Mifflin-St Jeor gives a starting guess for resting metabolism, which is then
multiplied by an activity factor chosen from a four-item dropdown. Both steps
carry error: the equation is a population fit, and "moderately active" means
whatever the user thought it meant. The result is routinely out by a couple of
hundred calories, which is the whole of a modest deficit.

The user's own logs contain a better answer. Body mass change is stored energy
change, so if the trend says they gained 200 kcal/day worth of tissue while
logging 3000 kcal/day, they expended about 2800. That inversion is the core of
MacroFactor's expenditure figure, and it needs no new data — this app already
stores everything it requires.

Two things make it correct rather than merely plausible here:

* **Exercise is subtracted.** Everywhere else in this codebase ``maintenance``
  means expenditure *excluding* deliberate exercise, because logged workout burn
  is added on top of it (see ``DayEnergy.net_balance``). Total expenditure
  derived from energy balance includes exercise, so handing it straight to the
  gauge would count every workout twice.
* **It is blended in, not switched on.** With four days of data the estimate is
  mostly noise, so it is weighted against the formula by how much history
  actually exists and how completely the days were logged, and clamped to a
  sane distance from the formula. A single mis-logged week cannot move someone's
  target by a thousand calories.

The estimate is only as honest as the food log. Under-reporting shows up as a
lower expenditure, which self-corrects for target setting — the target drops
until the weight moves — but it does mean the number should be presented as
"measured from your logs", never as metabolic truth. Hence ``how_calculated``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .energy import KCAL_PER_KG
from .trend import TrendDay

# Below this there is not enough signal to prefer data over the formula.
MIN_DAYS_FOR_ANY_WEIGHT = 10
# At and above this the estimate stands on its own.
FULL_TRUST_DAYS = 28
# Days where nothing was eaten according to the log are days the log is wrong.
MIN_LOGGED_FRACTION = 0.5
# The formula is a weak prior, not a straitjacket, but a 40% disagreement means
# something is broken (a mis-typed weight, a week of untracked holiday eating)
# and clamping beats handing the user a 900 kcal target.
MAX_DIVERGENCE_FRACTION = 0.4

Source = Literal["formula", "blended", "measured"]
Confidence = Literal["low", "medium", "high"]


@dataclass
class ExpenditureEstimate:
    #: The number the rest of the app should use.
    maintenance_kcal: float
    #: What Mifflin-St Jeor and the activity multiplier said.
    formula_kcal: float
    #: What the logs imply, before blending and clamping. None when unavailable.
    measured_kcal: float | None
    source: Source
    confidence: Confidence
    #: measured − formula, so the UI can say "260 kcal higher than the estimate".
    divergence_kcal: float | None
    days_used: int
    days_logged: int
    logged_fraction: float
    #: 0-1 weight given to the measured figure in the blend.
    trust: float
    how_calculated: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "maintenance_kcal": round(self.maintenance_kcal, 1),
            "formula_kcal": round(self.formula_kcal, 1),
            "measured_kcal": round(self.measured_kcal, 1) if self.measured_kcal else None,
            "source": self.source,
            "confidence": self.confidence,
            "divergence_kcal": round(self.divergence_kcal, 1)
            if self.divergence_kcal is not None
            else None,
            "days_used": self.days_used,
            "days_logged": self.days_logged,
            "logged_fraction": round(self.logged_fraction, 3),
            "trust": round(self.trust, 3),
            "how_calculated": self.how_calculated,
            "notes": self.notes,
        }


def _confidence(trust: float) -> Confidence:
    if trust >= 0.75:
        return "high"
    if trust >= 0.35:
        return "medium"
    return "low"


def estimate(
    *,
    formula_maintenance: float,
    trend_series: list[TrendDay],
    intake_by_day: dict[object, float],
    exercise_by_day: dict[object, float] | None = None,
    logged_days: set[object] | None = None,
    window_days: int = 28,
) -> ExpenditureEstimate:
    """Back out maintenance from intake and the trend weight.

    ``intake_by_day`` / ``exercise_by_day`` are keyed by date; ``logged_days``
    says which days actually had food recorded, since an unlogged day is a hole
    in the evidence rather than a fast.
    """
    exercise_by_day = exercise_by_day or {}
    notes: list[str] = []

    # Confine everything to the trailing window, and to days the trend covers.
    series = trend_series[-window_days:] if trend_series else []
    span_days = len(series) - 1

    if span_days < 1:
        return ExpenditureEstimate(
            maintenance_kcal=formula_maintenance,
            formula_kcal=formula_maintenance,
            measured_kcal=None,
            source="formula",
            confidence="low",
            divergence_kcal=None,
            days_used=0,
            days_logged=0,
            logged_fraction=0.0,
            trust=0.0,
            how_calculated=(
                "Estimated from your height, weight, age and activity level, because there are "
                "not yet enough weigh-ins to measure it from your own data."
            ),
            notes=["Weigh in regularly and this becomes a measured number instead of an estimate."],
        )

    covered = [d.day for d in series]
    logged = logged_days if logged_days is not None else set(intake_by_day)
    days_logged = sum(1 for day in covered if day in logged)
    logged_fraction = days_logged / len(covered)

    # Energy balance over the window, using the trend endpoints rather than raw
    # readings so a heavy first morning does not masquerade as a kilogram.
    stored_kcal = (series[-1].trend_kg - series[0].trend_kg) * KCAL_PER_KG
    intake_total = sum(intake_by_day.get(day, 0.0) for day in covered if day in logged)
    exercise_total = sum(exercise_by_day.get(day, 0.0) for day in covered if day in logged)

    measured: float | None = None
    if days_logged >= MIN_DAYS_FOR_ANY_WEIGHT and logged_fraction >= MIN_LOGGED_FRACTION:
        # Scale intake up to the whole window: the weight change covers every
        # day, so comparing it against only the logged days' intake would read
        # the gaps as zero-calorie days.
        daily_intake = intake_total / days_logged
        daily_exercise = exercise_total / days_logged
        daily_stored = stored_kcal / span_days
        # total expenditure = intake − stored; maintenance excludes exercise.
        measured = daily_intake - daily_stored - daily_exercise

    if measured is None:
        shortfall = max(0, MIN_DAYS_FOR_ANY_WEIGHT - days_logged)
        if shortfall:
            notes.append(
                f"{shortfall} more logged day{'s' if shortfall != 1 else ''} and this becomes "
                "a measured number rather than an estimate."
            )
        elif logged_fraction < MIN_LOGGED_FRACTION:
            notes.append(
                f"Only {int(logged_fraction * 100)}% of the last {len(covered)} days have food "
                "logged, which is too patchy to measure your expenditure from."
            )
        return ExpenditureEstimate(
            maintenance_kcal=formula_maintenance,
            formula_kcal=formula_maintenance,
            measured_kcal=None,
            source="formula",
            confidence="low",
            divergence_kcal=None,
            days_used=len(covered),
            days_logged=days_logged,
            logged_fraction=logged_fraction,
            trust=0.0,
            how_calculated=(
                "Estimated from your height, weight, age and activity level. Once you have "
                f"{MIN_DAYS_FOR_ANY_WEIGHT} logged days alongside your weigh-ins, this switches "
                "to a figure measured from your own intake and weight trend."
            ),
            notes=notes,
        )

    # Guard against a plainly broken estimate before it reaches anyone's target.
    floor = formula_maintenance * (1 - MAX_DIVERGENCE_FRACTION)
    ceiling = formula_maintenance * (1 + MAX_DIVERGENCE_FRACTION)
    clamped = min(max(measured, floor), ceiling)
    if clamped != measured:
        notes.append(
            "Your logs imply an expenditure far from what your stats predict, so it has been "
            "capped. That usually means some days went unlogged, or a weigh-in was mistyped."
        )

    # Trust grows with history and with how completely it was logged.
    trust = min(1.0, span_days / FULL_TRUST_DAYS) * min(1.0, logged_fraction / 0.8)
    blended = trust * clamped + (1 - trust) * formula_maintenance
    source: Source = "measured" if trust >= 0.75 else "blended"

    divergence = clamped - formula_maintenance
    direction = "higher" if divergence > 0 else "lower"
    how = (
        f"Measured from your data: over {span_days} days your trend weight moved "
        f"{series[-1].trend_kg - series[0].trend_kg:+.2f} kg while you logged "
        f"{intake_total / days_logged:.0f} kcal a day. Working backwards from that, and taking "
        f"logged workouts off separately, your body uses about {clamped:.0f} kcal a day at rest "
        f"and in daily life — {abs(divergence):.0f} kcal {direction} than your stats predict."
    )
    if source == "blended":
        how += (
            f" With {span_days} days of history this is still averaged with the formula "
            f"estimate, weighted {int(trust * 100)}% towards your measured figure."
        )

    return ExpenditureEstimate(
        maintenance_kcal=blended,
        formula_kcal=formula_maintenance,
        measured_kcal=clamped,
        source=source,
        confidence=_confidence(trust),
        divergence_kcal=divergence,
        days_used=len(covered),
        days_logged=days_logged,
        logged_fraction=logged_fraction,
        trust=trust,
        how_calculated=how,
        notes=notes,
    )
