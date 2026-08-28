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
    # Ghee is in USDA even though pongal is not, which is what makes the mixed
    # South Indian meal a good test of database-vs-estimate precedence.
    "ghee": {"fdc_id": "3", "name": "Ghee", "calories_per_100g": 900.0},
    # What FDC actually returns for "idli": the packet, at dry-weight density.
    "idli": {"fdc_id": "4", "name": "Idli Mix", "calories_per_100g": 360.0},
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



# A South Indian breakfast: USDA carries ghee and egg but not pongal, which is
# the common case for regional and homemade dishes.
PONGAL_MEAL: dict[str, Any] = {
    "items": [
        {
            "food_name": "pongal",
            "usda_query": "pongal",
            "estimated_grams": 150,
            "confidence": 0.7,
            "quantity_text": "1 small cup",
            "fallback_calories_per_100g": 130,
            "fallback_protein_per_100g": 3.5,
            "fallback_carbs_per_100g": 18,
            "fallback_fat_per_100g": 4.5,
        },
        {
            "food_name": "ghee",
            "usda_query": "ghee",
            "estimated_grams": 5,
            "confidence": 0.6,
            "quantity_text": "light",
            "fallback_calories_per_100g": 900,
        },
    ],
}


def test_dish_missing_from_usda_falls_back_to_an_estimate_not_a_dead_end(client, stub_ai):
    """USDA has no pongal; the entry must still arrive with usable numbers."""
    stub_ai(PONGAL_MEAL)

    body = client.post(
        "/api/ai/food-text",
        json={"text": "1 small cup pongal with light ghee and 1 boiled egg"},
    ).json()

    pongal = body["items"][0]
    assert pongal["resolution"] == "estimated"
    # 130 kcal/100g at 150g
    assert pongal["calories"] == pytest.approx(195.0, abs=0.5)
    assert pongal["protein_g"] == pytest.approx(5.3, abs=0.2)
    assert pongal["carbs_g"] == pytest.approx(27.0, abs=0.5)
    assert pongal["fat_g"] == pytest.approx(6.8, abs=0.2)
    assert pongal["fdc_id"] is None, "an estimate must not claim a database id"
    assert "estimate" in (pongal["notes"] or "").lower()

    # ghee is in USDA, so it must still prefer the database over the estimate
    ghee = body["items"][1]
    assert ghee["resolution"] == "usda"
    assert ghee["calories"] == pytest.approx(45.0, abs=0.5), "USDA's 900 kcal/100g at 5g"


def test_usda_wins_when_its_numbers_are_plausible(client, stub_ai):
    """A database row beats an estimate — as long as it is the same food."""
    stub_ai(
        {
            "items": [
                {
                    "food_name": "tea",
                    "usda_query": "tea",
                    "estimated_grams": 100,
                    "confidence": 0.9,
                    # close to USDA's 34 kcal/100g, so the row is trusted
                    "fallback_calories_per_100g": 30,
                }
            ]
        }
    )

    item = client.post("/api/ai/food-text", json={"text": "a cup of tea"}).json()["items"][0]
    assert item["resolution"] == "usda"
    assert item["calories"] == pytest.approx(34.0, abs=0.5), "USDA's figure, not the estimate"


def test_a_dry_mix_matched_to_a_cooked_dish_is_rejected(client, stub_ai):
    """The reason logged calories came out three times too high.

    FDC is full of packet goods, and they carry no brand string so they sorted
    first: steamed idli matched "Idli Mix", cooked rice matched raw rice. The row
    then priced a cooked portion at dry weight — about 360 kcal/100 g against 120
    for the food actually eaten. An energy density that far from the model's own
    estimate means a different food, so the estimate is used instead.
    """
    stub_ai(
        {
            "items": [
                {
                    "food_name": "idli",
                    "usda_query": "idli",
                    "estimated_grams": 110,
                    "confidence": 0.8,
                    "fallback_calories_per_100g": 120,
                }
            ]
        }
    )

    item = client.post("/api/ai/food-text", json={"text": "2 idli"}).json()["items"][0]
    assert item["resolution"] == "estimated", "the dry mix must not be used"
    assert item["calories"] == pytest.approx(132.0, abs=1.0), "110g at the estimated 120/100g"
    assert item["fdc_id"] is None
    assert item["matched_name"] is None


def test_no_usda_match_and_no_estimate_still_asks_for_manual_entry(client, stub_ai):
    stub_ai(
        {
            "items": [
                {
                    "food_name": "something unheard of",
                    "usda_query": "unheard of dish",
                    "estimated_grams": 200,
                    "confidence": 0.3,
                }
            ]
        }
    )

    item = client.post("/api/ai/food-text", json={"text": "a bowl of mystery"}).json()["items"][0]
    assert item["resolution"] == "unresolved"
    assert item["calories"] is None
    assert "manually" in (item["notes"] or "")



def test_mixed_batch_sends_identical_keys_to_postgrest(client):
    """Saving a USDA item beside an AI estimate must not trip PGRST102.

    PostgREST requires every object in a bulk insert to carry the same keys and
    answers "All object keys must match" otherwise. The row builder drops null
    fields and only sets food_item_id when known, so a real meal — pongal
    estimated, ghee matched — produced two different shapes and the save failed
    with a 400 the user could do nothing about.
    """
    payload = [
        {   # AI estimate: no fibre, no food_item_id, no fdc_id
            "food_name": "pongal",
            "portion_g": 150.0,
            "calories": 195.0,
            "protein_g": 5.3,
            "carbs_g": 27.0,
            "fat_g": 6.8,
            "meal_type": "breakfast",
            "source": "ai_confirmed",
            "ai_confidence": 0.7,
        },
        {   # USDA match: fibre present, and an image to widen the key set further
            "food_name": "ghee",
            "portion_g": 5.0,
            "calories": 45.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 5.0,
            "fiber_g": 0.0,
            "meal_type": "breakfast",
            "source": "ai_confirmed",
            "ai_confidence": 0.9,
            "image_url": "https://example.test/meal.jpg",
        },
    ]

    resp = client.post("/api/food/logs/batch", json=payload)
    assert resp.status_code == 201, resp.text

    # The fake layer echoes back exactly the rows it was handed, so the response
    # shows the shape PostgREST would have received.
    rows = resp.json()["logs"]
    assert len(rows) == 2

    key_sets = [frozenset(row.keys()) - {"id"} for row in rows]
    assert key_sets[0] == key_sets[1], (
        f"objects differ, PostgREST would reject this: "
        f"{sorted(key_sets[0] ^ key_sets[1])}"
    )
    # padding must be null rather than invented values
    by_name = {row["food_name"]: row for row in rows}
    assert by_name["pongal"]["fiber_g"] is None
    assert by_name["pongal"]["image_url"] is None
    assert by_name["ghee"]["fiber_g"] == 0.0
    # and the real values must survive the padding
    assert by_name["pongal"]["calories"] == 195.0
    assert by_name["ghee"]["image_url"] == "https://example.test/meal.jpg"


def test_a_single_entry_batch_is_left_alone(client):
    """One row cannot mismatch, so it must not be padded with empty columns."""
    resp = client.post("/api/food/logs/batch", json=[{
        "food_name": "pongal", "portion_g": 150.0, "calories": 195.0,
        "meal_type": "breakfast", "source": "ai_confirmed",
    }])
    assert resp.status_code == 201, resp.text

    row = resp.json()["logs"][0]
    assert "fiber_g" not in row, "a lone row should keep its compact shape"
