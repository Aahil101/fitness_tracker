"""Profile + onboarding."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from ..config import settings
from ..db import eq
from ..deps import UserContext, get_context
from ..schemas import OnboardingRequest, ProfileUpdate
from ..services import aggregate
from ..services.energy import age_from_birth_date, compute_goal

router = APIRouter(prefix="/api/me", tags=["profile"])


def _integration_status() -> dict[str, bool]:
    return {
        "supabase": settings.supabase_configured,
        "gemini": settings.gemini_configured,
        "usda": bool(settings.usda_api_key),
        "redis": settings.redis_configured,
    }


@router.get("")
async def get_me(ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    weight = await ctx.current_weight_kg()
    profile = dict(ctx.profile)
    profile.setdefault("email", ctx.user.email)
    return {
        "user": {"id": ctx.user_id, "email": ctx.user.email},
        "profile": profile,
        "goal": ctx.goal,
        "goal_is_provisional": ctx.goal_is_provisional,
        "current_weight_kg": weight,
        "today": ctx.today.isoformat(),
        "timezone": str(ctx.tz),
        "needs_onboarding": not bool(ctx.profile.get("onboarded_at")),
        "integrations": _integration_status(),
    }


@router.patch("")
async def update_me(
    payload: ProfileUpdate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    patch = payload.model_dump(mode="json", exclude_none=True)
    if not patch:
        return {"profile": ctx.profile}
    updated = await ctx.db.update_one("profiles", patch, {"id": eq(ctx.user_id)})
    return {"profile": updated}


@router.post("/onboarding")
async def complete_onboarding(
    payload: OnboardingRequest, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    """One round trip: profile fields, first weigh-in, and the initial goal."""
    profile_patch = payload.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"current_weight_kg", "weekly_change_kg", "maintenance_override"},
    )
    profile_patch["starting_weight_kg"] = payload.current_weight_kg
    profile_patch["onboarded_at"] = datetime.now(UTC).isoformat()

    profile = await ctx.db.update_one("profiles", profile_patch, {"id": eq(ctx.user_id)})
    tz = aggregate.resolve_tz(profile.get("timezone"))
    today = aggregate.today_in_tz(tz)

    await ctx.db.upsert(
        "weight_logs",
        {
            "user_id": ctx.user_id,
            "logged_at": today.isoformat(),
            "weight_kg": payload.current_weight_kg,
        },
        on_conflict="user_id,logged_at",
    )

    computed = compute_goal(
        weight_kg=payload.current_weight_kg,
        height_cm=float(profile.get("height_cm") or 170),
        age_years=age_from_birth_date(aggregate.parse_day(profile.get("birth_date")), today),
        sex=profile.get("sex"),
        activity_level=profile.get("activity_level"),
        weekly_change_kg=payload.weekly_change_kg,
        maintenance_override=payload.maintenance_override,
    )

    goal_rows = await ctx.db.upsert(
        "goals",
        {
            "user_id": ctx.user_id,
            "daily_calorie_target": computed.daily_calorie_target,
            "maintenance_calories": computed.maintenance_calories,
            "protein_target_g": computed.macros.protein_g,
            "carb_target_g": computed.macros.carb_g,
            "fat_target_g": computed.macros.fat_g,
            "fiber_target_g": computed.macros.fiber_g,
            "target_weekly_deficit_kcal": computed.target_weekly_deficit_kcal,
            "effective_from": today.isoformat(),
        },
        on_conflict="user_id,effective_from",
    )

    return {
        "profile": profile,
        "goal": goal_rows[0] if goal_rows else None,
        "computation": {
            "bmr": computed.bmr,
            "maintenance_calories": computed.maintenance_calories,
            "daily_calorie_target": computed.daily_calorie_target,
            "projected_weekly_change_kg": computed.projected_weekly_change_kg,
            "warnings": computed.warnings,
        },
    }
