"""
JM Pizza menu_cache rebuilder with category headers + variant prices.
(2026-05-12 — Q1 Fix 1+2+3 — LLM이 메뉴 구조 + size 가격 정확히 인식하게 개선)

Why a separate script (not edit sync.py):
  sync.py affects every vertical (cafe/kbbq/...). Pizza-specific formatting
  would risk regressions on already-validated stores. This rebuilder runs only
  for JM Pizza and writes back the same `stores.menu_cache` column — next
  voice agent prompt build reads it natively.

Output format (vs flat list):
  [SIGNATURE PIES]
  Big Joe (14 inch (Small)) - $26.00
  Big Joe (18 inch (Large)) - $34.00
  Meat Lover (14 inch (Small)) - $28.00
  ...

  [CLASSIC PIES]
  ...

Also fixes Q1 Fix 3 — modifier_groups.display_name uses the precise yaml
labels ("Pizza Size", "Crust Type") instead of `code.title()` defaults.

Run:
    .venv/bin/python scripts/rebuild_pizza_menu_cache.py
    .venv/bin/python scripts/rebuild_pizza_menu_cache.py --dry-run
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings

REST = f"{settings.supabase_url}/rest/v1"
H = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}

LOYVERSE_API = "https://api.loyverse.com/v1.0"
LOYVERSE_TOKEN = "819393dd06824b90ad41fd5adabb2a86"
LH = {"Authorization": f"Bearer {LOYVERSE_TOKEN}"}

STORE_ID = "7411aaee-8b50-49b0-bc7b-56627932b99a"
TPL = Path(__file__).resolve().parent.parent / "app" / "templates" / "pizza"

# Loyverse category UUIDs are unstable across creates — fetch live
# (Loyverse 카테고리 UUID는 새로 생성될 때마다 바뀌므로 실시간 조회)

# Display order — match the LLM-friendly flow (signature → drinks)
CATEGORY_DISPLAY_ORDER = [
    "Signature Pies",
    "Classic Pies",
    "Slices",
    "Salads",
    "Sides",
    "Desserts",
    "Drinks",
]

DRY_RUN = "--dry-run" in sys.argv


def _get(path: str, params: dict | None = None) -> list[dict] | dict:
    r = httpx.get(f"{REST}/{path}", headers=H, params=params or {}, timeout=15)
    if r.status_code != 200:
        print(f"  ✗ GET {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


def _patch(path: str, params: dict, body: dict) -> bool:
    if DRY_RUN:
        return True
    r = httpx.patch(f"{REST}/{path}", headers=H, params=params, json=body, timeout=15)
    if r.status_code not in (200, 204):
        print(f"  ✗ PATCH {path} failed: {r.status_code} {r.text[:300]}")
        return False
    return True


def fix_modifier_display_names() -> int:
    """Q1 Fix 3 — replace auto-generated display_name with yaml labels.
    (modifier_groups.display_name을 yaml의 정확한 라벨로 교체)
    """
    print("\n[Fix 3] modifier_groups.display_name")
    mg_yaml = yaml.safe_load((TPL / "modifier_groups.yaml").read_text())

    # The yaml `groups` keys are codes (e.g. 'size'); the human label is the
    # 'name' field if set, otherwise we hand-map to a known display name.
    # yaml에는 name 필드가 없으니 hand-map.
    yaml_display_map = {
        "size":         "Pizza Size",
        "crust":        "Crust Type",
        "sauce":        "Sauce",
        "cheese":       "Cheese",
        "topping_meat": "Meat Topping",
        "topping_veg":  "Veggie Topping",
        "wing_sauce":   "Wing Sauce",
        "dressing":     "Salad Dressing",
    }

    groups = _get("modifier_groups", {"store_id": f"eq.{STORE_ID}",
                                      "select": "id,code,display_name"})
    updated = 0
    for g in groups:
        code = g["code"]
        new_display = yaml_display_map.get(code)
        if not new_display:
            continue
        if g["display_name"] == new_display:
            print(f"    · {code:14s} already '{new_display}'")
            continue
        print(f"    + {code:14s} '{g['display_name']}' → '{new_display}'")
        ok = _patch("modifier_groups", {"id": f"eq.{g['id']}"},
                    {"display_name": new_display})
        if ok:
            updated += 1
    print(f"  → {updated} updated")
    return updated


def rebuild_menu_cache() -> int:
    """Q1 Fix 1+2 — group by category, each variant on its own line.
    Bug #4 fix (2026-05-12): portion info (yaml.serving) inlined per line
    so callers asking 'how many wings?' still get an answer even though
    the item name no longer carries the count.
    (카테고리 헤더 + variant별 가격 표시 + portion 정보 inline)
    """
    print("\n[Fix 1+2] stores.menu_cache rebuild")
    # 1. Load yaml to access `serving` info (e.g. '6 pieces', '12oz can')
    menu_yaml = yaml.safe_load((TPL / "menu.yaml").read_text())
    serving_by_name = {}   # canonical name → serving info
    for it in menu_yaml["items"]:
        srv = it.get("serving")
        if srv:
            serving_by_name[it["en"]] = srv

    # 2. Fetch all menu_items
    items = _get("menu_items", {
        "store_id":     f"eq.{STORE_ID}",
        "is_available": "eq.true",
        "select":       "name,price,category_id,option_value,sku",
        "order":        "name.asc",
        "limit":        "200",
    })

    # 2. Resolve category_id → name from Loyverse
    loy_cats = httpx.get(f"{LOYVERSE_API}/categories", headers=LH).json().get("categories", [])
    cat_name_by_id = {c["id"]: c["name"] for c in loy_cats}

    # 3. Group items by category name
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        cname = cat_name_by_id.get(it.get("category_id"), "Uncategorized")
        by_cat.setdefault(cname, []).append(it)

    # 4. Emit in CATEGORY_DISPLAY_ORDER
    lines: list[str] = []
    seen_cats: set[str] = set()
    for cname in CATEGORY_DISPLAY_ORDER + sorted(by_cat.keys()):
        if cname in seen_cats or cname not in by_cat:
            continue
        seen_cats.add(cname)
        lines.append(f"\n[{cname.upper()}]")
        # Sort items within category: by name, then by price ascending
        rows = sorted(by_cat[cname], key=lambda r: (r["name"], r["price"]))
        for r in rows:
            label = r["name"]
            ov = (r.get("option_value") or "").strip()
            if ov:
                label = f"{label} ({ov})"
            price_line = f"{label} - ${float(r['price']):.2f}"
            # Inline serving info so LLM can answer portion questions
            # without losing the simpler name for matching.
            # (portion 정보 inline — matching key는 단순, 사용자 안내는 풍부)
            srv = serving_by_name.get(r["name"])
            if srv:
                price_line += f" — {srv}"
            lines.append(price_line)

    cache = "\n".join(lines).strip()

    print(f"  preview (first 600 chars):")
    print("  " + cache[:600].replace("\n", "\n  "))
    print(f"  ...total {len(cache)} chars, {len(items)} variants, {len(seen_cats)} categories")

    ok = _patch("stores", {"id": f"eq.{STORE_ID}"}, {"menu_cache": cache})
    if ok and not DRY_RUN:
        print(f"  ✓ stores.menu_cache updated")
    return len(cache)


def main() -> int:
    print(f"\nJM Pizza menu rebuilder (DRY_RUN={DRY_RUN})")
    print(f"  store_id: {STORE_ID}")

    fix_modifier_display_names()
    rebuild_menu_cache()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
