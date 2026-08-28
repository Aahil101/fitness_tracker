"""Is the weight coming off fat, or off muscle?

The scale cannot answer that on its own, and neither can this module: telling
fat from lean mass needs DEXA, calipers or bio-impedance. What the logs *can*
support is the set of conditions under which a deficit spares lean tissue, and
each of those conditions is measurable from data the app already holds:

* how fast weight is falling, relative to bodyweight
* protein intake per kilogram
* whether any resistance training is happening
* how deep the calorie deficit is

Those four are the levers the literature consistently identifies for retaining
lean mass while losing weight, so the output is framed as risk indicators with
a plain-language focus, never as a body-composition measurement. Overstating it
would be both wrong and unhelpful — a user who believes they are losing pure fat
has no reason to fix the protein intake that is costing them muscle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Resistance work is the single strongest protector of lean mass in a deficit.
# Sports and mind-body sessions are not counted: they are not progressive
# loading, and crediting them would hide the gap this signal exists to reveal.
STRENGTH_ACTIVITIES = frozenset(
    {"weights", "weights_heavy", "calisthenics", "hiit", "crossfit", "core"}
)

# Fraction of bodyweight per week. Beyond roughly 1%, the deficit outpaces what
# fat stores can supply and the shortfall is increasingly met from lean tissue.
RATE_GOOD = 0.0075
RATE_WATCH = 0.010

# g protein per kg bodyweight per day.
PROTEIN_GOOD = 1.6
PROTEIN_WATCH = 1.2

# Deficit as a fraction below maintenance.
DEFICIT_GOOD = 0.25
DEFICIT_WATCH = 0.35

# A weight trend needs enough span to mean anything; below this it is noise,
# water and glycogen rather than tissue.
MIN_SPAN_DAYS = 10
MIN_LOGGED_DAYS = 5

Status = Literal["good", "watch", "risk", "unknown"]
Verdict = Literal[
    "insufficient_data", "mostly_fat", "some_lean_risk", "high_lean_risk", "gaining", "maintaining"
]


@dataclass
class Signal:
    key: str
    label: str
    status: Status
    value: float | None
    detail: str


@dataclass
class BodyCompositionAssessment:
    verdict: Verdict
    headline: str
    focus: str
    caveat: str
    signals: list[Signal] = field(default_factory=list)
    lean_risk_score: int = 0
    #: Two or three lines naming what the daily numbers need to become for the
    #: loss to be mostly fat, with the actual figures rather than principles.
    zone_note: str = ""
    #: True when every signal is already where it needs to be.
    in_fat_loss_zone: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _zone_note(
    signals: list[Signal],
    *,
    weight_kg: float | None,
    avg_protein_g: float | None,
    avg_calories_in: float | None,
    maintenance_calories: float | None,
) -> tuple[str, bool]:
    """Say what the daily limit has to become to keep the loss mostly fat.

    Deliberately arithmetic rather than advice: "add 62 g of protein" is
    actionable in a way that "prioritise protein" is not.
    """
    by_key = {s.key: s for s in signals}
    lacking = [s for s in signals if s.status in ("risk", "watch")]

    if not lacking:
        return (
            "You are in the fat-loss zone: the pace, protein, training and deficit "
            "are all where they need to be. Hold these numbers and the weight coming "
            "off should be mostly fat.",
            True,
        )

    lines: list[str] = []

    protein = by_key.get("protein")
    if protein and protein.status in ("risk", "watch") and weight_kg:
        needed = PROTEIN_GOOD * weight_kg
        short_by = needed - (avg_protein_g or 0)
        lines.append(
            f"Protein needs to reach about {needed:.0f} g a day "
            f"({short_by:.0f} g more than your recent average)."
        )

    deficit_signal = by_key.get("deficit")
    if deficit_signal and deficit_signal.status in ("risk", "watch") and maintenance_calories:
        floor = maintenance_calories * (1 - DEFICIT_GOOD)
        lines.append(
            f"Keep intake above roughly {floor:.0f} kcal — a deeper cut than that "
            "starts taking muscle with the fat."
        )

    rate = by_key.get("rate")
    if rate and rate.status in ("risk", "watch") and weight_kg:
        lines.append(
            f"Aim to lose no more than about {RATE_GOOD * weight_kg:.2f} kg a week; "
            "faster than that outruns what fat can supply."
        )

    training = by_key.get("training")
    if training and training.status in ("risk", "watch"):
        lines.append("Two resistance sessions a week give your body a reason to keep muscle.")

    # Two or three lines, highest leverage first.
    return " ".join(lines[:3]), False


def _rate_signal(weekly_change_kg: float | None, weight_kg: float | None) -> Signal:
    if weekly_change_kg is None or not weight_kg:
        return Signal(
            "rate", "Rate of loss", "unknown", None,
            "Not enough weigh-ins yet to see a trend.",
        )

    # Only losing weight can cost lean mass through speed.
    if weekly_change_kg >= 0:
        return Signal(
            "rate", "Rate of loss", "good", round(weekly_change_kg, 2),
            "Weight is stable or rising, so speed is not stripping lean tissue.",
        )

    fraction = abs(weekly_change_kg) / weight_kg
    pct = fraction * 100
    if fraction <= RATE_GOOD:
        status: Status = "good"
        detail = f"{pct:.2f}% of bodyweight a week is in the range that favours fat loss."
    elif fraction <= RATE_WATCH:
        status = "watch"
        detail = f"{pct:.2f}% a week is brisk; at this pace some lean loss is likely."
    else:
        status = "risk"
        detail = (
            f"{pct:.2f}% a week is faster than fat stores can supply, "
            "so muscle is probably making up the difference."
        )
    return Signal("rate", "Rate of loss", status, round(pct, 2), detail)


def _protein_signal(avg_protein_g: float | None, weight_kg: float | None) -> Signal:
    if not avg_protein_g or not weight_kg:
        return Signal(
            "protein", "Protein intake", "unknown", None,
            "Log protein for a few days to judge this.",
        )
    per_kg = avg_protein_g / weight_kg
    if per_kg >= PROTEIN_GOOD:
        status: Status = "good"
        detail = f"{per_kg:.1f} g/kg is enough to defend muscle in a deficit."
    elif per_kg >= PROTEIN_WATCH:
        status = "watch"
        detail = f"{per_kg:.1f} g/kg is on the low side; {PROTEIN_GOOD:.1f} g/kg protects lean mass better."
    else:
        status = "risk"
        detail = f"{per_kg:.1f} g/kg is well under the {PROTEIN_GOOD:.1f} g/kg that spares muscle."
    return Signal("protein", "Protein intake", status, round(per_kg, 2), detail)


def _training_signal(strength_sessions: int, span_days: int) -> Signal:
    weeks = max(1.0, span_days / 7)
    per_week = strength_sessions / weeks
    if strength_sessions == 0:
        return Signal(
            "training", "Resistance training", "risk", 0.0,
            "No strength sessions logged. Without a reason to keep muscle, the body sheds it.",
        )
    if per_week >= 2:
        status: Status = "good"
        detail = f"{per_week:.1f} strength sessions a week gives muscle a reason to stay."
    else:
        status = "watch"
        detail = f"{per_week:.1f} strength sessions a week; two or more protects lean mass better."
    return Signal("training", "Resistance training", status, round(per_week, 1), detail)


def _deficit_signal(avg_calories_in: float | None, maintenance: float | None) -> Signal:
    if not avg_calories_in or not maintenance:
        return Signal(
            "deficit", "Deficit depth", "unknown", None,
            "Log meals for a few days to judge this.",
        )
    fraction = (maintenance - avg_calories_in) / maintenance
    pct = fraction * 100
    if fraction <= 0:
        return Signal(
            "deficit", "Deficit depth", "good", round(pct, 1),
            "Eating at or above maintenance, so there is no deficit to overshoot.",
        )
    if fraction <= DEFICIT_GOOD:
        status: Status = "good"
        detail = f"Eating {pct:.0f}% below maintenance is a sustainable gap."
    elif fraction <= DEFICIT_WATCH:
        status = "watch"
        detail = f"{pct:.0f}% below maintenance is aggressive; muscle starts paying part of the bill."
    else:
        status = "risk"
        detail = f"{pct:.0f}% below maintenance is severe and hard to do without losing muscle."
    return Signal("deficit", "Deficit depth", status, round(pct, 1), detail)


def assess(
    *,
    weight_kg: float | None,
    weekly_change_kg: float | None,
    span_days: int,
    avg_protein_g: float | None,
    avg_calories_in: float | None,
    maintenance_calories: float | None,
    workout_rows: list[dict[str, Any]] | None = None,
    logged_days: int = 0,
) -> BodyCompositionAssessment:
    """Judge whether the current trend is likely fat loss or lean loss."""
    rows = workout_rows or []
    strength_sessions = sum(
        1 for row in rows if str(row.get("activity_type") or "").lower() in STRENGTH_ACTIVITIES
    )

    signals = [
        _rate_signal(weekly_change_kg, weight_kg),
        _protein_signal(avg_protein_g, weight_kg),
        _training_signal(strength_sessions, span_days),
        _deficit_signal(avg_calories_in, maintenance_calories),
    ]

    caveat = (
        "Worked out from your logs, not a body-composition measurement — only a DEXA "
        "or similar scan can split fat from muscle. Early drops are largely water and "
        "glycogen too."
    )

    # Too little data is its own answer; inventing a verdict from two weigh-ins
    # would be the most misleading thing this could do.
    zone_note, in_zone = _zone_note(
        signals,
        weight_kg=weight_kg,
        avg_protein_g=avg_protein_g,
        avg_calories_in=avg_calories_in,
        maintenance_calories=maintenance_calories,
    )

    if span_days < MIN_SPAN_DAYS or logged_days < MIN_LOGGED_DAYS or not weight_kg:
        return BodyCompositionAssessment(
            verdict="insufficient_data",
            headline="Not enough history yet to tell fat loss from muscle loss.",
            focus=(
                "Keep logging meals and weighing in for about two weeks — the trend needs "
                "that long before it means anything."
            ),
            caveat=caveat,
            signals=signals,
            lean_risk_score=0,
            zone_note=zone_note,
            in_fat_loss_zone=False,
        )

    risk = sum(1 for s in signals if s.status == "risk")
    watch = sum(1 for s in signals if s.status == "watch")
    score = risk * 2 + watch

    if weekly_change_kg is not None and weekly_change_kg > 0.1:
        verdict: Verdict = "gaining"
        headline = "You are gaining weight, not losing it."
    elif weekly_change_kg is not None and abs(weekly_change_kg) <= 0.1:
        verdict = "maintaining"
        headline = "Weight is holding steady."
    elif risk >= 2 or score >= 4:
        verdict = "high_lean_risk"
        headline = "This pattern is likely costing you muscle as well as fat."
    elif score >= 1:
        verdict = "some_lean_risk"
        headline = "Mostly fat loss, but some muscle is probably going with it."
    else:
        verdict = "mostly_fat"
        headline = "The loss looks like mostly fat."

    # Name the single highest-leverage fix rather than a list of everything.
    priority = ["protein", "training", "rate", "deficit"]
    ranked = sorted(
        signals,
        key=lambda s: (
            {"risk": 0, "watch": 1, "good": 2, "unknown": 3}[s.status],
            priority.index(s.key) if s.key in priority else 99,
        ),
    )
    worst = ranked[0]

    fixes = {
        "protein": "Push protein toward 1.6 g per kg of bodyweight — it is the biggest lever you have.",
        "training": "Add two resistance sessions a week; that is what tells your body to keep the muscle.",
        "rate": "Ease the pace to about 0.5-0.75% of bodyweight a week by eating a little more.",
        "deficit": "Shrink the deficit — a smaller gap held longer keeps more muscle than a crash.",
    }
    if worst.status in ("risk", "watch"):
        focus = fixes.get(worst.key, "Keep the current approach going.")
    elif verdict == "gaining":
        focus = "If losing is the aim, the deficit is not there yet — tighten intake first."
    else:
        focus = "Nothing to change: hold protein, training and pace where they are."

    return BodyCompositionAssessment(
        verdict=verdict,
        headline=headline,
        focus=focus,
        caveat=caveat,
        signals=signals,
        lean_risk_score=score,
        zone_note=zone_note,
        in_fat_loss_zone=in_zone,
    )
