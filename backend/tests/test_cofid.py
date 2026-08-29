"""The bundled composition table, and the matching that reads it.

USDA FoodData Central was the general-purpose source and was the wrong kind of
database for the question. Its searchable bulk is packaged goods, so a query about
home cooking returned the nearest packet: idli came back as a bag of Idli Mix at
dry-weight density. Open Food Facts was evaluated as a replacement and fails
identically by design — searching it for "idli" returns Rava idli *mix* at 365-404
kcal/100 g, and most products carry no nutrient values at all.

CoFID is a composition table instead of a product catalogue, and it distinguishes
preparations: chapatis made with fat and without, samosas baked and deep fried.
These tests cover the matching, which is ours, and the shape of the data.
"""

from __future__ import annotations

import pytest

from app.services import cofid


def test_the_table_is_bundled_and_substantial() -> None:
    assert cofid.count() > 2500, "the committed dataset looks truncated"
    assert cofid.attribution(), "the Open Government Licence requires attribution"
    assert "Open Government Licence" in cofid.attribution()


def test_lookups_need_no_network() -> None:
    """The reason for bundling it. Nothing here may perform IO.

    Resolution used to depend on a remote search that could be slow, rate limited,
    or simply wrong; a local file cannot be any of those.
    """
    import inspect

    source = inspect.getsource(cofid)
    for forbidden in ("httpx", "requests", "urllib.request", "aiohttp"):
        assert forbidden not in source, f"{forbidden} has no business in a local lookup"


# (query, expected substring in the matched name, plausible kcal range)
MATCHES = [
    # Preparation-aware, which is the whole reason for choosing this dataset.
    ("chapati", "Chapati", 180, 340),
    ("paratha", "Paratha", 150, 350),
    ("samosa", "Samosa", 250, 400),
    ("raita", "Raita", 40, 110),
    ("omelette", "Omelette", 150, 260),
    ("sambar", "Sambar", 30, 120),
    # Plain ingredients must resolve to the ingredient, not a product built on it.
    ("banana", "Banana", 60, 110),
    ("almonds", "Almond", 550, 650),
    ("peanut butter", "Peanut butter", 550, 650),
    ("baked beans", "Baked beans", 60, 120),
    ("cooked pasta", "Pasta", 100, 200),
    ("yoghurt", "Yogurt", 40, 120),
]


@pytest.mark.parametrize(("query", "expected", "low", "high"), MATCHES)
def test_matches_are_the_right_food_and_a_plausible_figure(
    query: str, expected: str, low: float, high: float
) -> None:
    hit = cofid.best_match(query)
    assert hit is not None, f"{query!r} found nothing"
    assert expected.lower() in hit.name.lower(), (
        f"{query!r} matched {hit.name!r}, which is a different food"
    )
    assert low <= hit.kcal <= high, f"{query!r} -> {hit.name!r} at {hit.kcal} kcal/100 g"


# Queries whose head noun is a food, paired with the product that used to swallow
# them. Token overlap alone cannot tell a head noun from a modifier, which is why
# matching now requires the query to account for the candidate's whole head.
HEAD_NOUN_TRAPS = [
    ("egg", "creme egg"),
    ("egg", "egg nog"),
    ("banana", "banana bread"),
    ("banana", "banana split"),
    ("milk", "porridge"),
    ("pasta", "pasta bake"),
    ("fish", "fish fingers"),
    ("almonds", "curry, almond"),
]


@pytest.mark.parametrize(("query", "trap"), HEAD_NOUN_TRAPS)
def test_a_product_built_from_a_food_does_not_answer_for_the_food(
    query: str, trap: str
) -> None:
    """Each of these was a real wrong answer during development."""
    hit = cofid.best_match(query)
    assert hit is not None, f"{query!r} should still match something"
    assert trap.lower() not in hit.name.lower(), (
        f"{query!r} matched {hit.name!r} — a product made from it, not the food"
    )


def test_a_preparation_word_alone_is_not_a_match() -> None:
    """Otherwise "boiled egg" would find every boiled thing in the table."""
    assert cofid.search("boiled") == []
    assert cofid.search("homemade") == []
    assert cofid.search("fresh") == []


def test_foods_the_table_does_not_have_return_nothing() -> None:
    """A composition table of UK foods does not know South Indian breakfasts.

    That is expected and is why the curated table sits in front of it. What
    matters is that it says so rather than offering a near miss.
    """
    for query in ("idli", "dosa", "pongal", "jowar chilla", "thalipeeth", "injera"):
        assert cofid.best_match(query) is None, f"{query!r} should not be answered here"


def test_energy_and_macros_agree_across_the_whole_table() -> None:
    """A sanity check on the conversion, not on the source data.

    Catches a column being read from the wrong place, which is the realistic way
    a spreadsheet import goes wrong. Allows generous slack: the dataset has
    alcohol, polyols and fibre that the 4/4/9 rule does not account for.
    """
    entries, _ = cofid._table()
    bad: list[str] = []
    for entry in entries:
        food = entry.food
        if food.kcal < 20:
            continue
        implied = food.protein_g * 4 + food.carbs_g * 4 + food.fat_g * 9
        if implied and not (0.45 <= implied / food.kcal <= 1.55):
            bad.append(f"{food.name} ({food.kcal} kcal vs {implied:.0f} implied)")

    # A handful of genuine outliers exist in the source (alcoholic drinks, foods
    # high in polyols). A large number would mean the import is misaligned.
    assert len(bad) < len(entries) * 0.06, (
        f"{len(bad)} of {len(entries)} entries fail the energy check: {bad[:5]}"
    )
