"""
Day 2 — Seed JM Korean BBQ store + menu_items + modifiers + mappings + cache.
(2026-05-10 — JM Korean BBQ vertical 첫 번째 매장 seed)

Idempotent: re-runnable. Each step checks for existing data via unique
constraints / count checks and either upserts or skips.

Pre-flight (run once before this script):
  - jmkbbq@test.com Supabase auth user must exist with email_confirmed_at != null
  - templates/kbbq/{menu,modifier_groups,allergen_rules}.yaml must exist
  - _VERTICALS in transactions.py must include 'kbbq'
  - migrate_modifier_system.sql + migrate_modifier_system_grants_fix.sql applied

Run from backend/ directory:
    .venv/bin/python scripts/seed_jm_kbbq.py            # apply
    .venv/bin/python scripts/seed_jm_kbbq.py --dry-run  # print plan only
"""
from __future__ import annotations

import sys
import json
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
KBBQ_OWNER_ID    = "0a1cf9bd-1ad6-49d1-b506-c1320e06d742"   # jmkbbq@test.com
KBBQ_AGENCY_ID   = "755fbac2-e311-4c76-ac3b-529a751ffc2b"   # JM Agency (shared with cafe)
KBBQ_STORE_NAME  = "JM Korean BBQ"
KBBQ_PHONE       = "+19714447137"
KBBQ_ADDRESS     = "Woodburn, OR"
KBBQ_HOURS       = "Tuesday to Sunday: 11:30 AM to 10:00 PM. Closed on Mondays."
LOYVERSE_TOKEN   = "40a1afc3e2784ea9b1ae4de4b279df12"

# Templates path
TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "kbbq"

# Selectable modifier groups (info-only / hard-rule / auto-rule are NOT seeded —
# those are enforced by voice agent system prompt, not POS/DB)
SELECTABLE_GROUPS = {
    "meat_doneness", "spice_level", "bbq_party_size",
    "pork_cut_thickness", "add_on_starch", "egg_style",
    "wrap_extras", "rice_swap", "size_s_m",
}

DRY_RUN = "--dry-run" in sys.argv


# ── Persona / FSR rules / facility info baked into stores columns ────────────
SYSTEM_PROMPT = (
    "You are Yuna, the AI voice assistant for JM Korean BBQ in Woodburn, "
    "Oregon. Speak naturally — like a friendly Korean restaurant host, not "
    "a robot. Keep every reply to 1-2 short sentences. Voice only — no "
    "markdown. Detect language from caller's first utterance and respond "
    "in English or Korean (한국어). Korean food proper nouns (Galbi, "
    "Bulgogi, Samgyeopsal, Bibimbap, Tteokbokki, Soondae, Banchan, Pajeon, "
    "Bossam, Jokbal, Kimchi) stay romanized — do not translate."
)

CUSTOM_KNOWLEDGE = """FSR RULES:
1. BBQ A La Carte requires minimum 2 portions per item — politely decline single-portion orders and offer 2.
2. Hot Pot (전골류) serves 2 people each. For larger parties, suggest multiple hot pots.
3. BBQ Combo A and Combo B are fixed sets — NO substitutions. Offer A La Carte if caller wants different combinations.
4. Rice and banchan (Korean side dishes) are unlimited refill on dine-in for BBQ A La Carte, Hot Pot, and Entrees. Combos include corn cheese/egg/rice cake but NO free refills on those.
5. For parties of 6 or more, automatically add 18% service charge — inform caller before confirming.
6. Solicit doneness for BBQ Beef (Saeng Galbi, Deung Shim, Jumullleok): rare/medium-rare/medium/medium-well/well-done.
7. Confirm spice level for spicy items: mild/medium/hot/extra hot.

FACILITY:
- Free Wi-Fi password: jmkbbq2026.
- Free parking lot adjacent.
- Restrooms by the entrance.
- BBQ shared grill — cross-contamination possible. Inform severe-allergy callers we cannot guarantee fully isolated cooking.

ALLERGEN DISCLOSURES:
- Kimchi at JM Korean BBQ contains anchovy + shrimp paste (멸치액젓/새우젓) — flag fish/shellfish allergy.
- Soondae (순대) contains pork blood + glass noodle (some recipes use wheat). Flag pork-avoiding diets.
- Halal/kosher options: Beef A La Carte, Chicken Bulgogi, vegetable Entrees (Soondubu, Dwenjang Jjigae)."""

