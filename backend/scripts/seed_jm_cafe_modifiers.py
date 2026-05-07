"""
Phase 7-A — Seed JM Cafe modifier groups + options + menu_item mappings.
(2026-05-07 — JM Cafe modifier 데이터 seed)

Prerequisite: backend/scripts/migrate_modifier_system.sql must be applied
via Supabase SQL Editor first (creates 3 tables + RLS).

Idempotent: re-running upserts existing rows by (store_id, code) /
(group_id, code) unique constraints. Safe to run multiple times.

Run from /Users/mchangpdx/jm-voice-ai-platform/backend:
    .venv/bin/python scripts/seed_jm_cafe_modifiers.py
"""
from __future__ import annotations

import sys
import httpx
from app.core.config import settings

REST = f"{settings.supabase_url}/rest/v1"
H_BASE = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
JM_CAFE = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"


# ── 9 modifier groups ─────────────────────────────────────────────────────────
GROUPS = [
    # (code, display_name, is_required, min, max, sort_order)
    ("size",          "Size",              True,  1, 1, 1),
    ("temperature",   "Temperature",       True,  1, 1, 2),
    ("milk",          "Milk",              True,  1, 1, 3),  # Required for milk drinks
    ("milk_optional", "Milk (optional)",   False, 0, 1, 4),  # Optional for non-milk drinks
    ("shots",         "Espresso shots",    False, 0, 2, 5),
    ("syrup",         "Syrup",             False, 0, 3, 6),
    ("strength",      "Strength",          False, 0, 1, 7),
    ("foam",          "Foam",              False, 0, 1, 8),
    ("whip",          "Whipped cream",     False, 0, 1, 9),
]


# ── Options per group ─────────────────────────────────────────────────────────
# (group_code, code, display_name, price_delta, allergen_add[], allergen_remove[], sort, is_default)
OPTIONS = [
    # Size
    ("size", "small",  "12oz",   0.00, [], [], 1, True),
    ("size", "medium", "16oz",   0.50, [], [], 2, False),
    ("size", "large",  "20oz",   1.00, [], [], 3, False),
    ("size", "single", "Single", 0.00, [], [], 4, False),  # for Espresso

    # Temperature
    ("temperature", "hot",     "Hot",     0.00, [],        [], 1, True),
    ("temperature", "iced",    "Iced",    0.00, [],        [], 2, False),
    ("temperature", "blended", "Blended", 0.75, ["dairy"], [], 3, False),

    # Milk (REQUIRED for milk drinks — allergen-impacting!)
    ("milk", "whole",   "Whole milk",   0.00, ["dairy"],          [],        1, True),
    ("milk", "two_pct", "2% milk",      0.00, ["dairy"],          [],        2, False),
    ("milk", "skim",    "Skim milk",    0.00, ["dairy"],          [],        3, False),
    ("milk", "oat",     "Oat milk",     0.75, ["gluten","wheat"], ["dairy"], 4, False),
    ("milk", "almond",  "Almond milk",  0.75, ["nuts"],           ["dairy"], 5, False),
    ("milk", "soy",     "Soy milk",     0.75, ["soy"],            ["dairy"], 6, False),
    ("milk", "coconut", "Coconut milk", 0.75, [],                 ["dairy"], 7, False),

    # Milk optional (same options for non-milk drinks like Drip/Americano)
    ("milk_optional", "whole",   "Whole milk",   0.00, ["dairy"],          [],        1, False),
    ("milk_optional", "two_pct", "2% milk",      0.00, ["dairy"],          [],        2, False),
    ("milk_optional", "skim",    "Skim milk",    0.00, ["dairy"],          [],        3, False),
    ("milk_optional", "oat",     "Oat milk",     0.75, ["gluten","wheat"], [],        4, False),
    ("milk_optional", "almond",  "Almond milk",  0.75, ["nuts"],           [],        5, False),
    ("milk_optional", "soy",     "Soy milk",     0.75, ["soy"],            [],        6, False),
    ("milk_optional", "coconut", "Coconut milk", 0.75, [],                 [],        7, False),

    # Shots
    ("shots", "plus_one", "+1 shot",  1.00, [], [], 1, False),
    ("shots", "plus_two", "+2 shots", 2.00, [], [], 2, False),

    # Syrup
    ("syrup", "vanilla",     "Vanilla",            0.75, [],        [], 1, False),
    ("syrup", "hazelnut",    "Hazelnut",           0.75, ["nuts"],  [], 2, False),
    ("syrup", "caramel",     "Caramel",            0.75, ["dairy"], [], 3, False),
    ("syrup", "lavender",    "Lavender",           0.75, [],        [], 4, False),
    ("syrup", "vanilla_sf",  "Sugar-free Vanilla", 0.75, [],        [], 5, False),
    ("syrup", "brown_sugar", "Brown sugar",        0.50, [],        [], 6, False),
    ("syrup", "honey",       "Honey",              0.50, [],        [], 7, False),

    # Strength
    ("strength", "regular",  "Regular",  0.00, [], [], 1, True),
    ("strength", "decaf",    "Decaf",    0.00, [], [], 2, False),
    ("strength", "half_caf", "Half-caf", 0.00, [], [], 3, False),

    # Foam
    ("foam", "regular", "Regular foam",      0.00, [], [], 1, True),
    ("foam", "dry",     "Extra foam (dry)",  0.00, [], [], 2, False),
    ("foam", "wet",     "Light foam (wet)",  0.00, [], [], 3, False),
    ("foam", "no_foam", "No foam",           0.00, [], [], 4, False),

    # Whip
    ("whip", "with_whip", "With whip", 0.00, ["dairy"], [], 1, False),
    ("whip", "no_whip",   "No whip",   0.00, [],        [], 2, True),
]


