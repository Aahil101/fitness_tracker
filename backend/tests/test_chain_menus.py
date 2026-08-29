"""The chain menu table, and reading a description onto the right row of it.

Named menu items used to be priced by asking Gemini, with Google Search, what the
chain publishes. That path is gone: Search grounding is not part of Gemini's free
tier, so every key refuses it. What replaced it is each chain's own published
nutrition data, built offline into app/data/chain_menus.json by
scripts/build_chain_menus.py.

Two kinds of test here. The first read the shipped data and assert properties it
must have — the build script's own validation runs at build time, and a committed
data file can rot without anyone noticing. The second exercise the free text to
menu row match, where the errors are the interesting ones: a Peppy Paneer priced
as a Margherita, a large pizza priced as a regular, a whole pizza logged as 100 g.
"""

from __future__ import annotations

import pytest

from app.services import restaurant

TABLE = restaurant.menu_table()

#: Enough of the menu to notice a source moving or a parser regressing, chosen as
#: the items a person in India is most likely to type. Values are what the chain
#: publishes, so a failure here means either the data changed or we broke reading it.
PUBLISHED = [
    # description, chain, expected kcal, expected portion in grams
    ("1 dominos margherita pizza", "Domino's", 687.6, 250),
    ("1 domonis peppy panner pizza", "Domino's", 857.1, 311),
    ("dominos farmhouse pizza", "Domino's", 727.3, 264),
    ("1 mc aloo tikki burger", "McDonald's", 339.5, 146),
    ("mcdonalds mcspicy paneer burger", "McDonald's", 652.8, 199),
    ("mcdonalds veg maharaja mac", "McDonald's", 832.7, 306),
    ("pizza hut margherita", "Pizza Hut", 725.1, 248),
    ("taco bell crunchy taco supreme veg", "Taco Bell", 218.8, 103),
]


@pytest.mark.parametrize(("text", "chain", "kcal", "grams"), PUBLISHED)
def test_a_named_item_resolves_to_the_figure_its_chain_publishes(
    text: str, chain: str, kcal: float, grams: float
) -> None:
    assert restaurant.detect_chain(text) == chain
    found = restaurant.lookup_known(text, chain)
    assert found is not None, f"{text!r} is on {chain}'s published menu"
    assert found.kcal == pytest.approx(kcal, abs=1.0)
    assert (found.serving_g or 0) == pytest.approx(grams, abs=1.0)
    assert found.source, "a figure under a brand name has to say where it came from"


def test_the_table_holds_every_chain_the_build_produced() -> None:
    assert set(TABLE.by_chain) == {"Domino's", "McDonald's", "Pizza Hut", "Taco Bell"}
    assert TABLE.size > 500, f"only {TABLE.size} items; a parser has probably regressed"
    for chain, items in TABLE.by_chain.items():
        assert len(items) > 50, f"{chain} has only {len(items)} items"


