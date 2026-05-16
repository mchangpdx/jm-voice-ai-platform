"""
Re-link JM Pizza items → Loyverse modifier_ids.
(2026-05-12 — auto_loyverse_setup.py에서 modifier_ids 미적용된 24 items 복구)

Why:
  When auto_loyverse_setup.py ran originally, Loyverse modifiers were created
  WITHOUT a `stores` array — they existed in Back Office but weren't visible
  to the POS app, AND Loyverse silently dropped `modifier_ids` from item
  creation requests because the modifiers weren't yet bound to the store.
  Q2 fix patched modifier.stores. This script now re-applies modifier_ids on
  the 24 items so they appear in the POS modifier menu.

Mechanism:
  Loyverse uses POST /items with `id` in body as the upsert pattern (same
  shape as the modifier upsert we used in Q2). Each item is patched with the
  full modifier_ids list mapped from menu.yaml + the cached loyverse_uuid
  mapping at scripts/.jm_pizza_loyverse_ids.json.

Run:
    .venv/bin/python scripts/relink_pizza_modifiers.py
    .venv/bin/python scripts/relink_pizza_modifiers.py --dry-run
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import yaml

LOYVERSE_API = "https://api.loyverse.com/v1.0"
LOYVERSE_TOKEN = "819393dd06824b90ad41fd5adabb2a86"
H = {"Authorization": f"Bearer {LOYVERSE_TOKEN}", "Content-Type": "application/json"}

HERE = Path(__file__).resolve().parent
TPL = HERE.parent / "app" / "templates" / "pizza"
MAPPING_FILE = HERE / ".jm_pizza_loyverse_ids.json"

# 'size' is a variant in Loyverse — not a modifier
SIZE_GROUP_CODE = "size"

DRY_RUN = "--dry-run" in sys.argv


def main() -> int:
    print(f"\nJM Pizza modifier re-link (DRY_RUN={DRY_RUN})\n")

    # 1. Load yaml-id → loyverse-uuid mapping
    if MAPPING_FILE.exists():
        mapping = json.loads(MAPPING_FILE.read_text())
        mod_map = mapping["modifiers"]       # {"crust": "0ae166d3-...", ...}
        item_map = mapping["items"]           # {"big_joe": {"id": "...", ...}}
        print(f"  Loaded mapping from {MAPPING_FILE.name}")
    else:
        # Rebuild from live Loyverse (fallback if mapping JSON missing)
        print("  Mapping file missing — rebuilding from live Loyverse...")
        mods = httpx.get(f"{LOYVERSE_API}/modifiers?limit=50", headers=H).json().get("modifiers", [])
        items = httpx.get(f"{LOYVERSE_API}/items?limit=200", headers=H).json().get("items", [])
        # Name → code is a known yaml mapping
        name_to_code = {
            "Pizza Size": "size", "Crust Type": "crust", "Sauce": "sauce",
            "Cheese": "cheese", "Meat Topping": "topping_meat",
            "Veggie Topping": "topping_veg", "Wing Sauce": "wing_sauce",
            "Salad Dressing": "dressing",
        }
        mod_map = {name_to_code.get(m["name"]): m["id"] for m in mods if name_to_code.get(m["name"])}
        item_map = {i["handle"].replace("-", "_"): {"id": i["id"]} for i in items}

    # 2. Load menu.yaml to know which item gets which modifier groups
    menu = yaml.safe_load((TPL / "menu.yaml").read_text())

    # 3. For each item, compute the modifier_ids list and POST upsert
    updated = skipped = failed = 0
    for item in menu["items"]:
        yaml_id = item["id"]
        item_info = item_map.get(yaml_id)
        if not item_info:
            # Try fuzzy fallback: items in Loyverse use handle = yaml_id but the
            # legacy mapping JSON may use a different key. Skip the unknown ones
            # and report at the end.
            print(f"  ? {item['en']:30s} SKIP — no Loyverse id in mapping (yaml_id={yaml_id!r})")
            skipped += 1
            continue

        loy_item_id = item_info["id"] if isinstance(item_info, dict) else item_info
        modifier_codes = [c for c in item.get("modifier_groups", []) if c != SIZE_GROUP_CODE]
        loy_mod_ids = [mod_map[c] for c in modifier_codes if c in mod_map]

        if not loy_mod_ids:
            print(f"  · {item['en']:30s} SKIP — no non-size modifiers in yaml")
            skipped += 1
            continue

        # Fetch live item so we don't accidentally clear other fields on upsert
        live = httpx.get(f"{LOYVERSE_API}/items/{loy_item_id}", headers=H, timeout=15).json()
        current_mod_ids = live.get("modifier_ids") or []
        if set(current_mod_ids) == set(loy_mod_ids):
            print(f"  · {item['en']:30s} OK — already linked ({len(loy_mod_ids)} mods)")
            skipped += 1
            continue

        body = {
            "id":           loy_item_id,
            "item_name":    live["item_name"],
            "handle":       live["handle"],
            "category_id":  live.get("category_id"),
            "modifier_ids": loy_mod_ids,
            "track_stock":  live.get("track_stock", False),
            "sold_by_weight": live.get("sold_by_weight", False),
            "is_composite": live.get("is_composite", False),
            "use_production": live.get("use_production", False),
            # Variants must be supplied or Loyverse will reset them
            "variants": [
                {
                    "variant_id":           v["variant_id"],
                    "sku":                  v.get("sku"),
                    "option1_value":        v.get("option1_value"),
                    "default_pricing_type": v.get("default_pricing_type", "FIXED"),
                    "default_price":        v.get("default_price"),
                    "stores":               v.get("stores", []),
                }
                for v in live.get("variants", [])
            ],
        }
        if live.get("option1_name"):
            body["option1_name"] = live["option1_name"]

        if DRY_RUN:
            print(f"  + {item['en']:30s} would link {len(loy_mod_ids)} modifiers (dry-run)")
            updated += 1
            continue

        r = httpx.post(f"{LOYVERSE_API}/items", headers=H, json=body, timeout=30)
        if r.status_code in (200, 201):
            new_mod_ids = r.json().get("modifier_ids") or []
            if set(new_mod_ids) == set(loy_mod_ids):
                print(f"  + {item['en']:30s} LINKED {len(loy_mod_ids)} modifiers ✓")
                updated += 1
            else:
                print(f"  ⚠ {item['en']:30s} returned {len(new_mod_ids)} modifiers (expected {len(loy_mod_ids)})")
                failed += 1
        else:
            print(f"  ✗ {item['en']:30s} HTTP {r.status_code}: {r.text[:200]}")
            failed += 1
        time.sleep(0.10)   # Loyverse rate-limit cushion

    print()
    print("=" * 70)
    print(f"  Updated: {updated}   Skipped: {skipped}   Failed: {failed}")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