# ── menu_item ↔ groups mapping (item name → list of group codes) ─────────────
ITEM_GROUPS = {
    # Espresso (8)
    "Drip Coffee":          ["size", "temperature", "milk_optional", "syrup", "strength"],
    "Americano":            ["size", "temperature", "milk_optional", "shots", "syrup", "strength"],
    "Espresso":             ["size", "strength"],
    "Macchiato":            ["size", "temperature", "milk", "shots", "syrup", "strength", "foam"],
    "Cappuccino":           ["size", "temperature", "milk", "shots", "syrup", "strength", "foam"],
    "Cafe Latte":           ["size", "temperature", "milk", "shots", "syrup", "strength", "foam"],
    "Mocha":                ["size", "temperature", "milk", "shots", "syrup", "strength", "foam", "whip"],
    "Flat White":           ["size", "temperature", "milk", "shots", "syrup", "strength"],

    # Non-Espresso (5)
    "Cold Brew":            ["size", "milk_optional", "syrup", "strength"],
    "Iced Tea":             ["size", "syrup"],
    "Matcha Latte":         ["size", "temperature", "milk", "syrup", "foam", "whip"],
    "Chai Latte":           ["size", "temperature", "milk", "syrup", "foam", "whip"],
    "Hot Chocolate":        ["size", "temperature", "milk", "syrup", "foam", "whip"],

    # Pastry / Food / Dessert: no modifiers in V0 (operator can add later)
}


