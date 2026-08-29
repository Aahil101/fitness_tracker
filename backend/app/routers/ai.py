"""Generative AI endpoints: photo food recognition and generated summaries."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ..cache import check_rate_limit
from ..config import settings
from ..db import eq
from ..deps import UserContext, fetch_food_logs, fetch_weight_logs, fetch_workouts, get_context
from ..errors import AppError, RateLimitError, UpstreamError
from ..schemas import (
    FoodPhotoDraft,
    FoodTextRequest,
    InsightOut,
    InsightRequest,
    RecognisedFood,
)
from ..services import aggregate, cofid, gemini, insights, resolve, restaurant, text_ai, usda
from ..services.forecast import forecast as run_forecast
from .food import ensure_food_item

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
# How far a database row's energy density may sit from the model's estimate
# before the row is treated as a different food. 1.75x is wide enough to absorb
# ordinary recipe variation and preparation differences, and narrow enough to
# catch a dry mix standing in for a cooked dish.
DENSITY_DISAGREEMENT = 1.75

EXTENSION_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}


@router.get("/status")
async def ai_status() -> dict[str, Any]:
    models = await gemini.list_models() if settings.gemini_configured else []
    return {
        "gemini_configured": settings.gemini_configured,
        "model": settings.gemini_model,
        "model_available": (not models) or settings.gemini_model in models,
        "available_models": [m for m in models if "flash" in m or "pro" in m][:25],
        "usda_key_is_demo": settings.usda_api_key.upper() == "DEMO_KEY",
        "redis_configured": settings.redis_configured,
    }


async def _resolve_branded(
    ctx: UserContext, *, description: str, grams: float
) -> resolve.Resolved | None:
    """A named chain item, priced from what the chain publishes.

    Cached in ``food_items`` because a grounded lookup costs one of the twenty
    Gemini requests the free tier allows per day, shared with ordinary meal
    parsing. Uncached, a few pizzas would exhaust the day.
    """
    chain = restaurant.detect_chain(description)
    if not chain:
        return None

    count = restaurant.serving_count(description)

    def build(item: dict[str, Any], confidence: float, note: str) -> resolve.Resolved:
        # Menus sell units, so the portion is the published serving times however
        # many were ordered. The model's gram estimate is discarded here on
        # purpose: asked about a Domino's Margherita it guessed 500 g, and scaling
        # the published 688 kcal to that gave 1110 for one pizza.
        serving = aggregate.num(item.get("serving_g"), 0.0)
        portion = serving * count if serving > 0 else grams
        scaled = usda.scale_to_portion(item, portion)
        return resolve.Resolved(
            name=display_or(item),
            grams=round(portion, 1),
            calories=aggregate.num(scaled.get("calories"), 0.0),
            protein_g=aggregate.num(scaled.get("protein_g"), 0.0),
            carbs_g=aggregate.num(scaled.get("carbs_g"), 0.0),
            fat_g=aggregate.num(scaled.get("fat_g"), 0.0),
            fiber_g=scaled.get("fiber_g"),
            source="brand",
            matched_name=item.get("name"),
            confidence=confidence,
            notes=[note] if note else [],
        )

    def display_or(item: dict[str, Any]) -> str:
        return str(item.get("name") or description)[:200]

    # Checked figures.
    known = restaurant.lookup_known(description, chain)
    if known:
        return build(known.as_item(), known.confidence, known.source)

    # Previously looked up, by anyone.
    cached = await ctx.db.select_one(
        "food_items",
        {
            "select": "*",
            "name": f"ilike.{chain}%",
            "calories_per_100g": "not.is.null",
            "order": "created_at.desc",
        },
    )
    if cached and restaurant.detect_chain(str(cached.get("name") or "")) == chain:
        tokens = {w for w in re.findall(r"[a-z]+", description.lower()) if len(w) > 2}
        cached_tokens = {w for w in re.findall(r"[a-z]+", str(cached.get("name") or "").lower())}
        # Only reuse a cached row that is the same menu item, not merely the same
        # chain — otherwise every Domino's order would be priced as the last one.
        if tokens and len(tokens & cached_tokens) >= max(1, len(tokens) - 2):
            return build(cached, 0.8, f"{chain} published figures (cached)")

    published = await restaurant.lookup_published(description, chain)
    if published is None:
        return None

    item = published.as_item()
    try:
        await ensure_food_item(ctx.db, {**item, "fdc_id": None})
    except Exception:  # caching is best effort
        log.info("Could not cache branded lookup for %r", description)
    return build(item, published.confidence, published.source)


async def _resolve_recognised_item(
    ctx: UserContext, raw: dict[str, Any]
) -> RecognisedFood:
    """Price one food, in descending order of how much the source can be trusted.

    curated table -> cached row -> USDA -> the model's own estimate, with every
    database row screened for relevance and density agreement, and a plausibility
    floor applied to whatever survives.

    The order matters and so does the screening. Previously USDA won by default
    and was only rejected if it disagreed with the model, which cannot catch the
    two of them being wrong together — the failure that logged milky sweet tea as
    1 kcal.
    """
    name = str(raw.get("food_name") or "Unknown food").strip()[:200]
    query = str(raw.get("usda_query") or name).strip()[:120]
    grams = max(1.0, min(5000.0, aggregate.num(raw.get("estimated_grams"), 100.0)))
    confidence = max(0.0, min(1.0, aggregate.num(raw.get("confidence"), 0.5)))
    preparation = raw.get("preparation")

    display_name = name
    if preparation:
        prep = str(preparation).strip().lower()
        if prep and prep not in display_name.lower():
            display_name = f"{name} ({prep})"

    # The floor is judged on everything we know the food is, not just its name:
    # the search phrase and the preparation both carry ingredients the name may
    # have dropped.
    description = " ".join(filter(None, [name, query, str(preparation or "")]))

    model_per_100g = aggregate.num(raw.get("fallback_calories_per_100g"), 0.0)

    # -- 0. named restaurant items. -------------------------------------------
    # A chain's own published figure is the truth for its own product, and no
    # composition table can reproduce it: a generic pizza entry and a Domino's
    # Peppy Paneer differ by hundreds of calories. Checked figures first, then a
    # cached lookup, then a grounded search — see services/restaurant.py.
    decided = await _resolve_branded(ctx, description=f"{name} {query}", grams=grams)

    # -- 1. our own table. A hit here is final. --------------------------------
    if decided is None:
        decided = resolve.from_curated(display_name, query, grams)

    # -- 2. a cached row, then USDA. Both are screened the same way. -----------
    if decided is None:
        item: dict[str, Any] | None = None
        resolution = "unresolved"
        food_item_id: str | None = None

        cached = await ctx.db.select_one(
            "food_items",
            {
                "select": "*",
                "name": f"ilike.{query}*",
                "calories_per_100g": "not.is.null",
                "order": "created_at.asc",
            },
        )
        if cached and usda.is_relevant(query, str(cached.get("name") or "")):
            item, resolution, food_item_id = cached, "cache", cached.get("id")

        # The bundled composition table. Ahead of USDA because it is the right
        # kind of source for what people describe: it lists foods as cooked and
        # eaten, where FDC's searchable bulk is packets. No network call either,
        # so this costs nothing and cannot fail.
        if item is None:
            local = cofid.best_match(query)
            if local:
                item, resolution = local.as_item(), "cofid"

        # USDA last, for anything the table above does not carry.
        if item is None:
            match = await usda.best_match(query)
            if match:
                item, resolution = match, "usda"
                food_item_id = await ensure_food_item(ctx.db, match)

        # A row is only better than the estimate if it is the same food. Comparing
        # densities catches cooked-versus-dry without enumerating the dishes it
        # happens to: idli against Idli Mix, cooked rice against raw.
        if item is not None:
            row_per_100g = aggregate.num(item.get("calories_per_100g"), 0.0)
            if not resolve.database_agrees(row_per_100g, model_per_100g):
                log.info(
                    "Rejecting %s match %r for %r: %.0f vs %.0f kcal/100g",
                    resolution, item.get("name"), query, row_per_100g, model_per_100g,
                )
                item, food_item_id = None, None

        if item is not None:
            scaled = usda.scale_to_portion(item, grams)
            decided = resolve.Resolved(
                name=display_name,
                grams=grams,
                calories=aggregate.num(scaled.get("calories"), 0.0),
                protein_g=aggregate.num(scaled.get("protein_g"), 0.0),
                carbs_g=aggregate.num(scaled.get("carbs_g"), 0.0),
                fat_g=aggregate.num(scaled.get("fat_g"), 0.0),
                fiber_g=scaled.get("fiber_g"),
                source=resolution,  # type: ignore[arg-type]
                matched_name=item.get("name"),
                confidence=confidence,
                food_item_id=food_item_id,
            )

    # -- 3. the model's estimate. Imprecise, but never absurd. -----------------
    if decided is None and model_per_100g > 0:
        factor = grams / 100
        decided = resolve.Resolved(
            name=display_name,
            grams=grams,
            calories=round(model_per_100g * factor, 1),
            protein_g=round(aggregate.num(raw.get("fallback_protein_per_100g"), 0.0) * factor, 1),
            carbs_g=round(aggregate.num(raw.get("fallback_carbs_per_100g"), 0.0) * factor, 1),
            fat_g=round(aggregate.num(raw.get("fallback_fat_per_100g"), 0.0) * factor, 1),
            fiber_g=None,
            source="estimated",
            matched_name=None,
            confidence=confidence,
        )

    if decided is None:
        return RecognisedFood(
            food_name=display_name[:200],
            portion_g=round(grams, 1),
            confidence=round(confidence, 2),
            resolution="unresolved",
            notes=_resolution_note("unresolved"),
        )

    # -- 4. the floor, on whatever came out of the above. ---------------------
    decided = resolve.apply_floor(decided, description)

    note = _resolution_note(decided.source)
    if decided.notes:
        note = " ".join(filter(None, [*decided.notes, note]))

    return RecognisedFood(
        food_name=display_name[:200],
        portion_g=round(grams, 1),
        confidence=round(decided.confidence, 2),
        calories=decided.calories,
        protein_g=decided.protein_g,
        carbs_g=decided.carbs_g,
        fat_g=decided.fat_g,
        fiber_g=decided.fiber_g,
        fdc_id=None,
        food_item_id=decided.food_item_id,
        matched_name=decided.matched_name,
        resolution=decided.source,
        notes=note,
    )


def _resolution_note(resolution: str) -> str | None:
    """Say where the numbers came from, but only when it changes what to do."""
    if resolution == "brand":
        # The chain's own published figure. Worth saying so: it is more
        # authoritative than anything we could compute, and it is also only as
        # good as the menu, which the user may want to know.
        return None
    if resolution == "cofid":
        return None
    if resolution == "estimated":
        return (
            "Not in the USDA database, so these numbers are the model's estimate — "
            "worth a glance before saving."
        )
    if resolution == "unresolved":
        return "No nutrition match found — enter the calories manually before saving."
    return None


@router.post("/food-photo", response_model=FoodPhotoDraft)
async def food_photo(
    file: UploadFile = File(...),
    hint: str | None = Form(default=None),
    ctx: UserContext = Depends(get_context),
) -> FoodPhotoDraft:
    """Photo -> Gemini -> USDA -> editable draft. Never writes a food_log."""
    limit = await check_rate_limit("vision", ctx.user_id, settings.rate_limit_vision_per_hour)
    if not limit.allowed:
        raise RateLimitError(
            f"Photo analysis limit reached ({limit.limit}/hour). Try again in "
            f"{max(1, limit.reset_in_s // 60)} minutes.",
            retry_after=limit.reset_in_s,
        )

    content_type = (file.content_type or "").lower().split(";")[0]
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError(f"Unsupported image type '{content_type or 'unknown'}'. Use JPEG, PNG or WebP.")

    image_bytes = await file.read()
    if not image_bytes:
        raise AppError("The uploaded file was empty.")
    if len(image_bytes) > settings.max_upload_bytes:
        raise AppError(
            f"Image is too large ({len(image_bytes) // 1024} KB). "
            f"Keep it under {settings.max_upload_bytes // 1024 // 1024} MB."
        )

    parsed = await gemini.recognise_food(image_bytes, content_type, hint=hint)

    raw_items = parsed.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []

    warnings: list[str] = []
    if note := parsed.get("notes"):
        warnings.append(str(note)[:300])
    if not raw_items:
        warnings.append("No food was detected in this photo. Try a closer, brighter shot.")

    items = [await _resolve_recognised_item(ctx, raw) for raw in raw_items[:8] if isinstance(raw, dict)]

    if any(i.resolution == "unresolved" for i in items):
        warnings.append("Some items could not be matched to nutrition data — check them before saving.")
    if items and all(i.confidence < 0.5 for i in items):
        warnings.append("Low confidence overall: verify the portions.")

    # Best effort: keep the photo alongside the log. Failure here must not lose
    # the analysis the user already waited for.
    image_path = None
    extension = EXTENSION_BY_TYPE.get(content_type, "jpg")
    try:
        stored = await ctx.db.upload_image(
            f"{ctx.user_id}/{date.today().isoformat()}-{uuid.uuid4().hex[:8]}.{extension}",
            image_bytes,
            content_type,
        )
        if stored:
            image_path = await ctx.db.signed_url(stored, expires_in=60 * 60 * 24 * 7) or stored
    except Exception as exc:  # noqa: BLE001 - storage is optional
        log.warning("Photo upload skipped: %s", exc)

    meal_type = str(parsed.get("meal_type") or "").lower()
    if meal_type not in ("breakfast", "lunch", "dinner", "snack"):
        meal_type = None  # type: ignore[assignment]

    return FoodPhotoDraft(
        items=items,
        image_url=image_path,
        model=settings.gemini_model,
        meal_type=meal_type,
        total_calories=round(sum(i.calories or 0 for i in items), 1),
        warnings=warnings,
    )


@router.post("/food-text", response_model=FoodPhotoDraft)
async def food_text(
    payload: FoodTextRequest,
    ctx: UserContext = Depends(get_context),
) -> FoodPhotoDraft:
    """Free text -> Gemini -> USDA -> editable draft. Never writes a food_log.

    Shares :func:`_resolve_recognised_item` with the photo path, so a described
    meal and a photographed one get their nutrition from the same place: the
    model only names foods and estimates grams.
    """
    limit = await check_rate_limit("vision", ctx.user_id, settings.rate_limit_vision_per_hour)
    if not limit.allowed:
        raise RateLimitError(
            f"AI logging limit reached ({limit.limit}/hour). Try again in "
            f"{max(1, limit.reset_in_s // 60)} minutes.",
            retry_after=limit.reset_in_s,
        )

    parsed, provider = await text_ai.parse_meal_text(payload.text)

    raw_items = parsed.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []

    warnings: list[str] = []
    if note := parsed.get("notes"):
        warnings.append(str(note)[:300])
    if not raw_items:
        warnings.append(
            "No food was recognised in that description. Try naming the food and "
            "the amount, for example 'half cup of tea with 1 spoon of sugar'."
        )

    items = [await _resolve_recognised_item(ctx, raw) for raw in raw_items[:8] if isinstance(raw, dict)]

    if any(i.resolution == "unresolved" for i in items):
        warnings.append("Some items could not be matched to nutrition data — check them before saving.")

    # Check the parts against the whole. The model estimates the meal's energy
    # independently of its own item list, which makes it the only figure able to
    # notice that the breakdown dropped something — a described boiled egg that
    # never became an item, for instance. Every per-item gate can pass while the
    # list as a whole is still incomplete.
    _, shortfall = resolve.reconcile_total(
        [
            resolve.Resolved(
                name=i.food_name,
                grams=i.portion_g,
                calories=aggregate.num(i.calories, 0.0),
                protein_g=aggregate.num(i.protein_g, 0.0),
                carbs_g=aggregate.num(i.carbs_g, 0.0),
                fat_g=aggregate.num(i.fat_g, 0.0),
                fiber_g=i.fiber_g,
                source=i.resolution,  # type: ignore[arg-type]
                matched_name=i.matched_name,
                confidence=i.confidence,
            )
            for i in items
        ],
        aggregate.num(parsed.get("total_calories_estimate"), 0.0),
    )
    if shortfall:
        warnings.append(shortfall)

    meal_type = str(parsed.get("meal_type") or "").lower()
    if meal_type not in ("breakfast", "lunch", "dinner", "snack"):
        meal_type = None  # type: ignore[assignment]

    return FoodPhotoDraft(
        items=items,
        image_url=None,
        model=provider,
        meal_type=meal_type,
        total_calories=round(sum(i.calories or 0 for i in items), 1),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
async def _build_metrics(ctx: UserContext, kind: str) -> tuple[dict[str, Any], date, date]:
    window = {"daily": 1, "weekly": 7, "monthly": 30}.get(kind, 7)
    start = ctx.today - timedelta(days=window - 1)

    food_rows = await fetch_food_logs(ctx, start, ctx.today)
    workout_rows = await fetch_workouts(ctx, start, ctx.today)
    weight_rows = await fetch_weight_logs(ctx, max(30, window + 14))

    target = ctx.daily_calorie_target
    maintenance = ctx.maintenance_calories
    totals = aggregate.totals(food_rows)
    days = aggregate.daily_series(
        food_rows=food_rows, workout_rows=workout_rows, tz=ctx.tz, start=start, end=ctx.today
    )
    logged_days = [d for d in days if d.logged]
    points = aggregate.weight_points(weight_rows)

    fc = run_forecast(
        days=days,
        maintenance_calories=maintenance,
        window_days=window,
        weight_points=points,
        goal_weight_kg=ctx.goal_weight_kg,
        today=ctx.today,
    )

    metrics: dict[str, Any] = {
        "window_days": window,
        "days_logged": len(logged_days),
        "daily_calorie_target": int(target),
        "maintenance_calories": int(maintenance),
        "protein_target_g": ctx.goal.get("protein_target_g"),
        "entry_count": len(food_rows),
        "workout_sessions": len(workout_rows),
        "workout_minutes": int(aggregate.sum_field(workout_rows, "duration_min")),
        "calories_burned": aggregate.sum_field(workout_rows, "calories_burned"),
        "current_weight_kg": fc.current_weight_kg,
        "goal_weight_kg": ctx.goal_weight_kg,
        "projected_weekly_change_kg": fc.projected_weekly_change_kg,
        "observed_weekly_change_kg": fc.observed_weekly_change_kg,
        "unit_preference": ctx.profile.get("unit_preference") or "metric",
    }

    if kind == "daily":
        metrics.update(
            {
                "calories_consumed": totals["calories"],
                "calories_remaining": round(target - totals["calories"], 1),
                "protein_g": totals["protein_g"],
                "carbs_g": totals["carbs_g"],
                "fat_g": totals["fat_g"],
                "fiber_g": totals["fiber_g"],
                "meals": [
                    {
                        "name": r.get("food_name"),
                        "calories": aggregate.num(r.get("calories")),
                        "meal": r.get("meal_type"),
                    }
                    for r in food_rows[:20]
                ],
            }
        )
    else:
        metrics.update(
            {
                "total_calories": totals["calories"],
                "avg_daily_calories": round(totals["calories"] / len(logged_days), 1)
                if logged_days
                else 0.0,
                "avg_protein_g": round(totals["protein_g"] / len(logged_days), 1)
                if logged_days
                else 0.0,
                "avg_fiber_g": round(totals["fiber_g"] / len(logged_days), 1)
                if logged_days
                else 0.0,
                "avg_daily_net_kcal": fc.avg_daily_net_kcal,
                "best_day": min(
                    (
                        {"date": d.day.isoformat(), "calories": round(d.calories_in)}
                        for d in logged_days
                    ),
                    key=lambda x: abs(x["calories"] - target),
                    default=None,
                ),
                "highest_day": max(
                    (
                        {"date": d.day.isoformat(), "calories": round(d.calories_in)}
                        for d in logged_days
                    ),
                    key=lambda x: x["calories"],
                    default=None,
                ),
            }
        )

    return metrics, start, ctx.today


@router.post("/insight", response_model=InsightOut)
async def insight(
    payload: InsightRequest, ctx: UserContext = Depends(get_context)
) -> InsightOut:
    """Generated recap. Cached per period in ai_insights; `refresh` re-runs it."""
    metrics, start, end = await _build_metrics(ctx, payload.kind)

    if not payload.refresh:
        existing = await ctx.db.select_one(
            "ai_insights",
            {
                "select": "*",
                "user_id": eq(ctx.user_id),
                "kind": eq(payload.kind),
                "period_start": eq(start.isoformat()),
                "order": "created_at.desc",
            },
        )
        if existing:
            return InsightOut(
                kind=payload.kind,
                period_start=start,
                period_end=end,
                headline=existing.get("headline") or "",
                body=existing.get("body") or "",
                highlights=existing.get("highlights") or [],
                metrics=existing.get("metrics") or metrics,
                model=existing.get("model"),
                generated=True,
                cached=True,
            )

    limit = await check_rate_limit("insight", ctx.user_id, settings.rate_limit_insight_per_hour)
    if not limit.allowed:
        raise RateLimitError(
            f"Summary limit reached ({limit.limit}/hour).", retry_after=limit.reset_in_s
        )

    result = await insights.generate_insight(payload.kind, metrics)

    try:
        await ctx.db.upsert(
            "ai_insights",
            {
                "user_id": ctx.user_id,
                "kind": payload.kind,
                "period_start": start.isoformat(),
                "period_end": end.isoformat(),
                "headline": result["headline"],
                "body": result["body"],
                "highlights": result["highlights"],
                "metrics": metrics,
                "model": result.get("model"),
            },
            on_conflict="user_id,kind,period_start",
        )
    except UpstreamError as exc:  # caching is a nicety, not a requirement
        log.warning("Could not cache insight: %s", exc.detail)

    return InsightOut(
        kind=payload.kind,
        period_start=start,
        period_end=end,
        headline=result["headline"],
        body=result["body"],
        highlights=result["highlights"],
        metrics=metrics,
        model=result.get("model"),
        generated=True,
        cached=False,
    )
