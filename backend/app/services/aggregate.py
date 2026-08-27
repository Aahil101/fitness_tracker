"""Timezone-aware roll-ups over raw log rows.

"Today" is a user-facing concept, so every bucket boundary is computed in the
profile's timezone and only then converted to UTC for querying. Getting this
wrong is how trackers show an empty gauge at 1am or roll over mid-evening.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .forecast import DayEnergy, WeightPoint

MACRO_FIELDS = ("protein_g", "carbs_g", "fat_g", "fiber_g")


def resolve_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def today_in_tz(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def parse_ts(raw: Any) -> datetime | None:
    """Parse a PostgREST timestamptz into an aware datetime."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = "".join(ch for ch in tail if ch.isdigit())[:6]
        rest = tail[len(digits) :] if len(tail) > len(digits) else ""
        offset = "".join(ch for ch in rest if ch in "+-:0123456789")
        text = f"{head}.{digits or '0'}{offset}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_day(raw: Any) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    ts = parse_ts(raw)
    if ts:
        return ts.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[str, str]:
    """[start, end) of a local calendar day, as UTC ISO strings."""
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).isoformat(),
        end_local.astimezone(UTC).isoformat(),
    )


def range_bounds_utc(start: date, end: date, tz: ZoneInfo) -> tuple[str, str]:
    """[start of `start` day, end of `end` day) in UTC."""
    start_iso, _ = day_bounds_utc(start, tz)
    _, end_iso = day_bounds_utc(end, tz)
    return start_iso, end_iso


def local_day_of(row: dict[str, Any], tz: ZoneInfo, field: str = "logged_at") -> date | None:
    ts = parse_ts(row.get(field))
    if ts is None:
        return parse_day(row.get(field))
    return ts.astimezone(tz).date()


def num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sum_field(rows: Iterable[dict[str, Any]], field: str) -> float:
    return round(sum(num(r.get(field)) for r in rows), 1)


def totals(food_rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    rows = list(food_rows)
    result = {"calories": sum_field(rows, "calories")}
    for field in MACRO_FIELDS:
        result[field] = sum_field(rows, field)
    return result


def daily_series(
    *,
    food_rows: Iterable[dict[str, Any]],
    workout_rows: Iterable[dict[str, Any]],
    tz: ZoneInfo,
    start: date,
    end: date,
) -> list[DayEnergy]:
    """One DayEnergy per calendar day in [start, end], zero-filled."""
    buckets: dict[date, DayEnergy] = {}
    cursor = start
    while cursor <= end:
        buckets[cursor] = DayEnergy(day=cursor)
        cursor += timedelta(days=1)

    for row in food_rows:
        day = local_day_of(row, tz)
        bucket = buckets.get(day) if day else None
        if bucket is None:
            continue
        bucket.calories_in += num(row.get("calories"))
        bucket.food_entries += 1

    for row in workout_rows:
        day = local_day_of(row, tz)
        bucket = buckets.get(day) if day else None
        if bucket is None:
            continue
        bucket.calories_out += num(row.get("calories_burned"))

    return [buckets[d] for d in sorted(buckets)]


def weight_points(rows: Iterable[dict[str, Any]]) -> list[WeightPoint]:
    points: list[WeightPoint] = []
    for row in rows:
        day = parse_day(row.get("logged_at"))
        weight = num(row.get("weight_kg"), default=-1.0)
        if day and weight > 0:
            points.append(WeightPoint(day=day, weight_kg=weight))
    return sorted(points, key=lambda p: p.day)


def macro_daily_series(
    *,
    food_rows: Iterable[dict[str, Any]],
    tz: ZoneInfo,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Per-day macro + calorie totals, zero-filled, for the charts."""
    buckets: dict[date, dict[str, float]] = {}
    cursor = start
    while cursor <= end:
        buckets[cursor] = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0}
        cursor += timedelta(days=1)

    for row in food_rows:
        day = local_day_of(row, tz)
        bucket = buckets.get(day) if day else None
        if bucket is None:
            continue
        bucket["calories"] += num(row.get("calories"))
        for field in MACRO_FIELDS:
            bucket[field] += num(row.get(field))

    return [
        {"date": day.isoformat(), **{k: round(v, 1) for k, v in values.items()}}
        for day, values in sorted(buckets.items())
    ]


def group_workouts(
    *,
    workout_rows: Iterable[dict[str, Any]],
    tz: ZoneInfo,
    bucket: str = "day",
) -> list[dict[str, Any]]:
    """Group workout burn by hour / day / week — the spec's queryable views."""
    groups: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calories_burned": 0.0, "duration_min": 0.0, "sessions": 0.0}
    )

    for row in workout_rows:
        ts = parse_ts(row.get("logged_at"))
        if ts is None:
            continue
        local = ts.astimezone(tz)
        if bucket == "hour":
            key = local.strftime("%Y-%m-%dT%H:00")
        elif bucket == "week":
            iso = local.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            key = local.date().isoformat()

        entry = groups[key]
        entry["calories_burned"] += num(row.get("calories_burned"))
        entry["duration_min"] += num(row.get("duration_min"))
        entry["sessions"] += 1

    return [
        {
            "bucket": key,
            "calories_burned": round(v["calories_burned"], 1),
            "duration_min": int(v["duration_min"]),
            "sessions": int(v["sessions"]),
        }
        for key, v in sorted(groups.items())
    ]
