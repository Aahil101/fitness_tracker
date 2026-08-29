"""USDA FoodData Central client.

Nutrient values are normalised to *per 100 g* so the rest of the app only ever
deals with one unit. Results are cached in Redis (24 h) and resolved items are
persisted into the shared ``food_items`` table, which keeps us well inside the
1,000 requests/hour free-tier limit.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ..cache import cache_get_json, cache_set_json
from ..config import settings
from ..http import get_http_client

log = logging.getLogger(__name__)

SEARCH_TTL_S = 60 * 60 * 24
DETAIL_TTL_S = 60 * 60 * 24 * 7

# FoodData Central nutrient IDs (the modern `nutrientId` field).
NUTRIENT_ENERGY_KCAL = "1008"
NUTRIENT_ENERGY_KJ = "1062"
NUTRIENT_ATWATER_GENERAL = "2047"
NUTRIENT_ATWATER_SPECIFIC = "2048"
NUTRIENT_PROTEIN = "1003"
NUTRIENT_CARBS = "1005"
NUTRIENT_FAT = "1004"
NUTRIENT_FIBER = "1079"

# The /foods/search endpoint reports *both* the modern id and the legacy INFOODS
# tagnumber, and confusingly names the latter `nutrientNumber`:
#     {"nutrientId": 1008, "nutrientNumber": "208", "nutrientName": "Energy"}
# Reading `nutrientNumber` and comparing it to "1008" therefore never matches,
# which silently dropped every search result for want of a calorie value. Both
# spellings are now resolved to the id above.
LEGACY_NUMBER_TO_ID: dict[str, str] = {
    "208": NUTRIENT_ENERGY_KCAL,
    "268": NUTRIENT_ENERGY_KJ,
    "957": NUTRIENT_ATWATER_GENERAL,
    "958": NUTRIENT_ATWATER_SPECIFIC,
    "203": NUTRIENT_PROTEIN,
    "205": NUTRIENT_CARBS,
    "204": NUTRIENT_FAT,
    "291": NUTRIENT_FIBER,
}

# Datasets searched, in preference order. "Survey (FNDDS)" is deliberately
# absent: its encoded space and parentheses (Survey+%28FNDDS%29) make the FDC
# edge proxy reject the request with an HTML 400 about two thirds of the time,
# and it fails in runs — measured 2/6 successes with it versus 6/6 without,
# including four consecutive failures. Foundation and SR Legacy already cover
# generic whole foods, so dropping it is a cheap trade for a reliable search.
# Survey (FNDDS) is the "as eaten" database — cooked, mixed, composite dishes,
# which is what someone logging a meal is describing. Omitting it was the root
# cause of threefold overestimates: without it the closest match for idli was a
# packet of Idli Mix at 360 kcal/100 g, where FNDDS carries plain "Idli" at 128.
# It leads the list for that reason. Foundation and SR Legacy cover single
# ingredients, Branded covers packaged goods, and both stay behind it.
PREFERRED_DATA_TYPES = ("Survey (FNDDS)", "Foundation", "SR Legacy", "Branded")

# Ranking weight per data type: lower sorts first.
DATA_TYPE_RANK = {
    "survey (fndds)": 0,
    "foundation": 1,
    "sr legacy": 1,
    "branded": 2,
}

# Words that mark a row as the packet rather than the meal. Matching one of
# these against a dish someone described as cooked prices it at dry weight,
# which is roughly three times too much for rice, dal, idli and dosa.
UNPREPARED_MARKERS = (
    "mix",
    "powder",
    "dry",
    "dried",
    "uncooked",
    "raw",
    "instant",
    "flour",
    "unprepared",
    "concentrate",
)

# nginx in front of the FDC API intermittently rejects a request that succeeds
# moments later with the same URL, so one retry is worth it. Genuine API
# validation errors come back as JSON and are not retried.
RETRY_STATUSES = frozenset({400, 500, 502, 503, 504})
RETRY_DELAY_S = 0.6

# Words that make a row a different *kind* of food from anything a person
# describes as a meal. FDC answered "jowar chilla" with "Chilla In Vanilla Bean
# Flavor Keto Frozen Dessert" — it shares the word "chilla", so token overlap
# alone accepted it, and the entry looked plausible enough to ship 16.8 g of fat
# for a savoury pancake. A match may not introduce one of these categories unless
# the query asked for it.
CATEGORY_CONFLICTS = (
    "dessert",
    "frozen",
    "ice cream",
    "candy",
    "chocolate",
    "cookie",
    "biscuit",
    "cake",
    "syrup",
    "soda",
    "soft drink",
    "energy drink",
    "supplement",
    "protein bar",
    "keto",
    "infant",
    "baby food",
    "pet",
    "dog",
    "cat food",
    "sauce, ",
    "seasoning",
    "flavoring",
    "flavouring",
    "extract",
)

# Words carrying no discriminating power when judging whether a match is about the
# same food as the query.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "with", "without", "and", "or", "in", "on", "for",
        "plain", "fresh", "cooked", "prepared", "homemade", "home", "made", "style",
        "type", "food", "dish", "hot", "cold", "regular", "original", "classic",
        "added", "not", "no", "from", "made with", "includes",
    }
)


def _content_words(text: str) -> set[str]:
    """Discriminating words of a food name, singularised the same way both sides."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    words = set()
    for word in cleaned.split():
        if word in _STOPWORDS or len(word) < 3 or word.isdigit():
            continue
        if len(word) >= 4 and word.endswith("s") and not word.endswith(("ss", "us")):
            word = word[:-1]
        words.add(word)
    return words


