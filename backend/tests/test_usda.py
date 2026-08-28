"""USDA FoodData Central normalisation.

The fixtures below are trimmed copies of real API responses. The search payload
is the one that mattered: it reports ``nutrientId: 1008`` alongside
``nutrientNumber: "208"``, and reading the latter as if it were the id meant no
food ever resolved a calorie value, so every search result was discarded.
"""

import httpx
import pytest

from app import http as app_http
from app.services import usda

# --- verbatim from GET /foods/search?query=basmati%20rice (Branded) ----------
SEARCH_FOOD = {
    "fdcId": 2103038,
    "description": "BASMATI RICE",
    "dataType": "Branded",
    "brandName": "ROYAL",
    "brandOwner": "Riviana Foods Inc.",
    "servingSize": 45.0,
    "servingSizeUnit": "g",
    "foodNutrients": [
        {"nutrientId": 1003, "nutrientName": "Protein", "nutrientNumber": "203", "unitName": "G", "value": 8.89},
        {"nutrientId": 1004, "nutrientName": "Total lipid (fat)", "nutrientNumber": "204", "unitName": "G", "value": 0.0},
        {"nutrientId": 1005, "nutrientName": "Carbohydrate, by difference", "nutrientNumber": "205", "unitName": "G", "value": 84.4},
        {"nutrientId": 1008, "nutrientName": "Energy", "nutrientNumber": "208", "unitName": "KCAL", "value": 333},
        {"nutrientId": 2000, "nutrientName": "Total Sugars", "nutrientNumber": "269", "unitName": "G", "value": 0.0},
        {"nutrientId": 1079, "nutrientName": "Fiber, total dietary", "nutrientNumber": "291", "unitName": "G", "value": 2.2},
    ],
}

