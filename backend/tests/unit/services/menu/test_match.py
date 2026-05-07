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


# ── Phase 7-A.C — selected_modifiers integration ─────────────────────────────
# Without modifier serialization the line item that gets booked into Loyverse
# carries only the base price. Live trigger 2026-05-07 call CA61eaa299b...
# created order $5.50 for what was actually a 20oz iced almond milk café latte
# ($5.50 + size $1.00 + almond $0.75 = $7.25). These tests pin the contract
# that resolve_items_against_menu enriches each line with effective_price
# (base + price_delta sum) and preserves the selected_modifiers payload.

def _multi_resp(*bodies):
    """httpx mock that returns each json body in order across successive GETs."""
    aiter = iter(bodies)
    async def _next_get(*a, **k):
        body = next(aiter)
        r = AsyncMock()
        r.status_code = 200
        r.json = lambda: body
        return r
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    client.get = _next_get
    return client


def _menu_rows():
    return [
        {"name": "Cafe Latte", "variant_id": "v-cl", "pos_item_id": "i-cl",
         "price": 5.50, "stock_quantity": 100},
    ]


def _modifier_groups():
    return [
        {"id": "g-size", "code": "size"},
        {"id": "g-milk", "code": "milk"},
    ]


def _modifier_options():
    return [
        {"id": "o-12", "group_id": "g-size", "code": "small",   "price_delta": 0.0},
        {"id": "o-16", "group_id": "g-size", "code": "medium",  "price_delta": 0.50},
        {"id": "o-20", "group_id": "g-size", "code": "large",   "price_delta": 1.00},
        {"id": "o-whole",  "group_id": "g-milk", "code": "whole",  "price_delta": 0.0},
        {"id": "o-oat",    "group_id": "g-milk", "code": "oat",    "price_delta": 0.75},
        {"id": "o-almond", "group_id": "g-milk", "code": "almond", "price_delta": 0.75},
    ]


@pytest.mark.asyncio
async def test_resolve_items_enriches_with_effective_price_for_modifiers():
    """20oz almond Cafe Latte → base 5.50 + size large 1.00 + milk almond 0.75 = 7.25."""
    from app.services.menu.match import resolve_items_against_menu

    client = _multi_resp(_menu_rows(), _modifier_groups(), _modifier_options())
    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{
                "name": "Cafe Latte",
                "quantity": 1,
                "selected_modifiers": [
                    {"group": "size", "option": "large"},
                    {"group": "milk", "option": "almond"},
                ],
            }],
        )

    assert len(resolved) == 1
    line = resolved[0]
    assert line["price"]           == 5.50  # base preserved for downstream
    assert line["effective_price"] == 7.25  # base + size 1.00 + almond 0.75
    assert line["selected_modifiers"] == [
        {"group": "size", "option": "large"},
        {"group": "milk", "option": "almond"},
    ]


@pytest.mark.asyncio
async def test_resolve_items_no_modifiers_falls_back_to_base_price():
    """Empty selected_modifiers (legacy path) — effective_price equals base.
    No second/third REST call must be made (perf + backward compat)."""
    from app.services.menu.match import resolve_items_against_menu

    client = _multi_resp(_menu_rows())  # ONLY menu_items rows, no modifier calls
    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{"name": "Cafe Latte", "quantity": 2}],
        )
    line = resolved[0]
    assert line["effective_price"] == 5.50
    assert line.get("selected_modifiers") in ([], None)


@pytest.mark.asyncio
async def test_resolve_items_unknown_modifier_skipped_no_crash():
    """LLM hallucinates {milk: rice} — line falls back to base + warning, never raises."""
    from app.services.menu.match import resolve_items_against_menu

    client = _multi_resp(_menu_rows(), _modifier_groups(), _modifier_options())
    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{
                "name": "Cafe Latte",
                "quantity": 1,
                "selected_modifiers": [
                    {"group": "milk", "option": "rice"},     # not in catalog
                    {"group": "milk", "option": "oat"},      # valid
                ],
            }],
        )
    # rice silently dropped, oat applied
    assert resolved[0]["effective_price"] == 6.25  # 5.50 + 0.75 oat


@pytest.mark.asyncio
async def test_resolve_items_modifier_load_failure_falls_back_to_base():
    """A 500 from /modifier_groups must not block the order — base price wins."""
    from app.services.menu.match import resolve_items_against_menu

    g_resp = AsyncMock(); g_resp.status_code = 200
    g_resp.json = lambda: _menu_rows()
    bad = AsyncMock(); bad.status_code = 500
    bad.json = lambda: {"error": "db down"}

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=[g_resp, bad])

    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{
                "name": "Cafe Latte",
                "quantity": 1,
                "selected_modifiers": [{"group": "size", "option": "large"}],
            }],
        )
    # Modifier index unavailable → effective == base
    assert resolved[0]["effective_price"] == 5.50
