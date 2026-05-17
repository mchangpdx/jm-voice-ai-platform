"""Seed templates/beauty/ menu + modifier_groups into JM Beauty Salon DB row.
(JM Beauty Salon에 beauty 템플릿 menu_items + modifier_groups 자동 seed)

Phase 5 live activation (2026-05-18) — the store row was activated via PATCH
but its menu_items table was empty, so service_lookup returned
service_not_found and the bot fell back to transfer_to_manager. This script
reuses db_seeder helpers (the same code paths wizard finalize uses) so the
seed is identical to what auto-onboarding would produce.

Idempotent against UNIQUE store_id+sku constraint via the seeder's existing
_post helper. Run once after the manual PATCH; subsequent runs are no-ops.

Usage:
    cd backend && .venv/bin/python -m scripts.seed_beauty_store
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import yaml

from app.services.onboarding.db_seeder import (
    rebuild_menu_cache,
    seed_menu_items,
    seed_modifier_groups,
    seed_modifier_options,
    wire_items_to_modifier_groups,
)


_STORE_ID  = "34f44792-b200-450e-aeed-cbaaa1c7ff6e"
_TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates" / "beauty"


async def main() -> None:
    menu_yaml = yaml.safe_load((_TEMPLATES / "menu.yaml").read_text())
    mods_yaml = yaml.safe_load((_TEMPLATES / "modifier_groups.yaml").read_text())

    items  = menu_yaml.get("items") or []
    groups = (mods_yaml or {}).get("groups") or {}

    print(f"Loaded menu.yaml: {len(items)} items")
    print(f"Loaded modifier_groups.yaml: {len(groups)} groups")
    print(f"Target store_id: {_STORE_ID}")
    print()

    async with httpx.AsyncClient(timeout=30) as client:
        print("=== seed_menu_items ===")
        item_ids = await seed_menu_items(client, _STORE_ID, items)
        print(f"  inserted {len(item_ids)} menu_items")

        print("=== seed_modifier_groups ===")
        group_ids = await seed_modifier_groups(client, _STORE_ID, groups)
        print(f"  inserted/upserted {len(group_ids)} modifier_groups")

        print("=== seed_modifier_options ===")
        opt_count = await seed_modifier_options(client, group_ids, groups)
        print(f"  inserted {opt_count} modifier_options")

        print("=== wire_items_to_modifier_groups ===")
        wire_count = await wire_items_to_modifier_groups(
            client, item_ids, group_ids, items, groups,
        )
        print(f"  wired {wire_count} item↔group links")

        print("=== rebuild_menu_cache ===")
        cache = await rebuild_menu_cache(client, _STORE_ID)
        print(f"  menu_cache = {len(cache)} chars")

    print()
    print("✅ JM Beauty Salon seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
