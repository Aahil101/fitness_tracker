"""Request/response models. Pydantic v2."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Sex = Literal["male", "female", "other"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active"]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]
FoodSource = Literal["manual", "ai_estimated", "ai_confirmed"]
Intensity = Literal["light", "moderate", "vigorous"]
UnitPreference = Literal["metric", "imperial"]
InsightKind = Literal["daily", "weekly", "monthly"]
ChatRole = Literal["user", "assistant", "system"]


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
class ProfileUpdate(ApiModel):
    full_name: str | None = Field(default=None, max_length=120)
    sex: Sex | None = None
    birth_date: date | None = None
    starting_weight_kg: float | None = Field(default=None, gt=20, lt=400)
    goal_weight_kg: float | None = Field(default=None, gt=20, lt=400)
    height_cm: float | None = Field(default=None, gt=90, lt=260)
    activity_level: ActivityLevel | None = None
    unit_preference: UnitPreference | None = None
    timezone: str | None = Field(default=None, max_length=64)


class OnboardingRequest(ProfileUpdate):
    """Profile + goal in a single call so onboarding is one round trip."""

    current_weight_kg: float = Field(gt=20, lt=400)
    weekly_change_kg: float = Field(default=-0.5, ge=-1.5, le=1.5)
    maintenance_override: int | None = Field(default=None, ge=800, le=6000)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
class GoalPreviewRequest(ApiModel):
    weight_kg: float | None = Field(default=None, gt=20, lt=400)
    height_cm: float | None = Field(default=None, gt=90, lt=260)
    age_years: int | None = Field(default=None, ge=13, le=100)
    sex: Sex | None = None
    activity_level: ActivityLevel | None = None
    weekly_change_kg: float | None = Field(default=None, ge=-1.5, le=1.5)
    maintenance_override: int | None = Field(default=None, ge=800, le=6000)


class GoalCreateRequest(GoalPreviewRequest):
    """Any explicitly supplied field overrides the computed value."""

    daily_calorie_target: int | None = Field(default=None, ge=800, le=8000)
    maintenance_calories: int | None = Field(default=None, ge=800, le=8000)
    protein_target_g: float | None = Field(default=None, ge=0, le=500)
    carb_target_g: float | None = Field(default=None, ge=0, le=1200)
    fat_target_g: float | None = Field(default=None, ge=0, le=400)
    fiber_target_g: float | None = Field(default=None, ge=0, le=200)
    effective_from: date | None = None


class MacroTargetsOut(ApiModel):
    protein_g: float
    carb_g: float
    fat_g: float
    fiber_g: float


class GoalPreviewOut(ApiModel):
    maintenance_calories: int
    daily_calorie_target: int
    bmr: int
    target_weekly_deficit_kcal: int
    projected_weekly_change_kg: float
    macros: MacroTargetsOut
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Food
# ---------------------------------------------------------------------------
class FoodLogCreate(ApiModel):
    food_name: str = Field(min_length=1, max_length=200)
    portion_g: float = Field(gt=0, le=5000)
    calories: float = Field(ge=0, le=20000)
    protein_g: float | None = Field(default=None, ge=0, le=2000)
    carbs_g: float | None = Field(default=None, ge=0, le=2000)
    fat_g: float | None = Field(default=None, ge=0, le=2000)
    fiber_g: float | None = Field(default=None, ge=0, le=500)
    meal_type: MealType | None = None
    food_item_id: str | None = None
    fdc_id: str | None = None
    source: FoodSource = "manual"
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    image_url: str | None = None
    logged_at: datetime | None = None


class FoodLogUpdate(ApiModel):
    food_name: str | None = Field(default=None, min_length=1, max_length=200)
    portion_g: float | None = Field(default=None, gt=0, le=5000)
    calories: float | None = Field(default=None, ge=0, le=20000)
    protein_g: float | None = Field(default=None, ge=0, le=2000)
    carbs_g: float | None = Field(default=None, ge=0, le=2000)
    fat_g: float | None = Field(default=None, ge=0, le=2000)
    fiber_g: float | None = Field(default=None, ge=0, le=500)
    meal_type: MealType | None = None
    source: FoodSource | None = None
    logged_at: datetime | None = None


class FoodSearchItem(ApiModel):
    fdc_id: str | None = None
    food_item_id: str | None = None
    name: str
    brand: str | None = None
    calories_per_100g: float | None = None
    protein_per_100g: float | None = None
    carbs_per_100g: float | None = None
    fat_per_100g: float | None = None
    fiber_per_100g: float | None = None
    serving_size_g: float | None = None
    source: str = "usda"


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------
class WorkoutCreate(ApiModel):
    activity_type: str = Field(min_length=1, max_length=80)
    duration_min: int = Field(gt=0, le=1440)
    calories_burned: float | None = Field(default=None, ge=0, le=10000)
    intensity: Intensity | None = "moderate"
    notes: str | None = Field(default=None, max_length=500)
    logged_at: datetime | None = None


class WorkoutUpdate(ApiModel):
    activity_type: str | None = Field(default=None, min_length=1, max_length=80)
    duration_min: int | None = Field(default=None, gt=0, le=1440)
    calories_burned: float | None = Field(default=None, ge=0, le=10000)
    intensity: Intensity | None = None
    notes: str | None = Field(default=None, max_length=500)
    logged_at: datetime | None = None


class WorkoutEstimateRequest(ApiModel):
    activity_type: str
    duration_min: int = Field(gt=0, le=1440)
    intensity: Intensity | None = "moderate"
    weight_kg: float | None = Field(default=None, gt=20, lt=400)


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------
class WeightLogCreate(ApiModel):
    weight_kg: float = Field(gt=20, lt=400)
    logged_at: date | None = None
    note: str | None = Field(default=None, max_length=300)

    @field_validator("weight_kg")
    @classmethod
    def _round(cls, v: float) -> float:
        return round(v, 2)


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
class RecognisedFood(ApiModel):
    food_name: str
    portion_g: float
    confidence: float = Field(ge=0, le=1)
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    fdc_id: str | None = None
    food_item_id: str | None = None
    matched_name: str | None = None
    resolution: str = "unresolved"  # cache | usda | estimated | unresolved
    notes: str | None = None


class FoodPhotoDraft(ApiModel):
    items: list[RecognisedFood]
    image_url: str | None = None
    model: str | None = None
    meal_type: MealType | None = None
    total_calories: float = 0
    warnings: list[str] = Field(default_factory=list)


class InsightRequest(ApiModel):
    kind: InsightKind = "daily"
    refresh: bool = False


class InsightOut(ApiModel):
    kind: InsightKind
    period_start: date
    period_end: date
    headline: str
    body: str
    highlights: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None
    generated: bool = True
    cached: bool = False


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
class ChatSessionCreate(ApiModel):
    title: str | None = Field(default=None, max_length=120)


class ChatMessageCreate(ApiModel):
    content: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatMessageOut(ApiModel):
    id: str
    session_id: str
    role: ChatRole
    content: str
    created_at: datetime | None = None
    model: str | None = None


class ChatReply(ApiModel):
    session_id: str
    session_title: str
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    context_used: dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
