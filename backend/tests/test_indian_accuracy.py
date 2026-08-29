"""Our Indian figures, held against an independently measured dataset.

This is the cross-check that answers "are the numbers actually right", as distinct
from "does the plumbing work". It is not circular: our curated values were authored
from standard composition values and ordinary recipes, CoFID was imported from a
national lab dataset, and neither was derived from the other. CoFID turns out to
carry a good deal of Indian cooking — around a hundred curry entries, the breads,
the fried snacks, sambar, lassi, raita.

Comparison is per 100 g so that portion guesswork cannot flatter the result. The
tolerance is 25%, which sounds loose and is not: two cooks making the same dal
differ by about that, while the failure this whole effort exists to prevent was an
answer out by a factor of ten.

Where CoFID lists several preparations of a dish the reference is the span between
them, because a chapati made with ghee and one made without differ by 60% and both
are chapatis. Demanding a single number would be demanding the wrong thing.
"""

from __future__ import annotations

import pytest

from app.services import cofid, food_facts

TOLERANCE = 0.25

# (our name, CoFID entry names, note)
COMPARISONS: list[tuple[str, tuple[str, ...], str]] = [
    ("roti", ("Chapatis, made without fat", "Chapatis, made with fat, retail"), "with/without fat"),
    ("paratha", ("Paratha, homemade",), ""),
    ("naan", ("Bread, naan, retail",), ""),
    ("sambar", ("Sambar, homemade",), ""),
    (
        "dal, cooked",
        ("Curry, chick pea dhal, homemade", "Curry, chick pea, UK type, homemade"),
        "CoFID's dhal is thicker than a thin toor dal",
    ),
    (
        "chicken curry",
        (
            "Curry, chicken korma, homemade",
            "Curry, chicken tikka masala, retail, reheated",
            "Curry, chicken vindaloo, homemade",
        ),
        "korma through vindaloo",
    ),
    ("biryani, chicken", ("Biryani, chicken, takeaway", "Curry, lamb biryani, homemade"), ""),
    ("sweet lassi", ("Lassi, sweetened",), ""),
    ("curd", ("Yogurt, whole milk, plain",), ""),
    ("whole milk", ("Milk, whole, pasteurised, average",), ""),
    ("toned milk", ("Milk, semi-skimmed, pasteurised, average",), ""),
    ("baked beans", ("Baked beans, canned in tomato sauce",), ""),
    ("ghee", ("Ghee, butter",), ""),
    ("butter", ("Butter, salted",), ""),
    ("vegetable oil", ("Oil, vegetable, average",), ""),
    ("boiled egg", ("Eggs, chicken, whole, boiled",), ""),
    ("almonds", ("Almonds, flaked and ground",), ""),
    ("cooked pasta", ("Pasta, white, spaghetti, dried, boiled in unsalted water",), ""),
    ("white bread", ("Bread, white, average",), ""),
    ("banana", ("Bananas, flesh only",), ""),
    (
        "cooked chickpeas",
        ("Beans, chick peas, Kabuli, whole, dried, boiled in unsalted",),
        "CoFID 129 against USDA 164 — the gap is drainage",
    ),
]

#: Foods with no honest reference. Named rather than dropped: a silent omission
#: would inflate the pass rate, and anyone reading this should know which of our
#: figures are corroborated and which are not.
NO_REFERENCE = {
    "paneer curry": "CoFID has paneer only as cheese, never as a made dish",
    "cooked rajma": "CoFID lists rajma only as a curry thinned with gravy",
    "chutney, coconut": "no coconut chutney entry",
    "idli": "not a UK food",
    "dosa": "only a dosa filling entry exists",
    "ven pongal": "not a UK food",
    "upma": "not a UK food",
    "poha": "not a UK food",
    "jowar chilla": "not a UK food",
    "tea with milk and sugar": "CoFID's tea-with-milk is a splash in a mug, not boiled chai",
}


def _reference(names: tuple[str, ...]) -> tuple[float, float]:
    entries, _ = cofid._table()
    by_name = {entry.food.name.lower(): entry.food for entry in entries}
    values: list[float] = []
    for name in names:
        food = by_name.get(name.lower()) or next(
            (f for key, f in by_name.items() if key.startswith(name.lower()[:34])), None
        )
        if food is not None:
            values.append(food.kcal)
    assert values, f"no CoFID entry matched {names!r} — the reference itself is broken"
    return min(values), max(values)


@pytest.mark.parametrize(
    ("our_name", "cofid_names", "note"),
    COMPARISONS,
    ids=[name for name, _, _ in COMPARISONS],
)
def test_our_figure_agrees_with_the_measured_one(
    our_name: str, cofid_names: tuple[str, ...], note: str
) -> None:
    fact = food_facts.lookup(our_name)
    assert fact is not None, f"{our_name!r} has left our table"

    low, high = _reference(cofid_names)
    if low != high:
        # A range: allow a little either side of it, since the extremes are
        # themselves particular recipes.
        margin = TOLERANCE * 0.4
        ok = low * (1 - margin) <= fact.kcal <= high * (1 + margin)
    else:
        ok = abs(fact.kcal - low) / low <= TOLERANCE

    assert ok, (
        f"{our_name!r} is {fact.kcal:g} kcal/100 g against a measured "
        f"{low:g}{f'-{high:g}' if high != low else ''}"
        + (f" ({note})" if note else "")
    )


@pytest.mark.parametrize("name", sorted(NO_REFERENCE))
def test_uncorroborated_figures_are_at_least_present_and_plausible(name: str) -> None:
    """These rest on authored values, so all that can be checked is sanity.

    Recorded here so the set is explicit. If one of them ever acquires a
    measured reference, it belongs in COMPARISONS instead.
    """
    fact = food_facts.lookup(name)
    assert fact is not None, f"{name!r} has left our table"
    assert 0 <= fact.kcal <= 950
    implied = fact.protein_g * 4 + fact.carbs_g * 4 + fact.fat_g * 9
    if fact.kcal >= 20:
        assert 0.7 <= implied / fact.kcal <= 1.3, (
            f"{name!r} claims {fact.kcal} kcal but its macros imply {implied:.0f}"
        )


def test_most_of_our_indian_figures_are_corroborated() -> None:
    """Guards the ratio, so the table cannot drift into being mostly unchecked."""
    corroborated = len(COMPARISONS)
    total = corroborated + len(NO_REFERENCE)
    assert corroborated / total >= 0.6, (
        f"only {corroborated} of {total} figures have an independent reference"
    )
