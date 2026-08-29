"""Deciding what a food actually contains, from several fallible sources.

The old arrangement asked USDA, compared its energy density against the model's
own guess, and took USDA unless the two disagreed by more than 1.75x. That looks
like a safety net and is not one, because it can only catch a source being wrong
*on its own*. A user logged "tea with milk and sugar" and got 1 kcal: the model
had named the item for the whole drink while pricing plain tea, USDA's brewed tea
agreed, and the check saw two sources concurring and shipped it.

So the decision is restructured around a different question. Not "do my two
sources agree" but "is this answer possible at all".

  1. A curated table of things people log constantly. A hit ends the matter.
     Deterministic, exact, no network call. Chai is 38 kcal/100 g here and cannot
     become 1 no matter what any other layer thinks.

  2. USDA, but only a row that passes a relevance test AND agrees with the
     model's density. Both must hold. Relevance stops a savoury pancake matching
     a keto frozen dessert; agreement stops dry Idli Mix pricing a steamed idli.

  3. The model's own estimate, when nothing better exists. Imprecise, but it has
     the useful property of never being absurd.

  4. Floors that apply to whatever came out of the above. If a food is described
     as containing milk, sugar, ghee, oil, butter, cream, cheese or nuts, there
     is an energy density below which the answer is simply impossible, whatever
     produced it. This is the layer that makes the original bug unrepresentable
     rather than merely unlikely.

The result carries how it was decided, so the UI can say "from our table",
"database" or "estimated" honestly instead of implying precision it lacks.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from . import food_facts

log = logging.getLogger(__name__)

Source = Literal["brand", "curated", "cofid", "usda", "cache", "estimated", "unresolved"]

#: A database row has to agree with the model's own density within this factor to
#: be trusted. Wider than it looks: cooked-vs-dry errors are threefold.
DENSITY_AGREEMENT = 1.75

#: Ingredients that cannot be present in quantity and leave a food near zero, with
#: the minimum kcal/100 g a food mentioning each can plausibly have. These are
#: floors for the *finished* food, deliberately set low enough that a genuinely
#: dilute preparation still passes — a floor that fires on correct data is worse
#: than no floor.
CALORIC_MARKERS: tuple[tuple[tuple[str, ...], float, str], ...] = (
    # Single words only: matching is word-by-word, so a two-word marker could
    # never fire. "fried" already covers "deep fried", and "milk" covers
    # "condensed milk" at a lower floor, which errs the safe way.
    (("ghee", "butter", "oil", "clarified", "fried"), 25.0, "cooked in fat"),
    (("cream", "malai", "khoya"), 30.0, "containing cream"),
    (("cheese", "paneer", "mayonnaise", "mayo"), 40.0, "containing cheese or paneer"),
    (("nut", "nuts", "almond", "almonds", "cashew", "cashews", "peanut", "peanuts", "coconut", "badam"),
     40.0, "containing nuts"),
    (("sugar", "honey", "jaggery", "gur", "syrup", "sweetened"), 15.0, "sweetened"),
    (("milk", "doodh", "curd", "yoghurt", "yogurt", "dahi"), 18.0, "containing milk"),
)

#: Words that cancel a nearby marker: "sugar free", "no milk", "unsweetened".
NEGATIONS = frozenset({"free", "less", "without", "no", "zero", "unsweetened", "sugarfree", "skip"})

#: How many words either side of a marker are searched for a negation. Three back
#: covers "unsweetened almond milk", where the negation is not adjacent.
NEGATION_WINDOW_BEFORE = 3
NEGATION_WINDOW_AFTER = 2


@dataclass
class Resolved:
    """One food, priced, with its provenance."""

    name: str
    grams: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float | None
    source: Source
    matched_name: str | None
    confidence: float
    food_item_id: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def density(self) -> float:
        return self.calories / self.grams * 100 if self.grams > 0 else 0.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def marker_floor(description: str) -> tuple[float, str] | None:
    """Lowest credible energy density for a food described this way.

    Returns ``(kcal_per_100g, reason)`` or None.

    Matching is on whole words. Substring matching looked adequate and was not:
    "oil" sits inside "boiled", so a boiled potato acquired a fried-food floor,
    and "butter" inside "buttermilk" would have pushed a 20 kcal drink up to 25.

    Negation is searched by word rather than by character distance. A character
    window missed "unsweetened almond milk", because counting backwards from
    "milk" landed inside "unsweetened" and split it — the negation was there and
    went unseen.
    """
    words_in_text = re.findall(r"[a-z]+", description.lower())

    def negated(index: int) -> bool:
        start = max(0, index - NEGATION_WINDOW_BEFORE)
        end = index + NEGATION_WINDOW_AFTER + 1
        return any(word in NEGATIONS for word in words_in_text[start:end])

    best: tuple[float, str] | None = None
    for markers, floor, reason in CALORIC_MARKERS:
        marker_set = set(markers)
        for index, word in enumerate(words_in_text):
            if word not in marker_set or negated(index):
                continue
            if best is None or floor > best[0]:
                best = (floor, reason)
            break

    return best


def _scale(per_100g: dict[str, Any], grams: float) -> dict[str, float | None]:
    factor = max(0.0, grams) / 100.0

    def value(key: str) -> float | None:
        raw = per_100g.get(key)
        return round(float(raw) * factor, 1) if raw is not None else None

    return {
        "calories": round(_num(per_100g.get("calories_per_100g")) * factor, 1),
        "protein_g": value("protein_per_100g") or 0.0,
        "carbs_g": value("carbs_per_100g") or 0.0,
        "fat_g": value("fat_per_100g") or 0.0,
        "fiber_g": value("fiber_per_100g"),
    }


def from_curated(name: str, query: str, grams: float) -> Resolved | None:
    """First and best answer, when the food is one we have written down."""
    fact = food_facts.lookup(name) or food_facts.lookup(query)
    if fact is None:
        return None

    scaled = _scale(food_facts.as_item(fact), grams)
    notes = [f"Matched our own table: {fact.name}."]
    if fact.note:
        notes.append(fact.note)
    return Resolved(
        name=name,
        grams=grams,
        calories=scaled["calories"],
        protein_g=scaled["protein_g"] or 0.0,
        carbs_g=scaled["carbs_g"] or 0.0,
        fat_g=scaled["fat_g"] or 0.0,
        fiber_g=scaled["fiber_g"],
        source="curated",
        matched_name=fact.name,
        # Curated entries are the one source we are sure about.
        confidence=0.95,
        notes=notes,
    )


def database_agrees(row_density: float, model_density: float) -> bool:
    """Is a database row's energy density consistent with the model's estimate?"""
    if row_density <= 0 or model_density <= 0:
        return True  # nothing to compare; other gates still apply
    ratio = row_density / model_density
    return 1 / DENSITY_AGREEMENT <= ratio <= DENSITY_AGREEMENT


def apply_floor(resolved: Resolved, description: str) -> Resolved:
    """Raise an impossible answer to the least it could credibly be.

    The last line of defence, and the only one that does not depend on any source
    being right. A drink described as containing milk and sugar cannot be 0.8
    kcal/100 g however confidently a database says so, and rather than discard the
    entry we lift it to the floor and say we did.
    """
    floor = marker_floor(description)
    if floor is None or resolved.grams <= 0:
        return resolved

    minimum, reason = floor
    if resolved.density >= minimum:
        return resolved

    factor = resolved.grams / 100.0
    corrected = round(minimum * factor, 1)
    log.info(
        "Floor applied to %r (%s): %.0f -> %.0f kcal (%.1f -> %.1f kcal/100g)",
        resolved.name,
        reason,
        resolved.calories,
        corrected,
        resolved.density,
        minimum,
    )

    scale = corrected / resolved.calories if resolved.calories > 0 else 0.0
    return Resolved(
        name=resolved.name,
        grams=resolved.grams,
        calories=corrected,
        # Macros scale with the correction when there were any; when the row was
        # essentially empty there is nothing to scale, so carbohydrate carries it,
        # which is right for the sweetened and milky cases this mostly catches.
        protein_g=round(resolved.protein_g * scale, 1) if scale else resolved.protein_g,
        carbs_g=round(resolved.carbs_g * scale, 1) if scale else round(corrected / 4, 1),
        fat_g=round(resolved.fat_g * scale, 1) if scale else 0.0,
        fiber_g=resolved.fiber_g,
        source=resolved.source,
        matched_name=resolved.matched_name,
        confidence=min(resolved.confidence, 0.4),
        food_item_id=resolved.food_item_id,
        notes=[
            *resolved.notes,
            f"Raised to the minimum for something {reason} — the matched figure was "
            f"too low to be possible.",
        ],
    )


def reconcile_total(
    items: list[Resolved], meal_estimate: float, *, shortfall_ratio: float = 0.6
) -> tuple[list[Resolved], str | None]:
    """Check the parts against an independently estimated whole.

    Every per-item gate can pass while the breakdown as a whole is still missing
    an ingredient — which is exactly what happened with the chai, where the milk
    was never emitted as an item at all. The model's own view of the total is the
    only figure computed without reference to the item list, so it is the only one
    that can catch that.

    A shortfall does not license inventing a row, so the items are left alone and
    the caller gets a warning to surface.
    """
    if meal_estimate <= 0 or not items:
        return items, None

    total = sum(item.calories for item in items)
    if total >= meal_estimate * shortfall_ratio:
        return items, None

    log.info(
        "Item total %.0f kcal is well under the %.0f kcal estimated for the whole meal",
        total,
        meal_estimate,
    )
    return items, (
        f"These items add up to {total:.0f} kcal, but the description reads more like "
        f"{meal_estimate:.0f}. Something may be missing — check before saving."
    )
