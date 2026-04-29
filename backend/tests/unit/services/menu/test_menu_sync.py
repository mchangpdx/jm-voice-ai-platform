# Phase 2-B.1.7 — Menu Sync Service TDD
# (Phase 2-B.1.7 — 메뉴 동기화 서비스 TDD)
#
# sync_menu_from_pos(store_id):
#   1. Resolve adapter via factory (uses stores.pos_provider)
#   2. Capability gate: SUPPORTS_MENU_SYNC must be True
#   3. Fetch normalized menu via adapter.fetch_menu()
#   4. Flatten items × variants → menu_items rows
#   5. Upsert to Supabase (on_conflict store_id+variant_id)
#   6. Build menu_cache string (deduped, lowest variant price per item)
#   7. PATCH stores.menu_cache
#
# Inventory webhook handler:
#   POST /api/webhooks/loyverse/inventory_levels → update menu_items.stock_quantity

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── sync_menu_from_pos ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_menu_calls_adapter_fetch_menu():
    from app.services.menu.sync import sync_menu_from_pos

    fake_adapter = MagicMock()
    fake_adapter.SUPPORTS_MENU_SYNC = True
    fake_adapter.fetch_menu = AsyncMock(return_value=[
        {
            "pos_item_id": "item-1", "name": "Latte",
            "category_id": "cat-1", "color": "BLUE", "description": None,
            "variants": [
                {"variant_id": "v-1", "sku": "LAT-S",
                 "option_value": "Small", "price": 4.50, "stock_quantity": 100},
                {"variant_id": "v-2", "sku": "LAT-L",
                 "option_value": "Large", "price": 5.50, "stock_quantity": 80},
            ],
        }
    ])

    fake_supa_resp = AsyncMock(); fake_supa_resp.status_code = 201
    fake_supa_resp.json = lambda: []

    with patch("app.services.menu.sync.get_pos_adapter_for_store",
               new=AsyncMock(return_value=fake_adapter)), \
         patch("app.services.menu.sync.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post  = AsyncMock(return_value=fake_supa_resp)
        instance.patch = AsyncMock(return_value=fake_supa_resp)

        result = await sync_menu_from_pos("STORE-UUID")

    assert result["success"] is True
    assert result["synced"] == 2          # two variants flattened to two rows
    assert result["item_count"] == 1
    fake_adapter.fetch_menu.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_menu_skips_when_capability_not_supported():
    """Adapter without SUPPORTS_MENU_SYNC returns capability error rather than crash.
    (capability flag 미지원 어댑터는 우아하게 거절)
    """
    from app.services.menu.sync import sync_menu_from_pos

    fake_adapter = MagicMock()
    fake_adapter.SUPPORTS_MENU_SYNC = False

    with patch("app.services.menu.sync.get_pos_adapter_for_store",
               new=AsyncMock(return_value=(fake_adapter, "S"))):
        result = await sync_menu_from_pos("S")

    assert result["success"] is False
    assert "menu_sync" in result["error"].lower()


@pytest.mark.asyncio
async def test_sync_menu_upserts_rows_with_required_fields():
    from app.services.menu.sync import sync_menu_from_pos

    fake_adapter = MagicMock()
    fake_adapter.SUPPORTS_MENU_SYNC = True
    fake_adapter.fetch_menu = AsyncMock(return_value=[
        {"pos_item_id": "i", "name": "Bagel", "category_id": None,
         "color": None, "description": None,
         "variants": [{"variant_id": "vb", "sku": "B-1",
                       "option_value": None, "price": 3.25, "stock_quantity": 12}]}
    ])

    fake_resp = AsyncMock(); fake_resp.status_code = 201
    fake_resp.json = lambda: []
    captured: dict = {}

    async def fake_post(url, **kw):
        captured["post_url"]  = url
        captured["post_body"] = kw.get("json")
        captured["headers"]   = kw.get("headers")
        return fake_resp

    async def fake_patch(url, **kw):
        captured["patch_url"]  = url
        captured["patch_body"] = kw.get("json")
        return fake_resp

    with patch("app.services.menu.sync.get_pos_adapter_for_store",
               new=AsyncMock(return_value=fake_adapter)), \
         patch("app.services.menu.sync.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post  = AsyncMock(side_effect=fake_post)
        instance.patch = AsyncMock(side_effect=fake_patch)

        await sync_menu_from_pos("STORE-UUID")

    # Upsert hits /rest/v1/menu_items with on_conflict
    assert "/menu_items" in captured["post_url"]
    assert "on_conflict" in captured["post_url"]
    rows = captured["post_body"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["store_id"]       == "STORE-UUID"
    assert row["pos_item_id"]    == "i"
    assert row["variant_id"]     == "vb"
    assert row["name"]           == "Bagel"
    assert row["price"]          == 3.25
    assert row["stock_quantity"] == 12

    # Prefer header for upsert (resolution=merge-duplicates)
    assert "merge-duplicates" in captured["headers"].get("Prefer", "")


@pytest.mark.asyncio
async def test_sync_menu_writes_menu_cache_with_lowest_variant_price():
    """menu_cache string lists each item once at its lowest variant price.
    (메뉴 캐시는 항목당 한 줄, 최저 변형 가격 사용)
    """
    from app.services.menu.sync import sync_menu_from_pos

    fake_adapter = MagicMock()
    fake_adapter.SUPPORTS_MENU_SYNC = True
    fake_adapter.fetch_menu = AsyncMock(return_value=[
        {"pos_item_id": "i1", "name": "Latte", "category_id": None,
         "color": None, "description": None,
         "variants": [
             {"variant_id": "v1", "sku": None, "option_value": "Small",
              "price": 4.50, "stock_quantity": 10},
             {"variant_id": "v2", "sku": None, "option_value": "Large",
              "price": 5.50, "stock_quantity": 8},
         ]},
        {"pos_item_id": "i2", "name": "Bagel", "category_id": None,
         "color": None, "description": None,
         "variants": [{"variant_id": "v3", "sku": None, "option_value": None,
                       "price": 3.25, "stock_quantity": 20}]},
    ])

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: []
    captured: dict = {}

    async def fake_patch(url, **kw):
        captured["patch_url"]  = url
        captured["patch_body"] = kw.get("json")
        return fake_resp

    with patch("app.services.menu.sync.get_pos_adapter_for_store",
               new=AsyncMock(return_value=fake_adapter)), \
         patch("app.services.menu.sync.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post  = AsyncMock(return_value=fake_resp)
        instance.patch = AsyncMock(side_effect=fake_patch)

        await sync_menu_from_pos("S")

    cache: str = captured["patch_body"]["menu_cache"]
    assert "Latte - $4.50" in cache    # lowest variant of Latte
    assert "Latte - $5.50" not in cache
    assert "Bagel - $3.25" in cache
    assert "/stores" in captured["patch_url"]


# ── Inventory webhook ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inventory_webhook_updates_stock_quantity():
    """POST /api/webhooks/loyverse/inventory_levels with payload of variants ⇒
    PATCH menu_items.stock_quantity per variant_id.
    (variant_id별 PATCH 수행)
    """
    from app.services.menu.inventory import apply_inventory_levels

    payload = [
        {"variant_id": "v-1", "in_stock": 25, "store_id": "lyv-store-1"},
        {"variant_id": "v-2", "in_stock":  0, "store_id": "lyv-store-1"},
    ]

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: []
    captured_calls: list[dict] = []

    async def fake_patch(url, **kw):
        captured_calls.append({
            "url":    url,
            "params": kw.get("params"),
            "json":   kw.get("json"),
        })
        return fake_resp

    with patch("app.services.menu.inventory.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.patch = AsyncMock(side_effect=fake_patch)

        result = await apply_inventory_levels(payload)

    assert result["updated"] == 2
    # Two PATCH calls, each scoped by variant_id
    assert len(captured_calls) == 2
    by_variant = {c["params"]["variant_id"]: c["json"] for c in captured_calls}
    assert by_variant["eq.v-1"]["stock_quantity"] == 25
    assert by_variant["eq.v-2"]["stock_quantity"] == 0


@pytest.mark.asyncio
async def test_inventory_webhook_tolerates_empty_payload():
    from app.services.menu.inventory import apply_inventory_levels

    result = await apply_inventory_levels([])
    assert result["updated"] == 0
