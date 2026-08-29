"""Named restaurant items, priced from what the chain itself publishes.

A composition table cannot answer "Domino's Peppy Paneer pizza". Chains publish
their own figures, those figures are the truth for that product, and no amount of
looking up "pizza" in a food table will reproduce them — a generic pizza entry and
a specific menu item differ by hundreds of calories.

So branded items take a different route entirely:

  1. A small table of items whose published figures have been checked. Instant,
     and it spends no API quota on the things people order most.
  2. Otherwise a Gemini call with Google Search grounding, which reads the chain's
     published nutrition and cites where it came from. Verified working: asked for
     a Domino's India Margherita it searched the chain's calorie guide and returned
     688 kcal.
  3. The answer is cached in ``food_items`` so any given menu item costs one
     lookup ever, for everybody.

Caching is load-bearing rather than an optimisation. Gemini's free tier allows
twenty requests a day in total, shared with ordinary meal parsing, so an uncached
grounded lookup per pizza would exhaust the day's quota in an afternoon.

Nothing here is presented as our own measurement. The resolution is reported as
``brand`` and carries the source, because a figure from a menu is exactly as good
as the menu and should be recognisable as such.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings
from ..http import get_http_client
from . import keypool
from .keypool import get_pool

log = logging.getLogger(__name__)

#: Grounding needs a model the whole pool can reach; see config.gemini_model.
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: Grounded answers spend tokens on retrieved pages, so the budget is generous.
MAX_OUTPUT_TOKENS = 2048
REQUEST_TIMEOUT_S = 90.0


#: Chains whose menus are worth looking up by name. Matching is on word
#: boundaries against the whole description, so "mcdonalds" and "mc donalds" both
#: land, and "dominos" is not found inside some unrelated word.
CHAINS: dict[str, tuple[str, ...]] = {
    "Domino's": ("dominos", "domino", "dominoes"),
    "McDonald's": ("mcdonalds", "mcdonald", "mcd", "macdonalds", "mcds"),
    "Pizza Hut": ("pizza hut", "pizzahut"),
    "KFC": ("kfc", "kentucky fried"),
    "Burger King": ("burger king", "burgerking"),
    "Subway": ("subway",),
    "Starbucks": ("starbucks",),
    "Cafe Coffee Day": ("cafe coffee day", "ccd"),
    "Taco Bell": ("taco bell", "tacobell"),
    "Wow! Momo": ("wow momo", "wowmomo"),
    "Haldiram's": ("haldiram", "haldirams"),
    "Faasos": ("faasos",),
    "Behrouz Biryani": ("behrouz",),
    "Biryani By Kilo": ("biryani by kilo", "bbk"),
    "Barista": ("barista",),
    "Chaayos": ("chaayos",),
    "Third Wave Coffee": ("third wave",),
    "Dunkin'": ("dunkin", "dunkin donuts"),
    "Papa John's": ("papa johns", "papa john"),
    "Costa Coffee": ("costa coffee",),
}

#: Product names that on their own imply a chain.
IMPLIED_CHAIN: dict[str, str] = {
    "mcaloo": "McDonald's",
    "mcveggie": "McDonald's",
    "mcspicy": "McDonald's",
    "mcpuff": "McDonald's",
    "mcflurry": "McDonald's",
    "maharaja mac": "McDonald's",
    "big mac": "McDonald's",
    "whopper": "Burger King",
    "zinger": "KFC",
    "peppy paneer": "Domino's",
    "farmhouse pizza": "Domino's",
    "frappuccino": "Starbucks",
}


@dataclass
class BrandedFood:
    """A menu item as the chain publishes it."""

    name: str
    chain: str
    serving_description: str
    serving_g: float | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    source: str
    confidence: float
    #: A size or crust, where the chain lists several of the same item. Empty when
    #: the item has only one form.
    size: str = ""
    #: What an unqualified mention means: 0 is the form a person gets by default.
    rank: int = 0
    #: True when the chain publishes energy but no weight, so the portion weight
    #: was derived from the energy. The energy is still exactly as published.
    weight_inferred: bool = False

    @property
    def provenance(self) -> str:
        """What to tell the user about where this figure came from."""
        note = f"{self.serving_description}, {self.source}"
        if self.weight_inferred:
            note += (
                f". {self.chain} publishes the calories but not the weight, so the "
                f"{self.serving_g:.0f} g shown is worked out from them — adjust it if "
                "you know better"
            )
        return note

    def as_item(self) -> dict[str, Any]:
        """Per-serving figures expressed per 100 g, for the shared scaling path.

        Menus publish per item, not per 100 g. Where a weight is given the
        conversion is exact; where it is not, the serving is treated as the
        portion so the arithmetic still lands on the published number.
        """
        grams = self.serving_g or 100.0
        factor = 100.0 / grams
        return {
            "name": f"{self.chain} {self.name}".strip(),
            "calories_per_100g": round(self.kcal * factor, 2),
            "protein_per_100g": round(self.protein_g * factor, 2),
            "carbs_per_100g": round(self.carbs_g * factor, 2),
            "fat_per_100g": round(self.fat_g * factor, 2),
            "fiber_per_100g": None,
            "serving_g": grams,
            "source": "brand",
            "note": self.provenance,
        }


# ---------------------------------------------------------------------------
# What the chains publish about their own menus
#
# Built offline by scripts/build_chain_menus.py from each chain's own nutrition
# data: Domino's India's menu pages, and the McDonald's, Pizza Hut and Taco Bell
# India nutrition booklets. Loaded from a data file rather than written out here
# because there are several hundred items and they change with the menu.
#
# This replaced a single hand-written entry plus a live grounded lookup for
# everything else. The lookup is dead on Gemini's free tier — Search grounding is
# not included, so every key refuses it — and the alternative was showing the
# model's guess with a brand name attached, which reads as authoritative and is
# not. These figures are exact, free, instant and the same every time.
# ---------------------------------------------------------------------------
MENU_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "chain_menus.json"


@dataclass(frozen=True)
class MenuTable:
    by_chain: dict[str, tuple[BrandedFood, ...]]
    sources: dict[str, str]

    @property
    def size(self) -> int:
        return sum(len(items) for items in self.by_chain.values())


@lru_cache(maxsize=1)
def menu_table() -> MenuTable:
    """Parsed once per process; a few hundred rows, so it stays in memory."""
    try:
        raw = json.loads(MENU_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # A missing table must not take food logging down: the caller falls back
        # to the generic sources exactly as it did before this file existed.
        log.error("Could not load the chain menu table: %s", exc)
        return MenuTable(by_chain={}, sources={})

    by_chain: dict[str, tuple[BrandedFood, ...]] = {}
    sources: dict[str, str] = {}
    for chain, payload in (raw.get("chains") or {}).items():
        source = str(payload.get("source") or f"{chain} published figures")
        sources[chain] = source
        items = []
        for row in payload.get("items") or []:
            kcal = row.get("kcal")
            if not kcal:
                continue
            items.append(
                BrandedFood(
                    name=str(row.get("name") or ""),
                    chain=chain,
                    serving_description=str(row.get("serving_description") or "one serving"),
                    serving_g=row.get("serving_g"),
                    kcal=float(kcal),
                    protein_g=float(row.get("protein_g") or 0.0),
                    carbs_g=float(row.get("carbs_g") or 0.0),
                    fat_g=float(row.get("fat_g") or 0.0),
                    source=source,
                    # Published by the chain for its own product, so as certain as
                    # this app gets. Not 1.0: the match from free text to a menu
                    # row is still an inference.
                    confidence=0.95,
                    size=str(row.get("size") or ""),
                    rank=int(row.get("rank") or 0),
                    weight_inferred=bool(row.get("weight_inferred")),
                )
            )
        by_chain[chain] = tuple(items)

    log.info(
        "Chain menu table loaded: %d items across %d chains",
        sum(len(v) for v in by_chain.values()),
        len(by_chain),
    )
    return MenuTable(by_chain=by_chain, sources=sources)


def known_chains() -> list[str]:
    """Chains whose published figures we hold. Used by diagnostics."""
    return sorted(menu_table().by_chain)


def _normalise(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: How close a word has to be to a chain's name to count. People type "domonis"
#: for Domino's, and a brand nobody spells correctly is a brand nobody can log.
FUZZY_THRESHOLD = 0.82


#: Written-out counts people use instead of digits. Ordered, and fractions come
#: first: "half a pizza" contains "a", so checking whole numbers first read it as
#: a whole one.
_WORD_COUNTS: tuple[tuple[str, float], ...] = (
    ("half", 0.5),
    ("quarter", 0.25),
    ("couple", 2.0),
    ("two", 2.0),
    ("three", 3.0),
    ("four", 4.0),
    ("five", 5.0),
    ("six", 6.0),
    ("one", 1.0),
    ("an", 1.0),
    ("a", 1.0),
)


def serving_count(text: str) -> float:
    """How many servings the description asks for.

    Branded portions come from the menu, not from a guess at grams. A chain sells
    units, so the only thing worth reading out of the description is how many of
    them — asked for "dominos margarita pizza" the model estimated 500 g, and
    scaling the published 688 kcal to that produced 1110 for a single pizza.
    """
    lowered = _normalise(text)
    match = re.search(r"\b(\d+(?:\.\d+)?)\b", lowered)
    if match:
        value = float(match.group(1))
        # Guard against a size in the text being read as a count.
        if 0 < value <= 12:
            return value
    for word, value in _WORD_COUNTS:
        if re.search(rf"\b{word}\b", lowered):
            return value
    return 1.0


def detect_chain(text: str) -> str | None:
    """Which chain, if any, this description names.

    Matched three ways, because the two examples that prompted this feature both
    failed a plain substring test: "1 domonis peppy panner pizza" misspells the
    chain, and "1 mc aloo tikki burger" splits a product name that the menu writes
    closed up.
    """
    normalised = _normalise(text)
    if not normalised:
        return None
    padded = f" {normalised} "
    # "mc aloo tikki" and "mcalootikki" have to meet somewhere.
    squashed = normalised.replace(" ", "")

    for chain, aliases in CHAINS.items():
        for alias in aliases:
            plain = _normalise(alias)
            if f" {plain} " in padded or plain.replace(" ", "") in squashed:
                return chain
    for product, chain in IMPLIED_CHAIN.items():
        plain = _normalise(product)
        if f" {plain} " in padded or plain.replace(" ", "") in squashed:
            return chain

    # Nothing matched exactly. Try each word against the chain names, which is
    # where a misspelling gets caught.
    words = [word for word in normalised.split() if len(word) >= 4]
    for chain, aliases in CHAINS.items():
        for alias in aliases:
            plain = _normalise(alias).replace(" ", "")
            if len(plain) < 4:
                continue
            for word in words:
                if abs(len(word) - len(plain)) > 3:
                    continue
                # Same letters in the wrong order. "domonis" is an exact anagram
                # of "dominos", which SequenceMatcher scores at only 0.71 because
                # it handles transpositions badly — and a transposition is the
                # commonest way anyone misspells a brand. An ordinary food word
                # being an anagram of a chain name does not happen.
                if sorted(word) == sorted(plain):
                    return chain
                if SequenceMatcher(None, word, plain).ratio() >= FUZZY_THRESHOLD:
                    return chain
    return None


#: Words that appear in half the menu and so distinguish nothing.
#:
#: "veg" and "non" are deliberately absent. On an Indian menu they are the primary
#: distinction, not filler: Taco Bell lists a Crunchy Taco Supreme in both, 219 and
#: 241 kcal, and treating them as generic left both entries with identical
#: distinguishing words, so "crunchy taco supreme veg" resolved to whichever came
#: first — the non-veg one.
_GENERIC_PRODUCT_WORDS = frozenset(
    {
        "pizza", "burger", "sandwich", "sub", "wrap", "roll", "meal", "combo",
        "regular", "medium", "large", "small", "classic", "hand", "tossed",
        "crust", "size", "chicken", "cheese", "coffee", "shake",
    }
)

#: How close a word has to be to count as the same product word. "margarita" and
#: "margherita" score 0.84, "panner" and "paneer" 0.83 — both are how people
#: actually spell these — while "peppy" against "margherita" is 0.13.
PRODUCT_WORD_THRESHOLD = 0.8


def _spoken_words(text: str) -> list[str]:
    """The words available to match, including neighbours run together.

    Menus close up names that people space out: the item is a McAloo Tikki and the
    description says "mc aloo tikki". Joining adjacent words recovers that without
    loosening the per-word comparison, which is what mattered — "aloo" on its own
    is two characters short of "mcaloo" and a threshold loose enough to bridge that
    also matched "chicken" to "McChicken", so "mcdonalds butter chicken" came back
    as a McChicken Burger.
    """
    words = _normalise(text).split()
    joined = [words[i] + words[i + 1] for i in range(len(words) - 1)]
    return [w for w in [*words, *joined] if len(w) > 2]


def _same_word(spoken: str, wanted: str) -> bool:
    """Is this the same word, allowing for how people actually spell things?

    A misspelling substitutes or transposes letters. Adding a couple of letters to
    the front or back makes a different word: "chicken" is not "mcchicken", "veg"
    is not "veggie". Both of those score above 0.8 on plain similarity, so
    containment is checked separately and rules the match out.
    """
    if spoken == wanted:
        return True
    if abs(len(spoken) - len(wanted)) >= 2 and (spoken in wanted or wanted in spoken):
        return False
    return SequenceMatcher(None, spoken, wanted).ratio() >= PRODUCT_WORD_THRESHOLD

#: Sizes, crusts and counts: the words that choose between forms of one product.
#: Kept apart from the generic list because they are worthless for identifying the
#: product and decisive for identifying which of its forms was ordered.
_SIZE_WORDS = frozenset(
    {
        "regular", "personal", "medium", "small", "large", "extra",
        "piece", "pieces", "pcs", "slice", "slices",
        "burst", "pan", "thin", "wheat", "stuffed", "wholewheat",
    }
)


def _product_of(name: str) -> str:
    """The item without its bracketed size or crust: what the person names."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def _variant_of(name: str) -> str:
    return " ".join(re.findall(r"\(([^)]*)\)", name))


