"""Workout logging, MET estimation, and hour/day/week roll-ups."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ..db import eq
from ..deps import UserContext, fetch_workouts, get_context
from ..schemas import WorkoutCreate, WorkoutEstimateRequest, WorkoutUpdate
from ..services import aggregate
from ..services.met import activity_catalog, estimate_calories_burned, resolve_met

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


@router.get("/catalog")
async def catalog() -> dict[str, Any]:
    """MET table for the activity picker (public — no user data involved)."""
    return {"activities": activity_catalog()}


@router.post("/estimate")
async def estimate(
    payload: WorkoutEstimateRequest, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    weight = payload.weight_kg or await ctx.current_weight_kg() or 70.0
    burned = estimate_calories_burned(
        payload.activity_type, payload.duration_min, float(weight), payload.intensity
    )
    return {
        "calories_burned": burned,
        "met": resolve_met(payload.activity_type),
        "weight_kg_used": round(float(weight), 1),
        "intensity": payload.intensity or "moderate",
    }


@router.get("")
async def list_workouts(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    days: int = Query(default=7, ge=1, le=365),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    end = date_to or ctx.today
    start = date_from or (end - timedelta(days=days - 1))
    rows = await fetch_workouts(ctx, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "workouts": rows,
        "totals": {
            "calories_burned": aggregate.sum_field(rows, "calories_burned"),
            "duration_min": int(aggregate.sum_field(rows, "duration_min")),
            "sessions": len(rows),
        },
    }


@router.get("/grouped")
async def grouped(
    bucket: Literal["hour", "day", "week"] = "day",
    days: int = Query(default=7, ge=1, le=365),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    start = ctx.today - timedelta(days=days - 1)
    rows = await fetch_workouts(ctx, start, ctx.today)
    return {
        "bucket": bucket,
        "from": start.isoformat(),
        "to": ctx.today.isoformat(),
        "groups": aggregate.group_workouts(workout_rows=rows, tz=ctx.tz, bucket=bucket),
    }


@router.post("", status_code=201)
async def create_workout(
    payload: WorkoutCreate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    row = payload.model_dump(mode="json", exclude_none=True)
    row["user_id"] = ctx.user_id
    row.setdefault("logged_at", datetime.now(UTC).isoformat())

    if payload.calories_burned is None:
        weight = await ctx.current_weight_kg() or 70.0
        row["calories_burned"] = estimate_calories_burned(
            payload.activity_type, payload.duration_min, float(weight), payload.intensity
        )
        row["source"] = "met_estimated"
    else:
        row["source"] = "manual"

    created = await ctx.db.insert_one("workouts", row)
    return {"workout": created}


@router.patch("/{workout_id}")
async def update_workout(
    workout_id: str, payload: WorkoutUpdate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    patch = payload.model_dump(mode="json", exclude_none=True)
    if not patch:
        row = await ctx.db.select_one(
            "workouts", {"select": "*", "id": eq(workout_id), "user_id": eq(ctx.user_id)}
        )
        return {"workout": row}
    updated = await ctx.db.update_one(
        "workouts", patch, {"id": eq(workout_id), "user_id": eq(ctx.user_id)}
    )
    return {"workout": updated}


@router.delete("/{workout_id}")
async def delete_workout(
    workout_id: str, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    deleted = await ctx.db.delete_one(
        "workouts", {"id": eq(workout_id), "user_id": eq(ctx.user_id)}
    )
    return {"deleted": deleted}
