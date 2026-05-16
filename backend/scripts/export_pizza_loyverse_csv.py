"""
Generate Loyverse-compatible items CSV for JM Pizza.
(2026-05-11 — JM Pizza menu → Loyverse import CSV)

Output schema follows official Loyverse export format (verified 2026-05-11):
  Handle, SKU, Name, Category, Description, Cost, Price, Default price,
  Available for sale, Sold by weight,
  Option 1 name, Option 1 value, Option 2 name, Option 2 value,
  Option 3 name, Option 3 value,
  Barcode, SKU of included item, Quantity of included item,
  Use production, Supplier, Purchase cost,
  Track stock, In stock, Low stock,
  Modifier - "<group display name>"  (one column per modifier group, Y if applies)
  Tax - "Sales tax"                    (optional, blank = no tax assignment)

Variant handling (per Loyverse docs):
  - Whole pies (signature + classic) have 2 size variants → 2 rows
    with SAME `Handle`. First row contains Name + Category, subsequent
    rows leave Name + Category BLANK.
  - Slices / Salads / Sides / Desserts / Drinks = 1 row each (no variant).

Run from backend/ directory:
    .venv/bin/python scripts/export_pizza_loyverse_csv.py
    # → writes ~/Downloads/jm_pizza_loyverse_import_<YYYY-MM-DD>.csv
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import date
from pathlib import Path

import yaml

TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "pizza"

# Categories the operator must create in Loyverse Back Office BEFORE import.
# (Import will accept names verbatim, but pre-creating them keeps colors/order tidy.)
REQUIRED_CATEGORIES = [
    "Signature Pies",
    "Classic Pies",
    "Slices",
    "Salads",
    "Sides",
    "Desserts",
    "Drinks",
]

# Modifier groups → Loyverse Back Office display names.
# These must be pre-created in Loyverse Back Office BEFORE import (Loyverse
# does NOT create modifier groups automatically — only marks Y for items).
MODIFIER_GROUPS_FOR_LOYVERSE = [
    ("size",         "Pizza Size"),
    ("crust",        "Crust Type"),
    ("sauce",        "Sauce"),
    ("cheese",       "Cheese"),
    ("topping_meat", "Meat Topping"),
    ("topping_veg",  "Veggie Topping"),
    ("wing_sauce",   "Wing Sauce"),
    ("dressing",     "Salad Dressing"),
]

CATEGORY_DISPLAY = {
    "signature_pie": "Signature Pies",
    "classic_pie":   "Classic Pies",
    "slice":         "Slices",
    "salad":         "Salads",
    "side":          "Sides",
    "dessert":       "Desserts",
    "drink":         "Drinks",
}


def _columns() -> list[str]:
    base = [
        "Handle", "SKU", "Name", "Category", "Description",
        "Cost", "Price", "Default price",
        "Available for sale", "Sold by weight",
        "Option 1 name", "Option 1 value",
        "Option 2 name", "Option 2 value",
        "Option 3 name", "Option 3 value",
        "Barcode", "SKU of included item", "Quantity of included item",
        "Use production", "Supplier", "Purchase cost",
        "Track stock", "In stock", "Low stock",
    ]
    # Dynamic modifier columns
    for _, name in MODIFIER_GROUPS_FOR_LOYVERSE:
        base.append(f'Modifier - "{name}"')
    return base


def _build_rows(menu_yaml: dict, mg_yaml: dict) -> list[dict]:
    rows: list[dict] = []
    groups = mg_yaml["groups"]

    for item in menu_yaml["items"]:
        item_id = item["id"]
        name = item["en"]
        cat = CATEGORY_DISPLAY.get(item["category"], item["category"])
        base_price = float(item["base_price"])
        desc = item.get("notes_en") or ""

        # Map item.modifier_groups → Loyverse modifier display flags
        active_mod_names = set()
        for gcode in item.get("modifier_groups", []):
            for code, display in MODIFIER_GROUPS_FOR_LOYVERSE:
                if code == gcode:
                    active_mod_names.add(display)

        # Determine variants — pizzas with `size` modifier → 2 rows
        has_size_variant = "size" in item.get("modifier_groups", [])

        if has_size_variant and "size" in groups:
            size_opts = groups["size"]["options"]   # [{id:14inch, en:"14\"", price_delta:0}, {id:18inch, ...}]
            for i, opt in enumerate(size_opts):
                row = _blank_row()
                # All variant rows share Handle (= item_id)
                row["Handle"] = item_id
                row["SKU"] = f"{item_id}_{opt['id']}"
                # First variant row carries Name + Category
                if i == 0:
                    row["Name"] = name
                    row["Category"] = cat
                    row["Description"] = desc
                row["Cost"] = ""
                price = base_price + float(opt.get("price_delta", 0))
                row["Price"] = f"{price:.2f}"
                row["Default price"] = f"{price:.2f}"
                row["Available for sale"] = "Y"
                row["Sold by weight"] = "N"
                # Variant option columns
                row["Option 1 name"] = "Size"
                row["Option 1 value"] = opt["en"]
                row["Track stock"] = "N"
                row["In stock"] = ""
                row["Low stock"] = ""
                # Modifier flags — only on first variant row (Loyverse
                # links modifiers to the item, not individual variants)
                if i == 0:
                    for _, display in MODIFIER_GROUPS_FOR_LOYVERSE:
                        if display in active_mod_names and display != "Pizza Size":
                            # Pizza Size is a variant, not a modifier
                            row[f'Modifier - "{display}"'] = "Y"
                rows.append(row)
        else:
            # Single-row item (slice, salad, side, dessert, drink)
            row = _blank_row()
            row["Handle"] = item_id
            row["SKU"] = item_id
            row["Name"] = name
            row["Category"] = cat
            row["Description"] = desc
            row["Cost"] = ""
            row["Price"] = f"{base_price:.2f}"
            row["Default price"] = f"{base_price:.2f}"
            row["Available for sale"] = "Y"
            row["Sold by weight"] = "N"
            row["Track stock"] = "N"
            for _, display in MODIFIER_GROUPS_FOR_LOYVERSE:
                if display in active_mod_names:
                    row[f'Modifier - "{display}"'] = "Y"
            rows.append(row)

    return rows


def _blank_row() -> dict:
    return {c: "" for c in _columns()}


def main() -> int:
    menu = yaml.safe_load((TPL / "menu.yaml").read_text())
    mg   = yaml.safe_load((TPL / "modifier_groups.yaml").read_text())

    rows = _build_rows(menu, mg)
    cols = _columns()

    # Default Downloads path (macOS); override with --out for CI.
    home = Path(os.path.expanduser("~"))
    out_path = home / "Downloads" / f"jm_pizza_loyverse_import_{date.today().isoformat()}.csv"
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"✓ Wrote {len(rows)} rows × {len(cols)} cols")
    print(f"  Path: {out_path}")
    print()
    print("📋 Manual pre-import setup required in Loyverse Back Office:")
    print("   1. Categories (7 — Items → Categories):")
    for c in REQUIRED_CATEGORIES:
        print(f"        • {c}")
    print("   2. Modifier Groups (8 — Items → Modifiers):")
    print("      (Each option's `price` field = USD delta over item base.)")
    print()
    print("      ┌────────────────────────────────────────────────────────────────────┐")
    print("      │ Group              Required  Options (en | $ delta)                │")
    print("      ├────────────────────────────────────────────────────────────────────┤")
    for code, display in MODIFIER_GROUPS_FOR_LOYVERSE:
        g = mg["groups"][code]
        req = "Yes" if g.get("required") else "No "
        print(f"      │ {display:18s} {req:8s}")
        for opt in g["options"]:
            label = opt["en"]
            delta = float(opt.get("price_delta", 0))
            sign = "+" if delta >= 0 else "−"
            print(f"      │   • {label:24s}    {sign}${abs(delta):.2f}")
        print("      │")
    print("      └────────────────────────────────────────────────────────────────────┘")
    print()
    print("   3. Import CSV: Back Office → Items → ⋯ → Import Items → Upload")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
