"""AI fitness assistant: persistent sessions, message history, injected context.

Two things make the answers useful rather than generic:

1. **Context injection** — every request rebuilds a compact JSON snapshot of the
   user's profile, goal, today's log, rolling averages and forecast, and passes
   it as a system instruction. The model is told never to invent numbers.
2. **History** — the last N turns of the session are replayed, so follow-ups like
   "what about tomorrow?" resolve correctly. The snapshot is stored with each
   assistant message so an old answer can still be explained later.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..cache import check_rate_limit
from ..config import settings
from ..db import eq
from ..deps import UserContext, fetch_food_logs, fetch_weight_logs, fetch_workouts, get_context
from ..errors import AppError, NotFoundError, RateLimitError
from ..schemas import ChatMessageCreate, ChatMessageOut, ChatReply, ChatSessionCreate
from ..services import aggregate, gemini
from ..services.forecast import forecast as run_forecast

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# How many prior turns to replay. Long enough for real follow-ups, short enough
# to stay inside the free tier's token budget.
HISTORY_TURNS = 12
CONTEXT_WINDOW_DAYS = 14

SUGGESTED_PROMPTS = (
    "How am I tracking against my goal this week?",
    "What should I eat tonight with my remaining calories?",
    "Why has my weight stalled?",
    "Build me a simple 3-day workout split",
    "Is my protein intake high enough?",
)


async def _build_context(ctx: UserContext) -> dict[str, Any]:
    """Compact snapshot of the user's real numbers for the system instruction."""
    start = ctx.today - timedelta(days=CONTEXT_WINDOW_DAYS - 1)
    food_rows = await fetch_food_logs(ctx, start, ctx.today)
    workout_rows = await fetch_workouts(ctx, start, ctx.today)
    weight_rows = await fetch_weight_logs(ctx, 60)

    today_rows = [r for r in food_rows if aggregate.local_day_of(r, ctx.tz) == ctx.today]
    today_workouts = [r for r in workout_rows if aggregate.local_day_of(r, ctx.tz) == ctx.today]
    today_totals = aggregate.totals(today_rows)

    days = aggregate.daily_series(
        food_rows=food_rows, workout_rows=workout_rows, tz=ctx.tz, start=start, end=ctx.today
    )
    points = aggregate.weight_points(weight_rows)
    fc = run_forecast(
        days=days,
        maintenance_calories=ctx.maintenance_calories,
        window_days=7,
        weight_points=points,
        goal_weight_kg=ctx.goal_weight_kg,
        today=ctx.today,
    )

    target = ctx.daily_calorie_target
    profile = ctx.profile

    return {
        "today": ctx.today.isoformat(),
        "profile": {
            "name": profile.get("full_name"),
            "sex": profile.get("sex"),
            "height_cm": profile.get("height_cm"),
            "activity_level": profile.get("activity_level"),
            "unit_preference": profile.get("unit_preference") or "metric",
        },
        "goal": {
            "daily_calorie_target": int(target),
            "maintenance_calories": int(ctx.maintenance_calories),
            "protein_target_g": ctx.goal.get("protein_target_g"),
            "carb_target_g": ctx.goal.get("carb_target_g"),
            "fat_target_g": ctx.goal.get("fat_target_g"),
            "fiber_target_g": ctx.goal.get("fiber_target_g"),
            "goal_weight_kg": ctx.goal_weight_kg,
            "weekly_deficit_kcal": ctx.goal.get("target_weekly_deficit_kcal"),
        },
        "today_so_far": {
            "calories": today_totals["calories"],
            "calories_remaining": round(target - today_totals["calories"], 1),
            "protein_g": today_totals["protein_g"],
            "carbs_g": today_totals["carbs_g"],
            "fat_g": today_totals["fat_g"],
            "fiber_g": today_totals["fiber_g"],
            "exercise_burn": aggregate.sum_field(today_workouts, "calories_burned"),
            "entries": [
                {
                    "name": r.get("food_name"),
                    "calories": aggregate.num(r.get("calories")),
                    "portion_g": aggregate.num(r.get("portion_g")),
                    "meal": r.get("meal_type"),
                }
                for r in today_rows[:15]
            ],
        },
        "last_14_days": {
            "days_logged": fc.days_with_data,
            "avg_daily_calories": fc.avg_daily_intake,
            "avg_daily_exercise_burn": fc.avg_daily_exercise_burn,
            "avg_daily_net_kcal": fc.avg_daily_net_kcal,
            "workout_sessions": len(workout_rows),
            "workout_minutes": int(aggregate.sum_field(workout_rows, "duration_min")),
            "recent_activities": sorted(
                {str(r.get("activity_type")) for r in workout_rows if r.get("activity_type")}
            )[:8],
        },
        "weight": {
            "current_kg": fc.current_weight_kg,
            "goal_kg": ctx.goal_weight_kg,
            "recent_log": [
                {"date": p.day.isoformat(), "kg": p.weight_kg} for p in points[-10:]
            ],
        },
        "forecast": {
            "projected_weekly_change_kg": fc.projected_weekly_change_kg,
            "observed_weekly_change_kg": fc.observed_weekly_change_kg,
            "days_to_goal": fc.days_to_goal,
            "confidence": fc.confidence,
        },
    }


def _title_from(content: str) -> str:
    text = " ".join(content.strip().split())
    return (text[:57] + "…") if len(text) > 58 else text or "New conversation"


