"""Fasting stages, timed against the user's own metabolism rather than a chart.

Every fasting app shows the same fixed timeline: fat burning at 12 hours,
ketosis at 16, autophagy at 24. Those numbers are population midpoints, and the
spread around them is enormous — the literature puts liver glycogen depletion
anywhere in 18-24 hours and measurable ketosis anywhere in 12-48, explicitly
depending on carbohydrate intake beforehand, activity, and metabolic history. A
fixed clock tells someone who ate a plate of rice at midnight the same thing it
tells someone who trained hard on a low-carb day, when in reality they will be
hours apart.

This app already stores what the difference depends on, so the boundaries are
shifted rather than fixed. The reasoning, in one line: ketosis waits for liver
glycogen, so estimate how long that will last.

    stored     = liver capacity (scales with bodyweight)
                 x how full it is (recent carbohydrate intake)
                 - what training has already taken out
    drain      = hepatic glucose output (scales with total energy needs)
    depletion  = stored / drain

The difference between that estimate and the ~18 hours the textbook timeline
assumes becomes a shift, applied to the glycogen-driven stages and clamped hard
so a sparse log can never produce a nonsense timeline. The later stages are
driven by elapsed time rather than fuel, so they are not shifted.

None of this is a measurement. It is a better-informed estimate than a fixed
number, and it is presented that way: every stage carries its own explanation,
and the personalisation reports the inputs it used so the user can see why their
timeline differs from the one their friend's app shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

# --- glycogen model ---------------------------------------------------------

#: Liver glycogen capacity per kg of bodyweight. The commonly cited store is
#: 80-120 g, which lands on roughly this figure across normal adult weights.
LIVER_GLYCOGEN_G_PER_KG = 1.1

#: Dietary carbohydrate is shared between liver and muscle, so filling the liver
#: takes appreciably more carbohydrate than the liver itself holds. Used only to
#: turn "how much did you eat" into "how full is the tank".
CARBS_TO_FILL_MULTIPLE = 2.0

#: Never assume a completely empty tank: gluconeogenesis keeps some glycogen
#: turning over even on no carbohydrate at all.
MIN_FILL_FRACTION = 0.25

#: Hepatic glucose output early in a fast, for a reference adult. The liver
#: releases glucose continuously to hold blood sugar up; this is the share of
#: that coming from stored glycogen.
REFERENCE_DRAIN_G_PER_H = 4.5
REFERENCE_MAINTENANCE_KCAL = 2200.0

#: Share of exercise energy coming from carbohydrate at moderate intensity, and
#: the share of that taken from *liver* rather than muscle glycogen. Muscle
#: glycogen cannot refill the bloodstream, so only the liver's share matters for
#: when ketosis starts.
EXERCISE_CARB_FRACTION = 0.5
LIVER_SHARE_OF_EXERCISE_CARBS = 0.25
KCAL_PER_G_CARB = 4.0

#: What the textbook boundaries below implicitly assume.
BASELINE_DEPLETION_HOURS = 18.0

#: The estimate is an estimate. Past this the timeline stops being credible, and
#: a wrong timeline is worse than a generic one.
MAX_SHIFT_HOURS = 6.0

#: Fasts longer than this get a safety note rather than encouragement.
EXTENDED_FAST_CAUTION_HOURS = 24.0

StageStatus = Literal["done", "active", "upcoming"]


@dataclass(frozen=True)
class StageSpec:
    key: str
    label: str
    summary: str
    detail: str
    start_hours: float
    #: How much of the personalisation shift this boundary takes. Fuel-driven
    #: stages move with the glycogen estimate; time-driven ones do not.
    shift_weight: float = 0.0


# Baseline timeline. Sources broadly agree on this shape: a fed window of about
# four hours, a long stretch running on liver glycogen, fat oxidation rising as
# that runs down, ketones becoming a meaningful fuel around the point the liver
# empties, and autophagy and growth-hormone effects accumulating well beyond a
# day.
STAGE_SPECS: tuple[StageSpec, ...] = (
    StageSpec(
        key="fed",
        label="Fed",
        summary="Still digesting",
        detail=(
            "Insulin is up and your body is storing what you last ate rather than "
            "spending it. Nothing to do here but wait it out."
        ),
        start_hours=0.0,
    ),
    StageSpec(
        key="glycogen",
        label="Running on stored carbs",
        summary="Blood sugar settling",
        detail=(
            "Insulin has come down and your liver is releasing stored carbohydrate to "
            "hold your blood sugar steady. Fat burning has started but is not yet the "
            "main event."
        ),
        start_hours=4.0,
        shift_weight=0.6,
    ),
    StageSpec(
        key="fat_burning",
        label="Fat burning",
        summary="Switching fuel",
        detail=(
            "Your glycogen is running low, so fat is becoming the fuel of choice. This "
            "is the point most of the benefit people fast for begins."
        ),
        start_hours=12.0,
        shift_weight=1.0,
    ),
    StageSpec(
        key="ketosis",
        label="Ketosis",
        summary="Making ketones",
        detail=(
            "With the liver's carbohydrate gone, it converts fat into ketones, which "
            "your brain can use directly. Appetite usually settles here and many "
            "people report their head clearing."
        ),
        start_hours=16.0,
        shift_weight=1.0,
    ),
    StageSpec(
        key="deep_ketosis",
        label="Deep ketosis and cellular cleanup",
        summary="Autophagy ramping",
        detail=(
            "Ketones are now a major fuel and autophagy — cells recycling their own "
            "worn-out parts — is stepping up. Growth hormone is rising, which is part "
            "of how muscle is spared."
        ),
        start_hours=24.0,
        shift_weight=0.5,
    ),
    StageSpec(
        key="deep_repair",
        label="Growth hormone and immune reset",
        summary="Beyond a day",
        detail=(
            "Growth hormone is well up and the immune system starts clearing out old "
            "cells. Worth doing only deliberately, with electrolytes, and not while "
            "training hard."
        ),
        start_hours=48.0,
    ),
    StageSpec(
        key="extended",
        label="Extended fast",
        summary="Three days and beyond",
        detail=(
            "Stem cell and immune regeneration effects are reported in this range. "
            "This is medically supervised territory — not something to reach by "
            "accident."
        ),
        start_hours=72.0,
    ),
)


@dataclass
class Personalisation:
    """Why this user's stage boundaries sit where they do."""

    shift_hours: float
    estimated_depletion_hours: float
    liver_glycogen_g: float
    fill_fraction: float
    drain_g_per_hour: float
    recent_carbs_g: float | None
    exercise_kcal: float
    exercise_glycogen_g: float
    weight_kg: float | None
    maintenance_kcal: float
    how_calculated: str
    inputs_used: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shift_hours": round(self.shift_hours, 2),
            "estimated_depletion_hours": round(self.estimated_depletion_hours, 1),
            "liver_glycogen_g": round(self.liver_glycogen_g, 1),
            "fill_fraction": round(self.fill_fraction, 3),
            "drain_g_per_hour": round(self.drain_g_per_hour, 2),
            "recent_carbs_g": round(self.recent_carbs_g, 1)
            if self.recent_carbs_g is not None
            else None,
            "exercise_kcal": round(self.exercise_kcal, 1),
            "exercise_glycogen_g": round(self.exercise_glycogen_g, 1),
            "weight_kg": self.weight_kg,
            "maintenance_kcal": round(self.maintenance_kcal, 1),
            "how_calculated": self.how_calculated,
            "inputs_used": self.inputs_used,
            "notes": self.notes,
        }