def is_relevant(query: str, candidate_name: str) -> bool:
    """Is this row plausibly the food that was asked for?

    ``best_match`` used to return whatever sorted first, with no test of whether
    the row had anything to do with the query. Two conditions now have to hold:
    the match must share a discriminating word with the query, and it must not
    drag in a food category the query never mentioned.

    Deliberately a cheap syntactic check rather than anything clever. It is a
    filter against nonsense, not a ranking function — the goal is that a wrong
    answer becomes "no answer" so a later layer can supply a sane one.
    """
    query_words = _content_words(query)
    match_words = _content_words(candidate_name)
    if not query_words or not match_words:
        return False

    if not (query_words & match_words):
        return False

    lowered_query = (query or "").lower()
    lowered_match = (candidate_name or "").lower()
    for conflict in CATEGORY_CONFLICTS:
        if conflict in lowered_match and conflict not in lowered_query:
            return False

    return True


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nutrient_key(entry: dict[str, Any]) -> str | None:
    """Canonical nutrient id for one foodNutrients entry, whatever its shape.

    Handles all three payload shapes FDC uses: search results (flat, with
    ``nutrientId``), abridged detail (flat), and full detail (nested under
    ``nutrient``). Falls back to translating the legacy tagnumber.
    """
    nested = entry.get("nutrient") or {}

    identifier = entry.get("nutrientId") or nested.get("id")
    if identifier is not None:
        return str(identifier)

    legacy = entry.get("nutrientNumber") or entry.get("number") or nested.get("number")
    if legacy is None:
        return None
    legacy = str(legacy)
    # A four-digit "number" is already an id in some payloads; pass it through.
    return LEGACY_NUMBER_TO_ID.get(legacy, legacy)


def _nutrient_map(food: dict[str, Any]) -> dict[str, float]:
    """Collect canonical nutrient id -> value from any FDC payload shape."""
    values: dict[str, float] = {}
    for entry in food.get("foodNutrients") or []:
        if not isinstance(entry, dict):
            continue
        key = _nutrient_key(entry)
        amount = _as_float(
            entry.get("value")
            if entry.get("value") is not None
            else entry.get("amount")
        )
        if key and amount is not None and key not in values:
            values[key] = amount
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
        "data_type": food.get("dataType"),
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
    url = f"{settings.usda_api_base}{path}"
    query = {**params, "api_key": settings.usda_api_key}

    for attempt in range(2):
        try:
            resp = await client.get(url, params=query)
        except httpx.HTTPError as exc:
            log.warning("USDA request failed: %s", exc)
            return None

        if resp.status_code < 400:
            try:
                return resp.json()
            except ValueError:
                log.warning("USDA returned a non-JSON success body")
                return None

        if resp.status_code == 429:
            log.warning("USDA rate limit hit")
            return None

        # An HTML body means the edge proxy rejected it, not the API — those are
        # transient. A JSON body is a real validation error; retrying is futile.
        body = resp.text[:200]
        transient = resp.status_code in RETRY_STATUSES and not body.lstrip().startswith("{")
        if transient and attempt == 0:
            log.info("USDA %s looks transient, retrying once", resp.status_code)
            await asyncio.sleep(RETRY_DELAY_S)
            continue

        log.warning("USDA error %s: %s", resp.status_code, body)
        return None

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
    #
    # Dry and unprepared rows are pushed back further still. FDC is full of
    # packet goods — "Idli Mix", "Dosa Mix", "Chana Dal", raw rice — which carry
    # no brand string and so used to sort first, then priced a cooked portion at
    # dry-weight density: around 370 kcal/100 g against roughly 120 for the
    # cooked food, a threefold overstatement on staples.
    def rank(food_item: dict[str, Any]) -> tuple[int, int, int]:
        name = (food_item.get("name") or "").lower()
        unprepared = 1 if any(word in name for word in UNPREPARED_MARKERS) else 0
        source = DATA_TYPE_RANK.get((food_item.get("data_type") or "").lower(), 3)
        branded = 1 if food_item.get("brand") else 0
        return (unprepared, source, branded)

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
    """Best FDC row that is actually about the food asked for, or None.

    Returning ``results[0]`` unconditionally is how a savoury sorghum pancake
    became a keto frozen dessert. Rows are now screened for relevance and the
    first survivor wins; if none survive, the caller falls through to a source
    that can give an honest answer instead of a confident wrong one.
    """
    results = await search_foods(query, page_size=10)
    for row in results:
        if is_relevant(query, row.get("name") or ""):
            return row
    if results:
        log.info(
            "No relevant USDA match for %r; best candidate was %r",
            query,
            results[0].get("name"),
        )
    return None


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
