#!/usr/bin/env python3
"""Build the chain menu table from what the chains themselves publish.

Run offline, occasionally, by hand. The output is committed, so at runtime the app
needs neither the network nor a PDF library:

    ~/.local/bin/uv run --with pdfplumber --with httpx --python 3.11 \
        python scripts/build_chain_menus.py

Why this exists. Named menu items were priced by asking Gemini, with Google Search
grounding, what the chain publishes. That path is dead on the free tier: all five
keys answer a grounded request with 429 RESOURCE_EXHAUSTED in about 120ms while
answering ordinary generateContent perfectly, so grounding is a capability the
free tier does not include rather than an allowance being consumed. Adding keys
cannot fix it.

Falling back to the model's own guess is not good enough for a brand. A figure
with "McDonald's" next to it reads as authoritative, and the app was showing
estimates that way. Meanwhile all four of these chains publish their own
laboratory-analysed figures, under FSSAI labelling rules, in machine-readable
form. Using those makes the answer exact, free, instant and identical every time.

Sources, all first-party:

* Domino's India — the menu nutrition page embeds the whole menu as JSON, with
  per-variant figures. Published per serve, with a serves count, so a large pizza
  is four times the number shown. Getting that backwards would under-count a large
  Margherita by about 1,500 kcal.
* McDonald's India — the 2024 nutrition PDF, per serve with the serving weight.
* Pizza Hut India — the nutrition and allergen booklet, per pizza with net weight
  and slice count. Note the column order differs from McDonald's: carbohydrate
  comes before protein.
* Taco Bell India — the nutritional information PDF, per serve with gross quantity.

Every row is checked against itself before being kept: energy computed from the
row's own macros at 4/4/9 kcal per gram has to land near the energy the row
states. That catches a column read in the wrong order, which is the failure mode
that matters here — a plausible-looking number in the wrong place is invisible
otherwise. Rows below a few tens of kcal are exempt, because a 4 kcal absolute
difference on a cup of green tea is a huge percentage and means nothing.

Nutritional composition figures are facts rather than creative expression, and are
published by these chains for exactly this purpose: so that a person can find out
what they are eating. Each entry carries its source.
"""

from __future__ import annotations

import contextlib
import html
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "chain_menus.json"
CACHE = Path("/tmp/chain-menus")

#: How far a row's stated energy may sit from the energy implied by its own
#: macros before the row is thrown away. Generous, because published figures are
#: rounded, fibre and polyols are counted inconsistently, and sugar alcohols in
#: desserts legitimately break 4/4/9. Tight enough to catch transposed columns,
#: which is the point.
ENERGY_TOLERANCE_PCT = 20.0

#: Below this, percentage agreement is meaningless: black coffee is 5 kcal and
#: its macros round to zero.
ENERGY_CHECK_FLOOR_KCAL = 40.0


class SourceError(RuntimeError):
    pass


def fetch(url: str, name: str) -> bytes:
    """Download once, then work from the cached copy while iterating the parsers."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / name
    if cached.exists() and cached.stat().st_size > 1024:
        return cached.read_bytes()
    print(f"  fetching {url}")
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=90.0,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    )
    resp.raise_for_status()
    cached.write_bytes(resp.content)
    return resp.content


def numbers(tokens: list[str]) -> list[float | None]:
    """Published tables write "ND" for not detected and "NA" for not applicable."""
    out: list[float | None] = []
    for token in tokens:
        if token.upper() in {"ND", "NA", "-", "–"}:
            out.append(None)
            continue
        try:
            out.append(float(token))
        except ValueError:
            out.append(None)
    return out


def energy_is_consistent(item: dict[str, Any]) -> tuple[bool, float]:
    """Does the row's own energy agree with 4/4/9 on its own macros?"""
    kcal = item.get("kcal") or 0.0
    if kcal < ENERGY_CHECK_FLOOR_KCAL:
        return True, 0.0
    protein = item.get("protein_g")
    carbs = item.get("carbs_g")
    fat = item.get("fat_g")
    if protein is None or carbs is None or fat is None:
        return True, 0.0
    derived = protein * 4 + carbs * 4 + fat * 9
    gap = abs(derived - kcal) / kcal * 100
    return gap <= ENERGY_TOLERANCE_PCT, gap


