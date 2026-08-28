"""Trend weight: separating a real change in body mass from daily noise.

A scale reading is the body plus whatever water, food and gut contents happen to
be in it. Day to day that noise is comfortably larger than the signal — a
kilogram of swing is ordinary, while a genuine week of fat loss is a few hundred
grams. Reporting the raw number therefore tells a user almost nothing about
their progress, and tells them something actively misleading whenever they had a
salty dinner the night before.

The fix is old and well established: smooth the readings with an exponentially
weighted moving average and treat *that* as the weight. This is the approach in
The Hacker's Diet, and the same idea underpins the trend figures in Happy Scale,
Libra and MacroFactor. We use alpha = 0.1, meaning each reading moves the trend
a tenth of the way towards itself, which gives a half-life of about a week: fast
enough to notice a real change within days, slow enough that one bad morning
cannot move it far.

Two details matter for correctness:

* **Gaps are interpolated before smoothing.** The EWMA is a per-step recurrence,
  so feeding it readings that are three days apart in one place and one day
  apart in another silently changes the smoothing constant. Filling the grid
  linearly first keeps a day worth one day, which is what MacroFactor does.
* **Rate of change is fitted to the trend, not the readings.** Regressing the
  raw scale over a fortnight inherits all the noise it was meant to remove.

The rate is also reported as a percentage of bodyweight, because that is the
form the safe-rate guidance takes: losing a kilogram a week is unremarkable at
110 kg and a lean-mass emergency at 55 kg. An absolute figure cannot express
that; a percentage can.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

# Each reading pulls the trend a tenth of the way towards itself. Half-life is
# ln(0.5)/ln(0.9), a touch under 7 days.
SMOOTHING_ALPHA = 0.1

# Seeding the recurrence with a single reading hands that reading full authority
# over the early trend. Fitting a short line through the opening readings and
# starting from that instead removes the start-up transient — see _seed.
SEED_WINDOW = 7
MIN_SEED_POINTS_FOR_SLOPE = 4
# A noisy opening week can fit an absurd slope; cap how far the correction may
# move the starting point.
MAX_SEED_CORRECTION_KG = 1.5

# Below this the EWMA has not converged and the rate fit has nothing to fit.
MIN_POINTS_FOR_TREND = 2
MIN_SPAN_DAYS_FOR_RATE = 7

# Fitting the rate over the recent past only: a 90-day regression would report
# an average that stopped being true a month ago.
RATE_WINDOW_DAYS = 14

# A gap longer than this is a break in the record, not a gap to bridge. Drawing
# a straight line across five weeks of silence invents data.
MAX_INTERPOLATION_GAP_DAYS = 21

# Weekly change as a percentage of bodyweight. The widely used guidance for fat
# loss is roughly 0.5-1%; Carbon's published band is exactly that. Above it,
# lean mass is increasingly what is being lost.
LOSS_BAND_MIN_PCT = 0.5
LOSS_BAND_MAX_PCT = 1.0
# Gaining is a slower business — past roughly 0.5%/week the surplus is
# outrunning what can be added as muscle.
GAIN_BAND_MIN_PCT = 0.125
GAIN_BAND_MAX_PCT = 0.5
# Inside this, the trend is flat and calling it either way is overreading.
HOLDING_PCT = 0.1

RateStatus = Literal[
    "unknown",  # not enough weigh-ins yet
    "holding",  # flat, within noise
    "gentle",  # moving the right way, slower than the guidance band
    "on_target",  # inside the guidance band
    "rapid",  # faster than the band — lean mass at risk
    "wrong_way",  # moving away from the goal
]

Direction = Literal["lose", "gain", "maintain"]


@dataclass
class TrendDay:
    """One day of the smoothed series, ready for charting."""

    day: date
    trend_kg: float
    scale_kg: float | None  # None on interpolated days — nothing was weighed


@dataclass
class WeightTrend:
    trend_kg: float | None
    scale_kg: float | None
    #: How far the latest reading sits from the trend. Shown to the user because
    #: it is the number that justifies ignoring the scale.
    deviation_kg: float | None
    #: Mean absolute distance between readings and the (de-lagged) trend — the
    #: user's personal noise level. "Your readings swing about 0.6 kg" is far
    #: more reassuring, and more actionable, than a generic warning not to trust
    #: the scale.
    noise_kg: float | None
    weekly_change_kg: float | None
    weekly_change_pct: float | None
    rate_status: RateStatus
    rate_label: str
    rate_detail: str
    days_of_data: int
    span_days: int
    interpolated_days: int
    how_calculated: str
    series: list[TrendDay] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "trend_kg": self.trend_kg,
            "scale_kg": self.scale_kg,
            "deviation_kg": self.deviation_kg,
            "noise_kg": self.noise_kg,
            "weekly_change_kg": self.weekly_change_kg,
            "weekly_change_pct": self.weekly_change_pct,
            "rate_status": self.rate_status,
            "rate_label": self.rate_label,
            "rate_detail": self.rate_detail,
            "days_of_data": self.days_of_data,
            "span_days": self.span_days,
            "interpolated_days": self.interpolated_days,
            "how_calculated": self.how_calculated,
            "series": [
                {"date": d.day.isoformat(), "trend_kg": d.trend_kg, "scale_kg": d.scale_kg}
                for d in self.series
            ],
        }


@dataclass
class WeightPoint:
    """A single weigh-in. Lives here because the trend owns weight history.

    Re-exported from ``forecast`` for the modules that already import it there.
    """

    day: date
    weight_kg: float


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _slope(xs: list[float], ys: list[float]) -> float | None:
    """Ordinary least-squares slope, or None when x has no spread."""
    if len(xs) < 2:
        return None
    mean_x, mean_y = _mean(xs), _mean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    return numerator / denominator


def _daily_grid(points: list[WeightPoint]) -> list[tuple[date, float, bool]]:
    """One entry per day from first to last weigh-in.

    Returns ``(day, weight, was_measured)``. Missing days are filled by linear
    interpolation between their neighbours so the EWMA advances one step per
    calendar day. Runs longer than ``MAX_INTERPOLATION_GAP_DAYS`` are left
    unbridged — the series restarts on the far side rather than inventing a
    month of readings.
    """
    if not points:
        return []

    by_day: dict[date, float] = {}
    for point in sorted(points, key=lambda p: p.day):
        by_day[point.day] = point.weight_kg  # a later row for a day wins
    measured = sorted(by_day.items())

    grid: list[tuple[date, float, bool]] = [(measured[0][0], measured[0][1], True)]
    for (prev_day, prev_kg), (next_day, next_kg) in zip(measured, measured[1:], strict=False):
        gap = (next_day - prev_day).days
        if gap > MAX_INTERPOLATION_GAP_DAYS:
            grid.append((next_day, next_kg, True))
            continue
        step = (next_kg - prev_kg) / gap if gap else 0.0
        for offset in range(1, gap):
            grid.append((prev_day + timedelta(days=offset), prev_kg + step * offset, False))
        grid.append((next_day, next_kg, True))
    return grid


#: An EWMA trails a moving series by ``(1 - alpha) / alpha`` steps. At alpha 0.1
#: that is nine days, which on a normal rate of loss puts the trend most of a
#: kilogram above what the user actually weighs. Correcting for it is what keeps
#: the trend figure recognisable next to the scale.
LAG_DAYS = (1 - SMOOTHING_ALPHA) / SMOOTHING_ALPHA
#: Window used to estimate the local slope when de-lagging.
LOCAL_SLOPE_DAYS = 7
#: A de-lag correction larger than this means the slope estimate is unreliable.
MAX_LAG_CORRECTION_KG = 2.0


def _delag(series: list[TrendDay]) -> list[TrendDay]:
    """Shift the smoothed series forward by the lag the smoother introduces.

    The EWMA is deliberately sluggish, which is what makes it robust, but it also
    means that while someone is losing weight the trend sits persistently above
    every reading they take. A user who weighs 82.4 and is shown a trend of 83.1
    concludes the app is broken, and they are not being unreasonable.

    Since the lag is a known function of alpha, it can be removed: estimate the
    local slope from the smoothed series and project forward along it by the lag.
    The result keeps the noise rejection of the EWMA while sitting where the
    readings actually are. It also makes the deviation figure mean what it says —
    measured against the uncorrected trend, "noise" would mostly be this lag.
    """
    if len(series) < 2:
        return series

    out: list[TrendDay] = []
    for index, day in enumerate(series):
        back = series[max(0, index - LOCAL_SLOPE_DAYS)]
        gap = (day.day - back.day).days
        slope = (day.trend_kg - back.trend_kg) / gap if gap else 0.0
        correction = slope * LAG_DAYS
        if abs(correction) > MAX_LAG_CORRECTION_KG:
            correction = MAX_LAG_CORRECTION_KG * (1 if correction > 0 else -1)
        out.append(
            TrendDay(
                day=day.day,
                trend_kg=round(day.trend_kg + correction, 3),
                scale_kg=day.scale_kg,
            )
        )
    return out


def _seed(grid: list[tuple[date, float, bool]]) -> float:
    """Starting value for the recurrence, chosen to avoid a start-up transient.

    An EWMA fed a steadily falling weight settles into a fixed lag behind it, of
    ``(1 - alpha) / alpha`` days — about nine here. That lag is harmless for the
    displayed figure and is why a trend weight is conservative by nature. What is
    *not* harmless is the journey into it: started level with the first reading,
    the trend spends its first fortnight falling more slowly than the user
    actually is, so a slope fitted over that stretch understates their progress.
    On real data this read 0.41 kg/week for someone losing 0.56.

    So instead of starting level with the data, start where a converged trend
    would already be: fit a line through the opening readings and step back along
    it by the known lag. The recurrence is then in its steady state from day one
    and the fitted rate is unbiased. Falls back to the plain mean when there are
    too few readings to fit anything, or when the fit wants to move the start
    implausibly far.
    """
    head = [(index, kg) for index, (_, kg, measured) in enumerate(grid[:SEED_WINDOW]) if measured]
    plain = _mean([kg for _, kg in head]) if head else grid[0][1]
    if len(head) < MIN_SEED_POINTS_FOR_SLOPE:
        return plain

    xs = [float(i) for i, _ in head]
    ys = [kg for _, kg in head]
    slope = _slope(xs, ys)
    if slope is None:
        return plain

    intercept = _mean(ys) - slope * _mean(xs)
    lag_days = (1 - SMOOTHING_ALPHA) / SMOOTHING_ALPHA
    correction = -slope * lag_days
    if abs(correction) > MAX_SEED_CORRECTION_KG:
        return plain
    return intercept + correction


def smooth(points: list[WeightPoint]) -> list[TrendDay]:
    """Exponentially weighted trend over a gap-filled daily grid."""
    grid = _daily_grid(points)
    if not grid:
        return []

    out: list[TrendDay] = []
    current = _seed(grid)
    for day, kg, was_measured in grid:
        current += SMOOTHING_ALPHA * (kg - current)
        out.append(
            TrendDay(
                day=day,
                trend_kg=round(current, 3),
                scale_kg=round(kg, 2) if was_measured else None,
            )
        )
    return _delag(out)


def _rate_from_trend(series: list[TrendDay], window_days: int) -> float | None:
    """Weekly kg change fitted to the trend over the trailing window."""
    if len(series) < MIN_POINTS_FOR_TREND:
        return None
    cutoff = series[-1].day - timedelta(days=window_days - 1)
    recent = [d for d in series if d.day >= cutoff]
    if len(recent) < MIN_POINTS_FOR_TREND:
        return None
    origin = recent[0].day
    xs = [float((d.day - origin).days) for d in recent]
    slope_per_day = _slope(xs, [d.trend_kg for d in recent])
    return None if slope_per_day is None else slope_per_day * 7.0


def _direction(current_kg: float | None, goal_kg: float | None) -> Direction:
    if current_kg is None or goal_kg is None:
        return "lose"  # the app's default posture
    if goal_kg < current_kg - 0.5:
        return "lose"
    if goal_kg > current_kg + 0.5:
        return "gain"
    return "maintain"


def classify_rate(pct_per_week: float | None, direction: Direction) -> tuple[RateStatus, str, str]:
    """Place a weekly rate against the guidance band for the user's goal.

    Returns the status plus a short label and a sentence of reasoning, so the UI
    never has to encode the thresholds itself and never shows a colour without
    words beside it.
    """
    if pct_per_week is None:
        return "unknown", "Not enough weigh-ins", (
            "Weigh in on a few more days and this will show how fast you are actually moving."
        )

    magnitude = abs(pct_per_week)
    if magnitude < HOLDING_PCT:
        detail = (
            f"Your trend is flat, within {HOLDING_PCT}% of bodyweight a week. "
            "That is maintenance, whatever the scale said this morning."
        )
        if direction == "maintain":
            return "holding", "Holding steady", detail
        return "holding", "Not moving yet", detail

    losing = pct_per_week < 0
    wanted_loss = direction == "lose"
    wanted_gain = direction == "gain"

    if direction == "maintain":
        return "wrong_way", "Drifting", (
            f"You are moving {magnitude:.2f}% of bodyweight a week while aiming to hold steady."
        )

    if (wanted_loss and not losing) or (wanted_gain and losing):
        verb = "gaining" if not losing else "losing"
        return "wrong_way", "Trending the wrong way", (
            f"Your trend is {verb} {magnitude:.2f}% of bodyweight a week, away from your goal. "
            "Check that intake matches the plan before changing the target."
        )

    low, high = (LOSS_BAND_MIN_PCT, LOSS_BAND_MAX_PCT) if wanted_loss else (
        GAIN_BAND_MIN_PCT,
        GAIN_BAND_MAX_PCT,
    )
    if magnitude < low:
        return "gentle", "Slow and steady", (
            f"{magnitude:.2f}% of bodyweight a week — below the usual {low}-{high}% band, "
            "so progress is real but unhurried. Sustainable, if you are content with the pace."
        )
    if magnitude <= high:
        return "on_target", "In the sweet spot", (
            f"{magnitude:.2f}% of bodyweight a week sits inside the {low}-{high}% band that "
            "tends to preserve muscle while the fat comes off."
        )
    if wanted_loss:
        return "rapid", "Faster than ideal", (
            f"{magnitude:.2f}% of bodyweight a week is above {high}%. Past that, more of the "
            "loss tends to come from muscle and water. Eating a little more usually keeps more."
        )
    return "rapid", "Gaining quickly", (
        f"{magnitude:.2f}% of bodyweight a week is above {high}%, faster than muscle is "
        "generally added, so more of it will be fat."
    )


def analyse(
    *,
    points: list[WeightPoint],
    goal_weight_kg: float | None = None,
    rate_window_days: int = RATE_WINDOW_DAYS,
) -> WeightTrend:
    """Smooth the weight log and describe what it is doing."""
    series = smooth(points)
    if not series:
        status, label, detail = classify_rate(None, "lose")
        return WeightTrend(
            trend_kg=None,
            scale_kg=None,
            deviation_kg=None,
            noise_kg=None,
            weekly_change_kg=None,
            weekly_change_pct=None,
            rate_status=status,
            rate_label=label,
            rate_detail=detail,
            days_of_data=0,
            span_days=0,
            interpolated_days=0,
            how_calculated="No weigh-ins recorded yet.",
            series=[],
        )

    measured = [d for d in series if d.scale_kg is not None]
    latest_trend = series[-1].trend_kg
    latest_scale = measured[-1].scale_kg if measured else None
    span_days = (series[-1].day - series[0].day).days

    deviation = (
        round(latest_scale - latest_trend, 2)
        if latest_scale is not None and series[-1].scale_kg is not None
        else None
    )
    noise = (
        round(_mean([abs(d.scale_kg - d.trend_kg) for d in measured]), 2)
        if len(measured) >= MIN_POINTS_FOR_TREND
        else None
    )

    weekly_kg = _rate_from_trend(series, rate_window_days) if span_days >= MIN_SPAN_DAYS_FOR_RATE else None
    weekly_pct = (
        round(weekly_kg / latest_trend * 100.0, 3)
        if weekly_kg is not None and latest_trend
        else None
    )
    status, label, detail = classify_rate(weekly_pct, _direction(latest_trend, goal_weight_kg))

    if weekly_kg is None:
        how = (
            f"{len(measured)} weigh-in{'s' if len(measured) != 1 else ''} smoothed into a trend. "
            f"A rate needs at least {MIN_SPAN_DAYS_FOR_RATE} days between your first and last."
        )
    else:
        how = (
            f"Each weigh-in moves the trend {int(SMOOTHING_ALPHA * 100)}% of the way towards "
            "itself, so water and food swings average out. The rate is a straight-line fit "
            f"through the last {min(rate_window_days, span_days + 1)} days of that trend, "
            "not through the raw readings, which is why it barely twitches when one morning "
            "comes in heavy."
        )

    return WeightTrend(
        trend_kg=round(latest_trend, 2),
        scale_kg=latest_scale,
        deviation_kg=deviation,
        noise_kg=noise,
        weekly_change_kg=round(weekly_kg, 3) if weekly_kg is not None else None,
        weekly_change_pct=weekly_pct,
        rate_status=status,
        rate_label=label,
        rate_detail=detail,
        days_of_data=len(measured),
        span_days=span_days,
        interpolated_days=len(series) - len(measured),
        how_calculated=how,
        series=series,
    )