def lookup_known(text: str, chain: str) -> BrandedFood | None:
    """The chain's published figures for this item, if we hold them.

    Two decisions, in order.

    Which product. Every distinguishing word of the stored product name has to be
    present, allowing for misspelling. An earlier version accepted any overlap at
    all, which meant a Peppy Paneer matched the Margherita entry on the shared word
    "pizza" and was reported as 688 kcal with the chain's name on it. A confident
    wrong figure under a brand is worse than no figure. Requiring all of them also
    settles "double cheese margherita" in favour of that product over plain
    Margherita, because it is the more specific match that still fits.

    Then which form of it. Chains list the same pizza in three sizes and four
    crusts, 440 to 2,035 kcal for a Margherita, so this cannot be left to whichever
    row comes first. A size or crust named in the description wins; otherwise the
    lowest-ranked form is used, which is the one the menu treats as standard.
    """
    spoken = _spoken_words(text)
    if not spoken:
        return None

    def present(word: str) -> bool:
        return any(_same_word(said, word) for said in spoken)

    best_specificity = 0
    candidates: list[BrandedFood] = []
    for item in menu_table().by_chain.get(chain, ()):
        product = _normalise(_product_of(item.name))
        distinctive = [
            w for w in product.split() if len(w) > 2 and w not in _GENERIC_PRODUCT_WORDS
        ]
        if not distinctive or not all(present(word) for word in distinctive):
            continue
        if len(distinctive) > best_specificity:
            best_specificity, candidates = len(distinctive), [item]
        elif len(distinctive) == best_specificity:
            candidates.append(item)

    if not candidates:
        return None
    return _pick_variant(candidates, _normalise(text).split())