# ---------------------------------------------------------------------------
# Domino's India
# ---------------------------------------------------------------------------
DOMINOS_URL = "https://www.dominos.co.in/menu-nutrition"

#: The crust and size a person means when they say "a Domino's Margherita" and
#: nothing else. Regular hand tossed is the default on the menu and the one
#: ordered most; anything else has to be named. Order matters — it is the
#: tie-break when someone names a size but no crust.
DOMINOS_CRUST_ORDER = (
    "New Hand Tossed",
    "Classic Hand Tossed",
    "Fresh Pan Pizza",
    "Cheese Burst",
    "100% Wheat Thin Crust",
    "Double Cheeseburst",
    "Pull Apart Crust",
)

#: Regular first: one person ordering one pizza. Sizes are also how a description
#: is disambiguated when it does say "medium". Small sits after medium because a
#: chain that offers no regular treats medium as its standard.
SIZE_ORDER = ("regular", "personal", "medium", "small", "large", "extra large")

#: A row whose name carries no size, competing against rows that do, is a
#: different item under the same name — Pizza Hut's Gap Pizza range repeats
#: "Margherita Pizza" with no size against the Pan Pizza of that name. It is
#: ranked after every size so that an unqualified mention resolves to a size
#: someone can actually order.
SIZELESS_AMBIGUOUS_RANK = 9


def rank_of(crust: str, size: str) -> int:
    """Lower is what an unqualified mention means. Crust dominates size."""
    crust_rank = (
        DOMINOS_CRUST_ORDER.index(crust) if crust in DOMINOS_CRUST_ORDER else len(DOMINOS_CRUST_ORDER)
    )
    size_rank = SIZE_ORDER.index(size) if size in SIZE_ORDER else len(SIZE_ORDER)
    return crust_rank * 10 + size_rank


#: Domino's publishes energy but no weights — confirmed by reading every metadata
#: key on their menu payload: there is a serves count and an "itemWeightage" that
#: is a display-ordering number, and nothing in grams.
#:
#: A portion still needs a weight. Without one the pipeline falls back to treating
#: the serving as 100 g, so a whole pizza was logged as "100 g", and the app lets
#: the user adjust that field — editing 100 to a realistic 250 would then have
#: tripled the calories.
#:
#: So the weight is inferred from energy, using the energy density of the pizzas
#: Pizza Hut India publishes *with* weights: 76 of them, median 275 kcal per 100 g.
#: Checked against those same 76, this recovers the published weight to within 6%
#: at the median and 16% at the 90th percentile. The published energy is never
#: touched; only the portion basis the user sees and can edit.
PIZZA_KCAL_PER_100G = 275.2


