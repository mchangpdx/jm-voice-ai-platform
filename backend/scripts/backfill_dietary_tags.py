"""Backfill `menu_items.dietary_tags` for stores whose wizard finalize
emitted empty arrays (Phase 2 carryover before infer_dietary_tags shipped).

Touches **only rows where dietary_tags is NULL or empty** — operator-set
or hand-curated rows (JM Cafe's 46 baseline items from setup_jm_cafe.py)
stay untouched. The inference reads each store's vertical and runs
`infer_dietary_tags(name, description, allergens, vertical)` per row.
(JM Cafe baseline 보호 — 빈 배열만 채움, 사람 설정 dietary는 건드리지 않음)

Run from backend/ directory:
    # Default: dry-run, prints planned UPDATEs without writing.
    .venv/bin/python scripts/backfill_dietary_tags.py

    # Commit the changes:
    .venv/bin/python scripts/backfill_dietary_tags.py --apply

    # Scope to a single store:
    .venv/bin/python scripts/backfill_dietary_tags.py --store-id <uuid>
    .venv/bin/python scripts/backfill_dietary_tags.py --apply --store-id <uuid>
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Any

import httpx

from app.core.config import settings
from app.services.onboarding.ai_helper import infer_dietary_tags


REST = f"{settings.supabase_url}/rest/v1"
H_BASE = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}


def _get(path: str, params: dict | None = None) -> list[dict]:
    r = httpx.get(f"{REST}/{path}", headers=H_BASE, params=params or {}, timeout=20)
    if r.status_code != 200:
        print(f"  ✗ GET {path} failed: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    return r.json()


def _patch(path: str, params: dict, body: dict) -> bool:
    headers = {**H_BASE, "Prefer": "return=minimal"}
    r = httpx.patch(
        f"{REST}/{path}", headers=headers, params=params, json=body, timeout=20,
    )
    if r.status_code not in (200, 204):
        print(f"  ✗ PATCH {path} failed: {r.status_code} {r.text[:300]}")
        return False
    return True


def _empty(tags: Any) -> bool:
    """True when dietary_tags is NULL, [], or only whitespace strings."""
    if tags is None:
        return True
    if not isinstance(tags, list):
        return False
    return len([t for t in tags if isinstance(t, str) and t.strip()]) == 0


def _resolve_vertical(store: dict[str, Any]) -> str:
    """Pick the vertical from store columns; fall back to 'general'.

    The schema carries `industry` (canonical, e.g. 'pizza', 'cafe',
    'mexican') and `business_type` (legacy, often identical). The
    inference's yaml lookup is by vertical slug; unknown verticals
    silently produce an empty rules dict so the call becomes a no-op.
    (industry 우선, business_type 폴백, 모르면 general no-op)
    """
    for key in ("industry", "business_type"):
        v = store.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return "general"


def backfill(apply: bool, store_id_filter: str | None) -> None:
    label = "APPLY" if apply else "DRY-RUN"
    print(f"== Backfill dietary_tags ({label}) ==")

    params: dict[str, str] = {"select": "id,name,industry,business_type"}
    if store_id_filter:
        params["id"] = f"eq.{store_id_filter}"
    stores = _get("stores", params)
    print(f"Stores in scope: {len(stores)}")

    total_rows_seen = 0
    total_eligible = 0
    total_filled = 0
    total_unchanged = 0
    tag_histogram: Counter[str] = Counter()

    for s in stores:
        store_id = s["id"]
        vertical = _resolve_vertical(s)
        items = _get(
            "menu_items",
            {
                "select": "id,name,description,allergens,dietary_tags",
                "store_id": f"eq.{store_id}",
            },
        )
        total_rows_seen += len(items)
        eligible = [it for it in items if _empty(it.get("dietary_tags"))]
        if not eligible:
            print(f"  - {s['name']} ({vertical}): {len(items)} items, none empty — skip")
            continue
        total_eligible += len(eligible)
        print(f"  • {s['name']} ({vertical}): {len(eligible)}/{len(items)} need backfill")

        for it in eligible:
            tags = infer_dietary_tags(
                name        = it.get("name") or "",
                description = it.get("description"),
                allergens   = it.get("allergens") or [],
                vertical    = vertical,
            )
            if not tags:
                total_unchanged += 1
                continue
            tag_histogram.update(tags)
            total_filled += 1
            preview = ",".join(tags)
            print(f"    {it['id'][:8]}.. {it.get('name','?')[:34]:<34} → [{preview}]")
            if apply:
                _patch(
                    "menu_items",
                    {"id": f"eq.{it['id']}"},
                    {"dietary_tags": tags},
                )

    print()
    print(f"Summary:")
    print(f"  rows scanned     : {total_rows_seen}")
    print(f"  eligible (empty) : {total_eligible}")
    print(f"  would set tags   : {total_filled}")
    print(f"  no inference     : {total_unchanged}")
    if tag_histogram:
        print(f"  tag distribution : {dict(tag_histogram.most_common())}")
    if not apply:
        print()
        print("Dry-run only — re-run with --apply to commit.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Commit changes (default: dry-run)")
    parser.add_argument("--store-id", default=None,
                        help="Scope to a single store UUID")
    args = parser.parse_args()
    backfill(apply=args.apply, store_id_filter=args.store_id)


if __name__ == "__main__":
    main()
