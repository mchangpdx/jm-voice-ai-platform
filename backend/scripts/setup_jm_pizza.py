"""
Day 1 — Set up JM Pizza store + menu_items + modifiers + mappings + cache.
(2026-05-11 — JM Pizza vertical 첫 번째 라이브 매장 셋업)

Mirrors seed_jm_kbbq.py pattern. Idempotent — re-runnable.

Pre-flight (verified 2026-05-11):
  - jmpizza@test.com Supabase auth user EXISTS (id=6f8a9187-bd30-4871-a17e-cefa34724a7a)
  - templates/pizza/{menu,modifier_groups,allergen_rules}.yaml + system_prompt_base.txt EXIST
  - _VERTICALS in transactions.py INCLUDES 'pizza'
  - knowledge/pizza.py EXISTS
  - agency.py industry == 'pizza' dispatch added

Convention notes:
  - stores.phone = manager contact (+1-503-707-9566) per JM Cafe convention.
    Twilio inbound (+1-971-444-7137) is handled in realtime_voice.py
    PHONE_TO_STORE map (Step 8).
  - industry = 'pizza' (not 'restaurant') so agency.py dispatch hits the
    pizza branch and frontend renders pizza-aware labels.
  - pos_provider = 'loyverse' + pos_api_key = access_token so Loyverse menu
    sync (Step 6, manual operator setup) can later upsert pos_item_id values
    onto these YAML-seeded rows.

Run from backend/ directory:
    .venv/bin/python scripts/setup_jm_pizza.py            # apply
    .venv/bin/python scripts/setup_jm_pizza.py --dry-run  # print plan only
"""
from __future__ import annotations

import sys
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings

REST = f"{settings.supabase_url}/rest/v1"
H_BASE = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}

# ── Constants ────────────────────────────────────────────────────────────────
PIZZA_OWNER_ID   = "6f8a9187-bd30-4871-a17e-cefa34724a7a"   # jmpizza@test.com
PIZZA_AGENCY_ID  = "755fbac2-e311-4c76-ac3b-529a751ffc2b"   # JM Agency (admin@test.com)
PIZZA_STORE_NAME = "JM Pizza"
PIZZA_PHONE      = "+15037079566"                            # manager contact (escalation)
PIZZA_TWILIO_IN  = "+19714447137"                            # Twilio inbound (informational)
PIZZA_ADDRESS    = "3570 SE Division St, Portland, OR 97202"
PIZZA_HOURS      = "Mon-Sun: 11:00 AM to 10:00 PM."
LOYVERSE_TOKEN   = "819393dd06824b90ad41fd5adabb2a86"

TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "pizza"

# Selectable modifier groups (all 8 are selectable in pizza vertical)
SELECTABLE_GROUPS = {
    "size", "crust", "sauce", "cheese",
    "topping_meat", "topping_veg",
    "wing_sauce", "dressing",
}

DRY_RUN = "--dry-run" in sys.argv


# ── Persona / Rules baked into stores columns ────────────────────────────────
SYSTEM_PROMPT = (TPL / "system_prompt_base.txt").read_text().strip()

CUSTOM_KNOWLEDGE = """FSR RULES:
1. Pickup time: standard 25-30 minutes. Friday/Saturday 6-9 PM = +10-15 min.
2. Whole pies REQUIRE size (14 inch or 18 inch) + crust (Thin / Regular / Gluten-Free / Deep Dish) before confirming price.
3. 18 inch pies = +$8 over 14 inch base.
4. Gluten-Free crust = +$4 over standard.
5. Build Your Own: ask size, crust, sauce, cheese, meat toppings, veggie toppings — in that order.
6. Slices have FIXED single size — no size or crust modifier on slices.
7. SEVERE ALLERGY (EpiPen, anaphylaxis, celiac, life-threatening) → transfer_to_manager at +1-503-707-9566. NO allergen_lookup call.
8. Cross-contamination disclosure: shared oven + flour-dusted prep surfaces. Mention for any gluten concern.

FACILITY:
- 3570 SE Division St (Main location). Other stores: N Killingsworth, East Side.
- Free Wi-Fi (ask for password at pickup).
- Pickup only (no delivery in pilot phase).
- Manager line: +1-503-707-9566.

ALLERGEN DISCLOSURES:
- Caesar dressing contains anchovy (fish) + parmesan (dairy) + egg yolk.
- Housemade meatballs contain egg + dairy + wheat (breadcrumb binder).
- Pesto contains pine nuts (tree_nut) + parmesan (dairy).
- All meats (pepperoni, sausage, Canadian bacon, bacon) are pork — flag for halal/kosher callers.
- Vegan/GF safe: Vegan Garden Pizza (with vegan_cheese), Vegan Slice, House Salad, soda."""

