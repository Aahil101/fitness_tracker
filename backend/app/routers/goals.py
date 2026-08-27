"""Goal & deficit management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..db import eq
from ..deps import UserContext, get_context
from ..schemas import GoalCreateRequest, GoalPreviewOut, GoalPreviewRequest
from ..services import aggregate
from ..services.energy import GoalComputation, age_from_birth_date, compute_goal

router = APIRouter(prefix="/api/goals", tags=["goals"])


async def _resolve_inputs(
    ctx: UserContext, payload: GoalPreviewRequest
) -> tuple[float, float, int, str | None, str | None]:
    """Fill any unspecified input from the stored profile / latest weigh-in."""
    weight = payload.weight_kg or await ctx.current_weight_kg() or 70.0
    height = payload.height_cm or float(ctx.profile.get("height_cm") or 170)
    age = payload.age_years or age_from_birth_date(
        aggregate.parse_day(ctx.profile.get("birth_date")), ctx.today
    )
    sex = payload.sex or ctx.profile.get("sex")
    activity = payload.activity_level or ctx.profile.get("activity_level")
    return float(weight), float(height), int(age), sex, activity


def _to_preview(computed: GoalComputation) -> GoalPreviewOut:
    return GoalPreviewOut(
        maintenance_calories=computed.maintenance_calories,
        daily_calorie_target=computed.daily_calorie_target,
        bmr=computed.bmr,
        target_weekly_deficit_kcal=computed.target_weekly_deficit_kcal,
        projected_weekly_change_kg=computed.projected_weekly_change_kg,
        macros={
            "protein_g": computed.macros.protein_g,
            "carb_g": computed.macros.carb_g,
            "fat_g": computed.macros.fat_g,
            "fiber_g": computed.macros.fiber_g,
        },
        warnings=computed.warnings,
    )


@router.get("")
async def list_goals(ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    rows = await ctx.db.select(
        "goals",
        {
            "select": "*",
            "user_id": eq(ctx.user_id),
            "order": "effective_from.desc",
            "limit": 50,
        },
    )
    return {"goals": rows, "active": ctx.goal, "is_provisional": ctx.goal_is_provisional}


@router.post("/preview", response_model=GoalPreviewOut)
async def preview_goal(
    payload: GoalPreviewRequest, ctx: UserContext = Depends(get_context)
) -> GoalPreviewOut:
    """Compute targets without persisting — drives the live onboarding preview."""
    weight, height, age, sex, activity = await _resolve_inputs(ctx, payload)
    computed = compute_goal(
        weight_kg=weight,
        height_cm=height,
        age_years=age,
        sex=sex,
        activity_level=activity,
        weekly_change_kg=payload.weekly_change_kg if payload.weekly_change_kg is not None else -0.5,
        maintenance_override=payload.maintenance_override,
    )
    return _to_preview(computed)


@router.post("")
async def create_goal(
    payload: GoalCreateRequest, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    """Create/replace the goal effective from a date (defaults to today)."""
    weight, height, age, sex, activity = await _resolve_inputs(ctx, payload)
    computed = compute_goal(
        weight_kg=weight,
        height_cm=height,
        age_years=age,
        sex=sex,
        activity_level=activity,
        weekly_change_kg=payload.weekly_change_kg if payload.weekly_change_kg is not None else -0.5,
        maintenance_override=payload.maintenance_override or payload.maintenance_calories,
    )

    effective_from = (payload.effective_from or ctx.today).isoformat()
    row = {
        "user_id": ctx.user_id,
        "daily_calorie_target": payload.daily_calorie_target or computed.daily_calorie_target,
        "maintenance_calories": payload.maintenance_calories or computed.maintenance_calories,
        "protein_target_g": payload.protein_target_g
        if payload.protein_target_g is not None
        else computed.macros.protein_g,
        "carb_target_g": payload.carb_target_g
        if payload.carb_target_g is not None
        else computed.macros.carb_g,
        "fat_target_g": payload.fat_target_g
        if payload.fat_target_g is not None
        else computed.macros.fat_g,
        "fiber_target_g": payload.fiber_target_g
        if payload.fiber_target_g is not None
        else computed.macros.fiber_g,
        "target_weekly_deficit_kcal": computed.target_weekly_deficit_kcal,
        "effective_from": effective_from,
    }

    # If the caller overrode the calorie target, keep the stored weekly deficit
    # consistent with what they actually chose.
    if payload.daily_calorie_target:
        row["target_weekly_deficit_kcal"] = int(
            round((row["daily_calorie_target"] - row["maintenance_calories"]) * 7)
        )

    saved = await ctx.db.upsert("goals", row, on_conflict="user_id,effective_from")
    return {
        "goal": saved[0] if saved else row,
        "computation": _to_preview(computed).model_dump(),
    }
