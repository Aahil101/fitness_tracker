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
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ..config import settings
from ..errors import UpstreamError
from ..http import get_http_client

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
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
            "note": self.source,
        }


# ---------------------------------------------------------------------------
# Checked figures for frequently ordered items
#
# Kept short on purpose. Every entry here is one whose published figure has been
# confirmed; the grounded lookup handles everything else and caches the result, so
# there is no need to pad this out with numbers nobody has verified.
# ---------------------------------------------------------------------------
KNOWN: tuple[BrandedFood, ...] = (
    BrandedFood(
        name="Margherita pizza (regular, hand tossed)",
        chain="Domino's",
        serving_description="one regular pizza",
        serving_g=310.0,
        kcal=688.0,
        protein_g=14.0,
        carbs_g=68.0,
        fat_g=22.0,
        source="Domino's India published calorie guide",
        confidence=0.9,
    ),
)


def _normalise(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: How close a word has to be to a chain's name to count. People type "domonis"
#: for Domino's, and a brand nobody spells correctly is a brand nobody can log.
FUZZY_THRESHOLD = 0.82


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


def lookup_known(text: str, chain: str) -> BrandedFood | None:
    """A checked entry for this item, if there is one."""
    tokens = set(_normalise(text).split())
    best: tuple[int, BrandedFood] | None = None
    for item in KNOWN:
        if item.chain != chain:
            continue
        # Match on the distinguishing words of the product name, ignoring the
        # bracketed size note.
        product = _normalise(re.sub(r"\(.*?\)", "", item.name))
        words = {w for w in product.split() if len(w) > 2}
        overlap = len(words & tokens)
        close_enough = overlap and overlap >= len(words) - 1
        if close_enough and (best is None or overlap > best[0]):
            best = (overlap, item)
    return best[1] if best else None


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


async def lookup_published(description: str, chain: str) -> BrandedFood | None:
    """Ask Gemini, with Google Search, what the chain publishes for this item.

    Returns None rather than a guess when nothing is found: a fabricated figure
    for a named product is worse than falling back to a generic food, because the
    brand name makes it look authoritative.
    """
    if not settings.gemini_api_key:
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

    client = get_http_client()
    try:
        response = await client.post(
            f"{GEMINI_URL}/{GEMINI_MODEL}:generateContent",
            params={"key": settings.gemini_api_key},
            json=body,
            timeout=REQUEST_TIMEOUT_S,
        )
    except Exception as exc:  # network, timeout
        log.info("Grounded brand lookup failed for %r: %s", description, exc)
        return None

    if response.status_code == 429:
        raise UpstreamError("Nutrition lookup limit reached for today. Try again tomorrow.")
    if response.status_code >= 400:
        log.info("Grounded brand lookup returned %s for %r", response.status_code, description)
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