TEMPORARY_PROMPT = (
    "TODAY: Big Joe is the chef's signature pie. Lunch deal (11 AM - 2 PM): "
    "2 slices + soda = $9.99."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_yaml(name: str) -> dict[str, Any]:
    return yaml.safe_load((TPL / name).read_text())


def _post(path: str, payload: list[dict] | dict, conflict: str | None = None) -> httpx.Response:
    headers = {**H_BASE, "Prefer": "return=representation"}
    if conflict:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    params = {"on_conflict": conflict} if conflict else None
    r = httpx.post(f"{REST}/{path}", headers=headers, json=payload, params=params, timeout=30)
    if r.status_code not in (200, 201):
        print(f"  ✗ POST {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r


def _get(path: str, params: dict | None = None) -> list[dict]:
    r = httpx.get(f"{REST}/{path}", headers=H_BASE, params=params or {}, timeout=15)
    if r.status_code != 200:
        print(f"  ✗ GET {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


# ── Step 1: stores INSERT ────────────────────────────────────────────────────

def create_store() -> str:
    existing = _get("stores", {"owner_id": f"eq.{PIZZA_OWNER_ID}", "select": "id,name"})
    if existing:
        store_id = existing[0]["id"]
        print(f"[Step 1] stores: existing row → {store_id} (\"{existing[0]['name']}\")")
        return store_id

    payload = {
        "owner_id":         PIZZA_OWNER_ID,
        "agency_id":        PIZZA_AGENCY_ID,
        "name":             PIZZA_STORE_NAME,
        "industry":         "pizza",
        "business_type":    "pizza",
        "phone":            PIZZA_PHONE,
        "address":          PIZZA_ADDRESS,
        "business_hours":   PIZZA_HOURS,
        "is_active":        True,
        "pos_provider":     "loyverse",
        "pos_api_key":      LOYVERSE_TOKEN,
        "system_prompt":    SYSTEM_PROMPT,
        "custom_knowledge": CUSTOM_KNOWLEDGE,
        "temporary_prompt": TEMPORARY_PROMPT,
    }

    if DRY_RUN:
        print(f"[Step 1] DRY-RUN stores INSERT:")
        for k, v in payload.items():
            short = (v[:80] + "...") if isinstance(v, str) and len(v) > 80 else v
            print(f"           {k:18s} {short}")
        return "DRY-RUN-STORE-ID"

    r = _post("stores", payload)
    row = r.json()[0]
    print(f"[Step 1] stores INSERT: {row['id']} (\"{row['name']}\")")
    return row["id"]


# ── Step 2: menu_items INSERT ────────────────────────────────────────────────

def seed_menu_items(store_id: str) -> dict[str, str]:
    menu = _load_yaml("menu.yaml")
    items_yaml = menu["items"]

    if DRY_RUN:
        existing = []
    else:
        existing = _get("menu_items", {"store_id": f"eq.{store_id}", "select": "id,name,sku", "limit": "200"})
    if len(existing) >= len(items_yaml):
        print(f"[Step 2] menu_items: {len(existing)} rows already exist (≥{len(items_yaml)}) — skip")
        by_sku = {row.get("sku"): row["id"] for row in existing if row.get("sku")}
        return {item["id"]: by_sku[item["id"]] for item in items_yaml if item["id"] in by_sku}

    rows = []
    for item in items_yaml:
        # variant_id + pos_item_id are NOT NULL in menu_items — generate
        # placeholder UUIDs pre-Loyverse-sync. Loyverse webhook will overwrite
        # these with real POS object IDs on first sync.
        rows.append({
            "store_id":       store_id,
            "name":           item["en"],
            "price":          item["base_price"],
            "category":       item["category"],
            "allergens":      item.get("base_allergens", []),
            "dietary_tags":   item.get("base_dietary", []),
            "is_available":   True,
            "stock_quantity": 100,
            "variant_id":     str(uuid.uuid4()),
            "pos_item_id":    str(uuid.uuid4()),
            "sku":            item["id"],
            "description":    item.get("notes_en"),
            "raw":            {"yaml_id": item["id"], "placeholder_ids": True, "rules": item.get("rules", [])},
        })

    if DRY_RUN:
        print(f"[Step 2] DRY-RUN menu_items INSERT × {len(rows)}")
        print(f"           sample[0]: {json.dumps(rows[0], default=str)[:250]}")
        print(f"           categories: {sorted(set(r['category'] for r in rows))}")
        return {item["id"]: f"DRY-RUN-{i}" for i, item in enumerate(items_yaml)}

    r = _post("menu_items", rows)
    inserted = r.json()
    print(f"[Step 2] menu_items INSERT × {len(inserted)}")
    by_sku = {row["sku"]: row["id"] for row in inserted}
    return {item["id"]: by_sku[item["id"]] for item in items_yaml if item["id"] in by_sku}


# ── Step 3: modifier_groups upsert ───────────────────────────────────────────

def seed_modifier_groups(store_id: str) -> dict[str, str]:
    mg_yaml = _load_yaml("modifier_groups.yaml")
    groups = mg_yaml["groups"]

    payload = []
    sort_idx = 1
    for code, g in groups.items():
        if code not in SELECTABLE_GROUPS:
            continue
        payload.append({
            "store_id":     store_id,
            "code":         code,
            "display_name": code.replace("_", " ").title(),
            "is_required":  bool(g.get("required", False)),
            "min_select":   g.get("min", 0),
            "max_select":   g.get("max", 1),
            "sort_order":   sort_idx,
        })
        sort_idx += 1

    if DRY_RUN:
        print(f"[Step 3] DRY-RUN modifier_groups upsert × {len(payload)}")
        for p in payload:
            print(f"           {p['code']:14s} req={p['is_required']!s:5s} min={p['min_select']} max={p['max_select']}")
        return {p["code"]: f"DRY-RUN-G-{p['code']}" for p in payload}

    r = _post("modifier_groups", payload, conflict="store_id,code")
    rows = r.json()
    print(f"[Step 3] modifier_groups upserted × {len(rows)}")
    return {row["code"]: row["id"] for row in rows}


# ── Step 4: modifier_options upsert ──────────────────────────────────────────

def seed_modifier_options(group_ids: dict[str, str]) -> int:
    mg_yaml = _load_yaml("modifier_groups.yaml")
    groups = mg_yaml["groups"]

    payload = []
    for code, g in groups.items():
        if code not in SELECTABLE_GROUPS:
            continue
        gid = group_ids[code]
        for sort_idx, opt in enumerate(g.get("options", []), start=1):
            payload.append({
                "group_id":        gid,
                "code":            opt["id"],
                "display_name":    opt["en"],
                "price_delta":     float(opt.get("price_delta", 0.0)),
                "allergen_add":    opt.get("allergen_add", []),
                "allergen_remove": opt.get("allergen_remove", []),
                "sort_order":      sort_idx,
                "is_default":      bool(opt.get("default", False)),
                "is_available":    True,
            })

    if DRY_RUN:
        print(f"[Step 4] DRY-RUN modifier_options upsert × {len(payload)}")
        for p in payload[:6]:
            print(f"           gid={p['group_id'][-8:]} {p['code']:18s} ${p['price_delta']:.2f} default={p['is_default']}")
        print(f"           ...({len(payload) - 6} more)")
        return len(payload)

    r = _post("modifier_options", payload, conflict="group_id,code")
    print(f"[Step 4] modifier_options upserted × {len(r.json())}")
    return len(r.json())


# ── Step 5: menu_item ↔ modifier_groups mapping ──────────────────────────────

def seed_item_modifier_mapping(item_ids: dict[str, str], group_ids: dict[str, str]) -> int:
    menu = _load_yaml("menu.yaml")

    payload = []
    skipped_items: list[str] = []
    for item in menu["items"]:
        item_db_id = item_ids.get(item["id"])
        if not item_db_id:
            skipped_items.append(item["id"])
            continue
        for sort_idx, gcode in enumerate(item.get("modifier_groups", []), start=1):
            if gcode not in SELECTABLE_GROUPS:
                continue
            gid = group_ids.get(gcode)
            if not gid:
                continue
            payload.append({
                "menu_item_id": item_db_id,
                "group_id":     gid,
                "sort_order":   sort_idx,
            })

    if skipped_items:
        print(f"  WARN: {len(skipped_items)} items not yet in DB: {skipped_items[:5]}")

    if DRY_RUN:
        print(f"[Step 5] DRY-RUN menu_item_modifier_groups upsert × {len(payload)}")
        return len(payload)

    if not payload:
        print(f"[Step 5] menu_item_modifier_groups: nothing to map")
        return 0

    r = _post("menu_item_modifier_groups", payload, conflict="menu_item_id,group_id")
    print(f"[Step 5] menu_item_modifier_groups upserted × {len(r.json())}")
    return len(r.json())


# ── Step 6: stores.menu_cache rebuild ────────────────────────────────────────

def update_menu_cache(store_id: str) -> None:
    if DRY_RUN:
        menu_yaml = _load_yaml("menu.yaml")
        items = sorted(
            [{"name": it["en"], "price": it["base_price"], "category": it["category"]}
             for it in menu_yaml["items"]],
            key=lambda x: (x["category"], x["name"]),
        )
    else:
        items = _get("menu_items", {
            "store_id":     f"eq.{store_id}",
            "is_available": "eq.true",
            "select":       "name,price,category",
            "order":        "category.asc,name.asc",
        })

    lines: list[str] = []
    last_cat: str | None = None
    for it in items:
        cat = it.get("category") or "other"
        if cat != last_cat:
            lines.append(f"\n[{cat.upper()}]")
            last_cat = cat
        lines.append(f"{it['name']} - ${float(it['price']):.2f}")
    cache = "\n".join(lines).strip()

    if DRY_RUN:
        print(f"[Step 6] DRY-RUN stores.menu_cache UPDATE ({len(cache)} chars)")
        print(f"           preview: {cache[:200]!r}")
        return

    r = httpx.patch(
        f"{REST}/stores",
        headers=H_BASE,
        params={"id": f"eq.{store_id}"},
        json={"menu_cache": cache},
        timeout=15,
    )
    if r.status_code not in (200, 204):
        print(f"  ✗ menu_cache UPDATE failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    print(f"[Step 6] stores.menu_cache updated ({len(cache)} chars, {len(items)} items)")


# ── Step 7: verify ───────────────────────────────────────────────────────────

def verify(store_id: str) -> None:
    if DRY_RUN:
        print(f"[Step 7] DRY-RUN — verify skipped")
        return

    items   = _get("menu_items", {"store_id": f"eq.{store_id}", "select": "id"})
    groups  = _get("modifier_groups", {"store_id": f"eq.{store_id}", "select": "id,code"})
    gids    = [g["id"] for g in groups]
    if gids:
        opts = _get("modifier_options", {"group_id": f"in.({','.join(gids)})", "select": "id"})
    else:
        opts = []
    print()
    print("=" * 60)
    print(f"  VERIFY (store_id={store_id})")
    print("=" * 60)
    print(f"  menu_items            {len(items):4d}  (expected 24)")
    print(f"  modifier_groups       {len(groups):4d}  (expected 8)")
    print(f"  modifier_options      {len(opts):4d}  (expected 39+)")
    print(f"  groups codes:         {sorted(g['code'] for g in groups)}")
    print()
    if len(items) != 24:
        print(f"  ⚠ menu_items count mismatch: {len(items)} != 24")
    if len(groups) != 8:
        print(f"  ⚠ modifier_groups count mismatch: {len(groups)} != 8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\nJM Pizza — Day 1 setup (DRY_RUN={DRY_RUN})\n")
    store_id  = create_store()
    item_ids  = seed_menu_items(store_id)
    group_ids = seed_modifier_groups(store_id)
    seed_modifier_options(group_ids)
    seed_item_modifier_mapping(item_ids, group_ids)
    update_menu_cache(store_id)
    verify(store_id)
    print(f"\n✓ Done. store_id = {store_id}")
    print(f"  Twilio inbound = {PIZZA_TWILIO_IN}  (configure routing in Step 8)")
    print(f"  Manager contact = {PIZZA_PHONE}  (escalation)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