def test_a_missing_data_file_does_not_take_food_logging_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The branded path is an enhancement; without it the generic sources still work."""
    from pathlib import Path

    monkeypatch.setattr(restaurant, "MENU_DATA_PATH", Path("/nonexistent/chain_menus.json"))
    restaurant.menu_table.cache_clear()
    try:
        assert restaurant.menu_table().size == 0
        assert restaurant.lookup_known("dominos margherita", "Domino's") is None
    finally:
        restaurant.menu_table.cache_clear()


# --- properties the shipped data has to have --------------------------------


def test_no_item_carries_an_impossible_energy_density() -> None:
    """Nothing on a menu is denser than pure fat, and nothing edible is 0 kcal/100 g.

    This is the check that would have caught reading Pepsi's 5.4 percent-of-RDA as
    its energy, and a 15 g dip's 155.7 mg of sodium as 155.7 kcal.
    """
    for chain, items in TABLE.by_chain.items():
        for item in items:
            grams = item.serving_g
            if not grams:
                continue
            per_100g = item.kcal / grams * 100
            assert per_100g <= 900, f"{chain} {item.name}: {per_100g:.0f} kcal/100 g"
            assert per_100g >= 1, f"{chain} {item.name}: {per_100g:.0f} kcal/100 g"


def test_every_item_agrees_with_its_own_macros() -> None:
    """Energy from protein, carbohydrate and fat has to land near the stated energy.

    A column read in the wrong order produces numbers that look perfectly
    reasonable on their own. This is the only cheap way to see it.

    Rows with no macros at all are skipped, not because they are fine but because
    there is nothing to check: Pizza Hut's salty lime soda states 43 kcal with
    every macro marked "not detected". A transposition cannot hide in a row that
    has no numbers to transpose.
    """
    offenders = []
    unmeasured = 0
    for chain, items in TABLE.by_chain.items():
        for item in items:
            if item.kcal < 40:
                continue  # percentages are meaningless on a cup of green tea
            if item.protein_g == 0 and item.carbs_g == 0 and item.fat_g == 0:
                unmeasured += 1
                continue
            derived = item.protein_g * 4 + item.carbs_g * 4 + item.fat_g * 9
            if abs(derived - item.kcal) / item.kcal > 0.25:
                offenders.append(f"{chain} {item.name}: stated {item.kcal:.0f}, macros {derived:.0f}")
    assert not offenders, offenders[:8]
    assert unmeasured <= TABLE.size * 0.02, (
        f"{unmeasured} of {TABLE.size} items have no macros at all, which is more "
        "than the sources leave blank — a parser has probably stopped reading them"
    )


def test_no_two_rows_share_a_name_within_a_chain() -> None:
    """Otherwise a lookup picks whichever comes first, silently.

    Pizza Hut lists the same pizza veg and non-veg with the marker in a column the
    PDF renders as a symbol, so the two rows arrive indistinguishable. The build
    drops such pairs rather than serving a coin flip between 736 and 850 kcal.
    """
    for chain, items in TABLE.by_chain.items():
        names = [item.name.lower() for item in items]
        assert len(names) == len(set(names)), f"{chain} has duplicate names"


def test_where_forms_of_a_product_differ_in_energy_exactly_one_is_standard() -> None:
    """"A Domino's Margherita" has to mean one thing.

    The same pizza runs 440 to 2,035 kcal across crusts and sizes. Rank 0 is the
    form an unqualified mention resolves to, so two of them would put that choice
    back in the hands of file order.

    Forms that tie on rank are only a problem when they disagree on the answer.
    Pizza Hut's fresh lime soda comes salty, sweet, and both, which are flavours
    rather than sizes and so carry no order — and all three are 43 kcal, so picking
    between them arbitrarily costs nothing. What must not happen is an arbitrary
    pick between two figures a person would notice.
    """
    for chain, items in TABLE.by_chain.items():
        by_product: dict[str, list[restaurant.BrandedFood]] = {}
        for item in items:
            by_product.setdefault(restaurant._product_of(item.name).lower(), []).append(item)

        for product, group in by_product.items():
            best = min(item.rank for item in group)
            standard = [item for item in group if item.rank == best]
            if len(standard) == 1:
                continue
            energies = [item.kcal for item in standard]
            spread = (max(energies) - min(energies)) / min(energies) * 100
            assert spread <= 10, (
                f"{chain} {product}: {len(standard)} forms tie for standard and "
                f"disagree by {spread:.0f}% ({min(energies):.0f}-{max(energies):.0f} kcal)"
            )


# --- reading a description onto a row ---------------------------------------


def test_a_bigger_size_costs_more_not_less() -> None:
    """Domino's publishes per serve, and a large pizza is four of them.

    Taking the published number as the whole pizza would have made a large
    Margherita 509 kcal — less than the regular, and 1,500 short.
    """
    regular = restaurant.lookup_known("dominos regular margherita", "Domino's")
    medium = restaurant.lookup_known("dominos medium margherita", "Domino's")
    large = restaurant.lookup_known("dominos large margherita", "Domino's")
    assert regular and medium and large
    assert regular.kcal < medium.kcal < large.kcal
    assert large.kcal > 1800, "a whole large pizza, not one slice of it"


@pytest.mark.parametrize(
    ("text", "expected_in_name"),
    [
        # Said nothing about size: the standard form.
        ("1 dominos margherita pizza", "New Hand Tossed-Regular"),
        # Said a size.
        ("dominos margherita medium", "Medium"),
        ("dominos large margherita", "Large"),
        # Said a crust.
        ("dominos cheese burst margherita", "Cheese Burst"),
        ("dominos thin crust margherita", "Thin Crust"),
    ],
)
def test_a_named_crust_or_size_is_honoured(text: str, expected_in_name: str) -> None:
    found = restaurant.lookup_known(text, "Domino's")
    assert found is not None
    assert expected_in_name in found.name, f"{text!r} gave {found.name!r}"


@pytest.mark.parametrize(
    ("text", "expected_kcal"),
    [
        ("mcdonalds 4 piece chicken mcnuggets", 169.7),
        ("mcdonalds 6 piece chicken mcnuggets", 254.5),
        ("mcdonalds 9 piece chicken mcnuggets", 381.8),
    ],
)
def test_a_piece_count_picks_the_right_box(text: str, expected_kcal: float) -> None:
    """The count is a single character, and the product matcher discards those.

    Scoring the variant on the filtered tokens meant the 6 was never seen and every
    box of nuggets resolved to the 4 piece at 170 kcal.
    """
    found = restaurant.lookup_known(text, "McDonald's")
    assert found is not None
    assert found.kcal == pytest.approx(expected_kcal, abs=1.0)


def test_a_single_letter_drink_size_still_matches_the_word() -> None:
    """McDonald's writes "Latte (L)". Nobody types "l"."""
    small = restaurant.lookup_known("mcdonalds small latte", "McDonald's")
    large = restaurant.lookup_known("mcdonalds large latte", "McDonald's")
    plain = restaurant.lookup_known("mcdonalds latte", "McDonald's")
    assert small and large and plain
    assert small.kcal < plain.kcal < large.kcal
    assert "(R)" in plain.name, "an unqualified latte is the regular"


