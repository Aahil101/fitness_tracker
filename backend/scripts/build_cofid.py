#!/usr/bin/env python3
"""Convert the UK CoFID spreadsheet into the compact table the app ships.

Run offline, occasionally, by hand. The output is committed, so the application
needs neither the network nor openpyxl at runtime.

    uv venv /tmp/xlsx-env
    uv pip install --python /tmp/xlsx-env/bin/python openpyxl
    curl -sL -o /tmp/cofid.xlsx <url from gov.uk publication page>
    /tmp/xlsx-env/bin/python scripts/build_cofid.py /tmp/cofid.xlsx

Why this dataset. The app was resolving food through USDA FoodData Central, which
is a poor fit for the cooking its users actually describe: FDC answers "idli" with
a packet of Idli Mix at dry-weight density, and "jowar chilla" with a branded keto
frozen dessert. Open Food Facts fails the same way for the same reason — it is a
database of *products*, so a query about home cooking returns the nearest packet.

CoFID is a composition table rather than a product catalogue, and it is
preparation-aware in exactly the way this app needs. "Chapatis, made without fat"
is 202 kcal/100 g and "made with fat" is 328. Samosas are listed baked and deep
fried separately. There are 106 curry entries, most of them marked homemade.

Licence: Crown copyright, published on gov.uk under the Open Government Licence
v3.0, which permits commercial use with attribution. The attribution is carried in
the generated file and surfaced in the app.

Source: McCance and Widdowson's The Composition of Foods Integrated Dataset 2021.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import openpyxl

SHEET = "1.3 Proximates"
HEADER_ROW = 1
FIRST_DATA_ROW = 4

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "cofid.json"

ATTRIBUTION = (
    "McCance and Widdowson's The Composition of Foods Integrated Dataset 2021, "
    "Public Health England. Contains public sector information licensed under the "
    "Open Government Licence v3.0."
)

# Header text -> the key we keep. Matched case-insensitively on a prefix, because
# the sheet's headers carry units and the odd doubled label
# ("Energy (kcal) (kcal)").
WANTED = {
    "food code": "code",
    "food name": "name",
    "description": "description",
    "group": "group",
    "protein (g)": "protein_g",
    "fat (g)": "fat_g",
    "carbohydrate (g)": "carbs_g",
    "energy (kcal)": "kcal",
    "aoac fibre (g)": "fibre_g",
    "fibre, aoac": "fibre_g",
    "englyst fibre (g)": "fibre_englyst_g",
    "total sugars (g)": "sugars_g",
}

# CoFID marks a trace as "Tr", an unmeasured value as "N", and some cells carry a
# leading comparator. None of those are numbers.
TRACE = {"tr", "trace"}
MISSING = {"n", "na", "n/a", ""}


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in MISSING:
        return None
    if text in TRACE:
        return 0.0
    # "<0.1" and similar: the value is below the stated figure, so take it as that.
    text = text.lstrip("<>~=").strip()
    try:
        return float(text)
    except ValueError:
        return None


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def main(source: str) -> int:
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    sheet = workbook[SHEET]

    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    for _ in range(FIRST_DATA_ROW - HEADER_ROW - 1):
        next(rows)

    # Map column index -> our key.
    columns: dict[int, str] = {}
    for index, label in enumerate(header):
        if label is None:
            continue
        lowered = str(label).strip().lower()
        for prefix, key in WANTED.items():
            if lowered.startswith(prefix) and key not in columns.values():
                columns[index] = key
                break

    missing = {"name", "kcal", "protein_g", "fat_g", "carbs_g"} - set(columns.values())
    if missing:
        print(f"!! could not find columns for {sorted(missing)}", file=sys.stderr)
        print(f"   headers seen: {[str(h) for h in header if h]}", file=sys.stderr)
        return 1

    foods: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        record: dict[str, Any] = {}
        for index, key in columns.items():
            if index < len(row):
                record[key] = row[index]

        name = str(record.get("name") or "").strip()
        kcal = parse_number(record.get("kcal"))
        if not name or kcal is None:
            skipped += 1
            continue

        entry: dict[str, Any] = {
            "n": name,
            "k": round(kcal, 1),
            "p": round(parse_number(record.get("protein_g")) or 0.0, 2),
            "c": round(parse_number(record.get("carbs_g")) or 0.0, 2),
            "f": round(parse_number(record.get("fat_g")) or 0.0, 2),
        }
        fibre = parse_number(record.get("fibre_g"))
        if fibre is None:
            fibre = parse_number(record.get("fibre_englyst_g"))
        if fibre is not None:
            entry["fb"] = round(fibre, 2)
        group = str(record.get("group") or "").strip()
        if group:
            entry["g"] = group
        # Kept because it distinguishes otherwise identical names, and says how the
        # food was prepared: "8 cans", "recipe", "takeaway".
        description = str(record.get("description") or "").strip()
        if description and description.lower() not in {"none", "n"}:
            entry["d"] = description[:120]
        foods.append(entry)

    payload = {
        "source": "CoFID 2021",
        "attribution": ATTRIBUTION,
        "licence": "OGL-UK-3.0",
        "count": len(foods),
        "foods": foods,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))

    size_kb = OUT.stat().st_size / 1024
    print(f"  wrote {OUT.relative_to(OUT.parent.parent.parent)}")
    print(f"  {len(foods)} foods, {skipped} rows skipped for want of a name or energy value")
    print(f"  {size_kb:.0f} KB")

    # A quick look at the entries that motivated the switch.
    print("\n  spot check:")
    index = {normalise(f["n"]): f for f in foods}
    for probe in (
        "chapatis, made without fat",
        "chapatis, made with fat, retail",
        "curry, chick pea dhal, homemade",
        "raita, homemade",
        "milk, whole, pasteurised, average",
        "coffee, infusion, average",
    ):
        hit = index.get(normalise(probe))
        if hit:
            print(f"    {hit['n'][:52]:54} {hit['k']:>6} kcal  P{hit['p']} C{hit['c']} F{hit['f']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