@dataclass
class Stage:
    spec: StageSpec
    start_hours: float
    end_hours: float | None
    status: StageStatus
    progress: float
    reached_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.spec.key,
            "label": self.spec.label,
            "summary": self.spec.summary,
            "detail": self.spec.detail,
            "start_hours": round(self.start_hours, 2),
            "end_hours": round(self.end_hours, 2) if self.end_hours is not None else None,
            "status": self.status,
            "progress": round(self.progress, 4),
            "reached_at": self.reached_at.isoformat() if self.reached_at else None,
        }


@dataclass
class FastingState:
    active: bool
    session_id: str | None
    started_at: datetime | None
    ended_at: datetime | None
    target_hours: float
    elapsed_hours: float
    remaining_hours: float
    progress: float
    target_reached: bool
    current_stage_key: str | None
    next_stage_key: str | None
    hours_to_next_stage: float | None
    stages: list[Stage]
    personalisation: Personalisation | None
    caution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "target_hours": round(self.target_hours, 2),
            "elapsed_hours": round(self.elapsed_hours, 4),
            "remaining_hours": round(self.remaining_hours, 4),
            "progress": round(self.progress, 4),
            "target_reached": self.target_reached,
            "current_stage_key": self.current_stage_key,
            "next_stage_key": self.next_stage_key,
            "hours_to_next_stage": round(self.hours_to_next_stage, 3)
            if self.hours_to_next_stage is not None
            else None,
            "stages": [s.to_dict() for s in self.stages],
            "personalisation": self.personalisation.to_dict() if self.personalisation else None,
            "caution": self.caution,
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def personalise(
    *,
    weight_kg: float | None,
    maintenance_kcal: float,
    recent_carbs_g: float | None,
    exercise_kcal: float = 0.0,
) -> Personalisation:
    """Estimate how long this user's liver glycogen will last, as an hours shift.

    Falls back to the textbook timeline (shift of zero) when there is no weight
    on file, since the capacity term is what makes the estimate personal at all.
    """
    notes: list[str] = []
    used: list[str] = []

    effective_weight = weight_kg or 75.0
    if weight_kg:
        used.append("your weight")
    else:
        notes.append(
            "No weigh-in on file, so this uses an average build. Log your weight for a "
            "timeline based on your own."
        )

    capacity_g = LIVER_GLYCOGEN_G_PER_KG * effective_weight

    if recent_carbs_g is None:
        # Nothing logged before the fast. Assuming an empty tank would promise
        # ketosis absurdly early, so assume a normal day and say so.
        fill = 1.0
        notes.append(
            "No food logged before this fast, so it assumes you ate normally. Logging "
            "your last meal sharpens these timings considerably."
        )
    else:
        fill = _clamp(
            recent_carbs_g / (capacity_g * CARBS_TO_FILL_MULTIPLE), MIN_FILL_FRACTION, 1.0
        )
        used.append("the carbs in your last meals")

    drain = REFERENCE_DRAIN_G_PER_H * (maintenance_kcal / REFERENCE_MAINTENANCE_KCAL)
    drain = max(1.5, drain)
    used.append("what you burn in a day")

    exercise_glycogen = (
        exercise_kcal * EXERCISE_CARB_FRACTION / KCAL_PER_G_CARB * LIVER_SHARE_OF_EXERCISE_CARBS
    )
    if exercise_kcal > 0:
        used.append("your recent training")

    available = max(0.0, capacity_g * fill - exercise_glycogen)
    depletion_hours = available / drain

    raw_shift = depletion_hours - BASELINE_DEPLETION_HOURS
    shift = _clamp(raw_shift, -MAX_SHIFT_HOURS, MAX_SHIFT_HOURS)
    if shift != raw_shift:
        notes.append(
            "Your inputs point even further from the standard timeline, but the shift is "
            "capped — past a few hours this estimate stops being trustworthy."
        )

    if not weight_kg:
        shift = 0.0

    direction = "earlier" if shift < 0 else "later"
    if abs(shift) < 0.25:
        how = (
            f"Your liver holds roughly {capacity_g:.0f} g of carbohydrate and you burn "
            f"through about {drain:.1f} g of it an hour, so it should last around "
            f"{depletion_hours:.0f} hours — close enough to the standard timeline that "
            "the stages below are unshifted."
        )
    else:
        how = (
            f"Your liver holds roughly {capacity_g:.0f} g of carbohydrate. "
            + (
                f"Your recent meals left it about {fill * 100:.0f}% full"
                if recent_carbs_g is not None
                else "Assuming it started full"
            )
            + (
                f", training has taken about {exercise_glycogen:.0f} g out, "
                if exercise_glycogen >= 1
                else ", "
            )
            + f"and you use about {drain:.1f} g an hour. That is roughly "
            f"{depletion_hours:.0f} hours of fuel against the {BASELINE_DEPLETION_HOURS:.0f} "
            f"a standard timeline assumes, so fat burning and ketosis are marked "
            f"{abs(shift):.1f} hours {direction} than a fixed chart would."
        )

    return Personalisation(
        shift_hours=shift,
        estimated_depletion_hours=depletion_hours,
        liver_glycogen_g=capacity_g,
        fill_fraction=fill,
        drain_g_per_hour=drain,
        recent_carbs_g=recent_carbs_g,
        exercise_kcal=exercise_kcal,
        exercise_glycogen_g=exercise_glycogen,
        weight_kg=weight_kg,
        maintenance_kcal=maintenance_kcal,
        how_calculated=how,
        inputs_used=used,
        notes=notes,
    )


