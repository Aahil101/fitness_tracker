"""What the curated table must refuse to answer.

Every case here is a figure the table once gave confidently and wrongly, and the
pattern in all of them is the pattern of the original 1 kcal chai: the food was
matched on a word that was not what the food is.

Accuracy of the numbers themselves is covered by test_indian_accuracy.py, which
checks them against a composition table. This file is about the step before that —
deciding which number the food gets — because a right number attached to the wrong
food is the failure that actually reaches a user.
"""

from __future__ import annotations

import pytest

from app.services import food_facts


def test_a_description_of_a_food_is_not_a_match_on_what_it_is_served_with() -> None:
    """The model names a food and then describes it, and the description is a trap.

    Asked about misal pav it returned "pav (soft yeast dinner rolls, typically
    served with butter)". Every word of that reaches the matcher, so the alias
    "butter" qualified — and because it was the only candidate it won on its own,
    pricing a 60 g roll at 430 kcal with 48.6 g of fat. The head-noun test existed
    but only ranked candidates; it did not admit them.
    """
    fact = food_facts.lookup("pav (soft yeast dinner rolls, typically served with butter)")
    assert fact is not None
    assert fact.name == "pav"
    assert fact.kcal == pytest.approx(254, abs=1)


@pytest.mark.parametrize(
    ("described", "accompaniment"),
    [
        ("roti (served with ghee)", "ghee"),
        ("rice (eaten with dal)", "dal, cooked"),
        ("dosa (with butter on top)", "butter"),
        ("chapati (usually eaten with butter)", "butter"),
    ],
)
def test_the_accompaniment_never_prices_the_food(described: str, accompaniment: str) -> None:
    """Whatever this matches, it must not be the thing named in the brackets."""
    fact = food_facts.lookup(described)
    if fact is None:
        return  # falling through to a composition table is a fine outcome
    assert fact.name != accompaniment, f"{described!r} was priced as {accompaniment}"


@pytest.mark.parametrize(
    ("dish", "component", "component_kcal"),
    [
        ("pav bhaji", "pav", 254),
        ("vada pav", "vada", 290),
        ("dal makhani", "dal, cooked", 116),
    ],
)
def test_a_dish_is_not_priced_as_the_one_part_of_it_we_hold(
    dish: str, component: str, component_kcal: float
) -> None:
    """Answering with the component silently drops the rest of the plate.

    Vada pav was answering 290 kcal — the fritter alone, no bread. Dal makhani was
    answering 116, the figure for plain boiled dal, for a dish finished with cream
    and butter. Both under-count, which is the direction that costs a person their
    deficit without telling them.

    They are declined here rather than estimated because the butter is most of the
    difference and varies by kitchen, so any single figure would be confidently
    wrong. The model prices the whole description instead, and labels it an
    estimate. An entry belongs here the moment there is a figure worth trusting.
    """
    assert food_facts.lookup(dish) is None, f"{dish} must not resolve here"

    held = food_facts.lookup(component)
    assert held is not None
    assert held.kcal == pytest.approx(component_kcal, abs=1)


def test_declining_a_compound_does_not_disable_its_words_elsewhere() -> None:
    """"pav bhaji" declining must not stop "pav" resolving."""
    for query in ("pav", "2 pav", "ladi pav", "burger bun"):
        fact = food_facts.lookup(query)
        assert fact is not None, query
        assert fact.name == "pav"


def test_the_chai_case_still_holds() -> None:
    """The gate added above must not have narrowed what a milky sweet tea matches.

    Its head noun is "milk" while the entry's subject is tea, so a gate keyed on
    the entry's own subject would have rejected it and sent a 90 kcal cup back to
    a database that calls it 1 kcal. The requirement is only that the entry
    accounts for the head noun somewhere, not that it leads with it.
    """
    for query in ("milk tea with 1 spoon sugar", "chai with milk and sugar", "tea with milk"):
        fact = food_facts.lookup(query)
        assert fact is not None, query
        assert fact.kcal > 20, f"{query!r} came back at {fact.kcal} kcal/100 g"


def test_an_ingredient_in_a_dish_is_still_priced_as_the_ingredient() -> None:
    """The other direction: "ghee (added to pongal)" is ghee, not a serving of pongal."""
    ghee = food_facts.lookup("ghee (added to pongal)")
    assert ghee is not None
    assert ghee.name == "ghee"

    sugar = food_facts.lookup("sugar (added to tea)")
    assert sugar is not None
    assert sugar.name == "sugar"
