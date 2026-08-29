"""Food search: the path a user lands on when AI logging is unavailable.

This matters more than its size suggests. The free Gemini tier allows twenty calls
a day across every user, so AI logging runs dry regularly and search is what people
fall back to. While search consulted only USDA, that fallback was also the
inaccurate path — searching "chai" returned packet mixes, which is the failure the
whole rebuild was about. The two paths now draw on the same figures.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import usda

# Foods whose correct figures live in our own tables. Searching for any of these
# must not need the network, and must not return a packet of mix.
LOCAL_FOODS = [
    ("chai", 25, 60),
    ("idli", 110, 175),
    ("dosa", 130, 200),
    ("jowar chilla", 140, 220),
    ("pongal", 120, 190),
    ("dal", 95, 160),
    ("roti", 200, 340),
    ("sambar", 40, 80),
    ("paratha", 250, 350),
    ("naan", 240, 320),
]


@pytest.fixture
def no_usda(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make any USDA call visible, and empty, so local coverage is measurable."""
    calls: list[str] = []

    async def fake_search(query: str, page_size: int = 20):
        calls.append(query)
        return []

    monkeypatch.setattr(usda, "search_foods", fake_search)
    return calls


@pytest.mark.parametrize(("query", "low", "high"), LOCAL_FOODS, ids=[q for q, _, _ in LOCAL_FOODS])
def test_common_foods_are_searchable_without_the_network(
    client: TestClient, no_usda: list[str], query: str, low: float, high: float
) -> None:
    results = client.get("/api/food/search", params={"q": query}).json()
    assert results, f"{query!r} returned nothing with USDA unavailable"

    top = results[0]
    assert top["source"] in {"curated", "cofid"}, (
        f"{query!r} was answered by {top['source']!r}; a local table should have it"
    )
    assert low <= top["calories_per_100g"] <= high, (
        f"{query!r} -> {top['name']!r} at {top['calories_per_100g']} kcal/100 g"
    )


def test_a_locally_answered_search_skips_usda_entirely(
    client: TestClient, no_usda: list[str]
) -> None:
    """Search should be instant and offline for the foods people search for."""
    client.get("/api/food/search", params={"q": "chai", "limit": 1})
    assert no_usda == [], "a local answer must not trigger a network call"


def test_usda_still_fills_the_gap_for_foods_we_lack(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping USDA would narrow coverage; it is demoted, not removed."""
    calls: list[str] = []

    async def fake_search(query: str, page_size: int = 20):
        calls.append(query)
        return [
            {
                "fdc_id": "999",
                "name": "Injera, teff flatbread",
                "brand": None,
                "calories_per_100g": 180.0,
                "protein_per_100g": 6.0,
                "carbs_per_100g": 35.0,
                "fat_per_100g": 1.0,
                "fiber_per_100g": None,
                "serving_size_g": None,
                "data_type": "Foundation",
            }
        ]

    monkeypatch.setattr(usda, "search_foods", fake_search)
    results = client.get("/api/food/search", params={"q": "injera"}).json()
    assert calls == ["injera"], "a food we lack must still reach USDA"
    assert any(r["source"] == "usda" for r in results)


def test_results_are_not_duplicated_across_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same food from two tables should appear once, not twice."""

    async def fake_search(query: str, page_size: int = 20):
        return [
            {
                "fdc_id": "1",
                "name": "Naan",
                "brand": None,
                "calories_per_100g": 300.0,
                "protein_per_100g": 8.0,
                "carbs_per_100g": 50.0,
                "fat_per_100g": 6.0,
                "fiber_per_100g": None,
                "serving_size_g": None,
                "data_type": "Branded",
            }
        ]

    monkeypatch.setattr(usda, "search_foods", fake_search)
    results = client.get("/api/food/search", params={"q": "naan"}).json()
    names = [r["name"].strip().lower() for r in results]
    assert len(names) == len(set(names)), f"duplicate entries: {names}"


def test_search_reports_where_each_figure_came_from(
    client: TestClient, no_usda: list[str]
) -> None:
    """So the UI can distinguish a checked figure from a database guess."""
    results = client.get("/api/food/search", params={"q": "sambar"}).json()
    assert results
    assert all(r["source"] in {"curated", "cofid", "cache", "usda"} for r in results)
