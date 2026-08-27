"""Dashboard + analytics aggregates.

The front page needs today's totals, three rolling windows, the forecast and the
weight state. Serving that as one response keeps the gauge a single fetch instead
of five, which matters on a phone on mobile data.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ..db import build_params, eq
from ..deps import UserContext, fetch_food_logs, fetch_weight_logs, fetch_workouts, get_context
from ..services import aggregate
from ..services.forecast import forecast as run_forecast
from ..services.forecast import observed_weekly_change, project_weight_series

router = APIRouter(prefix="/api", tags=["dashboard"])

# Rolling windows, per spec: trailing N days including today (not calendar-aligned).
PERIOD_DAYS: dict[str, int] = {"week": 7, "month": 30, "year": 365}
YEAR_DAYS = 365


async def _fetch_year_food(ctx: UserContext) -> list[dict[str, Any]]:
    """Slim projection over a year of food logs — only what the roll-ups need."""
    start_iso, end_iso = aggregate.range_bounds_utc(
        ctx.today - timedelta(days=YEAR_DAYS - 1), ctx.today, ctx.tz
    )
    return await ctx.db.select(
        "food_logs",
        build_params(
            {
                "select": "logged_at,calories,protein_g,carbs_g,fat_g,fiber_g",
                "user_id": eq(ctx.user_id),
                "order": "logged_at.desc",
                "limit": 20000,
            },
            ("logged_at", f"gte.{start_iso}"),
            ("logged_at", f"lt.{end_iso}"),
        ),
    )


async def _fetch_year_workouts(ctx: UserContext) -> list[dict[str, Any]]:
    start_iso, end_iso = aggregate.range_bounds_utc(
        ctx.today - timedelta(days=YEAR_DAYS - 1), ctx.today, ctx.tz
    )
    return await ctx.db.select(
        "workouts",
        build_params(
            {
                "select": "logged_at,calories_burned,duration_min,activity_type",
                "user_id": eq(ctx.user_id),
                "order": "logged_at.desc",
                "limit": 20000,
            },
            ("logged_at", f"gte.{start_iso}"),
            ("logged_at", f"lt.{end_iso}"),
        ),
    )


def _period_stats(
    *,
    food_rows: list[dict[str, Any]],
    workout_rows: list[dict[str, Any]],
    tz: Any,
    today: date,
    days: int,
) -> dict[str, Any]:
    start = today - timedelta(days=days - 1)
    in_window = [r for r in food_rows if (d := aggregate.local_day_of(r, tz)) and start <= d <= today]
    workouts_in = [
        r for r in workout_rows if (d := aggregate.local_day_of(r, tz)) and start <= d <= today
    ]

    logged_days = {aggregate.local_day_of(r, tz) for r in in_window}
    logged_days.discard(None)
    total = aggregate.sum_field(in_window, "calories")
    burned = aggregate.sum_field(workouts_in, "calories_burned")

    return {
        "days": days,
        "from": start.isoformat(),
        "to": today.isoformat(),
        "total_calories": total,
        # Average over days actually logged: dividing by 7 when only 3 days were
        # logged understates intake and makes the number useless.
        "daily_average": round(total / len(logged_days), 1) if logged_days else 0.0,
        "days_logged": len(logged_days),
        "total_burned": burned,
        "workout_sessions": len(workouts_in),
        "workout_minutes": int(aggregate.sum_field(workouts_in, "duration_min")),
        "protein_g": aggregate.sum_field(in_window, "protein_g"),
        "carbs_g": aggregate.sum_field(in_window, "carbs_g"),
        "fat_g": aggregate.sum_field(in_window, "fat_g"),
        "fiber_g": aggregate.sum_field(in_window, "fiber_g"),
    }


@router.get("/dashboard")
async def dashboard(
    forecast_window: Literal[7, 14, 30] = Query(default=7),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    year_food = await _fetch_year_food(ctx)
    year_workouts = await _fetch_year_workouts(ctx)
    today_logs = await fetch_food_logs(ctx, ctx.today, ctx.today)
    today_workouts = await fetch_workouts(ctx, ctx.today, ctx.today)
    weights = await fetch_weight_logs(ctx, YEAR_DAYS)

    today_totals = aggregate.totals(today_logs)
    burn_today = aggregate.sum_field(today_workouts, "calories_burned")

    target = ctx.daily_calorie_target
    maintenance = ctx.maintenance_calories
    logged = today_totals["calories"]

    points = aggregate.weight_points(weights)
    series = aggregate.daily_series(
        food_rows=year_food,
        workout_rows=year_workouts,
        tz=ctx.tz,
        start=ctx.today - timedelta(days=max(PERIOD_DAYS["month"], forecast_window) - 1),
        end=ctx.today,
    )

    fc = run_forecast(
        days=series,
        maintenance_calories=maintenance,
        window_days=forecast_window,
        weight_points=points,
        goal_weight_kg=ctx.goal_weight_kg,
        today=ctx.today,
    )

    logged_today_weight = bool(points and points[-1].day == ctx.today)

    return {
        "today": {
            "date": ctx.today.isoformat(),
            **today_totals,
            "entry_count": len(today_logs),
            "workout_burn": burn_today,
            "workout_sessions": len(today_workouts),
            "logs": today_logs,
            "workouts": today_workouts,
        },
        "goal": {
            **{
                k: ctx.goal.get(k)
                for k in (
                    "daily_calorie_target",
                    "maintenance_calories",
                    "protein_target_g",
                    "carb_target_g",
                    "fat_target_g",
                    "fiber_target_g",
                    "target_weekly_deficit_kcal",
                    "effective_from",
                )
            },
            "is_provisional": ctx.goal_is_provisional,
        },
        # Everything <HomeGauge /> needs to draw the three arc layers.
        "gauge": {
            "logged_calories": logged,
            "maintenance_calories": int(maintenance),
            "daily_calorie_target": int(target),
            "remaining_to_target": round(target - logged, 1),
            "remaining_to_maintenance": round(maintenance - logged, 1),
            "over_target": logged > target,
            "over_maintenance": logged > maintenance,
            "fraction_of_maintenance": round(min(1.0, logged / maintenance), 4) if maintenance else 0,
            "target_fraction_of_maintenance": round(min(1.0, target / maintenance), 4)
            if maintenance
            else 0,
            "workout_burn": burn_today,
        },
        "periods": {
            name: _period_stats(
                food_rows=year_food,
                workout_rows=year_workouts,
                tz=ctx.tz,
                today=ctx.today,
                days=days,
            )
            for name, days in PERIOD_DAYS.items()
        },
        "forecast": {
            "window_days": fc.window_days,
            "days_with_data": fc.days_with_data,
            "avg_daily_intake": fc.avg_daily_intake,
            "avg_daily_exercise_burn": fc.avg_daily_exercise_burn,
            "avg_daily_net_kcal": fc.avg_daily_net_kcal,
            "projected_weekly_change_kg": fc.projected_weekly_change_kg,
            "projected_monthly_change_kg": fc.projected_monthly_change_kg,
            "observed_weekly_change_kg": fc.observed_weekly_change_kg,
            "effective_weekly_change_kg": fc.effective_weekly_change_kg,
            "projected_weight_7d_kg": fc.projected_weight_7d_kg,
            "projected_weight_30d_kg": fc.projected_weight_30d_kg,
            "days_to_goal": fc.days_to_goal,
            "goal_date": fc.goal_date.isoformat() if fc.goal_date else None,
            "confidence": fc.confidence,
            "notes": fc.notes,
        },
        "weight": {
            "current_kg": fc.current_weight_kg,
            "goal_kg": ctx.goal_weight_kg,
            "starting_kg": float(ctx.profile["starting_weight_kg"])
            if ctx.profile.get("starting_weight_kg")
            else None,
            "logged_today": logged_today_weight,
            "latest_logged_at": points[-1].day.isoformat() if points else None,
            "total_change_kg": round(points[-1].weight_kg - points[0].weight_kg, 2)
            if len(points) > 1
            else None,
        },
        "profile": {
            "full_name": ctx.profile.get("full_name"),
            "unit_preference": ctx.profile.get("unit_preference") or "metric",
            "timezone": str(ctx.tz),
            "needs_onboarding": not bool(ctx.profile.get("onboarded_at")),
        },
    }


@router.get("/analytics")
async def analytics(
    days: int = Query(default=30, ge=7, le=365),
    forecast_window: Literal[7, 14, 30] = Query(default=14),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    """Series for the charts: weight + projection, calories in/out, macros."""
    start = ctx.today - timedelta(days=days - 1)

    food_rows = await fetch_food_logs(ctx, start, ctx.today)
    workout_rows = await fetch_workouts(ctx, start, ctx.today)
    weight_rows = await fetch_weight_logs(ctx, days + 30)

    energy_days = aggregate.daily_series(
        food_rows=food_rows, workout_rows=workout_rows, tz=ctx.tz, start=start, end=ctx.today
    )
    maintenance = ctx.maintenance_calories
    target = ctx.daily_calorie_target

    calorie_series = [
        {
            "date": d.day.isoformat(),
            "calories_in": round(d.calories_in, 1),
            "exercise_burn": round(d.calories_out, 1),
            "calories_out": round(maintenance + d.calories_out, 1),
            "net": round(d.net_balance(maintenance), 1) if d.logged else None,
            "target": int(target),
            "logged": d.logged,
        }
        for d in energy_days
    ]

    points = aggregate.weight_points(weight_rows)
    weight_series = [
        {"date": p.day.isoformat(), "weight_kg": p.weight_kg}
        for p in points
        if p.day >= start
    ]

    fc = run_forecast(
        days=energy_days,
        maintenance_calories=maintenance,
        window_days=forecast_window,
        weight_points=points,
        goal_weight_kg=ctx.goal_weight_kg,
        today=ctx.today,
    )

    projection: list[dict[str, Any]] = []
    if points:
        projection = project_weight_series(
            start_weight_kg=points[-1].weight_kg,
            weekly_change_kg=fc.effective_weekly_change_kg,
            start_day=points[-1].day,
            days=min(60, max(14, days // 2)),
        )

    observed_weekly, span_days = observed_weekly_change(points)
    macro_series = aggregate.macro_daily_series(
        food_rows=food_rows, tz=ctx.tz, start=start, end=ctx.today
    )
    logged_macro_days = [m for m in macro_series if m["calories"] > 0]

    def avg(field: str) -> float:
        if not logged_macro_days:
            return 0.0
        return round(sum(m[field] for m in logged_macro_days) / len(logged_macro_days), 1)

    macro_totals = {
        "protein_g": aggregate.sum_field(food_rows, "protein_g"),
        "carbs_g": aggregate.sum_field(food_rows, "carbs_g"),
        "fat_g": aggregate.sum_field(food_rows, "fat_g"),
        "fiber_g": aggregate.sum_field(food_rows, "fiber_g"),
    }

    return {
        "range": {"from": start.isoformat(), "to": ctx.today.isoformat(), "days": days},
        "calorie_series": calorie_series,
        "weight_series": weight_series,
        "weight_projection": projection,
        "macro_series": macro_series,
        "macro_totals": macro_totals,
        "macro_averages": {
            "calories": avg("calories"),
            "protein_g": avg("protein_g"),
            "carbs_g": avg("carbs_g"),
            "fat_g": avg("fat_g"),
            "fiber_g": avg("fiber_g"),
        },
        "macro_targets": {
            "protein_g": ctx.goal.get("protein_target_g"),
            "carbs_g": ctx.goal.get("carb_target_g"),
            "fat_g": ctx.goal.get("fat_target_g"),
            "fiber_g": ctx.goal.get("fiber_target_g"),
        },
        "workout_groups": {
            bucket: aggregate.group_workouts(workout_rows=workout_rows, tz=ctx.tz, bucket=bucket)
            for bucket in ("day", "week")
        },
        "activity_breakdown": _activity_breakdown(workout_rows),
        "forecast": {
            "window_days": fc.window_days,
            "days_with_data": fc.days_with_data,
            "avg_daily_net_kcal": fc.avg_daily_net_kcal,
            "projected_weekly_change_kg": fc.projected_weekly_change_kg,
            "observed_weekly_change_kg": observed_weekly,
            "observed_span_days": span_days,
            "effective_weekly_change_kg": fc.effective_weekly_change_kg,
            "days_to_goal": fc.days_to_goal,
            "goal_date": fc.goal_date.isoformat() if fc.goal_date else None,
            "confidence": fc.confidence,
            "notes": fc.notes,
        },
        "targets": {"daily_calorie_target": int(target), "maintenance_calories": int(maintenance)},
    }


def _activity_breakdown(workout_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    for row in workout_rows:
        key = (row.get("activity_type") or "other").replace("_", " ").title()
        entry = buckets.setdefault(key, {"calories_burned": 0.0, "duration_min": 0.0, "sessions": 0})
        entry["calories_burned"] += aggregate.num(row.get("calories_burned"))
        entry["duration_min"] += aggregate.num(row.get("duration_min"))
        entry["sessions"] += 1

    return sorted(
        (
            {
                "activity": name,
                "calories_burned": round(v["calories_burned"], 1),
                "duration_min": int(v["duration_min"]),
                "sessions": int(v["sessions"]),
            }
            for name, v in buckets.items()
        ),
        key=lambda item: item["calories_burned"],
        reverse=True,
    )