def test_veg_and_non_veg_are_different_foods() -> None:
    """On an Indian menu this is the distinction people state most often.

    Treating "veg" and "non" as filler words left both rows with identical
    distinguishing words, so asking for the veg one returned the non-veg figure.
    """
    veg = restaurant.lookup_known("taco bell crunchy taco supreme veg", "Taco Bell")
    non_veg = restaurant.lookup_known("taco bell crunchy taco supreme non veg", "Taco Bell")
    assert veg and non_veg
    assert veg.name != non_veg.name
    assert "non veg" not in veg.name.lower()
    assert "non veg" in non_veg.name.lower()


def test_a_more_specific_product_wins_over_the_one_inside_it() -> None:
    """"Double Cheese Margherita" contains "Margherita" and is not it."""
    plain = restaurant.lookup_known("dominos margherita pizza", "Domino's")
    double = restaurant.lookup_known("dominos double cheese margherita", "Domino's")
    assert plain and double
    assert plain.name.startswith("Margherita")
    assert double.name.startswith("Double Cheese Margherita")
    assert plain.kcal != double.kcal


def test_an_item_the_chain_does_not_sell_finds_nothing() -> None:
    """Better no figure than the nearest thing on the menu.

    Reaching for the closest match is how a McAloo Tikki became "Burger, beef,
    grilled" with 37 g of protein.
    """
    for text in ("dominos biryani", "mcdonalds butter chicken", "pizza hut sushi"):
        chain = restaurant.detect_chain(text)
        assert chain is not None
        assert restaurant.lookup_known(text, chain) is None, text


