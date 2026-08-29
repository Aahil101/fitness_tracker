"""A benchmark of real foods with accepted calorie ranges.

Written after a user logged "tea with milk and sugar" and the app recorded 1 kcal
in front of their client. Every other test here asserts that a mechanism behaves
as designed; this one asserts that the *answers* are right, which is the only
thing the user actually experiences.

Ranges rather than points, because a portion of dal is not a precise object. They
are wide enough that a correct implementation passes comfortably and narrow enough
that the failure which prompted this file — an answer out by a factor of ten —
cannot pass at all.

Every entry that has produced a complaint is pinned here permanently. If a change
makes any of these wrong, this file fails, and that is the point.
"""

from __future__ import annotations

import pytest

from app.services import food_facts
from app.services.resolve import Resolved, apply_floor, from_curated, marker_floor

# (query, grams, low_kcal, high_kcal, why)
BENCHMARK: list[tuple[str, float, float, float, str]] = [
    # ---- the incident -----------------------------------------------------
    ("tea with milk and sugar", 200, 55, 110, "a normal cup of Indian chai"),
    ("Tea (with milk and sugar)", 120, 30, 70, "the exact string that logged 1 kcal"),
    ("chai", 240, 65, 130, "a large cup"),
    ("milk tea", 200, 55, 110, ""),
    ("coffee with milk and sugar", 200, 50, 105, ""),
    # ---- and the drinks that really are near zero -------------------------
    ("black tea", 200, 0, 8, "must stay near zero — the floor must not fire"),
    ("green tea", 200, 0, 8, ""),
    ("black coffee", 200, 0, 8, ""),
    # ---- staples, cooked weight -------------------------------------------
    ("cooked white rice", 160, 180, 240, "a cup of cooked rice"),
    ("dal", 200, 190, 280, "a bowl as served"),
    ("roti", 80, 180, 250, "two rotis"),
    ("jowar roti", 100, 210, 290, ""),
    ("idli", 100, 120, 170, "two idli"),
    ("dosa", 90, 130, 190, "one dosa"),
    ("sambar", 150, 75, 130, ""),
    ("ven pongal", 200, 270, 360, "a cup with ghee"),
    ("upma", 200, 250, 330, ""),
    ("poha", 180, 220, 290, ""),
    ("paratha", 70, 180, 250, ""),
    ("puri", 60, 190, 260, "two puris"),
    # ---- the garbage-match case -------------------------------------------
    ("jowar chilla", 90, 130, 210, "matched a keto frozen dessert before"),
    # ---- protein and fats -------------------------------------------------
    ("boiled egg", 50, 65, 90, "one egg"),
    ("omelette", 100, 160, 230, ""),
    ("grilled chicken breast", 120, 170, 220, ""),
    ("ghee", 5, 40, 50, "a teaspoon"),
    ("butter", 10, 65, 80, ""),
    ("vegetable oil", 5, 40, 48, ""),
    ("almonds", 15, 78, 95, ""),
    # ---- dairy ------------------------------------------------------------
    ("whole milk", 200, 105, 140, "a glass"),
    ("curd", 150, 80, 105, "a bowl"),
    ("buttermilk", 250, 35, 70, "chaas — thin, must not be inflated"),
    # ---- sweeteners -------------------------------------------------------
    ("sugar", 5, 17, 22, "a teaspoon"),
    ("jaggery", 10, 34, 42, ""),
    # ---- mains ------------------------------------------------------------
    ("chicken curry", 200, 250, 340, ""),
    ("paneer curry", 180, 300, 380, ""),
    ("chicken biryani", 250, 400, 500, ""),
    ("mixed vegetable curry", 180, 145, 200, ""),
]


@pytest.mark.parametrize(
    ("query", "grams", "low", "high", "why"),
    BENCHMARK,
    ids=[f"{q}@{g:g}g" for q, g, _, _, _ in BENCHMARK],
)
def test_curated_answers_fall_in_the_accepted_range(
    query: str, grams: float, low: float, high: float, why: str
) -> None:
    """Every benchmark food must be answerable, and answerable correctly.

    Resolution goes through the curated table here rather than the endpoint, so
    the test needs no model and no network and runs in milliseconds — which is
    what makes it cheap enough to pin this many foods.
    """
    resolved = from_curated(query, query, grams)
    assert resolved is not None, (
        f"{query!r} is not in the curated table. Anything a user logs often enough "
        "to complain about belongs in it."
    )
    kcal = resolved.calories
    assert low <= kcal <= high, (
        f"{query!r} at {grams:g} g resolved to {kcal:.0f} kcal, outside the "
        f"accepted {low:.0f}-{high:.0f}" + (f" ({why})" if why else "")
    )


