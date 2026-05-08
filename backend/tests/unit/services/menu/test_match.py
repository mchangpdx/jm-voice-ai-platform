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


# ── Phase 7-A.D Wave A.3 — Pre-loaded modifier_index reuse ────────────────────
# realtime_voice.py already calls fetch_modifier_groups() at session.update to
# build the system-prompt modifier_section. Re-fetching the same data inside
# create_order adds ~400-500ms per order. These tests pin the contract that
# resolve_items_against_menu accepts a pre-built index and skips the second
# round-trip when given one — without changing the price-delta math.

def _single_resp(*bodies):
    """Like _multi_resp but asserts exactly len(bodies) GETs were issued."""
    aiter = iter(bodies)
    call_count = {"n": 0}
    async def _next_get(*a, **k):
        call_count["n"] += 1
        body = next(aiter)
        r = AsyncMock(); r.status_code = 200; r.json = lambda: body
        return r
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=False)
    client.get = _next_get
    return client, call_count


@pytest.mark.asyncio
async def test_build_modifier_index_from_groups_converts_shape():
    """Helper turns fetch_modifier_groups output into {(gcode, ocode): opt} index."""
    from app.services.menu.match import build_modifier_index_from_groups

    groups = [
        {"id": "g-size", "code": "size", "options": [
            {"id": "o-l", "group_id": "g-size", "code": "large",
             "price_delta": 1.00, "display_name": "Large 20oz"},
        ]},
        {"id": "g-milk", "code": "milk", "options": [
            {"id": "o-oat", "group_id": "g-milk", "code": "oat",
             "price_delta": 0.75, "display_name": "Oat milk"},
        ]},
    ]
    idx = build_modifier_index_from_groups(groups)

    assert ("size", "large") in idx
    assert ("milk", "oat")   in idx
    assert idx[("size", "large")]["price_delta"] == 1.00
    assert idx[("milk", "oat")]["display_name"]  == "Oat milk"


@pytest.mark.asyncio
async def test_build_modifier_index_handles_empty_and_missing_codes():
    """Empty groups → empty index. Group/option missing code → skipped (no crash)."""
    from app.services.menu.match import build_modifier_index_from_groups

    assert build_modifier_index_from_groups([]) == {}
    assert build_modifier_index_from_groups(None) == {}  # type: ignore[arg-type]

    bad = [
        {"id": "g-x", "code": "", "options": [{"code": "z", "price_delta": 0}]},
        {"id": "g-y", "code": "milk", "options": [{"code": "", "price_delta": 0}]},
    ]
    idx = build_modifier_index_from_groups(bad)
    assert idx == {}


@pytest.mark.asyncio
async def test_resolve_items_with_preloaded_index_skips_modifier_db_calls():
    """Pre-loaded modifier_index → only menu_items GET fires (1 round-trip vs 3).
    effective_price still computed correctly from the passed-in index.
    (사전 로드된 index → modifier REST 우회, price_delta 계산은 동일)
    """
    from app.services.menu.match import resolve_items_against_menu

    client, calls = _single_resp(_menu_rows())  # ONLY menu_items expected
    pre_index = {
        ("size", "large"):  {"code": "large",  "price_delta": 1.00,
                             "display_name": "Large 20oz"},
        ("milk", "almond"): {"code": "almond", "price_delta": 0.75,
                             "display_name": "Almond milk"},
    }

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
            modifier_index=pre_index,
        )

    assert calls["n"] == 1, f"expected 1 GET (menu_items only), got {calls['n']}"
    line = resolved[0]
    assert line["effective_price"] == 7.25  # 5.50 + 1.00 + 0.75
    assert line["modifier_lines"][0]["label"] == "Large 20oz"


@pytest.mark.asyncio
async def test_resolve_items_falls_back_to_db_load_when_index_none():
    """Backward compat — modifier_index=None preserves Phase 7-A.C behavior."""
    from app.services.menu.match import resolve_items_against_menu

    client, calls = _single_resp(_menu_rows(), _modifier_groups(), _modifier_options())

    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{
                "name": "Cafe Latte",
                "quantity": 1,
                "selected_modifiers": [{"group": "size", "option": "large"}],
            }],
            modifier_index=None,
        )

    assert calls["n"] == 3, "expected menu + groups + options round-trips"
    assert resolved[0]["effective_price"] == 6.50  # 5.50 + 1.00


@pytest.mark.asyncio
async def test_resolve_items_with_empty_preloaded_index_falls_back_to_base():
    """Empty {} index (e.g. store has no modifier system) → effective == base, no DB load.
    (빈 index → base price + 추가 REST 안 함)
    """
    from app.services.menu.match import resolve_items_against_menu

    client, calls = _single_resp(_menu_rows())

    with patch("app.services.menu.match.httpx.AsyncClient", return_value=client):
        resolved = await resolve_items_against_menu(
            store_id="STORE",
            items=[{
                "name": "Cafe Latte",
                "quantity": 1,
                "selected_modifiers": [{"group": "size", "option": "large"}],
            }],
            modifier_index={},
        )

    assert calls["n"] == 1
    assert resolved[0]["effective_price"] == 5.50  # unknown mod silently dropped
