"""
JM Pizza handoff — 2-phase placeholder cleanup + Loyverse sync handshake.
(2026-05-12 — JM Pizza 라이브 전환 자동화)

Why two phases:
  - Phase A (pre): runs BEFORE the operator uploads CSV to Loyverse.
    Freezes the store + deletes our DB's placeholder menu_items so that
    when Loyverse webhook later fires, the upsert keys (store_id, variant_id)
    won't collide with stale rows. (이중 entry 방지 — Q2 분석 참조)
  - Phase B (post): runs AFTER the operator finishes Loyverse Back Office
    setup (categories + modifier groups + CSV import). Triggers a one-time
    manual sync to pull the real Loyverse UUIDs into menu_items, then
    re-builds the menu_item_modifier_groups mappings using SKU as the
    bridge between yaml.id ↔ menu_items.sku. Unfreezes at the end.

Why we keep modifier_groups + modifier_options across the handoff:
  Loyverse's own modifier groups (created in Back Office) are a SEPARATE
  entity from our DB's modifier_groups (used by the voice agent for prompt
  building + allergen math). The two never need to be merged — only the
  menu_items ↔ modifier_groups mapping needs rebuilding after Loyverse
  hands us fresh UUIDs.
  (Loyverse 자체 modifier 시스템과 우리 voice agent용 modifier 시스템은 분리)

Run from backend/ directory:
    # Phase A — before uploading CSV to Loyverse
    .venv/bin/python scripts/cleanup_pizza_placeholders.py pre

    # Phase B — after Loyverse Back Office setup is done
    .venv/bin/python scripts/cleanup_pizza_placeholders.py post

    # Dry-run any phase
    .venv/bin/python scripts/cleanup_pizza_placeholders.py pre  --dry-run
    .venv/bin/python scripts/cleanup_pizza_placeholders.py post --dry-run
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings
from app.services.sync.freeze import (
    freeze_store,
    is_frozen,
    status as freeze_status,
    unfreeze_store,
)

REST = f"{settings.supabase_url}/rest/v1"
H_BASE = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}

JM_PIZZA_STORE_ID = "7411aaee-8b50-49b0-bc7b-56627932b99a"
TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "pizza"

# Freeze duration that covers expected manual Loyverse setup window.
FREEZE_PRE_MIN = 240   # 4 hours — generous for Back Office setup + import
DRY_RUN = "--dry-run" in sys.argv


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> list[dict]:
    r = httpx.get(f"{REST}/{path}", headers=H_BASE, params=params or {}, timeout=15)
    if r.status_code != 200:
        print(f"  ✗ GET {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


def _delete(path: str, params: dict) -> int:
    if DRY_RUN:
        return 0
    headers = {**H_BASE, "Prefer": "return=representation"}
    r = httpx.delete(f"{REST}/{path}", headers=headers, params=params, timeout=30)
    if r.status_code not in (200, 204):
        print(f"  ✗ DELETE {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    try:
        return len(r.json())
    except Exception:
        return 0


def _post(path: str, payload: list[dict], conflict: str | None = None) -> int:
    if DRY_RUN:
        return len(payload)
    headers = {**H_BASE, "Prefer": "return=representation"}
    if conflict:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    params = {"on_conflict": conflict} if conflict else None
    r = httpx.post(f"{REST}/{path}", headers=headers, json=payload, params=params, timeout=30)
    if r.status_code not in (200, 201):
        print(f"  ✗ POST {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return len(r.json())


def _placeholder_items() -> list[dict]:
    """Return menu_items rows that were seeded by setup_jm_pizza.py with
    `raw.placeholder_ids = true`. These are the rows to remove.
    (setup_jm_pizza.py가 심은 placeholder UUID rows)
    """
    rows = _get("menu_items", {
        "store_id": f"eq.{JM_PIZZA_STORE_ID}",
        "select":   "id,sku,name,raw",
        "limit":    "200",
    })
    return [r for r in rows if (r.get("raw") or {}).get("placeholder_ids") is True]


def _mapping_count(item_ids: list[str]) -> int:
    if not item_ids:
        return 0
    # PostgREST in.() chunks ≤ ~50 ids per request — safe for 24 items here
    rows = _get("menu_item_modifier_groups", {
        "menu_item_id": f"in.({','.join(item_ids)})",
        "select":       "menu_item_id,group_id",
    })
    return len(rows)


# ── Phase A — pre-upload cleanup ─────────────────────────────────────────────

def phase_pre() -> int:
    print(f"\n=== Phase A — PRE-upload cleanup (DRY_RUN={DRY_RUN}) ===\n")

    items = _placeholder_items()
    item_ids = [r["id"] for r in items]
    map_count = _mapping_count(item_ids)

    print(f"  Found {len(items)} placeholder menu_items "
          f"(raw.placeholder_ids = true)")
    print(f"  Linked menu_item_modifier_groups rows: {map_count}")
    print(f"  Sample SKUs: {[r.get('sku') for r in items[:5]]}")
    print()

    if not items:
        print("  ✓ Nothing to clean — placeholder seed already removed.")
        return 0

    # 1) Freeze the store so Loyverse webhook gets ignored during the window
    if DRY_RUN:
        print(f"  [Step 1] DRY-RUN freeze_store({JM_PIZZA_STORE_ID}, {FREEZE_PRE_MIN}min)")
    else:
        freeze_store(JM_PIZZA_STORE_ID, FREEZE_PRE_MIN)
        print(f"  [Step 1] freeze_store({JM_PIZZA_STORE_ID}, {FREEZE_PRE_MIN}min)  ✓")
        print(f"           current freeze status: {freeze_status()}")

    # 2) DELETE menu_item_modifier_groups (must be first — FK reference)
    if item_ids:
        n = _delete("menu_item_modifier_groups", {
            "menu_item_id": f"in.({','.join(item_ids)})",
        })
        print(f"  [Step 2] DELETE menu_item_modifier_groups × {n if not DRY_RUN else map_count}  ✓")

    # 3) DELETE menu_items where placeholder_ids = true
    n = _delete("menu_items", {
        "store_id":  f"eq.{JM_PIZZA_STORE_ID}",
        "raw->>placeholder_ids": "eq.true",
    })
    print(f"  [Step 3] DELETE menu_items × {n if not DRY_RUN else len(items)}  ✓")

    print()
    print("=" * 70)
    print("  NEXT — Loyverse Back Office (사용자 작업):")
    print("    1. Create 7 categories (Items → Categories)")
    print("    2. Create 8 modifier groups + 37 options (Items → Modifiers)")
    print("    3. Import CSV: Items → ⋯ → Import Items")
    print(f"        File: ~/Downloads/jm_pizza_loyverse_import_2026-05-11.csv")
    print()
    print("  WHEN DONE — run:")
    print("    .venv/bin/python scripts/cleanup_pizza_placeholders.py post")
    print("=" * 70)
    return 0


# ── Phase B — post-upload sync + remap ───────────────────────────────────────

async def _trigger_manual_sync() -> dict:
    from app.services.menu.sync import sync_menu_from_pos
    return await sync_menu_from_pos(JM_PIZZA_STORE_ID)


def _rebuild_mappings_from_yaml() -> dict:
    """Rebuild menu_item_modifier_groups using yaml.id ↔ menu_items.sku as
    the bridge. Loyverse CSV import preserves SKU verbatim, so SKUs like
    'big_joe', 'big_joe_14inch' survive and we can re-map.
    (Loyverse CSV import는 SKU를 보존하므로 SKU로 우리 yaml과 매칭)
    """
    menu = yaml.safe_load((TPL / "menu.yaml").read_text())

    # Current live menu_items (post-sync, real Loyverse UUIDs)
    live_items = _get("menu_items", {
        "store_id": f"eq.{JM_PIZZA_STORE_ID}",
        "select":   "id,sku,name",
        "limit":    "200",
    })
    # SKU base prefix → first matching row id (variants share base prefix)
    # "big_joe_14inch" / "big_joe_18inch" both map back to yaml.id "big_joe"
    by_sku = {row["sku"]: row["id"] for row in live_items}
    # Group variant SKUs under base id for mapping convenience
    base_to_first_item: dict[str, str] = {}
    for sku, item_id in by_sku.items():
        # Strip Loyverse-export size suffixes we wrote in export_pizza_loyverse_csv.py
        base = sku.split("_14inch")[0].split("_18inch")[0]
        # Keep the first variant we encounter for each base (mapping at item level)
        base_to_first_item.setdefault(base, item_id)

    # Modifier groups by code (already in DB from setup_jm_pizza.py)
    groups = _get("modifier_groups", {
        "store_id": f"eq.{JM_PIZZA_STORE_ID}",
        "select":   "id,code",
    })
    group_by_code = {g["code"]: g["id"] for g in groups}

    payload = []
    unmapped: list[str] = []
    for item in menu["items"]:
        yaml_id = item["id"]
        item_db_id = base_to_first_item.get(yaml_id)
        if not item_db_id:
            unmapped.append(yaml_id)
            continue
        for sort_idx, gcode in enumerate(item.get("modifier_groups", []), start=1):
            gid = group_by_code.get(gcode)
            if not gid:
                continue
            payload.append({
                "menu_item_id": item_db_id,
                "group_id":     gid,
                "sort_order":   sort_idx,
            })

    if DRY_RUN:
        return {"would_insert": len(payload), "unmapped": unmapped}

    inserted = _post("menu_item_modifier_groups", payload,
                     conflict="menu_item_id,group_id")
    return {"inserted": inserted, "unmapped": unmapped, "groups_used": len(group_by_code)}


def phase_post() -> int:
    import asyncio
    print(f"\n=== Phase B — POST-upload sync + remap (DRY_RUN={DRY_RUN}) ===\n")

    # 1) Trigger manual sync — Loyverse API GET /items → menu_items upsert
    print(f"  [Step 1] sync_menu_from_pos({JM_PIZZA_STORE_ID})")
    if DRY_RUN:
        print(f"           DRY-RUN skipped")
        sync_result = {"success": True, "synced": 0, "item_count": 0}
    else:
        sync_result = asyncio.run(_trigger_manual_sync())
    print(f"           result: {sync_result}")

    if not sync_result.get("success"):
        print(f"  ✗ Sync failed — aborting. Fix the error then re-run phase post.")
        return 1

    # 2) Verify how many menu_items now exist
    live = _get("menu_items", {
        "store_id": f"eq.{JM_PIZZA_STORE_ID}",
        "select":   "id,sku",
    })
    print(f"  [Step 2] live menu_items count: {len(live)} (expected 24+ after Loyverse import)")

    if len(live) == 0:
        print(f"  ⚠ No menu_items yet — did the Loyverse CSV import complete? Re-check Back Office.")
        return 1

    # 3) Rebuild menu_item_modifier_groups mappings
    remap = _rebuild_mappings_from_yaml()
    print(f"  [Step 3] remap menu_item_modifier_groups: {remap}")

    # 4) Unfreeze the store
    if DRY_RUN:
        print(f"  [Step 4] DRY-RUN unfreeze_store({JM_PIZZA_STORE_ID})")
    else:
        cleared = unfreeze_store(JM_PIZZA_STORE_ID)
        print(f"  [Step 4] unfreeze_store({JM_PIZZA_STORE_ID})  cleared={cleared}")

    print()
    print("=" * 70)
    print("  ✓ JM Pizza handoff complete.")
    print(f"    menu_items:                  {len(live)}")
    print(f"    menu_item_modifier_groups:   {remap.get('inserted') or remap.get('would_insert')}")
    if remap.get("unmapped"):
        print(f"    ⚠ unmapped yaml ids:         {remap['unmapped']}")
        print(f"      (SKU mismatch — verify Loyverse import preserved SKU column)")
    print()
    print("  NEXT — first live call to +1-971-444-7137 to validate voice agent.")
    print("=" * 70)
    return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # Drop --dry-run from argv before subcommand check
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    sub = args[0] if args else ""
    if sub == "pre":
        return phase_pre()
    if sub == "post":
        return phase_post()
    print(__doc__)
    print("Usage: cleanup_pizza_placeholders.py {pre|post} [--dry-run]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
