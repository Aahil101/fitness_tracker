"""Daily weight logging — one row per calendar day, upserted."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..db import eq
from ..deps import UserContext, fetch_weight_logs, get_context
from ..schemas import WeightLogCreate
from ..services import aggregate
from ..services.forecast import observed_weekly_change

router = APIRouter(prefix="/api/weight", tags=["weight"])


@router.get("")
async def list_weights(
    days: int = Query(default=90, ge=1, le=1825),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    rows = await fetch_weight_logs(ctx, days)
    points = aggregate.weight_points(rows)
    weekly, span = observed_weekly_change(points)
    return {
        "logs": rows,
        "count": len(rows),
        "latest": rows[-1] if rows else None,
        "observed_weekly_change_kg": weekly,
        "span_days": span,
    }


@router.post("", status_code=201)
async def upsert_weight(
    payload: WeightLogCreate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    """Re-logging the same day overwrites it, so the two-second flow is idempotent."""
    day = payload.logged_at or ctx.today
    row = {
        "user_id": ctx.user_id,
        "logged_at": day.isoformat(),
        "weight_kg": payload.weight_kg,
    }
    if payload.note:
        row["note"] = payload.note

    saved = await ctx.db.upsert("weight_logs", row, on_conflict="user_id,logged_at")
    entry = saved[0] if saved else row

    # First ever weigh-in also seeds the profile's starting weight.
    if not ctx.profile.get("starting_weight_kg"):
        await ctx.db.update(
            "profiles", {"starting_weight_kg": payload.weight_kg}, {"id": eq(ctx.user_id)}
        )

    previous = await ctx.db.select_one(
        "weight_logs",
        {
            "select": "weight_kg,logged_at",
            "user_id": eq(ctx.user_id),
            "logged_at": f"lt.{day.isoformat()}",
            "order": "logged_at.desc",
        },
    )
    delta = None
    if previous and previous.get("weight_kg") is not None:
        delta = round(payload.weight_kg - float(previous["weight_kg"]), 2)

    return {"log": entry, "change_since_previous_kg": delta, "previous": previous}


@router.delete("/{log_id}")
async def delete_weight(log_id: str, ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    deleted = await ctx.db.delete_one(
        "weight_logs", {"id": eq(log_id), "user_id": eq(ctx.user_id)}
    )
    return {"deleted": deleted}


@router.get("/streak")
async def weigh_in_streak(ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    """Consecutive days with a weigh-in, ending today or yesterday."""
    rows = await fetch_weight_logs(ctx, 400)
    days = {p.day for p in aggregate.weight_points(rows)}
    if not days:
        return {"streak": 0, "logged_today": False}

    logged_today = ctx.today in days
    cursor = ctx.today if logged_today else ctx.today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return {"streak": streak, "logged_today": logged_today}
