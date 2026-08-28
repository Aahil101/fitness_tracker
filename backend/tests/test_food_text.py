"""Logging a meal by typing it in plain language.

The model's only job here is naming foods and converting household measures to
grams — "half cup of tea with 1 spoon" has to become tea plus the sugar that
"1 spoon" implies, or those calories vanish. Nutrition itself still comes from
USDA via the same resolution step the photo path uses, so these tests stub
Gemini and assert the wiring, not the model.
"""

from typing import Any

import pytest

from app.services import gemini, usda

# Shape parse_meal_text returns for "half cup of tea with 1 spoon", as observed
# from the live API.
TEA_AND_SUGAR: dict[str, Any] = {
    "items": [
        {
            "food_name": "tea",
            "usda_query": "tea",
            "estimated_grams": 120,
            "confidence": 0.8,
            "quantity_text": "half cup",
        },
        {
            "food_name": "sugar",
            "usda_query": "sugar",
            "estimated_grams": 4,
            "confidence": 0.7,
            "quantity_text": "1 spoon",
        },
    ],
    "meal_type": "snack",
}

USDA_MATCHES = {
    "tea": {"fdc_id": "1", "name": "Tea", "calories_per_100g": 34.0, "protein_g": 0.1},
    "sugar": {"fdc_id": "2", "name": "Sugar, granulated", "calories_per_100g": 400.0},
}


@pytest.fixture
def stub_ai(monkeypatch: pytest.MonkeyPatch):
    """Stub the model and USDA so the test exercises our wiring only."""

    def install(parsed: dict[str, Any]) -> dict[str, list[str]]:
        seen: dict[str, list[str]] = {"prompts": [], "queries": []}

        async def fake_parse(text: str) -> dict[str, Any]:
            seen["prompts"].append(text)
            return parsed

        async def fake_best_match(query: str) -> dict[str, Any] | None:
            seen["queries"].append(query)
            return USDA_MATCHES.get(query.lower())

        monkeypatch.setattr(gemini, "parse_meal_text", fake_parse)
        monkeypatch.setattr(usda, "best_match", fake_best_match)
        return seen

    return install


def test_typed_meal_becomes_items_with_usda_nutrition(client, stub_ai):
    seen = stub_ai(TEA_AND_SUGAR)

    resp = client.post("/api/ai/food-text", json={"text": "half cup of tea with 1 spoon"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert [i["food_name"] for i in body["items"]] == ["tea", "sugar"]

    tea, sugar = body["items"]
    # 34 kcal/100g at 120g, and 400 kcal/100g at 4g.
    assert tea["portion_g"] == 120
    assert tea["calories"] == pytest.approx(40.8, abs=0.2)
    assert tea["resolution"] == "usda"
    assert sugar["portion_g"] == 4
    assert sugar["calories"] == pytest.approx(16.0, abs=0.2)

    assert body["total_calories"] == pytest.approx(56.8, abs=0.5)
    assert body["meal_type"] == "snack"
    assert seen["prompts"] == ["half cup of tea with 1 spoon"]
    # the model's search phrases, not the user's wording, reach USDA
    assert seen["queries"] == ["tea", "sugar"]


def test_the_endpoint_only_drafts_and_never_writes_a_log(client, stub_ai, queries):
    stub_ai(TEA_AND_SUGAR)

    resp = client.post("/api/ai/food-text", json={"text": "half cup of tea with 1 spoon"})
    assert resp.status_code == 200

    assert not any(table == "food_logs" for table, _ in queries), (
        "drafting must stay reviewable — the user confirms before anything is logged"
    )


def test_unmatched_food_is_flagged_rather_than_silently_zeroed(client, stub_ai):
    stub_ai(
        {
            "items": [
                {
                    "food_name": "grandmother's secret curry",
                    "usda_query": "unheard of dish",
                    "estimated_grams": 250,
                    "confidence": 0.4,
                }
            ]
        }
    )

    body = client.post("/api/ai/food-text", json={"text": "a bowl of my nan's curry"}).json()
    item = body["items"][0]

    assert item["resolution"] == "unresolved"
    assert item["calories"] is None, "no invented numbers when nutrition is unknown"
    assert item["notes"] and "manually" in item["notes"]
    assert any("could not be matched" in w for w in body["warnings"])


def test_nothing_edible_described_explains_itself(client, stub_ai):
    stub_ai({"items": [], "notes": "Water contains no calories."})

    body = client.post("/api/ai/food-text", json={"text": "just water"}).json()

    assert body["items"] == []
    assert body["total_calories"] == 0
    assert any("no calories" in w.lower() for w in body["warnings"])
    assert any("half cup of tea" in w for w in body["warnings"]), "show the user a usable example"


def test_blank_and_overlong_text_are_rejected_before_reaching_the_model(client, stub_ai):
    seen = stub_ai(TEA_AND_SUGAR)

    assert client.post("/api/ai/food-text", json={"text": " "}).status_code == 422
    assert client.post("/api/ai/food-text", json={"text": "x" * 1001}).status_code == 422
    assert seen["prompts"] == [], "validation must not spend model quota"
