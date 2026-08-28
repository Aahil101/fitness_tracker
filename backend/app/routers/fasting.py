"""Fasting sessions — one open fast at a time, with a personalised timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..db import eq
from ..deps import UserContext, fetch_food_logs, fetch_workouts, get_context
from ..errors import AppError
from ..schemas import FastingStartRequest, FastingStopRequest
from ..services import aggregate, fasting

router = APIRouter(prefix="/api/fasting", tags=["fasting"])

#: How far back to look for the meal that filled the user's glycogen. A day
#: covers the last eating window for every realistic fasting schedule.
FUEL_LOOKBACK_HOURS = 24

#: History depth for the summary and the list.
HISTORY_DAYS = 90


class AlreadyFastingError(AppError):
    """Starting a second fast would leave two open sessions and no right answer."""

    code = "already_fasting"

    def __init__(self, detail: str = "A fast is already running.") -> None:
        super().__init__(detail, 409)


class NotFastingError(AppError):
    code = "not_fasting"

    def __init__(self, detail: str = "No fast is running.") -> None:
        super().__init__(detail, 409)


async def _open_session(ctx: UserContext) -> dict[str, Any] | None:
    return await ctx.db.select_one(
        "fasting_sessions",
        {
            "select": "*",
            "user_id": eq(ctx.user_id),
            "ended_at": "is.null",
            "order": "started_at.desc",
        },
    )


async def _fuel_inputs(ctx: UserContext, since: datetime) -> tuple[float | None, float]:
    """Carbohydrate eaten and exercise burned in the window before the fast.

    Returns ``(carbs_g, exercise_kcal)``, with carbs as ``None`` when nothing was
    logged at all — an empty log is missing evidence, not a zero-carb day, and
    the two lead to very different timelines.
    """
    # Pull two calendar days and filter precisely, since the lookback is in hours
    # but the fetch helpers work in local days.
    start_day = (since - timedelta(days=1)).date()
    food = await fetch_food_logs(ctx, start_day, ctx.today)
    workouts = await fetch_workouts(ctx, start_day, ctx.today)

    def within(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        kept = []
        for row in rows:
            stamp = aggregate.parse_ts(row.get(field))
            if stamp is not None and stamp >= since:
                kept.append(row)
        return kept

    recent_food = within(food, "logged_at")
    recent_workouts = within(workouts, "logged_at")

    carbs = aggregate.sum_field(recent_food, "carbs_g") if recent_food else None
    burn = aggregate.sum_field(recent_workouts, "calories_burned")
    return carbs, burn


async def _state(ctx: UserContext, session: dict[str, Any] | None) -> dict[str, Any]:
    now = datetime.now(UTC)
    anchor = fasting._parse(session["started_at"]) if session else now
    carbs, burn = await _fuel_inputs(ctx, anchor - timedelta(hours=FUEL_LOOKBACK_HOURS))

    state = fasting.evaluate(
        session=session,
        now=now,
        weight_kg=await ctx.current_weight_kg(),
        maintenance_kcal=ctx.maintenance_calories,
        recent_carbs_g=carbs,
        exercise_kcal=burn,
    )
    return state.to_dict()


@router.get("/current")
async def current(ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    """The open fast if there is one, otherwise the timeline that would apply."""
    return await _state(ctx, await _open_session(ctx))


@router.post("/start", status_code=201)
async def start(
    payload: FastingStartRequest, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    if await _open_session(ctx):
        raise AlreadyFastingError("You already have a fast running. Stop that one first.")

    now = datetime.now(UTC)
    started = payload.started_at or now
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    # A fast cannot start in the future, and backdating past a week is almost
    # certainly a mistyped date rather than an intention.
    started = min(started, now)
    if (now - started) > timedelta(days=7):
        raise AppError("That start time is more than a week ago.")

    row: dict[str, Any] = {
        "user_id": ctx.user_id,
        "started_at": started.isoformat(),
        "target_hours": payload.target_hours,
    }
    if payload.note:
        row["note"] = payload.note

    saved = await ctx.db.insert_one("fasting_sessions", row)
    return {"session": saved, "state": await _state(ctx, saved)}


@router.post("/stop")
async def stop(
    payload: FastingStopRequest, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    session = await _open_session(ctx)
    if not session:
        raise NotFastingError("No fast is running at the moment.")

    now = datetime.now(UTC)
    ended = payload.ended_at or now
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=UTC)
    started = fasting._parse(session["started_at"])
    # Clamp into [started, now]: the database rejects an end before the start,
    # and an end in the future would make the duration grow as time passed.
    ended = max(started, min(ended, now))

    patch: dict[str, Any] = {"ended_at": ended.isoformat()}
    if payload.note:
        patch["note"] = payload.note

    saved = await ctx.db.update_one(
        "fasting_sessions", patch, {"id": eq(session["id"]), "user_id": eq(ctx.user_id)}
    )
    hours = (ended - started).total_seconds() / 3600.0
    return {
        "session": saved,
        "hours": round(hours, 3),
        "target_hours": float(saved.get("target_hours") or 0),
        "met_target": hours >= float(saved.get("target_hours") or 0),
        "state": await _state(ctx, None),
    }


@router.get("/history")
async def history(
    days: int = Query(default=HISTORY_DAYS, ge=1, le=365),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    since = (ctx.today - timedelta(days=days)).isoformat()
    rows = await ctx.db.select(
        "fasting_sessions",
        {
            "select": "*",
            "user_id": eq(ctx.user_id),
            "started_at": f"gte.{since}",
            "order": "started_at.desc",
            "limit": 400,
        },
    )
    return {"sessions": rows, "summary": fasting.summarise_history(rows)}


@router.delete("/{session_id}")
async def delete_session(
    session_id: str, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    deleted = await ctx.db.delete_one(
        "fasting_sessions", {"id": eq(session_id), "user_id": eq(ctx.user_id)}
    )
    return {"deleted": deleted}