def test_the_reported_failure_cannot_happen_again() -> None:
    """The precise case from the report, asserted directly.

    "Tea (with milk and sugar)", 120 g, logged as 1 kcal. Three independent
    mechanisms now have to fail for that to recur, so all three are checked.
    """
    query = "Tea (with milk and sugar)"

    # 1. The curated table answers it, and the bracketed qualifier does not hide
    #    the milk.
    fact = food_facts.lookup(query)
    assert fact is not None
    assert fact.kcal > 20, "a milky sweet drink cannot be a near-zero food"

    # 2. Resolution returns a sane number.
    resolved = from_curated(query, "tea", 120)
    assert resolved is not None
    assert 30 <= resolved.calories <= 70

    # 3. Even if both of those were bypassed and a database handed back brewed
    #    tea, the floor lifts it out of the impossible range.
    poisoned = Resolved(
        name=query,
        grams=120,
        calories=1.0,
        protein_g=0.0,
        carbs_g=0.2,
        fat_g=0.0,
        fiber_g=None,
        source="usda",
        matched_name="Tea, brewed",
        confidence=0.5,
    )
    repaired = apply_floor(poisoned, query)
    assert repaired.calories > 15, "the floor is the last line of defence and it must hold"
    assert repaired.notes, "and it must say that it fired"


def test_the_floor_stays_silent_on_foods_that_really_are_near_zero() -> None:
    """A floor that fires on correct data is worse than no floor.

    Black coffee is 1 kcal and must remain 1 kcal. If protecting chai came at the
    cost of inflating every unsweetened drink, the cure would be worse than the
    disease.
    """
    for query in ("black coffee", "black tea", "green tea", "plain water"):
        assert marker_floor(query) is None, f"{query!r} must not acquire a floor"

    resolved = from_curated("black coffee", "black coffee", 200)
    assert resolved is not None
    floored = apply_floor(resolved, "black coffee")
    assert floored.calories == resolved.calories
    assert floored.calories < 10


def test_negations_defeat_the_floor() -> None:
    """"Sugar free" mentions sugar and contains none."""
    for query in (
        "sugar free tea",
        "tea without milk",
        "unsweetened almond milk",
        "coffee, no sugar",
    ):
        assert marker_floor(query) is None, f"{query!r} must not acquire a floor"


def test_every_curated_entry_is_internally_consistent() -> None:
    """Macros must roughly account for the energy they claim.

    Catches a typo in the table itself, which is now a source of truth and so is
    worth checking as one. 4 kcal per gram of protein and carbohydrate, 9 per gram
    of fat; a 30% tolerance covers fibre, alcohol and rounding.
    """
    for fact in food_facts.ALL_FACTS:
        implied = fact.protein_g * 4 + fact.carbs_g * 4 + fact.fat_g * 9
        if fact.kcal < 10:
            continue  # near-zero foods: rounding dominates
        ratio = implied / fact.kcal
        assert 0.7 <= ratio <= 1.3, (
            f"{fact.name!r} claims {fact.kcal} kcal/100 g but its macros imply "
            f"{implied:.0f} — check the table"
        )


def test_no_curated_alias_is_ambiguous() -> None:
    """Two entries claiming the same alias would make lookups arbitrary."""
    seen: dict[str, str] = {}
    for fact in food_facts.ALL_FACTS:
        for alias in (fact.name, *fact.aliases):
            key = food_facts._normalise(alias)
            assert key not in seen or seen[key] == fact.name, (
                f"alias {alias!r} is claimed by both {seen.get(key)!r} and {fact.name!r}"
            )
            seen[key] = fact.name



