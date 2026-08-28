"""Adherence: how often the plan was actually followed.

The app already knows how many days a user logged. That is a measure of typing,
not of eating — a day where 3400 kcal was carefully recorded counts the same as
a day on target. So when the weight does not move, nothing on screen can
distinguish "the plan is wrong" from "the plan was not followed", and the app
ends up adjusting targets to compensate for a problem the targets did not cause.

What is measured here follows the rule a coach would use, and the one Carbon
publishes: a day counts when **calories and protein** both land in range. The
carb-to-fat split is deliberately ignored. With calories and protein matched,
that ratio has little bearing on the outcome, and grading people on it produces
a score that fails for reasons that do not matter.

Calories are judged as a band rather than a ceiling. Coming in far under target
is not a better day than hitting it — on a deficit it is how people lose muscle
and stall their metabolism — so the band is two-sided. Protein is one-sided,
since more than target is not a problem worth flagging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

# Nobody hits a number exactly. The band is the looser of a percentage and an
# absolute figure so that it stays reasonable at 1400 kcal and at 3200.
CALORIE_TOLERANCE_FRACTION = 0.10
CALORIE_TOLERANCE_MIN_KCAL = 150.0

# Protein is a floor, not a target to hit precisely. Just short still counts:
# the point is whether intake was in the right neighbourhood.
PROTEIN_FLOOR_FRACTION = 0.9

GOOD_RATE = 0.8
WATCH_RATE = 0.5

Status = Literal["unknown", "good", "watch", "risk"]


@dataclass
class DayVerdict:
    day: date
    calories: float
    protein_g: float
    calories_ok: bool
    protein_ok: bool

    @property
    def compliant(self) -> bool:
        return self.calories_ok and self.protein_ok


@dataclass
class Adherence:
    days_in_window: int
    days_logged: int
    days_compliant: int
    #: Compliant days over *logged* days. Unlogged days say nothing about
    #: whether the plan was followed, so counting them as failures would punish
    #: someone for a holiday they never claimed to be tracking.
    compliance_rate: float | None
    calorie_days: int
    protein_days: int
    current_streak: int
    best_streak: int
    status: Status
    headline: str
    detail: str
    how_calculated: str
    #: The limiting factor, so the UI can name one thing to fix.
    weakest_link: Literal["calories", "protein", "logging", "none"] = "none"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days_in_window": self.days_in_window,
            "days_logged": self.days_logged,
            "days_compliant": self.days_compliant,
            "compliance_rate": round(self.compliance_rate, 3)
            if self.compliance_rate is not None
            else None,
            "calorie_days": self.calorie_days,
            "protein_days": self.protein_days,
            "current_streak": self.current_streak,
            "best_streak": self.best_streak,
            "status": self.status,
            "headline": self.headline,
            "detail": self.detail,
            "how_calculated": self.how_calculated,
            "weakest_link": self.weakest_link,
            "notes": self.notes,
        }


def _band(target: float) -> float:
    return max(CALORIE_TOLERANCE_MIN_KCAL, target * CALORIE_TOLERANCE_FRACTION)


def _streaks(verdicts: list[DayVerdict]) -> tuple[int, int]:
    """Current run of compliant days ending at the most recent, and the best run.

    Only logged days are passed in, so a gap in logging does not break a streak
    outright — it simply is not counted either way.
    """
    best = run = 0
    for verdict in verdicts:
        run = run + 1 if verdict.compliant else 0
        best = max(best, run)
    current = 0
    for verdict in reversed(verdicts):
        if not verdict.compliant:
            break
        current += 1
    return current, best


def assess(
    *,
    macro_days: list[dict[str, Any]],
    calorie_target: float,
    protein_target_g: float | None,
) -> Adherence:
    """Grade each logged day against the calorie band and the protein floor.

    ``macro_days`` is the zero-filled series from ``aggregate.macro_daily_series``:
    one dict per calendar day with ``date``, ``calories`` and ``protein_g``.
    """
    band = _band(calorie_target)
    protein_floor = (protein_target_g or 0.0) * PROTEIN_FLOOR_FRACTION

    verdicts: list[DayVerdict] = []
    for row in macro_days:
        calories = float(row.get("calories") or 0.0)
        if calories <= 0:
            continue  # nothing logged; not a failure, just not evidence
        raw_day = row.get("date")
        day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else raw_day
        protein = float(row.get("protein_g") or 0.0)
        verdicts.append(
            DayVerdict(
                day=day,
                calories=calories,
                protein_g=protein,
                calories_ok=abs(calories - calorie_target) <= band,
                # With no protein target set there is nothing to fail against,
                # so protein cannot be the thing that sinks a day.
                protein_ok=protein >= protein_floor if protein_floor > 0 else True,
            )
        )

    days_in_window = len(macro_days)
    days_logged = len(verdicts)

    if not days_logged:
        return Adherence(
            days_in_window=days_in_window,
            days_logged=0,
            days_compliant=0,
            compliance_rate=None,
            calorie_days=0,
            protein_days=0,
            current_streak=0,
            best_streak=0,
            status="unknown",
            headline="No days logged yet",
            detail="Log a few days of food and this will show how closely you are following the plan.",
            how_calculated=(
                "A day counts when your calories land within "
                f"{int(CALORIE_TOLERANCE_FRACTION * 100)}% of target and your protein reaches "
                f"{int(PROTEIN_FLOOR_FRACTION * 100)}% of target."
            ),
            weakest_link="logging",
            notes=[],
        )

    verdicts.sort(key=lambda v: v.day)
    compliant = sum(1 for v in verdicts if v.compliant)
    calorie_days = sum(1 for v in verdicts if v.calories_ok)
    protein_days = sum(1 for v in verdicts if v.protein_ok)
    rate = compliant / days_logged
    current_streak, best_streak = _streaks(verdicts)

    status: Status = "good" if rate >= GOOD_RATE else "watch" if rate >= WATCH_RATE else "risk"

    # Name the single biggest drag, so the advice is actionable rather than a score.
    logging_gap = days_in_window - days_logged
    weakest: Literal["calories", "protein", "logging", "none"] = "none"
    if rate < GOOD_RATE:
        misses = {
            "calories": days_logged - calorie_days,
            "protein": days_logged - protein_days,
        }
        weakest = max(misses, key=lambda k: misses[k]) if any(misses.values()) else "none"
    elif logging_gap > days_in_window * 0.3:
        weakest = "logging"

    over = sum(1 for v in verdicts if not v.calories_ok and v.calories > calorie_target)
    under = (days_logged - calorie_days) - over

    if weakest == "logging":
        # Checked before the "good" branch on purpose: five perfect days out of
        # fourteen is not a good fortnight, and saying so is the honest reading.
        # It is also the only branch that explains why the forecast is vague.
        headline = f"On plan when logged, but {logging_gap} days are missing"
        detail = (
            f"The {days_logged} days you did log look good. The gaps are what make the "
            "projections uncertain, because an unlogged day could have been anything."
        )
    elif status == "good":
        headline = f"On plan {compliant} of {days_logged} logged days"
        detail = (
            "Calories and protein both landed in range on most days, so the plan is being "
            "followed and any change in weight reflects the plan rather than the gaps in it."
        )
    elif weakest == "protein":
        headline = f"Protein short on {days_logged - protein_days} of {days_logged} days"
        detail = (
            f"Calories were fine on {calorie_days} days, but protein reached its floor on only "
            f"{protein_days}. In a deficit that is the difference between losing fat and losing "
            "muscle — protein is the macro to fix first."
        )
    elif weakest == "calories":
        if over >= under:
            headline = f"Over target on {over} of {days_logged} days"
            detail = (
                f"Protein held up on {protein_days} days, but calories ran over on {over}. "
                "The deficit is the thing that drives weight change, so this is where the "
                "stall is coming from."
            )
        else:
            headline = f"Under target on {under} of {days_logged} days"
            detail = (
                f"Calories came in well below target on {under} days. Eating under a deficit "
                "target is not a bonus — it costs muscle and makes the plan harder to keep to."
            )
    else:
        headline = f"On plan {compliant} of {days_logged} logged days"
        detail = "Calories and protein both in range on most days."

    how = (
        f"A day counts when calories land within {int(band)} kcal of your "
        f"{int(calorie_target)} kcal target and protein reaches "
        f"{int(protein_floor)} g. The carb and fat split is not graded: with calories and "
        "protein matched it has little bearing on the result."
    )

    notes: list[str] = []
    if logging_gap and weakest != "logging":
        notes.append(
            f"{logging_gap} of the last {days_in_window} days have no food logged and are not "
            "counted either way."
        )

    return Adherence(
        days_in_window=days_in_window,
        days_logged=days_logged,
        days_compliant=compliant,
        compliance_rate=rate,
        calorie_days=calorie_days,
        protein_days=protein_days,
        current_streak=current_streak,
        best_streak=best_streak,
        status=status,
        headline=headline,
        detail=detail,
        how_calculated=how,
        weakest_link=weakest,
        notes=notes,
    )
