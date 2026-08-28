"""Weight forecasting from net calorie balance.

Deliberately classical statistics: a rolling mean of daily energy balance
converted at 7700 kcal/kg, plus an ordinary least-squares fit over the weight
log for the *observed* trend. No ML — with 5-10 users and a few hundred rows
there is nothing to learn that the arithmetic does not already say.

Two numbers are produced and they answer different questions:

* ``projected_weekly_change_kg`` — what the logged calories imply *should*
  happen. Reacts immediately to behaviour change.
* ``observed_weekly_change_kg`` — what the scale actually did. Ground truth,
  but lags and is noisy over short windows.

Days with no food logged are excluded from the average. Including them would
read a forgotten day as a 2000 kcal deficit and wreck the projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .energy import KCAL_PER_KG
from .trend import WeightPoint

__all__ = ["DayEnergy", "Forecast", "WeightPoint", "forecast", "observed_weekly_change"]

# A window needs this fraction of its days logged before we call it trustworthy.
CONFIDENCE_THRESHOLDS = ((0.8, "high"), (0.5, "medium"))
MIN_DAYS_FOR_REGRESSION = 3
MIN_SPAN_DAYS_FOR_REGRESSION = 5
MIN_SPAN_DAYS_FOR_OBSERVED_ETA = 14


@dataclass
class DayEnergy:
    day: date
    calories_in: float = 0.0
    calories_out: float = 0.0  # deliberate exercise only, not maintenance
    food_entries: int = 0

    @property
    def logged(self) -> bool:
        return self.food_entries > 0

    def net_balance(self, maintenance_calories: float) -> float:
        """Positive = surplus (gaining), negative = deficit (losing)."""
        return self.calories_in - (maintenance_calories + self.calories_out)


@dataclass
class Forecast:
    window_days: int
    days_with_data: int
    avg_daily_intake: float
    avg_daily_exercise_burn: float
    avg_daily_net_kcal: float
    projected_weekly_change_kg: float
    projected_monthly_change_kg: float
    observed_weekly_change_kg: float | None
    effective_weekly_change_kg: float
    current_weight_kg: float | None
    projected_weight_7d_kg: float | None
    projected_weight_30d_kg: float | None
    goal_weight_kg: float | None
    days_to_goal: int | None
    goal_date: date | None
    #: Bounds on the goal date. A single date implies a precision this maths
    #: does not have: the calorie estimate and the scale rarely agree, and the
    #: gap between them is the honest width of the answer.
    goal_date_earliest: date | None
    goal_date_latest: date | None
    goal_eta_note: str
    confidence: str
    notes: list[str] = field(default_factory=list)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """Ordinary least-squares slope. Returns None when x has no variance."""
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = _mean(xs), _mean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    return numerator / denominator


def observed_weekly_change(points: list[WeightPoint]) -> tuple[float | None, int]:
    """Weekly kg change implied by the weight log, plus the span in days."""
    if len(points) < MIN_DAYS_FOR_REGRESSION:
        return None, 0

    ordered = sorted(points, key=lambda p: p.day)
    origin = ordered[0].day
    span_days = (ordered[-1].day - origin).days
    if span_days < MIN_SPAN_DAYS_FOR_REGRESSION:
        return None, span_days

    xs = [float((p.day - origin).days) for p in ordered]
    ys = [p.weight_kg for p in ordered]
    slope_per_day = linear_slope(xs, ys)
    if slope_per_day is None:
        return None, span_days
    return slope_per_day * 7.0, span_days


def _confidence(days_with_data: int, window_days: int) -> str:
    if window_days <= 0:
        return "low"
    ratio = days_with_data / window_days
    for threshold, label in CONFIDENCE_THRESHOLDS:
        if ratio >= threshold:
            return label
    return "low"


def _eta_bounds(
    *,
    remaining: float,
    rates: list[float | None],
    fallback_rate: float,
    confidence: str,
    today: date,
) -> tuple[date | None, date | None, str]:
    """Bracket the goal date using the disagreement between our two rates.

    The calorie arithmetic and the scale give different answers, and that gap is
    real information: it is roughly how wrong the estimate could be. Using it as
    the width of the range is more honest than a single date, and more honest
    than an arbitrary +/- 20%.

    When only one rate is available there is nothing to disagree with, so the
    width comes from how much of the window was actually logged instead. Note
    that MyFitnessPal declines to give a target date at all, on the grounds that
    a fixed date invites an unhealthy pace. A range keeps the usefulness while
    dropping the false precision.
    """
    usable = [r for r in rates if r not in (None, 0) and (remaining > 0) == (r > 0)]
    if not usable:
        usable = [fallback_rate] if fallback_rate else []
    if not usable:
        return None, None, ""

    if len(usable) >= 2:
        slowest, fastest = min(usable, key=abs), max(usable, key=abs)
        basis = "your logged calories and your measured weight trend disagree by"
    else:
        # One source: widen by the confidence in it. Thin logging, wide range.
        spread = {"high": 0.15, "medium": 0.3}.get(confidence, 0.5)
        only = usable[0]
        slowest, fastest = only * (1 - spread), only * (1 + spread)
        basis = f"logging is {confidence} confidence, so the range allows"

    def _days(rate: float) -> int | None:
        if not rate:
            return None
        span = int(round(remaining / rate * 7))
        return span if 0 < span <= 3650 else None

    slow_days, fast_days = _days(slowest), _days(fastest)
    if slow_days is None or fast_days is None:
        return None, None, ""

    earliest = today + timedelta(days=min(slow_days, fast_days))
    latest = today + timedelta(days=max(slow_days, fast_days))
    note = (
        f"Somewhere between {earliest:%-d %b} and {latest:%-d %b} — {basis} enough to move the "
        f"date by {abs(slow_days - fast_days)} days. Keep logging and the range narrows."
    )
    return earliest, latest, note


def forecast(
    *,
    days: list[DayEnergy],
    maintenance_calories: float,
    window_days: int = 7,
    weight_points: list[WeightPoint] | None = None,
    goal_weight_kg: float | None = None,
    today: date | None = None,
) -> Forecast:
    """Project weight change from the trailing ``window_days`` of logs."""
    today = today or date.today()
    window_start = today - timedelta(days=window_days - 1)

    in_window = [d for d in days if window_start <= d.day <= today]
    logged_days = [d for d in in_window if d.logged]

    avg_intake = _mean([d.calories_in for d in logged_days])
    avg_burn = _mean([d.calories_out for d in logged_days])
    avg_net = _mean([d.net_balance(maintenance_calories) for d in logged_days])

    projected_weekly = avg_net * 7.0 / KCAL_PER_KG
    projected_monthly = avg_net * 30.0 / KCAL_PER_KG

    points = weight_points or []
    windowed_points = [p for p in points if p.day >= today - timedelta(days=max(window_days, 14))]
    observed_weekly, span_days = observed_weekly_change(windowed_points or points)

    notes: list[str] = []
    if not logged_days:
        notes.append("No food logged in this window yet — log a day to start the forecast.")
    elif len(logged_days) < window_days:
        notes.append(
            f"Based on {len(logged_days)} of {window_days} days with food logged; "
            "empty days are ignored rather than counted as fasting."
        )

    # Prefer the scale once it has a meaningful span; it captures water weight,
    # under-reporting and metabolic adaptation that the arithmetic cannot.
    effective_weekly = projected_weekly
    if observed_weekly is not None and span_days >= MIN_SPAN_DAYS_FOR_OBSERVED_ETA:
        effective_weekly = observed_weekly
        notes.append(
            f"Time-to-goal uses your measured trend ({observed_weekly:+.2f} kg/week over "
            f"{span_days} days) rather than the calorie estimate."
        )

    current_weight = sorted(points, key=lambda p: p.day)[-1].weight_kg if points else None

    projected_7d = projected_30d = None
    if current_weight is not None:
        projected_7d = round(current_weight + projected_weekly, 2)
        projected_30d = round(current_weight + projected_monthly, 2)

    days_to_goal: int | None = None
    goal_date: date | None = None
    earliest: date | None = None
    latest: date | None = None
    eta_note = ""
    if current_weight is not None and goal_weight_kg:
        remaining = goal_weight_kg - current_weight
        # Only meaningful when the trend actually points at the goal.
        if abs(remaining) < 0.1:
            days_to_goal, goal_date = 0, today
            eta_note = "You are at your goal weight."
        elif effective_weekly != 0 and (remaining > 0) == (effective_weekly > 0):
            weeks = remaining / effective_weekly
            days_to_goal = int(round(weeks * 7))
            if 0 < days_to_goal <= 3650:
                goal_date = today + timedelta(days=days_to_goal)
                earliest, latest, eta_note = _eta_bounds(
                    remaining=remaining,
                    rates=[projected_weekly, observed_weekly],
                    fallback_rate=effective_weekly,
                    confidence=_confidence(len(logged_days), window_days),
                    today=today,
                )
            else:
                days_to_goal = None
                eta_note = "At the current rate the goal is too far off to date usefully."
        else:
            eta_note = (
                "Your trend is not moving towards your goal at the moment, so there is no "
                "date to give yet."
            )

    return Forecast(
        window_days=window_days,
        days_with_data=len(logged_days),
        avg_daily_intake=round(avg_intake, 1),
        avg_daily_exercise_burn=round(avg_burn, 1),
        avg_daily_net_kcal=round(avg_net, 1),
        projected_weekly_change_kg=round(projected_weekly, 3),
        projected_monthly_change_kg=round(projected_monthly, 3),
        observed_weekly_change_kg=round(observed_weekly, 3) if observed_weekly is not None else None,
        effective_weekly_change_kg=round(effective_weekly, 3),
        current_weight_kg=current_weight,
        projected_weight_7d_kg=projected_7d,
        projected_weight_30d_kg=projected_30d,
        goal_weight_kg=goal_weight_kg,
        days_to_goal=days_to_goal,
        goal_date=goal_date,
        goal_date_earliest=earliest,
        goal_date_latest=latest,
        goal_eta_note=eta_note,
        confidence=_confidence(len(logged_days), window_days),
        notes=notes,
    )


def project_weight_series(
    *,
    start_weight_kg: float,
    weekly_change_kg: float,
    start_day: date,
    days: int = 30,
    step_days: int = 1,
) -> list[dict[str, object]]:
    """Points for the dashed trend line extending past the last weigh-in."""
    daily = weekly_change_kg / 7.0
    series: list[dict[str, object]] = []
    for offset in range(0, days + 1, step_days):
        series.append(
            {
                "date": (start_day + timedelta(days=offset)).isoformat(),
                "projected_kg": round(start_weight_kg + daily * offset, 2),
            }
        )
    return series
