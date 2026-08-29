"""Food search + food_logs CRUD."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..db import SupabaseREST, build_params, eq
from ..deps import UserContext, fetch_food_logs, get_context
from ..errors import AppError
from ..schemas import FoodLogCreate, FoodLogUpdate, FoodSearchItem
from ..services import aggregate, cofid, food_facts, usda

router = APIRouter(prefix="/api/food", tags=["food"])

FOOD_ITEM_FIELDS = (
    "fdc_id",
    "name",
    "brand",
    "calories_per_100g",
    "protein_per_100g",
    "carbs_per_100g",
    "fat_per_100g",
    "fiber_per_100g",
    "serving_size_g",
    "data_source",
)


async def ensure_food_item(db: SupabaseREST, item: dict[str, Any]) -> str | None:
    """Persist a USDA item into the shared cache; returns its food_items UUID."""
    fdc_id = item.get("fdc_id")
    if not fdc_id:
        return None

    existing = await db.select_one("food_items", {"select": "id", "fdc_id": eq(fdc_id)})
    if existing:
        return existing["id"]

    row = {k: item.get(k) for k in FOOD_ITEM_FIELDS if item.get(k) is not None}
    row.setdefault("name", item.get("name") or "Unknown food")
    saved = await db.upsert("food_items", row, on_conflict="fdc_id")
    return saved[0]["id"] if saved else None


@router.get("/search", response_model=list[FoodSearchItem])
async def search_food(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: UserContext = Depends(get_context),
) -> list[FoodSearchItem]:
    """Our own tables first, then the cache, then USDA.

    Order matters more here than anywhere else in the app. Search is what a user
    falls back to when AI logging is unavailable — and AI logging *is* regularly
    unavailable, because the free Gemini tier allows twenty calls a day across all
    users. Leaving this path on USDA alone meant the fallback was also the
    inaccurate one: searching "chai" returned packet mixes, which is the failure
    that started the whole rebuild.

    The local tables cost nothing to consult and are the same figures the AI path
    uses, so the two paths now agree.
    """
    results: list[FoodSearchItem] = []
    seen_fdc: set[str] = set()
    seen_names: set[str] = set()

    def remember(name: str) -> bool:
        """False when a food by this name has already been added."""
        key = name.strip().lower()
        if not key or key in seen_names:
            return False
        seen_names.add(key)
        return True

    # 1. The curated table: the foods people log most, with checked figures.
    curated = food_facts.lookup(q)
    if curated and remember(curated.name):
        results.append(
            FoodSearchItem(
                fdc_id=None,
                food_item_id=None,
                name=curated.name,
                brand=None,
                calories_per_100g=curated.kcal,
                protein_per_100g=curated.protein_g,
                carbs_per_100g=curated.carbs_g,
                fat_per_100g=curated.fat_g,
                fiber_per_100g=None,
                serving_size_g=curated.serving_g,
                source="curated",
            )
        )

    # 2. The bundled composition table.
    for food in cofid.search(q, limit=min(limit, 8)):
        if not remember(food.name):
            continue
        results.append(
            FoodSearchItem(
                fdc_id=None,
                food_item_id=None,
                name=food.name,
                brand=None,
                calories_per_100g=food.kcal,
                protein_per_100g=food.protein_g,
                carbs_per_100g=food.carbs_g,
                fat_per_100g=food.fat_g,
                fiber_per_100g=food.fibre_g,
                serving_size_g=None,
                source="cofid",
            )
        )

    cached_rows = await ctx.db.select(
        "food_items",
        {
            "select": "*",
            "name": f"ilike.*{q}*",
            "order": "name.asc",
            "limit": min(limit, 10),
        },
    )
    for row in cached_rows:
        if row.get("calories_per_100g") is None:
            continue
        if not remember(str(row.get("name") or "")):
            continue
        if row.get("fdc_id"):
            seen_fdc.add(str(row["fdc_id"]))
        results.append(
            FoodSearchItem(
                fdc_id=row.get("fdc_id"),
                food_item_id=row.get("id"),
                name=row.get("name") or "",
                brand=row.get("brand"),
                calories_per_100g=row.get("calories_per_100g"),
                protein_per_100g=row.get("protein_per_100g"),
                carbs_per_100g=row.get("carbs_per_100g"),
                fat_per_100g=row.get("fat_per_100g"),
                fiber_per_100g=row.get("fiber_per_100g"),
                serving_size_g=row.get("serving_size_g"),
                source="cache",
            )
        )

    # 4. USDA last, and only if the local sources left room. Skipping the call
    #    entirely when they answered keeps search instant and offline for the
    #    foods people actually search for.
    if len(results) < limit:
        for item in await usda.search_foods(q, page_size=limit):
            if item["fdc_id"] in seen_fdc or not remember(item.get("name") or ""):
                continue
            results.append(FoodSearchItem(**item, source="usda"))

    return results[:limit]


@router.get("/logs")
async def list_food_logs(
    day: date | None = Query(default=None, alias="date"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    start = date_from or day or ctx.today
    end = date_to or day or ctx.today
    if end < start:
        start, end = end, start

    rows = await fetch_food_logs(ctx, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "logs": rows,
        "totals": aggregate.totals(rows),
    }


@router.post("/logs", status_code=201)
async def create_food_log(
    payload: FoodLogCreate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    food_item_id = payload.food_item_id

    # A caller can pass an fdc_id instead of a resolved item; back-fill the cache.
    if not food_item_id and payload.fdc_id:
        item = await usda.get_food(payload.fdc_id) or {"fdc_id": payload.fdc_id, "name": payload.food_name}
        food_item_id = await ensure_food_item(ctx.db, item)

    row = payload.model_dump(mode="json", exclude_none=True, exclude={"fdc_id", "food_item_id"})
    row["user_id"] = ctx.user_id
    if food_item_id:
        row["food_item_id"] = food_item_id
    row.setdefault("logged_at", datetime.now(UTC).isoformat())
    row.setdefault("meal_type", _meal_type_for_now(ctx))

    created = await ctx.db.insert_one("food_logs", row)
    return {"log": created}


@router.post("/logs/batch", status_code=201)
async def create_food_logs_batch(
    payload: list[FoodLogCreate], ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    """Save several entries at once — used when confirming an AI photo draft."""
    if not payload:
        return {"logs": []}
    if len(payload) > 20:
        raise AppError("Too many entries in one batch (max 20).")

    rows: list[dict[str, Any]] = []
    default_meal = _meal_type_for_now(ctx)
    now_iso = datetime.now(UTC).isoformat()

    for entry in payload:
        food_item_id = entry.food_item_id
        if not food_item_id and entry.fdc_id:
            item = await usda.get_food(entry.fdc_id) or {
                "fdc_id": entry.fdc_id,
                "name": entry.food_name,
            }
            food_item_id = await ensure_food_item(ctx.db, item)

        row = entry.model_dump(
            mode="json", exclude_none=True, exclude={"fdc_id", "food_item_id"}
        )
        row["user_id"] = ctx.user_id
        if food_item_id:
            row["food_item_id"] = food_item_id
        row.setdefault("logged_at", now_iso)
        row.setdefault("meal_type", default_meal)
        rows.append(row)

    # PostgREST rejects a bulk insert whose objects have differing key sets with
    # PGRST102 "All object keys must match". exclude_none drops keys per row and
    # food_item_id is only set when known, so a mixed batch produced mismatched
    # shapes — a USDA item carrying fibre and a food_item_id next to an AI
    # estimate carrying neither. Padding to the union of keys keeps every object
    # identical; the added values are null, which is what the columns already
    # hold when omitted.
    if len(rows) > 1:
        columns = sorted(set().union(*(row.keys() for row in rows)))
        rows = [{column: row.get(column) for column in columns} for row in rows]

    created = await ctx.db.insert("food_logs", rows)
    return {"logs": created, "count": len(created)}


@router.patch("/logs/{log_id}")
async def update_food_log(
    log_id: str, payload: FoodLogUpdate, ctx: UserContext = Depends(get_context)
) -> dict[str, Any]:
    patch = payload.model_dump(mode="json", exclude_none=True)
    if not patch:
        row = await ctx.db.select_one(
            "food_logs", {"select": "*", "id": eq(log_id), "user_id": eq(ctx.user_id)}
        )
        return {"log": row}
    updated = await ctx.db.update_one(
        "food_logs", patch, {"id": eq(log_id), "user_id": eq(ctx.user_id)}
    )
    return {"log": updated}


@router.delete("/logs/{log_id}")
async def delete_food_log(log_id: str, ctx: UserContext = Depends(get_context)) -> dict[str, Any]:
    deleted = await ctx.db.delete_one(
        "food_logs", {"id": eq(log_id), "user_id": eq(ctx.user_id)}
    )
    return {"deleted": deleted}


@router.get("/recent")
async def recent_foods(
    limit: int = Query(default=12, ge=1, le=50),
    ctx: UserContext = Depends(get_context),
) -> dict[str, Any]:
    """Distinct recently logged foods — the fastest path to re-logging a meal."""
    since = (ctx.today - timedelta(days=45)).isoformat()
    rows = await ctx.db.select(
        "food_logs",
        build_params(
            {
                "select": "food_name,portion_g,calories,protein_g,carbs_g,fat_g,fiber_g,food_item_id,meal_type",
                "user_id": eq(ctx.user_id),
                "order": "logged_at.desc",
                "limit": 300,
            },
            ("logged_at", f"gte.{since}T00:00:00Z"),
        ),
    )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = (row.get("food_name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
        if len(unique) >= limit:
            break
    return {"foods": unique}


def _meal_type_for_now(ctx: UserContext) -> str:
    """Guess the meal from the local clock so quick-add needs no extra tap."""
    hour = datetime.now(ctx.tz).hour
    if hour < 11:
        return "breakfast"
    if hour < 16:
        return "lunch"
    if hour < 22:
        return "dinner"
    return "snack"
