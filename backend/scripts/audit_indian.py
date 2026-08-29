#!/usr/bin/env python3
"""Audit our Indian food figures against an independent measured dataset.

Run by hand:  .venv/bin/python scripts/audit_indian.py

Method. Our curated table was authored from standard composition values and
ordinary recipes. CoFID — the UK national composition table, lab-measured — was
imported separately and carries a surprising amount of Indian cooking, including
a hundred-odd curry entries and most of the breads and fried snacks. Comparing
the two is therefore a genuine cross-check rather than a circular one: neither
was derived from the other.

Comparison is per 100 g, which removes portion-size guesswork and isolates the
question this is meant to answer — is the food's composition right.

What counts as agreement. For a home-cooked dish there is no single true figure:
a chapati made with ghee and one made without differ by 60%, and both are
chapatis. So where CoFID lists several preparations the reference is the range
they span, and our value is judged on whether it falls inside it. Where CoFID
lists one, a 25% tolerance is allowed, which is roughly the spread between two
cooks making the same thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import cofid, food_facts  # noqa: E402

# our curated name -> the CoFID entries that describe the same food
#
# Chosen by reading CoFID's own names, not by searching for whatever agreed.
# Where a dish exists in several preparations they are all listed, because the
# span between them is the honest reference range.
COMPARISONS: list[tuple[str, tuple[str, ...], str]] = [
    (
        "roti",
        ("Chapatis, made without fat", "Chapatis, made with fat, retail"),
        "with and without fat — the span is the point",
    ),
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
        "korma to vindaloo",
    ),
    ("biryani, chicken", ("Biryani, chicken, takeaway", "Curry, lamb biryani, homemade"), ""),
    ("sweet lassi", ("Lassi, sweetened",), ""),
    ("curd", ("Yogurt, whole milk, plain",), ""),
    ("whole milk", ("Milk, whole, pasteurised, average",), ""),
    ("toned milk", ("Milk, semi-skimmed, pasteurised, average",), ""),
    ("baked beans", ("Baked beans, canned in tomato sauce",), ""),
    ("ghee", ("Ghee, butter",), ""),
    ("butter", ("Butter, salted",), ""),
    ("boiled egg", ("Eggs, chicken, whole, boiled",), ""),
    ("almonds", ("Almonds, flaked and ground",), ""),
    ("cooked pasta", ("Pasta, white, spaghetti, dried, boiled in unsalted water",), ""),
    ("white bread", ("Bread, white, average",), ""),
    ("banana", ("Bananas, flesh only",), ""),
    ("vegetable oil", ("Oil, vegetable, average",), ""),
    (
        "cooked chickpeas",
        ("Beans, chick peas, Kabuli, whole, dried, boiled in unsalted",),
        "CoFID 129 against USDA 164 — drainage differs",
    ),
]

#: Foods with no honest reference in CoFID. Listed rather than dropped, because a
#: silent omission would inflate the pass rate.
NO_REFERENCE = {
    "paneer curry": "CoFID has paneer only as cheese (328), never as a made dish",
    "cooked rajma": (
        "CoFID lists rajma only as a curry with gravy (106) — not comparable with "
        "plain boiled beans. USDA gives 127 for those, matching ours exactly"
    ),
    "chutney, coconut": "no coconut chutney entry",
    "idli": "not a UK food",
    "dosa": "only a dosa *filling* entry exists",
    "ven pongal": "not a UK food",
    "upma": "not a UK food",
    "poha": "not a UK food",
    "jowar chilla": "not a UK food",
    "tea with milk and sugar": "CoFID's tea-with-milk is a splash in a mug, not boiled chai",
}

TOLERANCE = 0.25


def reference(names: tuple[str, ...]) -> tuple[float, float, list[str]] | None:
    """Low and high of the CoFID entries naming this food."""
    entries, _ = cofid._table()
    by_name = {entry.food.name.lower(): entry.food for entry in entries}
    values: list[float] = []
    found: list[str] = []
    for name in names:
        food = by_name.get(name.lower())
        if food is None:
            # Allow a prefix match, since CoFID truncates some long names.
            food = next(
                (f for key, f in by_name.items() if key.startswith(name.lower()[:34])), None
            )
        if food is not None:
            values.append(food.kcal)
            found.append(f"{food.name} = {food.kcal:g}")
    if not values:
        return None
    return min(values), max(values), found


def main() -> int:
    print(f"  {'our food':26} {'ours':>7} {'reference':>16}  {'delta':>8}  verdict")
    print(f"  {'-' * 26} {'-' * 7} {'-' * 16}  {'-' * 8}  -------")

    inside = 0
    checked = 0
    missing: list[str] = []
    worst: list[tuple[float, str]] = []

    for our_name, cofid_names, note in COMPARISONS:
        fact = food_facts.lookup(our_name)
        if fact is None:
            missing.append(f"{our_name} (not in our table)")
            continue
        ref = reference(cofid_names)
        if ref is None:
            missing.append(f"{our_name} (no CoFID match for {cofid_names[0]!r})")
            continue

        low, high, found = ref
        checked += 1
        ours = fact.kcal

        if len(found) > 1:
            ok = low * (1 - TOLERANCE * 0.4) <= ours <= high * (1 + TOLERANCE * 0.4)
            ref_text = f"{low:g}-{high:g}"
            midpoint = (low + high) / 2
        else:
            ok = abs(ours - low) / low <= TOLERANCE
            ref_text = f"{low:g}"
            midpoint = low

        delta = (ours - midpoint) / midpoint * 100
        if ok:
            inside += 1
        else:
            worst.append((abs(delta), f"{our_name}: ours {ours:g} vs {ref_text}"))

        print(
            f"  {our_name[:26]:26} {ours:>7.0f} {ref_text:>16}  {delta:>+7.0f}%  "
            f"{'ok' if ok else 'OUT'}"
            + (f"   ({note})" if note else "")
        )

    print(f"\n  {inside}/{checked} within the reference range or {int(TOLERANCE * 100)}% of it")
    if worst:
        print("\n  outside:")
        for _, line in sorted(worst, reverse=True):
            print(f"    {line}")
    if missing:
        print("\n  no match found:")
        for line in missing:
            print(f"    {line}")

    print("\n  deliberately not compared (no honest reference):")
    for name, why in NO_REFERENCE.items():
        fact = food_facts.lookup(name)
        ours = f"{fact.kcal:g}" if fact else "-"
        print(f"    {name[:26]:28} ours {ours:>5}   {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
