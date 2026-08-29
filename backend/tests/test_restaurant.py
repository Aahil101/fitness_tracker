"""Named restaurant items, priced from the chain's own published figures.

No composition table can answer "Domino's Peppy Paneer". A generic pizza entry and
a specific menu item differ by hundreds of calories, and the chain's own number is
the only correct one for its own product.
"""

from __future__ import annotations

import pytest

from app.services import restaurant

# Phrasings that must be recognised as a chain. The first two are verbatim from
# the report that prompted this, and both defeated a plain substring test:
# "domonis" misspells the brand, "mc aloo" splits a name the menu writes closed up.
DETECTED = [
    ("1 domonis peppy panner pizza", "Domino's"),
    ("1 mc aloo tikki burger", "McDonald's"),
    ("dominos margarita pizza", "Domino's"),
    ("dominoes cheese pizza", "Domino's"),
    ("domino's peppy paneer", "Domino's"),
    ("mcdonlads fries", "McDonald's"),
    ("mcaloo tikki", "McDonald's"),
    ("McD mcveggie", "McDonald's"),
    ("kfc zinger burger", "KFC"),
    ("a whopper", "Burger King"),
    ("burgerking fries", "Burger King"),
    ("pizza hut margherita", "Pizza Hut"),
    ("pizzahut pan pizza", "Pizza Hut"),
    ("subway veggie delite", "Subway"),
    ("starbucks caramel frappuccino", "Starbucks"),
    ("ccd cappuccino", "Cafe Coffee Day"),
    ("wow momo steamed momos", "Wow! Momo"),
]


@pytest.mark.parametrize(("text", "chain"), DETECTED)
def test_chain_names_are_recognised_however_they_are_typed(text: str, chain: str) -> None:
    assert restaurant.detect_chain(text) == chain


# Ordinary food must never be routed down the branded path: it would spend an API
# call from a twenty-a-day budget and return nothing.
NOT_BRANDED = [
    "dal with a bowl of rice",
    "milk tea with 1 spoon sugar",
    "homemade pizza",
    "chicken curry",
    "2 rotis and dal",
    "paneer butter masala",
    "dosa with chutney",
    "cheese sandwich",
    "onion samosa",
    "mixed vegetable curry",
    "boiled eggs and toast",
    "almonds and raisins",
    "grilled chicken breast",
    "a cup of chai",
]


@pytest.mark.parametrize("text", NOT_BRANDED)
def test_ordinary_food_is_not_mistaken_for_a_chain(text: str) -> None:
    assert restaurant.detect_chain(text) is None


def test_a_transposed_brand_name_is_still_recognised() -> None:
    """The specific reason the anagram rule exists.

    "domonis" and "dominos" are exact anagrams, which SequenceMatcher scores at
    0.71 — below any threshold safe to use generally — because it handles
    transpositions badly. A transposition is the commonest brand misspelling.
    """
    assert restaurant.detect_chain("domonis pizza") == "Domino's"
    assert restaurant.detect_chain("dominsos pizza") == "Domino's"


COUNTS = [
    ("dominos margarita pizza", 1.0),
    ("1 domonis peppy panner pizza", 1.0),
    ("2 mcaloo tikki burgers", 2.0),
    ("three kfc zingers", 3.0),
    ("a whopper", 1.0),
    ("half a dominos pizza", 0.5),
    ("quarter of a pizza", 0.25),
    ("a couple of mcaloo tikki", 2.0),
]


@pytest.mark.parametrize(("text", "expected"), COUNTS)
def test_the_portion_is_a_count_of_servings_not_a_guess_at_grams(
    text: str, expected: float
) -> None:
    """A chain sells units, so the only quantity worth reading is how many.

    Asked about "dominos margarita pizza" the model estimated 500 g, and scaling
    the published 688 kcal figure to that reported 1110 kcal for a single pizza.
    Fractions are checked before whole numbers because "half a pizza" contains the
    word "a".
    """
    assert restaurant.serving_count(text) == expected


def test_checked_items_resolve_without_an_api_call() -> None:
    known = restaurant.lookup_known("dominos margherita pizza", "Domino's")
    assert known is not None
    assert known.chain == "Domino's"
    # Domino's India publishes 688 kcal for a regular Margherita.
    assert 600 <= known.kcal <= 780
    assert known.source


KNOWN_ITEM_MATCHES = [
    # Misspellings people actually type must still find the item.
    ("dominos margarita pizza", True),
    ("dominos margherita pizza", True),
    ("dominos margarita", True),
    # A different pizza must NOT inherit this one's figure. Accepting any overlap
    # meant a Peppy Paneer matched Margherita on the shared word "pizza" and was
    # reported as 688 kcal with the chain's name attached.
    ("1 domonis peppy panner pizza", False),
    ("dominos peppy paneer pizza", False),
    ("dominos farmhouse pizza", False),
    ("dominos cheese pizza", False),
    ("dominos chicken dominator", False),
]


@pytest.mark.parametrize(("text", "should_match"), KNOWN_ITEM_MATCHES)
def test_a_checked_figure_is_not_lent_to_a_different_menu_item(
    text: str, should_match: bool
) -> None:
    found = restaurant.lookup_known(text, "Domino's") is not None
    assert found is should_match, (
        f"{text!r} {'should' if should_match else 'must not'} match the stored Margherita"
    )


def test_a_serving_converts_to_per_100g_without_losing_the_published_figure() -> None:
    """Menus publish per item; the rest of the pipeline works per 100 g.

    Round-tripping has to land back on the menu's number, or the conversion is
    quietly rewriting the very figure that made this path worth building.
    """
    known = restaurant.lookup_known("dominos margherita pizza", "Domino's")
    assert known is not None
    item = known.as_item()
    grams = item["serving_g"]
    recovered = item["calories_per_100g"] * grams / 100
    assert recovered == pytest.approx(known.kcal, abs=1.0)


def test_a_lookup_with_no_credentials_declines_rather_than_guesses() -> None:
    """A fabricated figure under a brand name looks authoritative and is not."""
    import asyncio

    from app.config import settings

    original = settings.gemini_api_key
    try:
        settings.gemini_api_key = ""
        result = asyncio.run(restaurant.lookup_published("dominos farmhouse", "Domino's"))
        assert result is None
    finally:
        settings.gemini_api_key = original


class TestGroundedReplyParsing:
    """The grounded call cannot use a response schema, so replies are parsed."""

    def test_plain_json(self) -> None:
        parsed = restaurant._extract_json('{"found": true, "kcal": 688}')
        assert parsed == {"found": True, "kcal": 688}

    def test_fenced_json(self) -> None:
        parsed = restaurant._extract_json('```json\n{"found": true, "kcal": 500}\n```')
        assert parsed is not None
        assert parsed["kcal"] == 500

    def test_json_with_surrounding_prose(self) -> None:
        parsed = restaurant._extract_json(
            'Here is what I found:\n{"found": true, "kcal": 320}\nHope that helps.'
        )
        assert parsed is not None
        assert parsed["kcal"] == 320

    def test_nested_braces_are_balanced_correctly(self) -> None:
        parsed = restaurant._extract_json('{"a": {"b": 1}, "kcal": 42}')
        assert parsed is not None
        assert parsed["kcal"] == 42

    def test_truncated_reply_yields_nothing(self) -> None:
        """Grounded replies get cut off when the token budget runs out."""
        assert restaurant._extract_json('{"found": true, "kcal": 6') is None

    def test_not_found_is_respected(self) -> None:
        parsed = restaurant._extract_json('{"found": false}')
        assert parsed == {"found": False}