def upsert_groups() -> dict[str, str]:
    """Insert/update modifier_groups, return {code: id} map."""
    payload = [{
        "store_id":     JM_CAFE,
        "code":         code,
        "display_name": name,
        "is_required":  req,
        "min_select":   mn,
        "max_select":   mx,
        "sort_order":   sort,
    } for (code, name, req, mn, mx, sort) in GROUPS]

    r = httpx.post(
        f"{REST}/modifier_groups",
        headers={**H_BASE, "Prefer": "resolution=merge-duplicates,return=representation"},
        params={"on_conflict": "store_id,code"},
        json=payload,
    )
    if r.status_code not in (200, 201):
        print(f"  ERROR upserting groups: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    rows = r.json()
    print(f"[Step 1] modifier_groups upserted: {len(rows)}")
    return {row["code"]: row["id"] for row in rows}


def upsert_options(group_ids: dict[str, str]) -> int:
    """Insert/update modifier_options."""
    payload = []
    for (gcode, code, name, delta, add, remove, sort, default) in OPTIONS:
        payload.append({
            "group_id":        group_ids[gcode],
            "code":            code,
            "display_name":    name,
            "price_delta":     delta,
            "allergen_add":    add,
            "allergen_remove": remove,
            "sort_order":      sort,
            "is_default":      default,
            "is_available":    True,
        })
    r = httpx.post(
        f"{REST}/modifier_options",
        headers={**H_BASE, "Prefer": "resolution=merge-duplicates,return=representation"},
        params={"on_conflict": "group_id,code"},
        json=payload,
    )
    if r.status_code not in (200, 201):
        print(f"  ERROR upserting options: {r.status_code} {r.text[:500]}")
        sys.exit(1)
    print(f"[Step 2] modifier_options upserted: {len(r.json())}")
    return len(r.json())


def get_menu_item_ids() -> dict[str, str]:
    """Fetch menu_item.name → id map for active items."""
    r = httpx.get(
        f"{REST}/menu_items",
        headers=H_BASE,
        params={
            "store_id":     f"eq.{JM_CAFE}",
            "is_available": "eq.true",
            "select":       "id,name",
        },
    )
    return {row["name"]: row["id"] for row in r.json()}


def upsert_item_groups(item_ids: dict[str, str], group_ids: dict[str, str]) -> int:
    """Insert/update menu_item_modifier_groups mapping."""
    payload = []
    missing_items = []
    for (item_name, codes) in ITEM_GROUPS.items():
        item_id = item_ids.get(item_name)
        if not item_id:
            missing_items.append(item_name)
            continue
        for sort_idx, gcode in enumerate(codes, start=1):
            payload.append({
                "menu_item_id": item_id,
                "group_id":     group_ids[gcode],
                "sort_order":   sort_idx,
            })

    if missing_items:
        print(f"  WARN: {len(missing_items)} items not found in DB: {missing_items}")

    r = httpx.post(
        f"{REST}/menu_item_modifier_groups",
        headers={**H_BASE, "Prefer": "resolution=merge-duplicates,return=representation"},
        params={"on_conflict": "menu_item_id,group_id"},
        json=payload,
    )
    if r.status_code not in (200, 201):
        print(f"  ERROR upserting mappings: {r.status_code} {r.text[:500]}")
        sys.exit(1)
    print(f"[Step 3] menu_item_modifier_groups upserted: {len(r.json())}")
    return len(r.json())


def verify(group_ids: dict[str, str]) -> None:
    """Print summary."""
    # Per-group option counts
    print("\n[Verify] Options per group:")
    for code, gid in sorted(group_ids.items()):
        r = httpx.get(
            f"{REST}/modifier_options",
            headers=H_BASE,
            params={"group_id": f"eq.{gid}", "select": "code"},
        )
        print(f"  {code:18s} {len(r.json()):>2} options")

    # Per-item group count
    print("\n[Verify] Modifier groups per item:")
    item_ids = get_menu_item_ids()
    for name, item_id in sorted(item_ids.items()):
        r = httpx.get(
            f"{REST}/menu_item_modifier_groups",
            headers=H_BASE,
            params={"menu_item_id": f"eq.{item_id}", "select": "group_id"},
        )
        n = len(r.json())
        marker = "  " if n == 0 else " ✓"
        print(f" {marker} {name:35s} {n} groups")


def main():
    print("=== Seeding JM Cafe modifier system ===\n")
    group_ids = upsert_groups()
    upsert_options(group_ids)
    item_ids = get_menu_item_ids()
    upsert_item_groups(item_ids, group_ids)
    verify(group_ids)
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
