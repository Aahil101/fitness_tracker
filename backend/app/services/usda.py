"""USDA FoodData Central client.

Nutrient values are normalised to *per 100 g* so the rest of the app only ever
deals with one unit. Results are cached in Redis (24 h) and resolved items are
persisted into the shared ``food_items`` table, which keeps us well inside the
1,000 requests/hour free-tier limit.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..cache import cache_get_json, cache_set_json
from ..config import settings
from ..http import get_http_client

log = logging.getLogger(__name__)

SEARCH_TTL_S = 60 * 60 * 24
DETAIL_TTL_S = 60 * 60 * 24 * 7

# FoodData Central nutrient numbers.
NUTRIENT_ENERGY_KCAL = "1008"
NUTRIENT_ENERGY_KJ = "1062"
NUTRIENT_ATWATER_GENERAL = "2047"
NUTRIENT_ATWATER_SPECIFIC = "2048"
NUTRIENT_PROTEIN = "1003"
NUTRIENT_CARBS = "1005"
NUTRIENT_FAT = "1004"
NUTRIENT_FIBER = "1079"

PREFERRED_DATA_TYPES = ("Foundation", "SR Legacy", "Survey (FNDDS)", "Branded")


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nutrient_map(food: dict[str, Any]) -> dict[str, float]:
    """Collect nutrientNumber -> value from either search or detail payloads."""
    values: dict[str, float] = {}
    for entry in food.get("foodNutrients") or []:
        number = str(
            entry.get("nutrientNumber")
            or entry.get("number")
            or (entry.get("nutrient") or {}).get("number")
            or ""
        )
        amount = _as_float(
            entry.get("value")
            if entry.get("value") is not None
            else entry.get("amount")
        )
        if number and amount is not None and number not in values:
            values[number] = amount
    return values


def normalise_food(food: dict[str, Any]) -> dict[str, Any]:
    """Map a raw FDC food object into our ``food_items`` shape (per 100 g)."""
    nutrients = _nutrient_map(food)

    calories = nutrients.get(NUTRIENT_ENERGY_KCAL)
    if calories is None:
        calories = nutrients.get(NUTRIENT_ATWATER_SPECIFIC) or nutrients.get(
            NUTRIENT_ATWATER_GENERAL
        )
    if calories is None and NUTRIENT_ENERGY_KJ in nutrients:
        calories = nutrients[NUTRIENT_ENERGY_KJ] / 4.184

    description = (food.get("description") or food.get("lowercaseDescription") or "").strip()
    brand = food.get("brandName") or food.get("brandOwner")

    serving_size = _as_float(food.get("servingSize"))
    if serving_size and (food.get("servingSizeUnit") or "").lower() not in ("g", "gram", "grams"):
        serving_size = None  # ml/oz servings can't be trusted as grams

    return {
        "fdc_id": str(food["fdcId"]) if food.get("fdcId") else None,
        "name": description.title() if description.isupper() else description,
        "brand": brand,
        "calories_per_100g": round(calories, 1) if calories is not None else None,
        "protein_per_100g": _round(nutrients.get(NUTRIENT_PROTEIN)),
        "carbs_per_100g": _round(nutrients.get(NUTRIENT_CARBS)),
        "fat_per_100g": _round(nutrients.get(NUTRIENT_FAT)),
        "fiber_per_100g": _round(nutrients.get(NUTRIENT_FIBER)),
        "serving_size_g": serving_size,
        "data_source": "usda",
    }


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


async def _get(path: str, params: dict[str, Any]) -> Any | None:
    client = get_http_client()
    try:
        resp = await client.get(
            f"{settings.usda_api_base}{path}",
            params={**params, "api_key": settings.usda_api_key},
        )
    except httpx.HTTPError as exc:
        log.warning("USDA request failed: %s", exc)
        return None

    if resp.status_code == 429:
        log.warning("USDA rate limit hit")
        return None
    if resp.status_code >= 400:
        log.warning("USDA error %s: %s", resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except ValueError:
        return None


async def search_foods(query: str, page_size: int = 20) -> list[dict[str, Any]]:
    """Search FDC and return normalised per-100 g items, best matches first."""
    query = (query or "").strip()
    if len(query) < 2:
        return []

    cache_key = f"usda:search:{query.lower()}:{page_size}"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    payload = await _get(
        "/foods/search",
        {
            "query": query,
            "pageSize": min(50, max(1, page_size)),
            "dataType": ",".join(PREFERRED_DATA_TYPES),
            "requireAllWords": "false",
        },
    )
    if not payload:
        return []

    items: list[dict[str, Any]] = []
    for food in payload.get("foods") or []:
        item = normalise_food(food)
        # A food with no energy value is useless for calorie tracking.
        if item["fdc_id"] and item["name"] and item["calories_per_100g"] is not None:
            items.append(item)

    # Foundation/SR Legacy entries are generic whole foods and usually what a
    # person means when they type "chicken breast"; branded rows go last.
    def rank(food_item: dict[str, Any]) -> int:
        return 1 if food_item.get("brand") else 0

    items.sort(key=rank)
    await cache_set_json(cache_key, items, SEARCH_TTL_S)
    return items


async def get_food(fdc_id: str) -> dict[str, Any] | None:
    cache_key = f"usda:food:{fdc_id}"
    cached = await cache_get_json(cache_key)
    if cached is not None:
        return cached

    payload = await _get(f"/food/{fdc_id}", {"format": "abridged"})
    if not payload:
        return None
    item = normalise_food(payload)
    if item["calories_per_100g"] is None:
        return None
    await cache_set_json(cache_key, item, DETAIL_TTL_S)
    return item


async def best_match(query: str) -> dict[str, Any] | None:
    """Single best FDC match — used by the photo pipeline."""
    results = await search_foods(query, page_size=5)
    return results[0] if results else None


def scale_to_portion(item: dict[str, Any], grams: float) -> dict[str, float | None]:
    """Convert per-100 g values into a portion's absolute macros."""
    factor = max(0.0, grams) / 100.0

    def scaled(key: str) -> float | None:
        value = item.get(key)
        return round(float(value) * factor, 1) if value is not None else None

    return {
        "calories": scaled("calories_per_100g") or 0.0,
        "protein_g": scaled("protein_per_100g"),
        "carbs_g": scaled("carbs_per_100g"),
        "fat_g": scaled("fat_per_100g"),
        "fiber_g": scaled("fiber_per_100g"),
    }