def _to_message_out(row: dict[str, Any]) -> ChatMessageOut:
    return ChatMessageOut(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=row.get("created_at"),
        model=row.get("model"),
    )


@router.get("/suggestions")
async def suggestions() -> dict[str, Any]:
    return {"prompts": list(SUGGESTED_PROMPTS)}


@router.get("/sessions")
async def list_sessions(ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    rows = await ctx.db.select(
        "chat_sessions",
        {
            "select": "*",
            "user_id": eq(ctx.user_id),
            "order": "last_message_at.desc",
            "limit": 50,
        },
    )
    return {"sessions": rows}


@router.post("/sessions", status_code=201)
async def create_session(
    payload: ChatSessionCreate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    row = await ctx.db.insert_one(
        "chat_sessions",
        {"user_id": ctx.user_id, "title": payload.title or "New conversation"},
    )
    return {"session": row}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    deleted = await ctx.db.delete_one(
        "chat_sessions", {"id": eq(session_id), "user_id": eq(ctx.user_id)}
    )
    return {"deleted": deleted}


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=300),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    session = await ctx.db.select_one(
        "chat_sessions", {"select": "*", "id": eq(session_id), "user_id": eq(ctx.user_id)}
    )
    if not session:
        raise NotFoundError("Conversation not found")

    rows = await ctx.db.select(
        "chat_messages",
        {
            "select": "id,session_id,role,content,model,created_at",
            "session_id": eq(session_id),
            "user_id": eq(ctx.user_id),
            "order": "created_at.asc",
            "limit": limit,
        },
    )
    return {"session": session, "messages": rows}


@router.post("/messages", response_model=ChatReply)
async def send_message(
    payload: ChatMessageCreate, ctx: UserContext = Depends(get_context)
) -> ChatReply:
    """Send a turn and get the assistant's reply. Creates a session if needed."""
    content = payload.content.strip()
    if not content:
        raise AppError("Message cannot be empty.")

    limit = await check_rate_limit("chat", ctx.user_id, settings.rate_limit_chat_per_hour)
    if not limit.allowed:
        raise RateLimitError(
            f"Chat limit reached ({limit.limit}/hour). Try again in "
            f"{max(1, limit.reset_in_s // 60)} minutes.",
            retry_after=limit.reset_in_s,
        )

    # -- session -----------------------------------------------------------
    session: dict[str, Any] | None = None
    if payload.session_id:
        session = await ctx.db.select_one(
            "chat_sessions",
            {"select": "*", "id": eq(payload.session_id), "user_id": eq(ctx.user_id)},
        )
        if not session:
            raise NotFoundError("Conversation not found")
    else:
        session = await ctx.db.insert_one(
            "chat_sessions", {"user_id": ctx.user_id, "title": _title_from(content)}
        )
    session_id = session["id"]

    # -- history + context -------------------------------------------------
    history_rows = await ctx.db.select(
        "chat_messages",
        {
            "select": "role,content",
            "session_id": eq(session_id),
            "user_id": eq(ctx.user_id),
            "order": "created_at.desc",
            "limit": HISTORY_TURNS,
        },
    )
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in reversed(history_rows)
        if r.get("role") in ("user", "assistant")
    ]
    history.append({"role": "user", "content": content})

    context = await _build_context(ctx)

    user_row = await ctx.db.insert_one(
        "chat_messages",
        {
            "session_id": session_id,
            "user_id": ctx.user_id,
            "role": "user",
            "content": content,
        },
    )

    degraded = False
    try:
        reply_text = await gemini.chat(
            history, context_json=json.dumps(context, default=str, separators=(",", ":"))
        )
    except AppError as exc:
        degraded = True
        reply_text = (
            "I can't reach the AI service right now, so here are your numbers straight from "
            f"your log: you've eaten {context['today_so_far']['calories']:.0f} kcal today of a "
            f"{context['goal']['daily_calorie_target']} kcal target, leaving "
            f"{context['today_so_far']['calories_remaining']:.0f} kcal. "
            f"({exc.detail})"
        )
        log.info("Chat degraded: %s", exc.detail)

    assistant_row = await ctx.db.insert_one(
        "chat_messages",
        {
            "session_id": session_id,
            "user_id": ctx.user_id,
            "role": "assistant",
            "content": reply_text,
            "context_snapshot": context,
            "model": None if degraded else settings.gemini_model,
        },
    )

    patch: dict[str, Any] = {
        "last_message_at": assistant_row.get("created_at")
        or datetime.now(UTC).isoformat()
    }
    if session.get("title") in (None, "", "New conversation"):
        patch["title"] = _title_from(content)
    try:
        updated = await ctx.db.update_one("chat_sessions", patch, {"id": eq(session_id)})
        session_title = updated.get("title") or session.get("title") or "New conversation"
    except AppError:
        session_title = session.get("title") or "New conversation"

    return ChatReply(
        session_id=session_id,
        session_title=session_title,
        user_message=_to_message_out(user_row),
        assistant_message=_to_message_out(assistant_row),
        context_used={
            "today_calories": context["today_so_far"]["calories"],
            "calories_remaining": context["today_so_far"]["calories_remaining"],
            "days_logged_14d": context["last_14_days"]["days_logged"],
            "current_weight_kg": context["weight"]["current_kg"],
        },
        degraded=degraded,
    )
