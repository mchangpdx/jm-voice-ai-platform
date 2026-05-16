"""
Auto-create Loyverse categories + modifiers + items from JM Pizza templates.
(2026-05-12 — Loyverse Back Office 수동 입력 대체 자동화)

Why:
  Loyverse Back Office에 24 items + 7 categories + 8 modifiers + 37 options를
  수동 입력하면 30-45분 소요됨. Loyverse API가 모든 entity의 POST를 지원하므로
  90초 안에 자동 셋업 가능. CSV import도 우회.

Idempotency strategy:
  - Categories: skip if name already exists (case-sensitive match)
  - Modifiers: skip if name already exists
  - Items: skip if handle already exists (handle = yaml.id)
  Re-running this script is safe — already-created entities are reused.

Order of operations (CRITICAL — items depend on category + modifier IDs):
  1. POST /categories × 7   (Signature Pies, Classic Pies, ...)
  2. POST /modifiers × 8    (Pizza Size NOT POSTed — handled as variant)
  3. POST /items × 24       (with variants, category_id, modifier_ids[])
  4. Save mapping JSON      (yaml.id ↔ loyverse_uuid)

Variant vs Modifier distinction (matches export_pizza_loyverse_csv.py):
  - Pizza Size (14"/18") → Loyverse VARIANT (option1_name="Size",
                                              option1_value="14 inch" etc.)
  - Crust/Sauce/Cheese/Meat/Veggie/Wing/Dressing → Loyverse MODIFIER
                                                    (modifier_ids[] on item)

Mapping output:
  backend/scripts/.jm_pizza_loyverse_ids.json
  Used by cleanup_pizza_placeholders.py post to verify SKU matching.

Run:
    .venv/bin/python scripts/auto_loyverse_setup.py            # apply
    .venv/bin/python scripts/auto_loyverse_setup.py --dry-run  # plan only
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

LOYVERSE_API = "https://api.loyverse.com/v1.0"
LOYVERSE_TOKEN = "819393dd06824b90ad41fd5adabb2a86"
LOYVERSE_STORE_ID = "7d6cad08-5b7b-4f8c-b9d1-e3998ca655f0"   # JM Pizza Loyverse store
H = {
    "Authorization": f"Bearer {LOYVERSE_TOKEN}",
    "Content-Type":  "application/json",
}

TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "pizza"
MAPPING_FILE = Path(__file__).resolve().parent / ".jm_pizza_loyverse_ids.json"

# yaml category id → Loyverse display name + color
CATEGORY_DISPLAY = [
    ("signature_pie", "Signature Pies", "RED"),
    ("classic_pie",   "Classic Pies",   "ORANGE"),
    ("slice",         "Slices",         "PINK"),    # YELLOW is not a Loyverse enum
    ("salad",         "Salads",         "GREEN"),
    ("side",          "Sides",          "BLUE"),
    ("dessert",       "Desserts",       "PURPLE"),
    ("drink",         "Drinks",         "GREY"),
]

# yaml modifier group code → (Loyverse display name, treat-as-variant?)
# 'size' is variant (option1), the rest are modifiers.
MODIFIER_DISPLAY = [
    ("size",         "Pizza Size",     True),   # variant — NOT POSTed as modifier
    ("crust",        "Crust Type",     False),
    ("sauce",        "Sauce",          False),
    ("cheese",       "Cheese",         False),
    ("topping_meat", "Meat Topping",   False),
    ("topping_veg",  "Veggie Topping", False),
    ("wing_sauce",   "Wing Sauce",     False),
    ("dressing",     "Salad Dressing", False),
]

DRY_RUN = "--dry-run" in sys.argv


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(f"{LOYVERSE_API}/{path}", headers=H, params=params or {}, timeout=20)
    if r.status_code != 200:
        print(f"  ✗ GET /{path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(f"{LOYVERSE_API}/{path}", headers=H, json=body, timeout=30)
    if r.status_code not in (200, 201):
        print(f"  ✗ POST /{path} failed: {r.status_code}")
        print(f"      body={json.dumps(body)[:300]}")
        print(f"      resp={r.text[:300]}")
        sys.exit(1)
    return r.json()


# ── Phase 1.1 — Categories ───────────────────────────────────────────────────

def setup_categories() -> dict[str, str]:
    """Create 7 categories. Returns {yaml_id: loyverse_uuid}."""
    print("\n[1/3] Categories")
    existing = _get("categories", {"limit": "100"}).get("categories", [])
    by_name = {c["name"]: c["id"] for c in existing}

    out: dict[str, str] = {}
    created = skipped = 0
    for yaml_id, display, color in CATEGORY_DISPLAY:
        if display in by_name:
            out[yaml_id] = by_name[display]
            skipped += 1
            print(f"    · {display:18s} SKIP (exists) → {by_name[display][:8]}")
            continue

        if DRY_RUN:
            out[yaml_id] = f"DRY-{yaml_id}"
            created += 1
            print(f"    + {display:18s} CREATE  color={color}  (dry-run)")
            continue

        body = {"name": display, "color": color}
        resp = _post("categories", body)
        out[yaml_id] = resp["id"]
        created += 1
        print(f"    + {display:18s} CREATE  color={color} → {resp['id'][:8]}")

    print(f"  → {created} created, {skipped} skipped")
    return out


# ── Phase 1.2 — Modifiers (size is excluded — variant instead) ──────────────

def setup_modifiers(menu_yaml: dict, mg_yaml: dict) -> dict[str, str]:
    """Create 7 modifiers (size excluded). Returns {yaml_id: loyverse_uuid}."""
    print("\n[2/3] Modifiers")
    existing = _get("modifiers", {"limit": "100"}).get("modifiers", [])
    by_name = {m["name"]: m["id"] for m in existing}

    out: dict[str, str] = {}
    created = skipped = 0
    for yaml_id, display, is_variant in MODIFIER_DISPLAY:
        if is_variant:
            # Pizza Size is handled as Loyverse variant, not modifier.
            continue

        if display in by_name:
            out[yaml_id] = by_name[display]
            skipped += 1
            print(f"    · {display:18s} SKIP (exists) → {by_name[display][:8]}")
            continue

        # Build modifier_options from yaml
        group = mg_yaml["groups"][yaml_id]
        opts = []
        for opt in group["options"]:
            # Loyverse uses non-negative prices; clamp negatives.
            price = max(0.0, float(opt.get("price_delta", 0.0)))
            opts.append({"name": opt["en"], "price": round(price, 2)})

        if DRY_RUN:
            out[yaml_id] = f"DRY-{yaml_id}"
            created += 1
            print(f"    + {display:18s} CREATE  options={len(opts)}  (dry-run)")
            continue

        # Without `stores`, the modifier is created but invisible in the POS
        # app (Back Office shows it, but cashier UI does not). Assigning the
        # store ID here makes it usable for in-store ordering.
        # (modifier가 POS app에 노출되려면 stores 배열 필수)
        body = {"name": display, "modifier_options": opts, "stores": [LOYVERSE_STORE_ID]}
        resp = _post("modifiers", body)
        out[yaml_id] = resp["id"]
        created += 1
        print(f"    + {display:18s} CREATE  options={len(opts)} → {resp['id'][:8]}")

    print(f"  → {created} created, {skipped} skipped (size is a variant — not posted)")
    return out


# ── Phase 1.3 — Items + Variants ─────────────────────────────────────────────

def setup_items(menu_yaml: dict, mg_yaml: dict,
                cat_map: dict[str, str], mod_map: dict[str, str]) -> dict[str, dict]:
    """Create 24 items with variants + category + modifiers. Returns mapping."""
    print("\n[3/3] Items")
    existing = _get("items", {"limit": "200"}).get("items", [])
    by_handle = {i["handle"]: i for i in existing}

    size_group = mg_yaml["groups"]["size"]
    size_options = size_group["options"]   # [{id:14inch, en:"14 inch (Small)", price_delta:0}, ...]

    out: dict[str, dict] = {}
    created = skipped = 0

    for item in menu_yaml["items"]:
        yaml_id = item["id"]
        name = item["en"]
        cat_id = cat_map.get(item["category"])
        base_price = float(item["base_price"])
        item_modifier_codes = [g for g in item.get("modifier_groups", []) if g != "size"]
        item_modifier_ids = [mod_map[c] for c in item_modifier_codes if c in mod_map]
        has_size = "size" in item.get("modifier_groups", [])

        if yaml_id in by_handle:
            existing_item = by_handle[yaml_id]
            out[yaml_id] = {
                "id": existing_item["id"],
                "variants": {v["sku"]: v["variant_id"] for v in existing_item.get("variants", [])},
            }
            skipped += 1
            print(f"    · {name:30s} SKIP (exists) → {existing_item['id'][:8]}")
            continue

        # Build variants
        variants_body = []
        if has_size:
            for opt in size_options:
                vp = base_price + float(opt.get("price_delta", 0.0))
                variants_body.append({
                    "variant_name": opt["en"],
                    "sku":          f"{yaml_id}_{opt['id']}",
                    "option1_value": opt["en"],
                    "default_pricing_type": "FIXED",
                    "default_price": round(vp, 2),
                    "stores": [{
                        "store_id":     LOYVERSE_STORE_ID,
                        "pricing_type": "FIXED",
                        "price":        round(vp, 2),
                        "available_for_sale": True,
                    }],
                })
        else:
            variants_body.append({
                "variant_name": "",
                "sku":          yaml_id,
                "default_pricing_type": "FIXED",
                "default_price": round(base_price, 2),
                "stores": [{
                    "store_id":     LOYVERSE_STORE_ID,
                    "pricing_type": "FIXED",
                    "price":        round(base_price, 2),
                    "available_for_sale": True,
                }],
            })

        body: dict[str, Any] = {
            "item_name":      name,
            "handle":         yaml_id,
            "category_id":    cat_id,
            "modifier_ids":   item_modifier_ids,
            "description":    item.get("notes_en"),
            "track_stock":    False,
            "sold_by_weight": False,
            "is_composite":   False,
            "use_production": False,
            "variants":       variants_body,
        }
        if has_size:
            body["option1_name"] = "Size"

        if DRY_RUN:
            out[yaml_id] = {"id": f"DRY-{yaml_id}", "variants": {v["sku"]: f"DRY-V-{v['sku']}" for v in variants_body}}
            created += 1
            print(f"    + {name:30s} CREATE  variants={len(variants_body)} mods={len(item_modifier_ids)}  (dry-run)")
            continue

        resp = _post("items", body)
        out[yaml_id] = {
            "id":       resp["id"],
            "variants": {v["sku"]: v["variant_id"] for v in resp["variants"]},
        }
        created += 1
        print(f"    + {name:30s} CREATE  variants={len(variants_body)} mods={len(item_modifier_ids)} → {resp['id'][:8]}")
        # Loyverse rate limit cushion (≤ 300 req / 5 min — well within)
        time.sleep(0.10)

    print(f"  → {created} created, {skipped} skipped")
    return out


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\nLoyverse auto-setup — JM Pizza (DRY_RUN={DRY_RUN})")
    print(f"  store: {LOYVERSE_STORE_ID}")

    menu_yaml = yaml.safe_load((TPL / "menu.yaml").read_text())
    mg_yaml = yaml.safe_load((TPL / "modifier_groups.yaml").read_text())

    cat_map = setup_categories()
    mod_map = setup_modifiers(menu_yaml, mg_yaml)
    item_map = setup_items(menu_yaml, mg_yaml, cat_map, mod_map)

    mapping = {
        "loyverse_store_id": LOYVERSE_STORE_ID,
        "categories":        cat_map,
        "modifiers":         mod_map,
        "items":             item_map,
    }

    if not DRY_RUN:
        MAPPING_FILE.write_text(json.dumps(mapping, indent=2))
        print(f"\n✓ Mapping saved: {MAPPING_FILE}")

    print()
    print("=" * 70)
    print(f"  CATEGORIES   {len(cat_map)} (expect 7)")
    print(f"  MODIFIERS    {len(mod_map)} (expect 7 — 'size' is variant)")
    print(f"  ITEMS        {len(item_map)} (expect 24)")
    n_variants = sum(len(v["variants"]) for v in item_map.values())
    print(f"  VARIANTS     {n_variants} (expect 34 — 10 pies×2 + 14 single)")
    print("=" * 70)

    if not DRY_RUN:
        print("\n  NEXT — run:")
        print("    .venv/bin/python scripts/cleanup_pizza_placeholders.py pre")
        print("    .venv/bin/python scripts/cleanup_pizza_placeholders.py post")
    return 0


if __name__ == "__main__":
    sys.exit(main())