TEMPORARY_PROMPT = (
    "TODAY: BBQ Combo A is the chef's special. Lunch special (11:30 AM "
    "- 2 PM): Bibimbap + miso soup + 1 banchan refill = $14.95."
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_yaml(name: str) -> dict[str, Any]:
    """Load yaml from templates/kbbq/{name}."""
    return yaml.safe_load((TPL / name).read_text())


def _post(path: str, payload: list[dict] | dict, conflict: str | None = None) -> httpx.Response:
    """POST helper with merge-duplicates if conflict given."""
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
    """GET helper returning .json()."""
    r = httpx.get(f"{REST}/{path}", headers=H_BASE, params=params or {}, timeout=15)
    if r.status_code != 200:
        print(f"  ✗ GET {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


# ── Step 1: stores INSERT ────────────────────────────────────────────────────

def create_store() -> str:
    """Create JM Korean BBQ store row. Returns store_id.
    Idempotent: returns existing id if owner already has a store.
    """
    existing = _get("stores", {"owner_id": f"eq.{KBBQ_OWNER_ID}", "select": "id,name"})
    if existing:
        store_id = existing[0]["id"]
        print(f"[Step 1] stores: existing row found → {store_id} (\"{existing[0]['name']}\")")
        return store_id

    payload = {
        "owner_id":         KBBQ_OWNER_ID,
        "agency_id":        KBBQ_AGENCY_ID,
        "name":             KBBQ_STORE_NAME,
        "industry":         "kbbq",
        "business_type":    "kbbq",
        "phone":            KBBQ_PHONE,
        "address":          KBBQ_ADDRESS,
        "business_hours":   KBBQ_HOURS,
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


# ── Step 2: menu_items INSERT × 79 ───────────────────────────────────────────

def seed_menu_items(store_id: str) -> dict[str, str]:
    """Seed 79 menu items from kbbq/menu.yaml. Returns {item_id_yaml: db_id} map."""
    menu = _load_yaml("menu.yaml")
    items_yaml = menu["items"]

    # Idempotency check: skip if already seeded (real run only)
    if DRY_RUN:
        existing = []
    else:
        existing = _get("menu_items", {"store_id": f"eq.{store_id}", "select": "id,name", "limit": "200"})
    if len(existing) >= len(items_yaml):
        print(f"[Step 2] menu_items: {len(existing)} rows already exist (≥{len(items_yaml)}) — skip")
        # Build map from existing rows by name match (best-effort)
        by_name = {row["name"]: row["id"] for row in existing}
        out: dict[str, str] = {}
        for item in items_yaml:
            db_id = by_name.get(item["en"])
            if db_id:
                out[item["id"]] = db_id
        return out

    # Build payload
    rows = []
    for item in items_yaml:
        rows.append({
            "store_id":      store_id,
            "name":          item["en"],            # Loyverse-friendly English name
            "price":         item["base_price"],
            "category":      item["category"],
            "allergens":     item.get("base_allergens", []),
            "dietary_tags":  item.get("base_dietary", []),
            "is_available":  True,
            "stock_quantity": 100,
            "pos_item_id":   None,    # POS sync will populate; null here per cafe pattern
            "sku":           item["id"],            # use yaml id as SKU for cross-reference
            "description":   item.get("notes_en"),
            "raw":           {"yaml_id": item["id"], "ko": item.get("ko"), "rules": item.get("rules", [])},
        })

    if DRY_RUN:
        print(f"[Step 2] DRY-RUN menu_items INSERT × {len(rows)}")
        print(f"           sample[0]: {json.dumps(rows[0], default=str)[:250]}")
        print(f"           sample[40]: {json.dumps(rows[40], default=str)[:250]}")
        print(f"           categories: {sorted(set(r['category'] for r in rows))}")
        return {item["id"]: f"DRY-RUN-{i}" for i, item in enumerate(items_yaml)}

    r = _post("menu_items", rows)
    inserted = r.json()
    print(f"[Step 2] menu_items INSERT × {len(inserted)}")

    # Build yaml_id → db_id map
    by_sku = {row["sku"]: row["id"] for row in inserted}
    return {item["id"]: by_sku[item["id"]] for item in items_yaml if item["id"] in by_sku}


# ── Step 3: modifier_groups upsert ───────────────────────────────────────────

def seed_modifier_groups(store_id: str) -> dict[str, str]:
    """Upsert 9 selectable modifier_groups. Returns {code: id} map."""
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
            print(f"           {p['code']:22s} req={p['is_required']!s:5s} min={p['min_select']} max={p['max_select']}")
        return {p["code"]: f"DRY-RUN-G-{p['code']}" for p in payload}

    r = _post("modifier_groups", payload, conflict="store_id,code")
    rows = r.json()
    print(f"[Step 3] modifier_groups upserted × {len(rows)}")
    return {row["code"]: row["id"] for row in rows}


# ── Step 4: modifier_options upsert ──────────────────────────────────────────

def seed_modifier_options(group_ids: dict[str, str]) -> int:
    """Upsert all options for selectable groups."""
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
            print(f"           gid={p['group_id'][-8:]} {p['code']:22s} ${p['price_delta']:.2f} default={p['is_default']}")
        print(f"           ...({len(payload) - 6} more)")
        return len(payload)

    r = _post("modifier_options", payload, conflict="group_id,code")
    print(f"[Step 4] modifier_options upserted × {len(r.json())}")
    return len(r.json())


# ── Step 5: menu_item ↔ modifier_groups mapping ──────────────────────────────

def seed_item_modifier_mapping(item_ids: dict[str, str], group_ids: dict[str, str]) -> int:
    """Insert menu_item_modifier_groups mappings from yaml item.modifier_groups[]."""
    menu = _load_yaml("menu.yaml")

    payload = []
    skipped_items: list[str] = []
    skipped_groups: list[str] = []
    for item in menu["items"]:
        item_db_id = item_ids.get(item["id"])
        if not item_db_id:
            skipped_items.append(item["id"])
            continue
        for sort_idx, gcode in enumerate(item.get("modifier_groups", []), start=1):
            if gcode not in SELECTABLE_GROUPS:
                # info_only / hard_rule / auto_rule — system prompt territory
                skipped_groups.append(f"{item['id']}:{gcode}")
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
        print(f"  WARN: {len(skipped_items)} items not yet in DB: {skipped_items[:5]}{'...' if len(skipped_items) > 5 else ''}")
    if skipped_groups:
        print(f"  INFO: {len(skipped_groups)} info/rule group references skipped (handled by system prompt)")

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
    """Rebuild stores.menu_cache to reflect freshly seeded items.
    (system prompt 합성 시 사용되는 메뉴 텍스트 갱신)
    """
    if DRY_RUN:
        # Skip live read; use yaml as preview source
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

    # Group by category, then "Name - $X.XX" lines
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


# ── Step 7: verify counts ────────────────────────────────────────────────────

def verify(store_id: str) -> None:
    """Final integrity counts."""
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
    map_q = "&".join(f"group_id=eq.{gid}" for gid in gids[:1])  # sample
    print()
    print("=" * 60)
    print(f"  VERIFY (store_id={store_id})")
    print("=" * 60)
    print(f"  menu_items            {len(items):4d}  (expected 79)")
    print(f"  modifier_groups       {len(groups):4d}  (expected 9)")
    print(f"  modifier_options      {len(opts):4d}  (expected 30+)")
    print(f"  groups codes:         {sorted(g['code'] for g in groups)}")
    print()
    if len(items) != 79:
        print(f"  ⚠ menu_items count mismatch: {len(items)} != 79")
    if len(groups) != 9:
        print(f"  ⚠ modifier_groups count mismatch: {len(groups)} != 9")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\nJM Korean BBQ — Day 2 seed (DRY_RUN={DRY_RUN})\n")
    store_id  = create_store()
    item_ids  = seed_menu_items(store_id)
    group_ids = seed_modifier_groups(store_id)
    seed_modifier_options(group_ids)
    seed_item_modifier_mapping(item_ids, group_ids)
    update_menu_cache(store_id)
    verify(store_id)
    print(f"\n✓ Done. store_id = {store_id}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