def build_stages(
    *, elapsed_hours: float, shift_hours: float, started_at: datetime | None
) -> list[Stage]:
    """Place the stage boundaries and mark where the user currently sits."""
    # Apply the shift, then keep the sequence monotonic: a large negative shift
    # could otherwise push a later boundary below an earlier one and produce a
    # stage with negative width.
    boundaries: list[float] = []
    for spec in STAGE_SPECS:
        shifted = spec.start_hours + shift_hours * spec.shift_weight
        floor = 0.0 if not boundaries else boundaries[-1] + 0.5
        boundaries.append(max(floor, shifted))

    stages: list[Stage] = []
    for index, spec in enumerate(STAGE_SPECS):
        start = boundaries[index]
        end = boundaries[index + 1] if index + 1 < len(boundaries) else None

        if end is not None and elapsed_hours >= end:
            status: StageStatus = "done"
            progress = 1.0
        elif elapsed_hours >= start:
            status = "active"
            # The open-ended final stage has no meaningful fraction; report it as
            # begun rather than inventing a denominator.
            progress = 1.0 if end is None else _clamp((elapsed_hours - start) / (end - start), 0, 1)
        else:
            status = "upcoming"
            progress = 0.0

        stages.append(
            Stage(
                spec=spec,
                start_hours=start,
                end_hours=end,
                status=status,
                progress=progress,
                reached_at=(
                    started_at + timedelta(hours=start)
                    if started_at is not None and elapsed_hours >= start
                    else None
                ),
            )
        )
    return stages