def infer_weights(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in items:
        if item.get("serving_g") or item.get("serving_ml"):
            continue
        kcal = item.get("kcal")
        if not kcal:
            continue
        item["serving_g"] = round(kcal / PIZZA_KCAL_PER_100G * 100)
        item["weight_inferred"] = True
    return items


def one_of(name: str) -> str:
    """"one McAloo Tikki Burger" — the wording shown next to the figure.

    Case is kept and the trademark symbols dropped: lowercasing produced
    "one mcaloo tikki burger®", which reads like a transcription error in a note
    whose whole job is to make the number look accountable.
    """
    cleaned = re.sub(r"[™®©]", "", name).strip()
    return f"one {cleaned}"


def size_and_rank(name: str) -> tuple[str, int]:
    """Read a size or a piece count out of a parenthesised suffix.

    The three PDF sources all write the variant in brackets: "(Personal)",
    "(Medium)", "(L)", "(4 pcs)". Which one an unqualified mention means is a real
    decision — "a Pizza Hut Margherita" has to resolve to one of 725, 1377 or 2269
    kcal — so it is made here, once, rather than left to whichever row the lookup
    happens to reach first.
    """
    suffix = re.findall(r"\(([^)]*)\)", name)
    if not suffix:
        # A leading count, as in "4 piece Chicken McNuggets".
        leading = re.match(r"^(\d+)\s+(?:piece|pc|pcs)\b", name, re.IGNORECASE)
        if leading:
            return f"{leading.group(1)} pieces", int(leading.group(1))
        return "", 0

    label = suffix[-1].strip().lower()
    if label in SIZE_ORDER:
        return label, SIZE_ORDER.index(label)
    # McDonald's writes drink sizes as single letters.
    for short, full in (("r", "regular"), ("s", "small"), ("m", "medium"), ("l", "large")):
        if label == short:
            return full, SIZE_ORDER.index(full) if full in SIZE_ORDER else 3
    count = re.match(r"^(\d+)\s*(?:pcs?|pieces?|slices?)\.?$", label)
    if count:
        # Fewest first: someone who does not say how many wings usually means the
        # small portion, and over-counting a brand is the more harmful error.
        return f"{count.group(1)} pieces", int(count.group(1))
    return label, 5


def _variant_fields(name: str) -> dict[str, Any]:
    size, rank = size_and_rank(name)
    return {"size": size, "rank": rank}


def product_of(name: str) -> str:
    """The name with its parenthesised size or count removed."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def finalise(items: list[dict[str, Any]], *, recompute_ranks: bool = True) -> list[dict[str, Any]]:
    """Settle names and ranks once, after every row for the chain is known.

    Two things can only be decided by looking at a product's rows together. A
    piece count is only worth putting in the name when it is what distinguishes
    two rows. And a sizeless row is only ambiguous when a sized row shares its
    name. Both were previously computed per row, so the piece count arrived after
    the rank had already been taken from the shorter name and every wings portion
    ranked 0 — meaning the choice between 322 and 805 kcal came down to file order.

    ``recompute_ranks`` is off for Domino's, whose rank already accounts for the
    crust as well as the size; re-deriving it from the name would read
    "New Hand Tossed-Regular" as an unrecognised size and throw that away.
    """
    items = _label_by_piece_count(items)

    if recompute_ranks:
        for item in items:
            item.update(_variant_fields(item["name"]))

    by_product: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_product.setdefault(product_of(item["name"]).lower(), []).append(item)

    for group in by_product.values():
        if len(group) < 2:
            continue
        if any(item.get("size") for item in group):
            for item in group:
                if not item.get("size"):
                    item["rank"] = SIZELESS_AMBIGUOUS_RANK
    return items


def parse_dominos(page: bytes) -> list[dict[str, Any]]:
    text = html.unescape(page.decode("utf-8", errors="replace"))
    decoder = json.JSONDecoder()

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for match in re.finditer(r'\{"productMasterUID"', text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue

        meta = obj.get("metadataMap") or {}
        elements: dict[str, float] = {}
        for value in ((meta.get("Elements") or {}).get("values") or []):
            parts = str(value).split("|")
            if len(parts) == 3:
                with contextlib.suppress(ValueError):
                    elements[parts[0]] = float(parts[1])
        if "Energy" not in elements:
            continue

        product = str(obj.get("productName") or "").strip()
        variant = str(obj.get("name") or "").strip()
        if not product:
            continue
        if (product, variant) in seen:
            continue
        seen.add((product, variant))

        serves_values = (meta.get("serves") or {}).get("values") or []
        try:
            serves = int(float(serves_values[0])) if serves_values else 1
        except (ValueError, TypeError):
            serves = 1
        serves = max(1, serves)

        crust, _, size = variant.rpartition("-")
        crust = crust.strip() or variant.strip()
        size = size.strip().lower()

        # Published per serve. A medium pizza is two serves and a large is four,
        # so the whole item is the per-serve figure times the count.
        items.append(
            {
                "name": product if not variant else f"{product} ({variant})",
                "product": product,
                "variant": variant,
                "size": size,
                "rank": rank_of(crust, size),
                "serving_description": _dominos_serving(variant, serves),
                "serving_g": None,  # Domino's publishes no weights.
                "kcal": round(elements["Energy"] * serves, 1),
                "protein_g": _scaled(elements.get("Protein"), serves),
                "carbs_g": _scaled(elements.get("Total_Carbohydrate"), serves),
                "fat_g": _scaled(elements.get("Total_Fat"), serves),
            }
        )
    return finalise(infer_weights(items), recompute_ranks=False)


def _plausible_mcd_name(name: str) -> bool:
    """Reject the wreckage of a name that wrapped onto the previous line.

    Three columns of items sit side by side, and where an item's name is long
    enough to wrap, the next line begins with the leftovers of the row above: a
    bare "g" or "ml" followed by that row's figures. Matching from there produced
    entries called "g 228.21 5.45 11.44 ..." carrying real numbers, which is worse
    than a missing entry because it looks like data.
    """
    if len(name) < 3:
        return False
    if re.match(r"^(?:g|ml|kcal)\b", name, re.IGNORECASE):
        return False
    # A genuine menu name does not contain a run of figures.
    if re.search(r"\d+\.\d+\s+\d", name):
        return False
    return bool(re.search(r"[A-Za-z]{3}", name))


def _scaled(value: float | None, serves: int) -> float | None:
    return None if value is None else round(value * serves, 1)


def _dominos_serving(variant: str, serves: int) -> str:
    size = variant.rsplit("-", 1)[-1].strip().lower() if "-" in variant else ""
    if size:
        return f"one {size} pizza"
    return "one serving" if serves == 1 else f"{serves} servings"


# ---------------------------------------------------------------------------
# McDonald's India
# ---------------------------------------------------------------------------
MCD_URL = "https://www.mcdonaldsindia.com/pdf/2024/nutrition-information.pdf"

#: name, serving, unit, then energy, protein, fat, sat fat, trans fat,
#: cholesterol, carbohydrate, total sugars, added sugars, sodium.
#:
#: The optional leading count matters: "4 piece Chicken McNuggets" starts with a
#: digit, so a name pattern anchored on a letter began matching at "piece" and the
#: 4, 6 and 9 piece boxes all collapsed into one entry called "piece Chicken
#: McNuggets" — three different foods, 170 to 382 kcal, indistinguishable.
MCD_ROW = re.compile(
    r"(?P<name>(?:\d{1,2}\s+(?=[Pp]))?[A-Za-z][^\n]*?)\s(?P<serve>\d+(?:\.\d+)?)\s?"
    r"(?P<unit>g|ml)\s(?P<nums>(?:-?\d+(?:\.\d+)?\s+){9}-?\d+(?:\.\d+)?)"
)

#: Section headings share a line with the first item under them.
MCD_HEADING = re.compile(
    r"^(?:(?:[A-Z][A-Za-z]*\s)*?(?:REGULAR|McCAFE|MCCAFE|DESSERTS?|GOURMET|BEVERAGES?|"
    r"BREAKFAST|SIDES?|HAPPY[A-Z\s]*|CONDIMENTS?|VALUE)[A-Za-z]*\s+MENU)\s*",
    re.IGNORECASE,
)


def parse_mcdonalds(pdf_bytes: bytes) -> list[dict[str, Any]]:
    import pdfplumber

    (CACHE / "mcd.pdf").write_bytes(pdf_bytes)
    with pdfplumber.open(CACHE / "mcd.pdf") as pdf:
        # Page 1 is the allergen table; page 2 carries the nutrition figures.
        text = "\n".join(page.extract_text() or "" for page in pdf.pages[1:])

    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("per serve percentage"):
            continue
        for match in MCD_ROW.finditer(line):
            name = MCD_HEADING.sub("", match.group("name").strip()).strip()
            name = re.sub(r"\s+", " ", name)
            if not _plausible_mcd_name(name):
                continue
            values = [float(v) for v in match.group("nums").split()]
            items.append(
                {
                    "name": name,
                    "serving_description": one_of(name),
                    "serving_g": float(match.group("serve"))
                    if match.group("unit") == "g"
                    else None,
                    "serving_ml": float(match.group("serve"))
                    if match.group("unit") == "ml"
                    else None,
                    "kcal": values[0],
                    "protein_g": values[1],
                    "fat_g": values[2],
                    "carbs_g": values[6],
                }
            )
    return finalise(items)


# ---------------------------------------------------------------------------
# Pizza Hut India
# ---------------------------------------------------------------------------
PIZZA_HUT_INDEX = "https://www.pizzahut.co.in/nutrition"

#: Every value in the row, in order. The columns differ between sections — pizzas
#: carry a slice count that beverages do not — so the position of energy is found
#: per row rather than assumed. See _locate_energy.
PH_TOKEN = r"(?:-?\d+(?:\.\d+)?|ND|NA|-)"
PH_ROW = re.compile(rf"(?P<name>[A-Za-z][^\n]*?)\s(?P<nums>(?:{PH_TOKEN}\s+){{18,23}}{PH_TOKEN})")

#: Energy is followed by energy as a percentage of a 2,000 kcal day, so
#: ``value / 20`` must equal the next column. That identity locates the energy
#: column without trusting the section layout, and it is what caught Pepsi being
#: read as 5.4 kcal: the beverage rows have no slice count, so a fixed offset put
#: every beverage figure one column to the left, turning 107.5 kcal into the
#: percentage beside it.
#:
#: Only the first two positions are considered. Sodium is also published against a
#: 2,000 mg reference, so sodium and its percentage satisfy the same identity
#: exactly — scanning the whole row read a 15 g dip's 155.7 mg of sodium as
#: 155.7 kcal. Energy is the second or third column and nowhere else.
RDA_KCAL_BASIS = 2000.0
ENERGY_COLUMN_CANDIDATES = (1, 2)


def _locate_energy(values: list[float | None]) -> int | None:
    for index in ENERGY_COLUMN_CANDIDATES:
        if index + 1 >= len(values):
            break
        energy, pct = values[index], values[index + 1]
        if not energy or pct is None or energy < 5:
            continue
        expected = energy / RDA_KCAL_BASIS * 100
        # Percentages are published to one decimal place and sometimes truncated
        # rather than rounded, so a small absolute slack is required.
        if abs(expected - pct) <= max(0.15, expected * 0.03):
            return index
    return None


def pizza_hut_pdf_url() -> str:
    page = fetch(PIZZA_HUT_INDEX, "pizzahut-index.html").decode("utf-8", errors="replace")
    match = re.search(r'href="(/order/pdfs/in/nutritionals\.[^"]+\.pdf)"', page)
    if not match:
        raise SourceError("Could not find the Pizza Hut nutritionals PDF link")
    return f"https://www.pizzahut.co.in{match.group(1)}"


def parse_pizza_hut(pdf_bytes: bytes) -> list[dict[str, Any]]:
    import pdfplumber

    (CACHE / "pizzahut.pdf").write_bytes(pdf_bytes)
    with pdfplumber.open(CACHE / "pizzahut.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        # The header rows are rendered as interleaved characters and contain no
        # 21-value run, so they do not match; the note pages contain prose.
        for match in PH_ROW.finditer(line):
            name = re.sub(r"\s+", " ", match.group("name")).strip()
            # Drop a section title that shares the line, e.g. "Products Pan Pizza".
            name = re.sub(
                r"^(?:V\s*N\s*e\s*o\s*g\s*n\s*/|Products?|Net Weight)\b.*?(?=[A-Z])",
                "",
                name,
            ).strip()
            # Extraction sometimes splits a leading capital from its word, giving
            # "J apanese Wasabi". Rejoining is safe here because no menu name in
            # this booklet is a single capital followed by a lowercase word.
            name = re.sub(r"\b([A-Z]) ([a-z]{2,})", r"\1\2", name)
            # "Stretched (With 100% Mozzarella)" and "Stretched With WCD" are
            # fragments of the crust-upgrade section's heading, not orderable items.
            if re.match(r"^(?:Stretched|Products?|Net Weight)\b", name):
                continue
            if len(name) < 3:
                continue
            values = numbers(match.group("nums").split())
            energy_at = _locate_energy(values)
            if energy_at is None:
                continue
            kcal = values[energy_at]
            if not kcal:
                continue
            # Relative to energy: carbohydrate, protein, fibre, total sugar, added
            # sugar, added %RDA, then total fat. Carbohydrate before protein, the
            # reverse of McDonald's. A slice or piece count sits between the net
            # weight and energy on the food rows and is absent on the drinks.
            slices = values[energy_at - 1] if energy_at >= 2 else None
            items.append(
                {
                    "name": name,
                    "serving_description": _pizza_hut_serving(name, slices),
                    "serving_g": values[0],
                    "slices": slices,
                    "kcal": kcal,
                    "carbs_g": _at(values, energy_at + 2),
                    "protein_g": _at(values, energy_at + 3),
                    "fat_g": _at(values, energy_at + 8),
                    "fiber_g": _at(values, energy_at + 4),
                }
            )
    return finalise(items)


def _at(values: list[float | None], index: int) -> float | None:
    return values[index] if 0 <= index < len(values) else None


def _label_by_piece_count(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put the piece count in the name where it is the only thing distinguishing rows.

    Wings are listed as one name per portion size — "BBQ Chicken Wings" appears at
    156 g for 4 and 234 g for 6 — with the count only in the slices column. Left
    alone, the two rows are the same name with a 50% difference in energy and the
    lookup picks whichever comes first.
    """
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_name.setdefault(item["name"].lower(), []).append(item)

    for group in by_name.values():
        counts = {item.get("slices") for item in group}
        if len(group) < 2 or len(counts) < 2 or None in counts:
            continue
        for item in group:
            count = int(item["slices"])
            unit = "slices" if "pizza" in item["name"].lower() else "pcs"
            item["name"] = f"{item['name']} ({count} {unit})"
    return items


def _pizza_hut_serving(name: str, slices: float | None) -> str:
    lowered = name.lower()
    if "pizza" in lowered or slices:
        size = re.search(r"\((personal|medium|large|regular)\)", lowered)
        return f"one {size.group(1)} pizza" if size else "one pizza"
    return f"one {lowered}"


# ---------------------------------------------------------------------------
# Taco Bell India
# ---------------------------------------------------------------------------
TACO_BELL_URL = "https://www.tacobell.co.in/pub/media/pdf/nutritional-info-new.pdf"

#: S.N., name, [veg marker], serve count, gross quantity with unit, then energy,
#: protein, carbohydrate, total sugar, added sugar, fat, sat fat, trans fat,
#: cholesterol, sodium.
TB_ROW = re.compile(
    r"^\d+\s+(?P<name>[A-Za-z][^\d]*?)\s+\d+\s+(?P<qty>\d+(?:\.\d+)?)\s?(?P<unit>g|ml)\s+"
    r"(?P<nums>(?:-?\d+(?:\.\d+)?\s+){9}-?\d+(?:\.\d+)?)"
)


def parse_taco_bell(pdf_bytes: bytes) -> list[dict[str, Any]]:
    import pdfplumber

    (CACHE / "tacobell.pdf").write_bytes(pdf_bytes)
    with pdfplumber.open(CACHE / "tacobell.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    items: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = TB_ROW.match(line.strip())
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group("name")).strip()
        # "Mini Cheese Quesadilla Veg" keeps its marker; a bare trailing "1" does not.
        if len(name) < 3:
            continue
        values = [float(v) for v in match.group("nums").split()]
        items.append(
            {
                "name": name,
                "serving_description": one_of(name),
                "serving_g": float(match.group("qty")) if match.group("unit") == "g" else None,
                "serving_ml": float(match.group("qty")) if match.group("unit") == "ml" else None,
                "kcal": values[0],
                "protein_g": values[1],
                "carbs_g": values[2],
                "fat_g": values[5],
            }
        )
    return finalise(items)


# ---------------------------------------------------------------------------
CHAINS: tuple[dict[str, Any], ...] = (
    {
        "chain": "Domino's",
        "source": "Domino's Pizza India, published menu nutrition",
        "source_url": DOMINOS_URL,
        "fetch": lambda: fetch(DOMINOS_URL, "dominos.html"),
        "parse": parse_dominos,
    },
    {
        "chain": "McDonald's",
        "source": "McDonald's India, nutrition information 2024",
        "source_url": MCD_URL,
        "fetch": lambda: fetch(MCD_URL, "mcdonalds.pdf"),
        "parse": parse_mcdonalds,
    },
    {
        "chain": "Pizza Hut",
        "source": "Pizza Hut India, nutrition and allergen booklet",
        "source_url": PIZZA_HUT_INDEX,
        "fetch": lambda: fetch(pizza_hut_pdf_url(), "pizzahut.pdf"),
        "parse": parse_pizza_hut,
    },
    {
        "chain": "Taco Bell",
        "source": "Taco Bell India, nutritional and allergen information",
        "source_url": TACO_BELL_URL,
        "fetch": lambda: fetch(TACO_BELL_URL, "tacobell.pdf"),
        "parse": parse_taco_bell,
    },
)


#: Two rows with the same name and materially different figures cannot both be
#: served: the lookup would pick whichever came first. Where the difference is
#: this large, both are dropped — a confident wrong figure under a brand name is
#: worse than falling back to an estimate that says it is one.
AMBIGUOUS_SPREAD_PCT = 5.0


def drop_ambiguous(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_name.setdefault(item["name"].lower(), []).append(item)

    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for name, group in by_name.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        energies = [item["kcal"] for item in group if item.get("kcal")]
        low, high = min(energies), max(energies)
        if low and (high - low) / low * 100 <= AMBIGUOUS_SPREAD_PCT:
            # Same dish listed twice, near-identical figures: keep one.
            kept.append(group[0])
            continue
        dropped.append(f"{name} ({len(group)} rows, {low:.0f}-{high:.0f} kcal)")
    return kept, dropped


def main() -> None:
    result: dict[str, Any] = {
        "note": (
            "Figures published by each chain for its own menu, collected by "
            "scripts/build_chain_menus.py. Energy is for the whole item as sold."
        ),
        "built_at": datetime.now(UTC).date().isoformat(),
        "chains": {},
    }

    total = 0
    for spec in CHAINS:
        chain = spec["chain"]
        print(f"{chain}:")
        try:
            payload = spec["fetch"]()
            items = spec["parse"](payload)
        except Exception as exc:  # noqa: BLE001 - a source being down is not fatal
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            continue

        kept: list[dict[str, Any]] = []
        rejected: list[tuple[str, float]] = []
        for item in items:
            if not item.get("kcal"):
                continue
            ok, gap = energy_is_consistent(item)
            if ok:
                kept.append(item)
            else:
                rejected.append((item["name"], gap))

        kept, ambiguous = drop_ambiguous(kept)

        print(f"  {len(items)} rows parsed, {len(kept)} kept, {len(rejected)} rejected")
        for name, gap in rejected[:6]:
            print(f"    rejected {name[:52]:54} energy off by {gap:.0f}%")
        if ambiguous:
            print(f"    {len(ambiguous)} name(s) dropped as ambiguous:")
            for label in ambiguous[:6]:
                print(f"      {label}")
        if not kept:
            print("  nothing usable; leaving this chain out")
            continue

        result["chains"][chain] = {
            "source": spec["source"],
            "source_url": spec["source_url"],
            "items": sorted(kept, key=lambda i: i["name"].lower()),
        }
        total += len(kept)

    if not result["chains"]:
        sys.exit("No chain produced any rows; refusing to write an empty table.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False, sort_keys=False))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nwrote {OUT} — {total} items across {len(result['chains'])} chains, {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