# --- shape returned by GET /food/{id}?format=abridged ------------------------
ABRIDGED_FOOD = {
    "fdcId": 171705,
    "description": "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
    "dataType": "SR Legacy",
    "foodNutrients": [
        {"nutrientId": 1008, "nutrientName": "Energy", "unitName": "KCAL", "value": 165},
        {"nutrientId": 1003, "nutrientName": "Protein", "unitName": "G", "value": 31.0},
        {"nutrientId": 1004, "nutrientName": "Total lipid (fat)", "unitName": "G", "value": 3.57},
        {"nutrientId": 1005, "nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 0.0},
    ],
}

# --- shape returned by the full (non-abridged) detail endpoint ---------------
FULL_DETAIL_FOOD = {
    "fdcId": 169704,
    "description": "Rice, white, long-grain, regular, cooked",
    "foodNutrients": [
        {"nutrient": {"id": 1008, "number": "208", "name": "Energy"}, "amount": 130},
        {"nutrient": {"id": 1003, "number": "203", "name": "Protein"}, "amount": 2.69},
        {"nutrient": {"id": 1079, "number": "291", "name": "Fiber"}, "amount": 0.4},
    ],
}


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------
def test_search_payload_resolves_calories_via_nutrient_id():
    item = usda.normalise_food(SEARCH_FOOD)
    assert item["calories_per_100g"] == 333
    assert item["protein_per_100g"] == 8.89
    assert item["carbs_per_100g"] == 84.4
    assert item["fat_per_100g"] == 0.0
    assert item["fiber_per_100g"] == 2.2


def test_legacy_nutrient_numbers_map_to_the_same_ids():
    # Same food described only by the legacy INFOODS tagnumbers.
    legacy_only = {
        "fdcId": 1,
        "description": "Legacy shape",
        "foodNutrients": [
            {"nutrientNumber": "208", "value": 250},
            {"nutrientNumber": "203", "value": 12},
            {"nutrientNumber": "205", "value": 30},
            {"nutrientNumber": "204", "value": 5},
            {"nutrientNumber": "291", "value": 3},
        ],
    }
    item = usda.normalise_food(legacy_only)
    assert item["calories_per_100g"] == 250
    assert item["protein_per_100g"] == 12
    assert item["carbs_per_100g"] == 30
    assert item["fat_per_100g"] == 5
    assert item["fiber_per_100g"] == 3


def test_abridged_detail_payload_resolves():
    item = usda.normalise_food(ABRIDGED_FOOD)
    assert item["calories_per_100g"] == 165
    assert item["protein_per_100g"] == 31.0


def test_full_detail_payload_with_nested_nutrient_resolves():
    item = usda.normalise_food(FULL_DETAIL_FOOD)
    assert item["calories_per_100g"] == 130
    assert item["protein_per_100g"] == 2.69
    assert item["fiber_per_100g"] == 0.4


def test_nutrient_key_handles_every_shape():
    assert usda._nutrient_key({"nutrientId": 1008, "nutrientNumber": "208"}) == "1008"
    assert usda._nutrient_key({"nutrientNumber": "208"}) == "1008"
    assert usda._nutrient_key({"number": "203"}) == "1003"
    assert usda._nutrient_key({"nutrient": {"id": 1005}}) == "1005"
    assert usda._nutrient_key({"nutrient": {"number": "291"}}) == "1079"
    # Unknown tagnumbers pass through rather than being dropped.
    assert usda._nutrient_key({"nutrientNumber": "269"}) == "269"
    assert usda._nutrient_key({}) is None


# ---------------------------------------------------------------------------
# Surrounding behaviour
# ---------------------------------------------------------------------------
def test_metadata_is_carried_through():
    item = usda.normalise_food(SEARCH_FOOD)
    assert item["fdc_id"] == "2103038"
    assert item["brand"] == "ROYAL"
    assert item["data_source"] == "usda"
    # All-caps descriptions are title-cased for display.
    assert item["name"] == "Basmati Rice"


def test_serving_size_only_trusted_when_already_in_grams():
    assert usda.normalise_food(SEARCH_FOOD)["serving_size_g"] == 45.0

    in_millilitres = {**SEARCH_FOOD, "servingSize": 240.0, "servingSizeUnit": "ml"}
    assert usda.normalise_food(in_millilitres)["serving_size_g"] is None


def test_kilojoule_only_food_is_converted_to_kcal():
    kj_only = {
        "fdcId": 2,
        "description": "KJ only",
        "foodNutrients": [{"nutrientId": 1062, "value": 1000}],
    }
    assert usda.normalise_food(kj_only)["calories_per_100g"] == round(1000 / 4.184, 1)


def test_atwater_energy_is_used_when_1008_is_absent():
    atwater = {
        "fdcId": 3,
        "description": "Atwater",
        "foodNutrients": [{"nutrientId": 2048, "value": 412}],
    }
    assert usda.normalise_food(atwater)["calories_per_100g"] == 412


def test_food_without_any_energy_value_yields_none():
    empty = {"fdcId": 4, "description": "Mystery", "foodNutrients": []}
    assert usda.normalise_food(empty)["calories_per_100g"] is None


def test_malformed_entries_are_skipped_not_fatal():
    messy = {
        "fdcId": 5,
        "description": "Messy",
        "foodNutrients": [
            None,
            "not a dict",
            {"nutrientId": 1008, "value": "not a number"},
            {"nutrientId": 1008, "value": 200},
        ],
    }
    # The unparsable value is skipped, so the good one still wins.
    assert usda.normalise_food(messy)["calories_per_100g"] == 200


def test_scale_to_portion_is_linear_in_grams():
    item = usda.normalise_food(SEARCH_FOOD)
    portion = usda.scale_to_portion(item, 150)
    assert portion["calories"] == round(333 * 1.5, 1)
    assert portion["protein_g"] == round(8.89 * 1.5, 1)

    assert usda.scale_to_portion(item, 0)["calories"] == 0.0


def test_scale_to_portion_preserves_missing_macros_as_none():
    sparse = {"calories_per_100g": 100, "protein_per_100g": None}
    portion = usda.scale_to_portion(sparse, 200)
    assert portion["calories"] == 200
    assert portion["protein_g"] is None


def test_retry_only_targets_proxy_style_failures():
    # JSON bodies are real validation errors and must not be retried.
    assert 400 in usda.RETRY_STATUSES
    assert 429 not in usda.RETRY_STATUSES
    assert 404 not in usda.RETRY_STATUSES



# ---------------------------------------------------------------------------
# Transient-failure retry (mocked transport — no network)
# ---------------------------------------------------------------------------
NGINX_400 = (
    "<html>\n<head><title>400 Bad Request</title></head>\n"
    "<body><center><h1>400 Bad Request</h1></center></body>\n</html>"
)


@pytest.fixture
def mock_usda(monkeypatch: pytest.MonkeyPatch):
    """Swap the shared httpx client for one backed by a scripted transport."""
    monkeypatch.setattr(usda, "RETRY_DELAY_S", 0)

    def install(responses: list[httpx.Response]) -> dict[str, int]:
        calls = {"n": 0}
        queue = list(responses)

        def handler(_: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return queue.pop(0) if queue else httpx.Response(500, text="exhausted")

        monkeypatch.setattr(
            app_http,
            "_client",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        return calls

    return install


async def test_transient_proxy_400_is_retried_once_and_then_succeeds(mock_usda):
    calls = mock_usda(
        [
            httpx.Response(400, text=NGINX_400),
            httpx.Response(200, json={"foods": [SEARCH_FOOD]}),
        ]
    )
    items = await usda.search_foods("basmati rice", page_size=5)
    assert calls["n"] == 2, "should have retried exactly once"
    assert len(items) == 1
    assert items[0]["calories_per_100g"] == 333


async def test_json_400_is_a_real_error_and_is_not_retried(mock_usda):
    calls = mock_usda([httpx.Response(400, json={"error": {"message": "bad dataType"}})])
    assert await usda.search_foods("chicken breast", page_size=5) == []
    assert calls["n"] == 1, "a validation error must not be retried"


async def test_rate_limit_is_never_retried(mock_usda):
    calls = mock_usda([httpx.Response(429, text="over rate limit")])
    assert await usda.search_foods("rice pudding", page_size=5) == []
    assert calls["n"] == 1, "retrying a 429 would make it worse"


async def test_two_consecutive_transient_failures_give_up_cleanly(mock_usda):
    calls = mock_usda(
        [httpx.Response(400, text=NGINX_400), httpx.Response(400, text=NGINX_400)]
    )
    assert await usda.search_foods("quinoa salad", page_size=5) == []
    assert calls["n"] == 2



# --- data-type preference ----------------------------------------------------
# FDC returns several rows for a dish. The one that matters is the "as eaten"
# entry, and it is not the one the API lists first: searching "idli" surfaces a
# packet of Idli Mix at dry-weight density before FNDDS's cooked Idli.
IDLI_MIX = {
    "fdcId": 111,
    "description": "Idli Mix",
    "dataType": "Branded",
    "foodNutrients": [{"nutrientId": 1008, "unitName": "KCAL", "value": 360}],
}
IDLI_FNDDS = {
    "fdcId": 222,
    "description": "Idli",
    "dataType": "Survey (FNDDS)",
    "foodNutrients": [{"nutrientId": 1008, "unitName": "KCAL", "value": 128}],
}
RICE_RAW = {
    "fdcId": 333,
    "description": "White Rice",
    "dataType": "SR Legacy",
    "foodNutrients": [{"nutrientId": 1008, "unitName": "KCAL", "value": 370}],
}
RICE_COOKED = {
    "fdcId": 444,
    "description": "Rice, cooked, NFS",
    "dataType": "Survey (FNDDS)",
    "foodNutrients": [{"nutrientId": 1008, "unitName": "KCAL", "value": 129}],
}


async def test_the_as_eaten_row_is_preferred_over_the_packet(mock_usda):
    """A cooked dish must not be priced from a dry mix."""
    mock_usda([httpx.Response(200, json={"foods": [IDLI_MIX, IDLI_FNDDS]})])

    items = await usda.search_foods("idli", page_size=5)

    assert items[0]["name"] == "Idli", "FNDDS leads, whatever order FDC returned"
    assert items[0]["calories_per_100g"] == 128


async def test_raw_grain_loses_to_the_cooked_entry(mock_usda):
    mock_usda([httpx.Response(200, json={"foods": [RICE_RAW, RICE_COOKED]})])

    items = await usda.search_foods("rice cooked", page_size=5)

    assert items[0]["calories_per_100g"] == 129, "cooked, not the 370 of dry rice"
    assert items[0]["data_type"] == "Survey (FNDDS)"


async def test_requests_include_the_survey_dataset(mock_usda, monkeypatch):
    """Omitting FNDDS from the query is what caused the overestimates."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"foods": [IDLI_FNDDS]})

    monkeypatch.setattr(
        app_http, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    # a query string not used by another test, or the cache answers instead
    await usda.search_foods("idli steamed cake", page_size=5)

    assert "url" in seen, "expected a live request rather than a cache hit"
    assert "FNDDS" in seen["url"]
