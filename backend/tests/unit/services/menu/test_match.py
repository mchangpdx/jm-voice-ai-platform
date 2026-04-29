# Phase 2-B.1.8 — Menu match helper TDD
# (Phase 2-B.1.8 — 메뉴 매칭 헬퍼 TDD)
#
# resolve_items_against_menu(store_id, items) takes the items dict from a
# Gemini create_order tool call and returns enriched line items by joining
# against menu_items. Each enriched line carries:
#   variant_id, item_id, name, price (real catalog price), quantity,
#   stock_quantity, missing (bool — True when name didn't match any row)
#
# Decisions baked in (per user direction):
#   * Exact, case-insensitive name match only (no fuzzy)
#   * stock_quantity == 0  ⇒ rejected at the line level (sold_out)
#   * stock_quantity is null ⇒ allowed (item is untracked, treat as unlimited)

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_resolve_items_attaches_variant_and_price_from_catalog():
    """Each requested item gets variant_id/item_id/price filled from menu_items.
    (각 요청 항목이 카탈로그에서 variant_id/item_id/가격을 받음)
    """
    from app.services.menu.match import resolve_items_against_menu

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"name": "Latte", "variant_id": "v-1", "pos_item_id": "item-1",
         "price": 4.50, "stock_quantity": 100},
        {"name": "Bagel", "variant_id": "v-2", "pos_item_id": "item-2",
         "price": 3.25, "stock_quantity": 50},
    ]

    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        resolved = await resolve_items_against_menu(
            store_id="STORE-UUID",
            items=[
                {"name": "Latte", "quantity": 2},
                {"name": "Bagel", "quantity": 1},
            ],
        )

    assert len(resolved) == 2
    latte = next(r for r in resolved if r["name"] == "Latte")
    assert latte["variant_id"]     == "v-1"
    assert latte["item_id"]        == "item-1"
    assert latte["price"]          == 4.50
    assert latte["quantity"]       == 2
    assert latte["stock_quantity"] == 100
    assert latte["missing"]        is False


@pytest.mark.asyncio
async def test_resolve_items_is_case_insensitive():
    """Customer says 'latte' or 'LATTE' or 'Latte' — same match.
    (대소문자 무시 매칭)
    """
    from app.services.menu.match import resolve_items_against_menu

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"name": "Latte", "variant_id": "v-1", "pos_item_id": "i-1",
         "price": 4.50, "stock_quantity": 10},
    ]

    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        resolved = await resolve_items_against_menu(
            store_id="S",
            items=[{"name": "  LATTE  ", "quantity": 1}],
        )

    assert resolved[0]["missing"] is False
    assert resolved[0]["variant_id"] == "v-1"


@pytest.mark.asyncio
async def test_resolve_items_marks_unknown_items_missing():
    """Item name with no menu match ⇒ missing=True (caller decides what to say).
    (메뉴에 없는 항목 ⇒ missing=True)
    """
    from app.services.menu.match import resolve_items_against_menu

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"name": "Latte", "variant_id": "v-1", "pos_item_id": "i-1",
         "price": 4.50, "stock_quantity": 10},
    ]

    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        resolved = await resolve_items_against_menu(
            store_id="S",
            items=[
                {"name": "Latte",       "quantity": 1},
                {"name": "Unobtainium", "quantity": 1},
            ],
        )

    assert next(r for r in resolved if r["name"] == "Latte")["missing"]       is False
    assert next(r for r in resolved if r["name"] == "Unobtainium")["missing"] is True


@pytest.mark.asyncio
async def test_resolve_items_treats_null_stock_as_unlimited():
    """stock_quantity NULL means the item is untracked. Allowed (sufficient_stock=True).
    Only stock_quantity == 0 with explicit tracking is rejected.
    (재고 NULL ⇒ 미추적, 통과; 0이면 거절)
    """
    from app.services.menu.match import resolve_items_against_menu

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"name": "Latte",   "variant_id": "v-1", "pos_item_id": "i-1",
         "price": 4.50, "stock_quantity": None},
        {"name": "SoldOut", "variant_id": "v-2", "pos_item_id": "i-2",
         "price": 5.00, "stock_quantity": 0},
    ]

    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        resolved = await resolve_items_against_menu(
            store_id="S",
            items=[
                {"name": "Latte",   "quantity": 1},
                {"name": "SoldOut", "quantity": 1},
            ],
        )

    latte   = next(r for r in resolved if r["name"] == "Latte")
    soldout = next(r for r in resolved if r["name"] == "SoldOut")
    assert latte["sufficient_stock"]   is True
    assert soldout["sufficient_stock"] is False


@pytest.mark.asyncio
async def test_resolve_items_flags_insufficient_stock_when_qty_exceeds():
    """If requested quantity > stock_quantity (and stock is tracked),
    sufficient_stock=False so flow can refuse.
    (요청량 > 재고 ⇒ sufficient_stock=False)
    """
    from app.services.menu.match import resolve_items_against_menu

    fake_resp = AsyncMock(); fake_resp.status_code = 200
    fake_resp.json = lambda: [
        {"name": "Latte", "variant_id": "v-1", "pos_item_id": "i-1",
         "price": 4.50, "stock_quantity": 1},
    ]

    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        resolved = await resolve_items_against_menu(
            store_id="S",
            items=[{"name": "Latte", "quantity": 5}],   # request 5, have 1
        )

    assert resolved[0]["sufficient_stock"] is False


@pytest.mark.asyncio
async def test_resolve_items_returns_empty_list_for_empty_input():
    from app.services.menu.match import resolve_items_against_menu

    # No HTTP call should happen for an empty items list
    with patch("app.services.menu.match.httpx.AsyncClient") as MockClient:
        result = await resolve_items_against_menu(store_id="S", items=[])
        assert result == []
        MockClient.assert_not_called()