def _pick_variant(candidates: list[BrandedFood], said: list[str]) -> BrandedFood:
    """Among forms of the same product, the one the description asks for.

    Scored on the whole normalised description rather than the filtered product
    tokens, because the words that pick a form are exactly the ones product
    matching throws away: the sizes, and the piece counts. "6 piece chicken
    mcnuggets" was resolving to the 4 piece box at 170 kcal because the token list
    dropped everything shorter than three characters, so the 6 was never seen.
    """
    if len(candidates) == 1:
        return candidates[0]

    spoken = set(said)

    def score(item: BrandedFood) -> tuple[int, int]:
        # The stored size is the expanded form, which matters because McDonald's
        # writes drink sizes as a single letter: "Latte (L)" normalises to "latte
        # l", and nobody types "l", so "large latte" was resolving to the regular.
        words = set(_normalise(item.size).split())
        words |= {
            word
            for word in _normalise(_variant_of(item.name)).split()
            if word in _SIZE_WORDS or word.isdigit()
        }
        # Counts are written into the name for McDonald's boxes of nuggets.
        words |= set(re.findall(r"\d+", item.name))
        # Negative rank so that, at equal evidence, the standard form sorts first.
        return len(words & spoken), -item.rank

    return max(candidates, key=score)


PROMPT = """You look up the nutrition a restaurant chain publishes for its own menu items.

Item described by the user: {description}
Chain: {chain}

Find the chain's own published nutrition information for this item, preferring the
country's official menu or nutrition guide. Indian outlets publish different
figures from American ones for the same product name, so prefer India where the
chain operates there.

Reply with JSON only, no prose and no code fence:
{{"found": true, "name": "", "serving_description": "", "serving_g": 0,
  "kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0,
  "source": "", "confidence": 0.0}}

Rules:
* kcal, protein_g, carbs_g and fat_g are for ONE serving of the item as sold, not
  per 100 g.
* serving_g is the item's weight in grams if published, otherwise 0.
* source names where the figure came from, e.g. "Domino's India nutrition guide".
* confidence is 0-1: high when you found the chain's own published figure, low
  when you are reasoning from a similar item.
* If you cannot find anything for this item, reply {{"found": false}} and nothing
  else. Do not invent a number.
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a grounded reply.

    Grounded responses cannot be constrained by a response schema, so the model
    answers in prose-ish text and occasionally wraps the JSON in a fence.
    """
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        if cleaned[index] == "{":
            depth += 1
        elif cleaned[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


#: Search grounding is not part of Gemini's free tier. Every key answers a
#: grounded request with 429 RESOURCE_EXHAUSTED immediately — while the same keys
#: answer ordinary generateContent perfectly — so this is a missing capability,
#: not an allowance being consumed. Adding keys cannot fix it; only billing on the
#: project can. Until then, attempting it costs one wasted call per key and about
#: 1.5s of latency on every branded item, so a refusal from the whole pool turns
#: it off for a while rather than being rediscovered on the next pizza.
GROUNDING_BACKOFF_S = 6 * 60 * 60

_grounding_unavailable_until = 0.0


def grounding_available() -> bool:
    return time.monotonic() >= _grounding_unavailable_until


def _disable_grounding(reason: str) -> None:
    global _grounding_unavailable_until
    _grounding_unavailable_until = time.monotonic() + GROUNDING_BACKOFF_S
    log.warning(
        "Search grounding refused by every key (%s); not attempting it for %.0f h. "
        "Branded items will use the checked menu table or an estimate. Enabling "
        "billing on one Gemini project restores it.",
        reason,
        GROUNDING_BACKOFF_S / 3600,
    )


def reset_grounding_backoff() -> None:
    """For tests, and for anyone who has just enabled billing and wants it back."""
    global _grounding_unavailable_until
    _grounding_unavailable_until = 0.0


async def lookup_published(description: str, chain: str) -> BrandedFood | None:
    """Ask Gemini, with Google Search, what the chain publishes for this item.

    Returns None rather than a guess when nothing is found: a fabricated figure
    for a named product is worse than falling back to a generic food, because the
    brand name makes it look authoritative.
    """
    if not settings.gemini_configured or not grounding_available():
        return None

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": PROMPT.format(description=description, chain=chain)}],
            }
        ],
        # Grounding cannot be combined with a response schema, so the shape is
        # asked for in the prompt and parsed defensively.
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }

    # Grounded lookups are the most quota-hungry call the app makes, so they walk
    # the whole pool before giving up.
    #
    # They deliberately do not bench a key. A grounded refusal says nothing about
    # whether that key can still answer ordinary calls, and treating it as if it
    # did poisoned the pool: one Domino's lookup benched all five keys for an
    # hour, so /api/ai/status reported nothing available while every key was in
    # fact answering the coach and the meal parser normally. If a key really is
    # out of its daily allowance, the next plain call will find that out and bench
    # it for the right reason.
    pool = get_pool("gemini", settings.gemini_key_list)
    client = get_http_client()
    response = None
    refusals = 0
    keys = pool.healthy()
    for key in keys:
        try:
            attempt = await client.post(
                f"{GEMINI_URL}/{GEMINI_MODEL}:generateContent",
                # The key goes in a header, not the query string. As a query
                # parameter it was written verbatim into the logs, because httpx
                # logs the full URL of every request at INFO — so each grounded
                # lookup published a live credential to the Render log.
                headers={"x-goog-api-key": key.value},
                json=body,
                timeout=REQUEST_TIMEOUT_S,
            )
        except Exception as exc:  # network, timeout
            log.info("Grounded brand lookup failed for %r: %s", description, exc)
            continue
        if attempt.status_code < 400:
            response = attempt
            break
        verdict = keypool.classify(attempt.status_code, attempt.text[:200])
        log.info(
            "Grounded lookup got %s on one key for %r; %s",
            attempt.status_code,
            description,
            "trying the next" if verdict else "the request itself was refused",
        )
        if verdict is None:
            # Same request, same refusal on every key — spending the pool on it
            # only delays the fallback to a generic food.
            break
        refusals += 1

    if response is None:
        if keys and refusals == len(keys):
            _disable_grounding(f"{refusals} of {refusals} keys")
        # Not an error the user can act on: the caller has a checked menu table
        # and an estimate to fall back to, and both are better than a dead entry.
        return None

    payload = response.json()
    candidate = (payload.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)

    parsed = _extract_json(text)
    if not parsed or not parsed.get("found"):
        log.info("No published figure found for %r at %s", description, chain)
        return None

    kcal = _number(parsed.get("kcal"))
    if kcal <= 0:
        return None

    # Where the reply cited pages, name the first one: it is more use to the user
    # than the model's own summary of where it looked.
    grounding = candidate.get("groundingMetadata") or {}
    chunks = grounding.get("groundingChunks") or []
    cited = ""
    for chunk in chunks[:1]:
        cited = ((chunk.get("web") or {}).get("title") or "").strip()

    source = str(parsed.get("source") or "").strip() or cited or f"{chain} published figures"
    if cited and cited.lower() not in source.lower():
        source = f"{source} ({cited})"

    return BrandedFood(
        name=str(parsed.get("name") or description)[:160],
        chain=chain,
        serving_description=str(parsed.get("serving_description") or "one serving")[:80],
        serving_g=_number(parsed.get("serving_g")) or None,
        kcal=kcal,
        protein_g=_number(parsed.get("protein_g")),
        carbs_g=_number(parsed.get("carbs_g")),
        fat_g=_number(parsed.get("fat_g")),
        source=source[:200],
        confidence=min(1.0, max(0.0, _number(parsed.get("confidence"), 0.6))),
    )
