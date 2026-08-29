"""Lookups against the bundled UK composition table.

Replaces USDA FoodData Central as the general-purpose nutrition source. The
reasoning is not that FDC's numbers are wrong — they are fine for the foods it
covers — but that it is the wrong *kind* of database for what this app is asked.

FDC's searchable bulk is packaged goods, so a query about home cooking returns the
nearest packet: "idli" gave a bag of Idli Mix at dry-weight density, three times
the energy of the steamed cake, and "jowar chilla" gave a branded keto frozen
dessert. Open Food Facts was considered and fails identically, being a product
catalogue by design — searching it for "idli" returns Rava idli *mix* at 365-404
kcal/100 g.

CoFID is a composition table, and it is preparation-aware in the way that matters
here: chapatis appear separately made with fat (328 kcal/100 g) and without (202),
samosas baked and deep fried, and there are around a hundred curry entries mostly
marked homemade.

Two further advantages follow from it being a file rather than a service. There is
no network call on the hot path, so resolution is immediate and cannot fail or rate
limit. And matching is ours, so the relevance rules that stopped FDC returning
nonsense apply here by construction rather than as a patch over someone's search
engine.

Licence: Crown copyright under the Open Government Licence v3.0, which permits
commercial use with attribution. ``ATTRIBUTION`` is surfaced in the app.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "cofid.json"

#: Words with no discriminating power in a food name.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "with", "and", "or", "in", "on", "for", "average",
        "retail", "sample", "samples", "weighed", "each", "per", "type", "types",
        "assorted", "mixed", "variety", "not", "no", "as", "to", "from", "made",
        "only", "flesh", "kernel", "edible", "portion",
    }
)

#: Preparation words. Present in both a query and a candidate they are strong
#: evidence; they are just not enough on their own to call a match.
_PREPARATION = frozenset(
    {
        "raw", "boiled", "steamed", "fried", "grilled", "roasted", "baked",
        "poached", "stewed", "microwaved", "canned", "dried", "frozen", "fresh",
        "homemade", "takeaway", "cooked", "uncooked", "reheated", "brewed",
        "infusion", "unsweetened", "sweetened", "salted", "unsalted",
        # Processing, not identity. Without these, "Porridge, made with whole
        # milk" scored level with "Milk, whole, pasteurised" for "whole milk".
        "pasteurised", "pasteurized", "sterilised", "uht", "longlife",
        "plain", "natural",
    }
)

#: States in which a food is not the food someone describes eating. Left merely
#: as preparation words these were invisible to the scoring, so a bare "rice"
#: matched wild rice *raw* at 343 kcal/100 g and "cooked pasta" matched dried
#: spaghetti at 329 — the threefold dry-weight overstatement that started all of
#: this, arriving from a new direction. Penalised rather than refused, because
#: someone weighing dry pasta is entitled to ask for it.
_UNPREPARED = frozenset({"raw", "dried", "dehydrated", "uncooked", "flour", "powder"})

#: Words that cancel the above. CoFID writes "Pasta, white, spaghetti, dried,
#: boiled in unsalted water" — dried pasta that has since been boiled, which is
#: cooked pasta. Penalising it for the word "dried" pushed "cooked pasta" onto
#: canned spaghetti in tomato sauce instead.
_COOKED = frozenset(
    {
        "boiled", "cooked", "steamed", "fried", "grilled", "baked", "roasted",
        "poached", "stewed", "microwaved", "reheated", "toasted",
    }
)

#: Categories that make a candidate a different kind of food from the query.
#: Mirrors the rule that stopped a savoury pancake matching a frozen dessert.
_CONFLICTS = (
    "dessert", "ice cream", "candy", "chocolate", "cake", "biscuit", "cookie",
    "syrup", "soft drink", "supplement", "infant", "baby", "pet", "dog", "cat",
    "sandwich", "burger", "pizza", "nugget", "casserole", "salad",
    "powder", "mix", "dry",
)
# Deliberately short. Products built out of an ingredient — banana bread, creme
# egg, fish fingers — are refused by the head-noun gate below, which is stricter
# than a keyword list and needs no maintenance. Only genuinely different
# categories are named here.


@dataclass(frozen=True)
class Food:
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fibre_g: float | None
    group: str
    description: str

    def as_item(self) -> dict[str, Any]:
        """Shape it like the nutrition rows the resolver already handles."""
        return {
            "name": self.name,
            "calories_per_100g": self.kcal,
            "protein_per_100g": self.protein_g,
            "carbs_per_100g": self.carbs_g,
            "fat_per_100g": self.fat_g,
            "fiber_per_100g": self.fibre_g,
            "source": "cofid",
        }


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("(", " ").replace(")", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Spelling variants that would otherwise miss each other entirely.
_SYNONYMS = {
    "yoghurt": "yogurt",
    "yoghourt": "yogurt",
    "chapatti": "chapati",
    "chappati": "chapati",
    "curd": "yogurt",
    "aubergine": "aubergine",
    "brinjal": "aubergine",
    "ladyfinger": "okra",
    "bhindi": "okra",
    "capsicum": "pepper",
    "coriander": "coriander",
    "dhania": "coriander",
    "channa": "chickpea",
    "chana": "chickpea",
    "kabuli": "chickpea",
    "atta": "wheat",
    "maida": "wheat",
    "curds": "yogurt",
}


def _stem(word: str) -> str:
    """Crude singulariser, applied identically to queries and to the table.

    The -oes plural needs its own case: trimming one letter from "potatoes" gives
    "potatoe", which matches nothing, so "potato" found no potatoes at all.
    """
    if len(word) < 4 or not word.endswith("s") or word.endswith(("ss", "us")):
        return word
    if word.endswith("oes"):  # potatoes, tomatoes, mangoes
        return word[:-2]
    if word.endswith("ies"):  # berries -> berry
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes", "zes")):  # dishes -> dish
        return word[:-2]
    return word[:-1]


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        _SYNONYMS.get(_stem(word), _stem(word))
        for word in _normalise(text).split()
        if word not in _STOPWORDS and len(word) > 1 and not word.isdigit()
    )


@dataclass(frozen=True)
class _Entry:
    food: Food
    tokens: frozenset[str]
    content: frozenset[str]  # tokens excluding preparation words
    #: Content words of the name's first comma-separated segment.
    #:
    #: CoFID names foods "head noun, qualifier, qualifier": "Egg, chicken, whole,
    #: boiled", "Milk, whole, pasteurised". That convention is a structural fact
    #: about the dataset, and using it is what finally stopped the matching
    #: mistaking a food for a product built out of it — "egg" found Creme egg and
    #: then Egg nog, "banana" found banana bread and then banana split, because
    #: token overlap alone cannot tell a head noun from a modifier.
    head: frozenset[str]
    #: The segment after a leading category word, where there is one: "Bread,
    #: naan" and "Cheese, Paneer" file the food under its category, so naan and
    #: paneer are never the first segment. Matching here is allowed but scores
    #: lower, so a food named directly always beats one reached this way — which
    #: is what stops "egg" landing on "Rice, egg fried".
    alt_head: frozenset[str]


#: CoFID files some foods under a broad category first: "Bread, naan, retail",
#: "Cheese, Paneer", "Curry, chicken korma". Read literally, the head noun of
#: those is the category, so a search for naan or paneer matched nothing at all.
#: Where a name leads with one of these, the following segment is the real head.
_CATEGORY_PREFIXES = frozenset(
    {
        "bread", "cheese", "curry", "milk", "oil", "flour", "juice", "rice",
        "pasta", "yogurt", "fish", "nuts", "soup", "sauce", "drink", "cereal",
        "biscuits", "cake", "pie", "pudding", "egg", "eggs", "meat", "beans",
    }
)


@lru_cache(maxsize=1)
def _table() -> tuple[tuple[_Entry, ...], str]:
    """Parse the bundled file once, on first use."""
    if not DATA_FILE.exists():
        return (), ""

    payload = json.loads(DATA_FILE.read_text())
    entries: list[_Entry] = []
    for row in payload.get("foods", []):
        food = Food(
            name=row["n"],
            kcal=float(row["k"]),
            protein_g=float(row.get("p") or 0.0),
            carbs_g=float(row.get("c") or 0.0),
            fat_g=float(row.get("f") or 0.0),
            fibre_g=float(row["fb"]) if row.get("fb") is not None else None,
            group=str(row.get("g") or ""),
            description=str(row.get("d") or ""),
        )
        tokens = _tokens(f"{food.name} {food.description}")
        segments = [segment for segment in food.name.split(",") if segment.strip()]
        head_tokens = _tokens(segments[0]) if segments else frozenset()
        alt_tokens: frozenset[str] = frozenset()
        if len(segments) > 1 and head_tokens and head_tokens <= _CATEGORY_PREFIXES:
            alt_tokens = frozenset(_tokens(segments[1]) - _PREPARATION)
        entries.append(
            _Entry(
                food=food,
                tokens=tokens,
                content=frozenset(tokens - _PREPARATION),
                head=frozenset(head_tokens - _PREPARATION),
                alt_head=alt_tokens,
            )
        )
    return tuple(entries), str(payload.get("attribution") or "")


def attribution() -> str:
    return _table()[1]


def count() -> int:
    return len(_table()[0])


def _conflicts(query: str, candidate: str) -> bool:
    lowered_query, lowered_candidate = query.lower(), candidate.lower()
    return any(
        word in lowered_candidate and word not in lowered_query for word in _CONFLICTS
    )


def search(query: str, limit: int = 5) -> list[Food]:
    """Best matching foods, most specific first.

    Scored rather than ranked by a remote relevance engine, which is the point:
    every rule here is one we chose.

    The gate is structural. CoFID names a food "head noun, qualifier, qualifier",
    so a candidate qualifies only when the query accounts for its entire head —
    which is how "egg" stops matching Creme egg and Egg nog, and "banana" stops
    matching banana bread. Ranking among the survivors is then just a matter of
    which qualifiers the query asked for.
    """
    entries, _ = _table()
    query_tokens = _tokens(query)
    content_tokens = query_tokens - _PREPARATION
    if not entries or not content_tokens:
        return []

    scored: list[tuple[float, int, Food]] = []
    for entry in entries:
        # The candidate's head noun must be *entirely* accounted for by the query.
        # "Egg nog" leads with two content words and the query supplies one, so it
        # is a different food and is refused outright rather than ranked low.
        via_head = bool(
            entry.head and (entry.head & content_tokens) and not (entry.head - content_tokens)
        )
        via_alt = bool(
            entry.alt_head
            and (entry.alt_head & content_tokens)
            and not (entry.alt_head - content_tokens)
        )
        if not (via_head or via_alt):
            continue
        if _conflicts(query, f"{entry.food.name} {entry.food.description}"):
            continue
        matched_head = entry.head if via_head else entry.alt_head

        # Past that gate, rank on the qualifiers: reward the ones the query asked
        # for, charge for the ones it did not.
        qualifiers = entry.content - matched_head
        explained = qualifiers & content_tokens
        unexplained = qualifiers - content_tokens
        prep_shared = (query_tokens & entry.tokens) & _PREPARATION
        # Dry or raw when nothing in the query asked for it — unless it has since
        # been cooked, in which case the dry state is just provenance.
        unprepared: frozenset[str] = frozenset()
        if not (entry.tokens & _COOKED):
            unprepared = (entry.tokens & _UNPREPARED) - query_tokens

        score = (
            len(matched_head & content_tokens) * 2.0
            + len(explained) * 1.0
            + len(prep_shared) * 0.5
            - len(unexplained) * 0.5
            # Reached through a category prefix rather than named directly.
            - (0.0 if via_head else 1.5)
            - len(unprepared) * 2.5
        )
        scored.append((score, -len(entry.tokens), entry.food))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [food for _score, _tiebreak, food in scored[:limit]]


def best_match(query: str) -> Food | None:
    results = search(query, limit=1)
    return results[0] if results else None
