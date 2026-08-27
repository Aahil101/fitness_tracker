"""Request-scoped context: the user's DB handle, profile, active goal, timezone."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends

from .db import SupabaseREST, build_params, eq
from .security import CurrentUser, get_current_user
from .services import aggregate
from .services.energy import age_from_birth_date, compute_goal

# Used only when a user has no profile numbers at all, so the dashboard still
# renders something sane instead of dividing by zero.
FALLBACK_MAINTENANCE = 2000
FALLBACK_TARGET = 1800


@dataclass
class UserContext:
    user: CurrentUser
    db: SupabaseREST
    profile: dict[str, Any]
    goal: dict[str, Any]
    tz: ZoneInfo
    today: date
    goal_is_provisional: bool

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def maintenance_calories(self) -> float:
        return float(self.goal.get("maintenance_calories") or FALLBACK_MAINTENANCE)

    @property
    def daily_calorie_target(self) -> float:
        return float(self.goal.get("daily_calorie_target") or FALLBACK_TARGET)

    @property
    def goal_weight_kg(self) -> float | None:
        value = self.profile.get("goal_weight_kg")
        return float(value) if value else None

    async def current_weight_kg(self) -> float | None:
        """Latest weigh-in, falling back to the onboarding starting weight."""
        row = await self.db.select_one(
            "weight_logs",
            {
                "select": "weight_kg,logged_at",
                "user_id": eq(self.user_id),
                "order": "logged_at.desc",
            },
        )
        if row and row.get("weight_kg"):
            return float(row["weight_kg"])
        starting = self.profile.get("starting_weight_kg")
        return float(starting) if starting else None


async def get_db(user: CurrentUser = Depends(get_current_user)) -> SupabaseREST:
    return SupabaseREST(user.access_token)


async def load_profile(db: SupabaseREST, user_id: str) -> dict[str, Any]:
    profile = await db.select_one("profiles", {"select": "*", "id": eq(user_id)})
    if profile:
        return profile
    # The auth trigger normally creates this row; self-heal if it is missing
    # (e.g. the user existed before the trigger was installed).
    created = await db.upsert("profiles", {"id": user_id}, on_conflict="id")
    return created[0] if created else {"id": user_id}


async def load_active_goal(
    db: SupabaseREST, user_id: str, today: date
) -> tuple[dict[str, Any], bool]:
    """Latest goal effective on or before today; otherwise a derived provisional one."""
    goal = await db.select_one(
        "goals",
        {
            "select": "*",
            "user_id": eq(user_id),
            "effective_from": f"lte.{today.isoformat()}",
            "order": "effective_from.desc",
        },
    )
    if goal:
        return goal, False
    return {}, True


def derive_provisional_goal(profile: dict[str, Any], weight_kg: float | None) -> dict[str, Any]:
    """Compute a goal on the fly so the gauge works before onboarding finishes."""
    height = profile.get("height_cm")
    if not (weight_kg and height):
        return {
            "maintenance_calories": FALLBACK_MAINTENANCE,
            "daily_calorie_target": FALLBACK_TARGET,
            "protein_target_g": 120,
            "carb_target_g": 190,
            "fat_target_g": 50,
            "fiber_target_g": 25,
            "target_weekly_deficit_kcal": -1400,
            "provisional": True,
        }

    computed = compute_goal(
        weight_kg=float(weight_kg),
        height_cm=float(height),
        age_years=age_from_birth_date(aggregate.parse_day(profile.get("birth_date"))),
        sex=profile.get("sex"),
        activity_level=profile.get("activity_level"),
        weekly_change_kg=-0.5,
    )
    return {
        "maintenance_calories": computed.maintenance_calories,
        "daily_calorie_target": computed.daily_calorie_target,
        "protein_target_g": computed.macros.protein_g,
        "carb_target_g": computed.macros.carb_g,
        "fat_target_g": computed.macros.fat_g,
        "fiber_target_g": computed.macros.fiber_g,
        "target_weekly_deficit_kcal": computed.target_weekly_deficit_kcal,
        "provisional": True,
    }


async def get_context(
    user: CurrentUser = Depends(get_current_user),
    db: SupabaseREST = Depends(get_db),
) -> UserContext:
    profile = await load_profile(db, user.id)
    tz = aggregate.resolve_tz(profile.get("timezone"))
    today = aggregate.today_in_tz(tz)

    goal, provisional = await load_active_goal(db, user.id, today)
    if provisional:
        weight_row = await db.select_one(
            "weight_logs",
            {"select": "weight_kg", "user_id": eq(user.id), "order": "logged_at.desc"},
        )
        weight = (
            float(weight_row["weight_kg"])
            if weight_row and weight_row.get("weight_kg")
            else (float(profile["starting_weight_kg"]) if profile.get("starting_weight_kg") else None)
        )
        goal = derive_provisional_goal(profile, weight)

    return UserContext(
        user=user,
        db=db,
        profile=profile,
        goal=goal,
        tz=tz,
        today=today,
        goal_is_provisional=provisional,
    )


async def fetch_food_logs(ctx: UserContext, start: date, end: date) -> list[dict[str, Any]]:
    start_iso, end_iso = aggregate.range_bounds_utc(start, end, ctx.tz)
    return await ctx.db.select(
        "food_logs",
        build_params(
            {
                "select": "*",
                "user_id": eq(ctx.user_id),
                "order": "logged_at.desc",
                "limit": 5000,
            },
            ("logged_at", f"gte.{start_iso}"),
            ("logged_at", f"lt.{end_iso}"),
        ),
    )


async def fetch_workouts(ctx: UserContext, start: date, end: date) -> list[dict[str, Any]]:
    start_iso, end_iso = aggregate.range_bounds_utc(start, end, ctx.tz)
    return await ctx.db.select(
        "workouts",
        build_params(
            {
                "select": "*",
                "user_id": eq(ctx.user_id),
                "order": "logged_at.desc",
                "limit": 5000,
            },
            ("logged_at", f"gte.{start_iso}"),
            ("logged_at", f"lt.{end_iso}"),
        ),
    )


async def fetch_weight_logs(ctx: UserContext, days: int = 365) -> list[dict[str, Any]]:
    since = (ctx.today - timedelta(days=days)).isoformat()
    return await ctx.db.select(
        "weight_logs",
        {
            "select": "*",
            "user_id": eq(ctx.user_id),
            "logged_at": f"gte.{since}",
            "order": "logged_at.asc",
            "limit": 2000,
        },
    )