def evaluate(
    *,
    session: dict[str, Any] | None,
    now: datetime,
    weight_kg: float | None,
    maintenance_kcal: float,
    recent_carbs_g: float | None,
    exercise_kcal: float = 0.0,
    default_target_hours: float = 16.0,
) -> FastingState:
    """Current fasting state, including where the user is in the timeline.

    With no open session this still returns the personalised timeline, so the
    page can show what *would* happen before anyone commits to it.
    """
    personal = personalise(
        weight_kg=weight_kg,
        maintenance_kcal=maintenance_kcal,
        recent_carbs_g=recent_carbs_g,
        exercise_kcal=exercise_kcal,
    )

    if not session or not session.get("started_at"):
        return FastingState(
            active=False,
            session_id=None,
            started_at=None,
            ended_at=None,
            target_hours=default_target_hours,
            elapsed_hours=0.0,
            remaining_hours=default_target_hours,
            progress=0.0,
            target_reached=False,
            current_stage_key=None,
            next_stage_key=STAGE_SPECS[0].key,
            hours_to_next_stage=None,
            stages=build_stages(elapsed_hours=-1.0, shift_hours=personal.shift_hours, started_at=None),
            personalisation=personal,
        )

    started_at = _parse(session["started_at"])
    ended_at = _parse(session.get("ended_at")) if session.get("ended_at") else None
    target = float(session.get("target_hours") or default_target_hours)

    end_point = ended_at or now
    elapsed = max(0.0, (end_point - started_at).total_seconds() / 3600.0)

    stages = build_stages(
        elapsed_hours=elapsed, shift_hours=personal.shift_hours, started_at=started_at
    )
    current = next((s for s in stages if s.status == "active"), None)
    upcoming = next((s for s in stages if s.status == "upcoming"), None)

    caution = None
    if elapsed >= EXTENDED_FAST_CAUTION_HOURS or target >= EXTENDED_FAST_CAUTION_HOURS:
        caution = (
            "Past a day, fasting needs water, salt and a reason. Stop if you feel "
            "faint, and talk to a doctor before making a habit of fasts this long — "
            "especially on any medication that affects blood sugar."
        )

    return FastingState(
        active=ended_at is None,
        session_id=session.get("id"),
        started_at=started_at,
        ended_at=ended_at,
        target_hours=target,
        elapsed_hours=elapsed,
        remaining_hours=max(0.0, target - elapsed),
        progress=_clamp(elapsed / target, 0.0, 1.0) if target > 0 else 0.0,
        target_reached=elapsed >= target,
        current_stage_key=current.spec.key if current else None,
        next_stage_key=upcoming.spec.key if upcoming else None,
        hours_to_next_stage=max(0.0, upcoming.start_hours - elapsed) if upcoming else None,
        stages=stages,
        personalisation=personal,
        caution=caution,
    )


def _parse(raw: Any) -> datetime:
    """PostgREST timestamps, normalised to aware UTC."""
    if isinstance(raw, datetime):
        return raw
    text = str(raw).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:

        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def summarise_history(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up completed fasts: count, streak of days, longest and average.

    Only closed sessions count. An open fast has no duration yet, and including
    it would make the average drift down every time the page refreshed.
    """
    closed = [s for s in sessions if s.get("ended_at") and s.get("started_at")]
    durations: list[float] = []
    for row in closed:
        hours = (_parse(row["ended_at"]) - _parse(row["started_at"])).total_seconds() / 3600.0
        if hours > 0:
            durations.append(hours)

    completed_target = sum(
        1
        for row, hours in zip(closed, durations, strict=False)
        if hours >= float(row.get("target_hours") or 0)
    )

    return {
        "sessions": len(closed),
        "completed_on_target": completed_target,
        "longest_hours": round(max(durations), 2) if durations else None,
        "average_hours": round(sum(durations) / len(durations), 2) if durations else None,
        "total_hours": round(sum(durations), 1) if durations else 0.0,
    }