# ---------------------------------------------------------------------------
# Lookup precedence
# ---------------------------------------------------------------------------
HEAD_NOUN_CASES = [
    # The regression: "chai with milk and sugar" matched the bare "sugar" alias
    # and priced a cup of tea as 240 g of sugar — 929 kcal.
    ("chai with milk and sugar", "tea with milk and sugar"),
    ("pongal with ghee", "ven pongal"),
    ("dosa with chutney", "dosa"),
    ("rice with dal", "cooked white rice"),
    ("paratha with butter", "paratha"),
    ("idli with sambar", "idli"),
    ("curd with sugar", "curd"),
    # A bare ingredient must still resolve to itself.
    ("sugar", "sugar"),
    ("milk", "whole milk"),
    ("ghee", "ghee"),
]


@pytest.mark.parametrize(("query", "expected"), HEAD_NOUN_CASES)
def test_the_dish_wins_over_its_ingredients(query: str, expected: str) -> None:
    """A name listing its ingredients must resolve to the dish, not an ingredient.

    Several curated aliases can legitimately match one query: "chai with milk and
    sugar" contains chai, milk and sugar, all three of which are entries. Picking
    among them by alias length put sugar first and produced a 929 kcal cup of tea.
    The first content word is the head noun and decides it.
    """
    fact = food_facts.lookup(query)
    assert fact is not None, f"{query!r} should resolve"
    assert fact.name == expected, (
        f"{query!r} resolved to {fact.name!r}; the head noun says it should be {expected!r}"
    )


def test_a_dish_named_with_its_ingredients_is_priced_as_the_dish() -> None:
    """The 929 kcal cup of tea, asserted in calories rather than in names."""
    resolved = from_curated("chai with milk and sugar", "chai", 240)
    assert resolved is not None
    assert 60 <= resolved.calories <= 140, (
        f"a 240 ml cup of chai came out at {resolved.calories:.0f} kcal"
    )



# ---------------------------------------------------------------------------
# Preparation words
# ---------------------------------------------------------------------------
PREPARATION_CASES = [
    # The model appends how the food was made. One such word used to defeat the
    # lookup entirely: "tea (brewed)" matched nothing and fell through to a
    # database that priced it at 1 kcal.
    ("tea (brewed)", "tea with milk and sugar"),
    ("coffee (brewed)", "coffee with milk and sugar"),
    ("sambar (stew)", "sambar"),
    ("milk (liquid)", "whole milk"),
    ("sugar (granulated)", "sugar"),
    ("ghee (melted)", "ghee"),
    ("pongal (cooked)", "ven pongal"),
    ("jowar chilla (pan-fried)", "jowar chilla"),
    ("idli (steamed)", "idli"),
    ("dal (cooked)", "dal, cooked"),
    # Qualifiers that distinguish real entries must survive. "plain tea" is not
    # chai, and treating "plain" as noise would make it so.
    ("tea (plain)", "black tea, unsweetened"),
    ("plain tea", "black tea, unsweetened"),
    ("green tea (brewed)", "black tea, unsweetened"),
    ("black coffee (brewed)", "black coffee, unsweetened"),
]


@pytest.mark.parametrize(("query", "expected"), PREPARATION_CASES)
def test_a_preparation_word_does_not_defeat_the_lookup(query: str, expected: str) -> None:
    fact = food_facts.lookup(query)
    assert fact is not None, f"{query!r} should still resolve with a preparation attached"
    assert fact.name == expected


# Foods genuinely absent from the table. Each shares a word with something in it,
# which is what makes them the dangerous cases.
NOT_IN_TABLE = [
    "grilled fish",  # shares "grilled" with grilled chicken breast
    "grilled salmon",
    "grandmother's secret curry",  # shares "curry" with three entries
    "unheard of dish",
    "thalipeeth",
    "pizza",
    "sushi",
]


@pytest.mark.parametrize("query", NOT_IN_TABLE)
def test_a_food_we_do_not_have_returns_nothing_rather_than_a_near_miss(query: str) -> None:
    """Falling through to another source beats confidently answering wrongly.

    An earlier version dropped every word it did not recognise and retried, which
    threw away the noun and kept the modifier: "grilled fish" came back as grilled
    chicken breast. A curated table earns its authority by refusing to guess.
    """
    assert food_facts.lookup(query) is None, (
        f"{query!r} is not in the table and must not be answered by a near miss"
    )
