"""A curated nutrition table, consulted before any database or model.

Why this exists: a user logged "tea with milk and sugar" and the app recorded
1 kcal. The failure was not a bad database — it was three fallible layers agreeing
on the same wrong answer. The model named the item "Tea (with milk and sugar)"
while estimating the energy density of *plain* tea, and USDA's "Tea, brewed" said
roughly the same, so the cross-check comparing them saw agreement and shipped it.

The lesson is that for the small number of things people log constantly, guessing
at all is the mistake. A cup of milky sweet tea is about 90 kcal. That is not a
fact worth deriving twice from unreliable sources on every request — it is a fact
worth writing down.

So this table is the first thing consulted, and a hit here ends the matter: no
network call, no model estimate, no fuzzy search, identical answer every time.
Everything in it is a *prepared* food as actually eaten, and the entries chosen
are the ones the other layers demonstrably get wrong:

  * Milk-based hot drinks. USDA carries brewed tea and black coffee, which are
    near-zero, and the milk and sugar routinely go missing.
  * Indian home cooking. FDC is US-centric: it answers "idli" with "Idli Mix"
    (dry powder, three times the density of the steamed cake) and "jowar chilla"
    with a branded keto frozen dessert.
  * Staples whose cooked and dry weights differ enormously — rice, dal, pasta.

Figures are per 100 g as eaten, from standard composition tables and ordinary
recipes. They are approximations, but they are *bounded* approximations: none of
them can be out by a factor of ten, which is the failure this replaces.

Adding an entry is cheap and is the right response to any future report of a
wrong number on a common food. Keep names lowercase and list every phrasing a
user might type in ``aliases``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Fact:
    """Per-100 g composition of a food as eaten."""

    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    aliases: tuple[str, ...] = ()
    #: Typical single serving, so "a cup of chai" needs no volume guesswork.
    serving_g: float | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# Hot drinks
#
# The category that caused the incident. A "cup of tea" in India is boiled with
# milk and sugar; in the US it is a near-zero infusion. Both spellings of the
# intent appear here so neither reading can produce a 1 kcal cup.
# ---------------------------------------------------------------------------
DRINKS: tuple[Fact, ...] = (
    Fact(
        "tea with milk and sugar",
        kcal=38,
        protein_g=1.1,
        carbs_g=6.0,
        fat_g=1.1,
        serving_g=200,
        aliases=(
            "chai",
            "masala chai",
            "milk tea",
            "tea with milk",
            "tea with sugar",
            "sweet tea with milk",
            "indian tea",
            "cutting chai",
            "doodh patti",
            "tea milk sugar",
            "hot tea with milk and sugar",
        ),
        note="Boiled with about a third milk and a teaspoon of sugar per cup.",
    ),
    Fact(
        "tea with milk, no sugar",
        kcal=22,
        protein_g=1.1,
        carbs_g=2.0,
        fat_g=1.1,
        serving_g=200,
        aliases=("unsweetened milk tea", "tea with milk no sugar", "sugar free milk tea"),
    ),
    Fact(
        "black tea, unsweetened",
        kcal=1,
        protein_g=0.0,
        carbs_g=0.3,
        fat_g=0.0,
        serving_g=200,
        aliases=("black tea", "green tea", "plain tea", "tea without milk", "herbal tea"),
        note="Only when milk and sugar are explicitly absent.",
    ),
    Fact(
        "coffee with milk and sugar",
        kcal=36,
        protein_g=1.0,
        carbs_g=5.6,
        fat_g=1.1,
        serving_g=200,
        aliases=(
            "coffee with milk",
            "milk coffee",
            "filter coffee",
            "south indian coffee",
            "cafe au lait",
            "coffee with sugar and milk",
            "sweet coffee",
        ),
    ),
    Fact(
        "black coffee, unsweetened",
        kcal=1,
        protein_g=0.1,
        carbs_g=0.0,
        fat_g=0.0,
        serving_g=200,
        aliases=("black coffee", "americano", "plain coffee", "coffee without milk", "espresso"),
    ),
    Fact(
        "cappuccino",
        kcal=44,
        protein_g=2.4,
        carbs_g=4.2,
        fat_g=1.9,
        serving_g=180,
        aliases=("latte", "cafe latte", "flat white"),
    ),
    Fact(
        "whole milk",
        kcal=61,
        protein_g=3.2,
        carbs_g=4.8,
        fat_g=3.3,
        serving_g=200,
        aliases=("milk", "full fat milk", "buffalo milk", "cow milk", "doodh"),
    ),
    Fact(
        "toned milk",
        kcal=47,
        protein_g=3.1,
        carbs_g=4.7,
        fat_g=1.7,
        serving_g=200,
        aliases=("toned milk", "semi skimmed milk", "low fat milk", "skimmed milk"),
    ),
    Fact(
        "sugar",
        kcal=387,
        protein_g=0.0,
        carbs_g=100.0,
        fat_g=0.0,
        serving_g=5,
        aliases=("white sugar", "table sugar", "granulated sugar", "cane sugar", "chini"),
    ),
    Fact(
        "jaggery",
        kcal=383,
        protein_g=0.4,
        carbs_g=98.0,
        fat_g=0.1,
        serving_g=10,
        aliases=("gur", "gud", "palm jaggery"),
    ),
    Fact(
        "buttermilk, salted",
        kcal=20,
        protein_g=1.6,
        carbs_g=2.4,
        fat_g=0.6,
        serving_g=250,
        aliases=("chaas", "chhaas", "salted lassi", "majjige"),
    ),
    Fact(
        # Measured at 65 by CoFID against our 95. Ours assumed full-fat curd and a
        # generous hand with the sugar; most lassi is thinner than that.
        "sweet lassi",
        kcal=80,
        protein_g=2.9,
        carbs_g=13.5,
        fat_g=1.8,
        serving_g=250,
        aliases=("lassi", "mango lassi", "sweet curd drink"),
    ),
)

# ---------------------------------------------------------------------------
# Indian staples and home cooking, as served
# ---------------------------------------------------------------------------
INDIAN: tuple[Fact, ...] = (
    Fact(
        "roti",
        kcal=264,
        protein_g=8.1,
        carbs_g=50.0,
        fat_g=3.7,
        serving_g=40,
        aliases=("chapati", "phulka", "wheat roti", "atta roti", "rotli"),
    ),
    Fact(
        "jowar roti",
        kcal=250,
        protein_g=7.0,
        carbs_g=52.0,
        fat_g=2.4,
        serving_g=50,
        aliases=("jowar bhakri", "sorghum roti", "bhakri", "jolada rotti"),
    ),
    Fact(
        "jowar chilla",
        kcal=180,
        protein_g=6.0,
        carbs_g=28.0,
        fat_g=4.5,
        serving_g=90,
        aliases=("jowar cheela", "sorghum pancake", "jowar pancake", "chilla", "cheela", "besan chilla"),
        note="Savoury batter pancake cooked with a little oil, not a dessert.",
    ),
    Fact(
        "cooked white rice",
        kcal=130,
        protein_g=2.7,
        carbs_g=28.0,
        fat_g=0.3,
        serving_g=160,
        aliases=("white rice", "steamed rice", "boiled rice", "plain rice", "rice", "chawal", "sadam"),
        note="Cooked weight. Dry rice is about 350 kcal/100 g — a threefold error.",
    ),
    Fact(
        "cooked brown rice",
        kcal=123,
        protein_g=2.7,
        carbs_g=26.0,
        fat_g=1.0,
        serving_g=160,
        aliases=("brown rice",),
    ),
    Fact(
        "dal, cooked",
        kcal=116,
        protein_g=7.0,
        carbs_g=17.0,
        fat_g=1.9,
        serving_g=200,
        aliases=("dal", "daal", "toor dal", "moong dal", "masoor dal", "lentil curry", "dal tadka", "dal fry", "sambar dal"),
        note="As served, watered and tempered. Dry dal is roughly 340 kcal/100 g.",
    ),
    Fact(
        # CoFID measures a homemade sambar at 49 and our own figure was 65. Both
        # are internally consistent; they are different recipes, one barely
        # tempered and one with a proper oil tadka. Settled between them.
        "sambar",
        kcal=58,
        protein_g=3.0,
        carbs_g=8.4,
        fat_g=1.4,
        serving_g=150,
        aliases=("sambhar", "saaru"),
    ),
    Fact(
        "rasam",
        kcal=35,
        protein_g=1.2,
        carbs_g=5.0,
        fat_g=1.0,
        serving_g=150,
        aliases=("rasam", "charu"),
    ),
    Fact(
        "idli",
        kcal=140,
        protein_g=4.4,
        carbs_g=28.0,
        fat_g=0.9,
        serving_g=50,
        aliases=("idly", "steamed idli", "rice idli"),
        note="Steamed. FDC answers this query with dry Idli Mix at three times the density.",
    ),
    Fact(
        "dosa",
        kcal=168,
        protein_g=3.9,
        carbs_g=29.0,
        fat_g=4.0,
        serving_g=90,
        aliases=("plain dosa", "sada dosa", "dosai"),
    ),
    Fact(
        "masala dosa",
        kcal=185,
        protein_g=4.0,
        carbs_g=30.0,
        fat_g=5.5,
        serving_g=150,
        aliases=("masala dosai",),
    ),
    Fact(
        "ven pongal",
        kcal=155,
        protein_g=4.5,
        carbs_g=24.0,
        fat_g=4.5,
        serving_g=200,
        aliases=("pongal", "khara pongal", "ghee pongal", "rice and dal pongal"),
        note="Rice and moong dal with ghee, pepper and cumin.",
    ),
    Fact(
        "upma",
        kcal=145,
        protein_g=3.4,
        carbs_g=23.0,
        fat_g=4.2,
        serving_g=200,
        aliases=("uppuma", "rava upma", "semolina upma"),
    ),
    Fact(
        "poha",
        kcal=140,
        protein_g=2.7,
        carbs_g=25.0,
        fat_g=3.4,
        serving_g=180,
        aliases=("pohe", "flattened rice", "aval", "kanda poha"),
    ),
    Fact(
        "paratha",
        kcal=300,
        protein_g=7.0,
        carbs_g=45.0,
        fat_g=10.0,
        serving_g=70,
        aliases=("plain paratha", "aloo paratha", "stuffed paratha", "parotta"),
    ),
    Fact(
        "puri",
        kcal=360,
        protein_g=6.5,
        carbs_g=45.0,
        fat_g=17.0,
        serving_g=30,
        aliases=("poori", "fried puri"),
    ),
    Fact(
        "vada",
        kcal=290,
        protein_g=8.0,
        carbs_g=30.0,
        fat_g=15.0,
        serving_g=45,
        aliases=("medu vada", "urad vada", "vadai"),
    ),
    Fact(
        "chicken curry",
        kcal=145,
        protein_g=13.0,
        carbs_g=4.0,
        fat_g=8.5,
        serving_g=200,
        aliases=("chicken masala", "chicken gravy", "murgh curry", "chicken sabzi"),
    ),
    Fact(
        "paneer curry",
        kcal=190,
        protein_g=9.0,
        carbs_g=7.0,
        fat_g=14.0,
        serving_g=180,
        aliases=("paneer butter masala", "palak paneer", "paneer masala", "shahi paneer"),
    ),
    Fact(
        "mixed vegetable curry",
        kcal=95,
        protein_g=2.6,
        carbs_g=10.0,
        fat_g=5.0,
        serving_g=180,
        aliases=("sabzi", "sabji", "veg curry", "vegetable curry", "kootu", "poriyal"),
    ),
    Fact(
        # Whole-milk yogurt measures 79; ours at 60 assumed toned milk. Indian
        # households use both, so the figure sits between them.
        "curd",
        kcal=68,
        protein_g=4.0,
        carbs_g=5.5,
        fat_g=3.4,
        serving_g=150,
        aliases=("yoghurt", "yogurt", "dahi", "plain curd", "thick curd"),
    ),
    Fact(
        "chutney, coconut",
        kcal=180,
        protein_g=3.0,
        carbs_g=8.0,
        fat_g=15.0,
        serving_g=40,
        aliases=("coconut chutney", "chutney"),
    ),
    Fact(
        "naan",
        kcal=285,
        protein_g=8.9,
        carbs_g=50.0,
        fat_g=6.0,
        serving_g=90,
        aliases=("naan bread", "plain naan", "butter naan", "garlic naan", "tandoori roti"),
        note="Leavened and baked; richer than a chapati and not the same as white bread.",
    ),
    Fact(
        "baked beans",
        kcal=81,
        protein_g=4.7,
        carbs_g=12.9,
        fat_g=0.6,
        serving_g=200,
        aliases=("baked beans in tomato sauce", "beans on toast beans"),
        note="Haricot beans in tomato sauce — much lighter than rajma.",
    ),
    Fact(
        "biryani, chicken",
        kcal=180,
        protein_g=8.5,
        carbs_g=22.0,
        fat_g=6.5,
        serving_g=250,
        aliases=("chicken biryani", "biryani", "biriyani"),
    ),
)

# ---------------------------------------------------------------------------
# Everyday additions that carry real energy and are easy to lose
# ---------------------------------------------------------------------------
BASICS: tuple[Fact, ...] = (
    Fact("ghee", kcal=900, protein_g=0.0, carbs_g=0.0, fat_g=100.0, serving_g=5,
         aliases=("clarified butter", "desi ghee")),
    Fact("butter", kcal=717, protein_g=0.9, carbs_g=0.1, fat_g=81.0, serving_g=10,
         aliases=("salted butter", "unsalted butter", "makhan")),
    Fact("vegetable oil", kcal=884, protein_g=0.0, carbs_g=0.0, fat_g=100.0, serving_g=5,
         aliases=("oil", "sunflower oil", "cooking oil", "groundnut oil", "olive oil", "coconut oil")),
    Fact("boiled egg", kcal=155, protein_g=13.0, carbs_g=1.1, fat_g=11.0, serving_g=50,
         aliases=("egg", "hard boiled egg", "egg boiled", "anda")),
    Fact("omelette", kcal=195, protein_g=13.0, carbs_g=1.5, fat_g=15.0, serving_g=100,
         aliases=("egg omelette", "masala omelette", "scrambled egg", "egg bhurji")),
    Fact("grilled chicken breast", kcal=165, protein_g=31.0, carbs_g=0.0, fat_g=3.6, serving_g=120,
         aliases=("chicken breast", "grilled chicken", "roast chicken breast")),
    Fact("banana", kcal=89, protein_g=1.1, carbs_g=23.0, fat_g=0.3, serving_g=120,
         aliases=("kela",)),
    Fact("apple", kcal=52, protein_g=0.3, carbs_g=14.0, fat_g=0.2, serving_g=180),
    Fact("white bread", kcal=265, protein_g=9.0, carbs_g=49.0, fat_g=3.2, serving_g=30,
         aliases=("bread", "bread slice", "sandwich bread")),
    # A soft white roll. CoFID's "Bread rolls, white, soft" over 10 samples is 254
    # kcal/100 g; the pav sold with bhaji and misal is the same thing, usually
    # brushed with butter on the tava, which the serving does not include.
    #
    # It is here because of what its absence caused. Asked about misal pav the
    # model returned "pav (soft yeast dinner rolls, typically served with butter)",
    # nothing in this table answered to "pav", and the only alias whose words all
    # appeared in that description was "butter" — so a 60 g roll was priced at
    # 430 kcal with 48.6 g of fat, and the same meal came out at 459 or 730 kcal
    # depending on how the model happened to describe the bread.
    Fact("pav", kcal=254, protein_g=9.3, carbs_g=51.5, fat_g=2.6, serving_g=45,
         aliases=("pao", "ladi pav", "bread roll", "bread rolls", "dinner roll",
                  "dinner rolls", "soft roll", "burger bun", "bun"),
         note="Soft white roll, as sold with bhaji or misal. Butter added on the tava is extra."),
    Fact("peanut butter", kcal=588, protein_g=25.0, carbs_g=20.0, fat_g=50.0, serving_g=15,
         aliases=("peanutbutter",)),
    Fact("almonds", kcal=579, protein_g=21.0, carbs_g=22.0, fat_g=50.0, serving_g=15,
         aliases=("badam", "almond")),
    Fact("cooked pasta", kcal=158, protein_g=5.8, carbs_g=31.0, fat_g=0.9, serving_g=140,
         aliases=("pasta", "spaghetti", "penne", "macaroni")),
    # USDA says 164 for boiled chickpeas, CoFID 129; the gap is how much water is
    # drained off. Between the two.
    Fact("cooked chickpeas", kcal=148, protein_g=8.6, carbs_g=23.0, fat_g=2.4, serving_g=160,
         aliases=("chana", "chole", "chickpeas", "garbanzo")),
    Fact("cooked rajma", kcal=127, protein_g=8.7, carbs_g=23.0, fat_g=0.5, serving_g=180,
         aliases=("rajma", "kidney beans")),
)

ALL_FACTS: tuple[Fact, ...] = DRINKS + INDIAN + BASICS


def _normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace.

    Also drops parenthesised asides, because the model that caused the incident
    liked to write "Tea (with milk and sugar)". The words inside matter, so they
    are kept as plain text rather than discarded — the brackets are the noise,
    not the content.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("(", " ").replace(")", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Ways of cooking or presenting a food, which the model likes to append as a
#: parenthetical: "tea (brewed)", "sambar (stew)", "sugar (granulated)". These may
#: be discarded when a name would otherwise not match anything.
#:
#: Deliberately an explicit list rather than "any word the table does not know".
#: That looser rule matched "grilled fish" to grilled chicken breast, by throwing
#: away the noun and keeping the modifier. Words like "plain", "black" and "green"
#: are excluded because they distinguish real entries — plain tea is not chai.
PREPARATION_WORDS = frozenset(
    {
        "brewed", "steeped", "infused", "cooked", "uncooked", "steamed", "boiled",
        "fried", "pan", "panfried", "grilled", "roasted", "baked", "toasted",
        "granulated", "powdered", "liquid", "melted", "stew", "gravy", "curry",
        "dish", "preparation", "portion", "serving", "leftover", "reheated",
    }
)

#: Words that carry no discriminating meaning in a food name.
_FILLER = frozenset(
    {
        "a", "an", "the", "of", "with", "and", "some", "cup", "cups", "glass", "bowl",
        "plate", "piece", "pieces", "small", "medium", "large", "hot", "cold", "fresh",
        "homemade", "home", "made", "my", "one", "two", "half", "full", "served",
    }
)


def _stem(word: str) -> str:
    """Crudest possible singulariser, applied to both sides of every comparison.

    "2 rotis" has to reach the "roti" entry. A real stemmer would be overkill and
    would start mangling words like "grass"; trimming one trailing s from words of
    four letters or more is enough for food names, and because aliases go through
    the same function any distortion is symmetrical and cancels out.
    """
    # "ss" and "us" are protected (grass, hummus). An "is" ending is *not*, because
    # in this domain those are almost all plurals of words ending in i — rotis,
    # idlis, puris — and excluding them was why "2 rotis" found nothing.
    if len(word) >= 4 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        _stem(w)
        for w in _normalise(text).split()
        # Bare numbers are counts, not food. "2 rotis" must not fail to match
        # merely because it says how many.
        if w not in _FILLER and len(w) > 1 and not w.isdigit()
    )


# Alias -> Fact, built once. Longer aliases are matched first so that
# "tea with milk and sugar" cannot be captured by the bare alias "tea".
def _head_token(text: str) -> str | None:
    """First content word — the head noun of a food name."""
    tokens = _tokens(text)
    return next((_stem(w) for w in _normalise(text).split() if _stem(w) in tokens), None)


#: (normalised alias, alias tokens, alias head token, fact).
_INDEX: list[tuple[str, frozenset[str], str | None, Fact]] = sorted(
    (
        (_normalise(alias), _tokens(alias), _head_token(alias), fact)
        for fact in ALL_FACTS
        for alias in (fact.name, *fact.aliases)
    ),
    key=lambda entry: -len(entry[0]),
)


#: A parenthetical opening with one of these is saying where an ingredient went,
#: not what it is: "sugar (added to tea)", "milk (in coffee)", "ghee (added to
#: pongal)". Those words have to be discarded, or the ingredient gets priced as
#: the dish — a spoon of sugar came out as 1.5 kcal because "tea with sugar"
#: outranked "sugar", and ghee in pongal came out as a serving of pongal.
#:
#: Deliberately not "with", which is load-bearing: "Tea (with milk and sugar)"
#: describes the drink, and dropping it is what caused the original 1 kcal chai.
_PLACEMENT = re.compile(r"^\s*(in|added|for|used|to|on|into|alongside)\b", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"^(?P<stem>[^(]+)\((?P<inside>[^)]*)\)\s*$")


def _strip_placement(query: str) -> str | None:
    """The food on its own, when the brackets only say where it ended up."""
    match = _PARENTHETICAL.match(query.strip())
    if not match:
        return None
    inside = match.group("inside")
    if not _PLACEMENT.match(inside):
        return None
    stem = match.group("stem").strip()
    return stem or None


#: Dishes this table can only get wrong, because it holds one of their components
#: and not the dish. "Pav bhaji" is a buttery vegetable mash served with rolls; the
#: table knows the roll, so a match on it prices a 600 kcal plate at 254 and loses
#: the bhaji entirely. "Vada pav" and "dal makhani" fail the same way — the second
#: has been quietly answering 116 kcal, the figure for plain boiled dal, for a dish
#: finished with cream and butter.
#:
#: They are declined rather than estimated here because the butter is most of the
#: difference and varies enormously between kitchens, so any single figure would be
#: confidently wrong. Declining sends them to the model, which prices the whole
#: description and says it is an estimate. An entry should be added the moment
#: there is a figure worth trusting.
_UNPRICEABLE_COMPOUNDS = frozenset(
    {
        "pav bhaji",
        "vada pav",
        "misal pav",
        "dal makhani",
        "dal fry",
        "dal tadka",
        "chole bhature",
        "aloo paratha",
        "paneer butter masala",
        "butter chicken",
    }
)


def lookup(query: str) -> Fact | None:
    """Best curated entry for a food name, or None.

    Deliberately conservative: it will return nothing rather than a loose match,
    because a wrong curated answer is worse than falling through to USDA. Three
    passes, in descending strictness.
    """
    # "sugar (added to tea)" is sugar. Resolve the food by itself before letting
    # the surrounding context influence the match.
    bare = _strip_placement(query)
    if bare:
        direct = lookup(bare)
        if direct is not None:
            return direct

    normalised = _normalise(query)
    if not normalised:
        return None

    # A dish we hold only a component of. Answering with the component is worse
    # than not answering: it drops the rest of the plate.
    if normalised in _UNPRICEABLE_COMPOUNDS:
        return None

    # 1. Exact alias.
    for entry in _INDEX:
        alias, fact = entry[0], entry[3]
        if alias == normalised:
            return fact

    query_tokens = _tokens(query)
    if not query_tokens:
        return None

    # First content word of the query, which for a food name is almost always the
    # head noun: "chai with milk and sugar" is a chai, not a sugar.
    head = next((_stem(w) for w in _normalise(query).split() if w in query_tokens), None)

    # 2. Every word of an alias appears in the query. Several entries can qualify
    #    at once, so they are scored rather than taken first-come.
    #
    #    Ordering by alias length looked reasonable and was badly wrong: for
    #    "chai with milk and sugar" the aliases "chai", "milk" and "sugar" all
    #    qualify, "sugar" sorted ahead of "chai", and a cup of tea was priced as
    #    240 g of sugar — 929 kcal.
    #
    #    Ranking by specificity first was also wrong, more subtly. For "sugar
    #    (added to tea)" both "sugar" and the alias "tea with sugar" qualify, and
    #    the longer one won, so a spoonful of sugar was priced as a cup of tea —
    #    1.5 kcal instead of 15.5. What settles it is whether the alias is *about*
    #    the same thing: its own head noun has to be the query's head noun.
    #
    #    That test ranked candidates but did not admit them, which left the door
    #    open when there was only one. The model names a food and then describes
    #    it — "pav (soft yeast dinner rolls, typically served with butter)" — and
    #    every word of that ends up in the query, so the alias "butter" qualified,
    #    was the only candidate, and won by default: a 60 g bread roll priced at
    #    430 kcal with 48.6 g of fat. So an alias now has to account for the head
    #    noun at all. It need not be the alias's own subject, because "milk tea
    #    with sugar" has the head noun "milk" and belongs to "tea with milk and
    #    sugar" — it just has to be in there somewhere.
    candidates: list[tuple[int, int, int, Fact]] = []
    for alias, alias_tokens, alias_head, fact in _INDEX:
        if not alias_tokens or not alias_tokens <= query_tokens:
            continue
        if head and head not in alias_tokens:
            continue
        candidates.append(
            (
                1 if head and alias_head == head else 0,  # same subject
                len(alias_tokens),  # then: more of the query accounted for
                len(alias),
                fact,
            )
        )
    if candidates:
        candidates.sort(key=lambda entry: (-entry[0], -entry[1], -entry[2]))
        return candidates[0][3]

    # 3. Every word of the query is present in an alias — catches "chilla" for
    #    "jowar chilla" but never matches on a single shared filler word.
    best: tuple[int, Fact] | None = None
    for _alias, alias_tokens, _alias_head, fact in _INDEX:
        if alias_tokens and query_tokens <= alias_tokens:
            overlap = len(query_tokens)
            if best is None or overlap > best[0]:
                best = (overlap, fact)
    if best:
        return best[1]

    # 4. Retry with preparation words removed.
    #
    #    The model decorates names with how the food was made: "tea (brewed)",
    #    "sambar (stew)", "sugar (granulated)". A single such word was enough to
    #    defeat both passes above — "tea (brewed)" matched nothing at all and fell
    #    through to a database that priced it as 1 kcal.
    #
    #    Only recognised preparation words are dropped, and only if something else
    #    remains. Dropping every unfamiliar word instead matched "grilled fish" to
    #    grilled chicken breast: it discarded the noun and kept the modifier.
    trimmed = query_tokens - PREPARATION_WORDS
    if trimmed and trimmed != query_tokens:
        known = {word for _a, tokens, _h, _f in _INDEX for word in tokens}
        if trimmed <= known:
            return lookup(" ".join(sorted(trimmed)))

    return None


def as_item(fact: Fact) -> dict[str, Any]:
    """Shape a Fact like a resolved nutrition row."""
    return {
        "name": fact.name,
        "calories_per_100g": fact.kcal,
        "protein_per_100g": fact.protein_g,
        "carbs_per_100g": fact.carbs_g,
        "fat_per_100g": fact.fat_g,
        "fiber_per_100g": None,
        "serving_g": fact.serving_g,
        "source": "curated",
        "note": fact.note,
    }