# --- the arithmetic the rest of the pipeline does with the row ---------------


@pytest.mark.parametrize(("text", "chain"), [(t, c) for t, c, _, _ in PUBLISHED])
def test_the_per_100g_conversion_lands_back_on_the_published_figure(
    text: str, chain: str
) -> None:
    """The pipeline works per 100 g; menus publish per item.

    Every branded figure makes that round trip, so an error in it rewrites the very
    number that made this path worth building.
    """
    found = restaurant.lookup_known(text, chain)
    assert found is not None
    item = found.as_item()
    recovered = item["calories_per_100g"] * item["serving_g"] / 100
    assert recovered == pytest.approx(found.kcal, abs=1.0)


def test_an_inferred_weight_says_so() -> None:
    """Domino's publishes calories and no weights.

    Without a weight the serving defaulted to 100 g, so a whole pizza was logged as
    "100 g" — and that field is editable, so a user correcting it to a realistic 250
    would have tripled the calories. The weight is now derived from the energy, and
    the note has to admit that rather than presenting it as published.
    """
    found = restaurant.lookup_known("dominos margherita pizza", "Domino's")
    assert found is not None
    assert found.weight_inferred
    assert 200 <= (found.serving_g or 0) <= 320, "a regular pizza, not 100 g"
    assert "not the weight" in found.provenance
    assert "adjust" in found.provenance

    # McDonald's publishes weights, so nothing is inferred and nothing is claimed.
    burger = restaurant.lookup_known("mc aloo tikki burger", "McDonald's")
    assert burger is not None
    assert not burger.weight_inferred
    assert "not the weight" not in burger.provenance



# --- through the endpoint ---------------------------------------------------


PEPPY_PANEER_PARSE = {
    "items": [
        {
            "food_name": "Domino's Peppy Paneer Pizza",
            "usda_query": "paneer pizza",
            # What the model actually guesses for this, and deliberately wrong:
            # the published serving is what the chain sells, and the two must not
            # be mixed.
            "estimated_grams": 300,
            "confidence": 0.6,
            "quantity_text": "1",
            "fallback_calories_per_100g": 260,
            "item_calories": 780,
        }
    ],
    "meal_type": "dinner",
    "total_calories_estimate": 780,
}


def test_a_menu_item_is_served_with_the_published_portion_not_the_models_guess(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two numbers have to describe the same thing.

    The response paired the model's 300 g with the published 857 kcal, which is
    the chain's figure for a 311 g pizza. On its own that reads as a rounding
    quirk; it is not, because the app lets the user edit the portion. Correcting
    300 to a realistic weight rescaled a figure that was already exact.
    """
    from app.services import gemini, usda

    async def fake_parse(text: str):
        return PEPPY_PANEER_PARSE

    async def no_usda(query: str):
        return None

    monkeypatch.setattr(gemini, "parse_meal_text", fake_parse)
    monkeypatch.setattr(usda, "best_match", no_usda)

    body = client.post(
        "/api/ai/food-text", json={"text": "1 dominos peppy paneer pizza"}
    ).json()

    item = body["items"][0]
    published = restaurant.lookup_known("dominos peppy paneer pizza", "Domino's")
    assert published is not None

    assert item["resolution"] == "brand"
    # as_item() prefixes the chain, so the user sees whose figure this is.
    assert item["matched_name"] == f"Domino's {published.name}"
    assert item["calories"] == pytest.approx(published.kcal, abs=1.0)
    assert item["portion_g"] == pytest.approx(published.serving_g, abs=1.0)
    assert item["portion_g"] != 300, "the model's guess must not survive"
    # And the pair is self-consistent, which is what the frontend relies on when
    # the portion is edited.
    assert item["calories"] / item["portion_g"] * 100 == pytest.approx(
        published.kcal / (published.serving_g or 1) * 100, abs=1.0
    )
