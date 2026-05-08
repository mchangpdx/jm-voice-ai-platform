# CRM Wave 1 — customer_lookup unit tests (Tier 1, 8 cases U1–U8)
# (CRM Wave 1 — customer_lookup 단위 테스트 8건)
#
# Mocks httpx.AsyncClient at the module level (same pattern as
# test_transactions.py). Each test asserts the contract documented in
# docs/superpowers/specs/2026-05-08-crm-wave-1-design.md Section 7.2.

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.crm import CustomerContext, customer_lookup
from app.services.crm.customer_lookup import _items_match, _item_multiset

STORE_ID = "PDX-cafe-01"
PHONE    = "+15035551234"


# ── Test infrastructure ───────────────────────────────────────────────────────

def _mk_response(*, status: int, json_body=None, content_range: str | None = None):
    """Build a fake httpx.Response that mocks raise_for_status + headers."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json = lambda: (json_body if json_body is not None else [])
    resp.headers = {"Content-Range": content_range} if content_range else {}
    resp.text = "" if status < 400 else "error"
    if status >= 400:
        # Build a real HTTPStatusError so the lookup's except branch fires
        request = httpx.Request("GET", "http://test")
        real_resp = httpx.Response(status, request=request)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("err", request=request, response=real_resp)
        )
    else:
        resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _patch_client(get_responses: list):
    """Patch httpx.AsyncClient so .get returns the supplied responses in order.

    Both _fetch_recent and _fetch_visit_count call client.get — and they run
    via asyncio.gather, so order is non-deterministic but each gets one.
    Use side_effect with a list so each call pops one response.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=get_responses)
    return patch("app.services.crm.customer_lookup.httpx.AsyncClient",
                 return_value=client)


# ── U1: first-time caller (zero rows, count=0) ────────────────────────────────

@pytest.mark.asyncio
async def test_u1_first_time_caller_zero_rows():
    recent_resp = _mk_response(status=200, json_body=[])
    count_resp  = _mk_response(status=200, json_body=[], content_range="*/0")

    with _patch_client([recent_resp, count_resp]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is not None
    assert ctx.visit_count == 0
    assert ctx.recent == []
    assert ctx.usual_eligible is False
    assert ctx.name is None
    assert ctx.email is None


# ── U2: returning, 1 paid tx ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_u2_returning_one_paid():
    one_tx = {
        "id": "tx1", "created_at": "2026-05-05T12:00:00+00:00",
        "state": "paid", "total_cents": 650,
        "items_json": [{"item_id": "A", "quantity": 1, "name": "latte"}],
        "customer_name": "Jamie", "customer_email": "jamie@x.com",
    }
    recent_resp = _mk_response(status=200, json_body=[one_tx])
    count_resp  = _mk_response(status=200, json_body=[], content_range="0-0/1")

    with _patch_client([recent_resp, count_resp]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is not None
    assert ctx.visit_count == 1
    assert len(ctx.recent) == 1
    assert ctx.usual_eligible is False  # need >= 2 to be eligible
    assert ctx.name == "Jamie"
    assert ctx.email == "jamie@x.com"


# ── U3: returning 5 paid, last 2 multiset-equal → usual eligible ──────────────

@pytest.mark.asyncio
async def test_u3_returning_five_paid_usual_eligible():
    same_items = [{"item_id": "A", "quantity": 1, "name": "latte"}]
    diff_items = [{"item_id": "B", "quantity": 1, "name": "drip"}]
    rows = [
        {"id": "tx5", "created_at": "2026-05-05", "state": "paid",
         "total_cents": 650, "items_json": same_items,
         "customer_name": "J", "customer_email": "j@x.com"},
        {"id": "tx4", "created_at": "2026-05-02", "state": "paid",
         "total_cents": 650, "items_json": same_items},
        {"id": "tx3", "created_at": "2026-04-28", "state": "paid",
         "total_cents": 400, "items_json": diff_items},
        {"id": "tx2", "created_at": "2026-04-22", "state": "paid",
         "total_cents": 650, "items_json": same_items},
        {"id": "tx1", "created_at": "2026-04-15", "state": "paid",
         "total_cents": 400, "items_json": diff_items},
    ]
    recent_resp = _mk_response(status=200, json_body=rows)
    count_resp  = _mk_response(status=200, json_body=[], content_range="0-0/5")

    with _patch_client([recent_resp, count_resp]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is not None
    assert ctx.visit_count == 5
    assert len(ctx.recent) == 5
    assert ctx.usual_eligible is True
    assert ctx.name == "J"


# ── U4: server returns 5 max even when caller has 7+ visits ───────────────────

@pytest.mark.asyncio
async def test_u4_recent_capped_at_five():
    rows = [
        {"id": f"tx{i}", "created_at": "2026-05-01", "state": "paid",
         "total_cents": 100, "items_json": [{"item_id": "A", "quantity": 1}]}
        for i in range(5)  # server already applied limit=5
    ]
    recent_resp = _mk_response(status=200, json_body=rows)
    count_resp  = _mk_response(status=200, json_body=[], content_range="0-0/7")

    with _patch_client([recent_resp, count_resp]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is not None
    assert ctx.visit_count == 7
    assert len(ctx.recent) == 5  # capped


# ── U5: visit_count includes canceled/no_show; recent excludes them ───────────

@pytest.mark.asyncio
async def test_u5_visit_count_includes_canceled_recent_excludes():
    """Server-side filter does the actual work — _fetch_recent passes only
    paid/settled/fired_unpaid, _fetch_visit_count passes all 5. Test verifies
    the lookup wires the two together (visit_count > len(recent) for canceled).
    """
    paid_rows = [
        {"id": "tx1", "created_at": "2026-05-05", "state": "paid",
         "total_cents": 650,
         "items_json": [{"item_id": "A", "quantity": 1, "name": "latte"}]},
        {"id": "tx2", "created_at": "2026-05-04", "state": "settled",
         "total_cents": 650,
         "items_json": [{"item_id": "A", "quantity": 1, "name": "latte"}]},
        {"id": "tx3", "created_at": "2026-05-03", "state": "fired_unpaid",
         "total_cents": 400,
         "items_json": [{"item_id": "B", "quantity": 1, "name": "drip"}]},
    ]
    recent_resp = _mk_response(status=200, json_body=paid_rows)
    count_resp  = _mk_response(status=200, json_body=[], content_range="0-0/5")
    # 5 includes 3 paid + 2 canceled

    with _patch_client([recent_resp, count_resp]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is not None
    assert ctx.visit_count == 5
    assert len(ctx.recent) == 3
    assert ctx.usual_eligible is True  # last 2 paid (tx1, tx2) match


# ── U6: anonymous caller — multiple invalid phone shapes ──────────────────────

@pytest.mark.parametrize("phone", [
    None, "", "Private", "anonymous", "unknown",
    "+0", "+0000", "1234", "abc", "+1503", "15035551234",  # missing +
])
@pytest.mark.asyncio
async def test_u6_anonymous_caller_all_shapes_skip(phone):
    """No HTTP client should ever be opened for these — short-circuit at top."""
    with patch("app.services.crm.customer_lookup.httpx.AsyncClient") as MockClient:
        ctx = await customer_lookup(STORE_ID, phone)
    assert ctx is None
    MockClient.assert_not_called()


# ── U7: Supabase 5xx → graceful None, never raise ─────────────────────────────

@pytest.mark.asyncio
async def test_u7_supabase_5xx_graceful_none():
    err_resp_a = _mk_response(status=503)
    err_resp_b = _mk_response(status=503)

    with _patch_client([err_resp_a, err_resp_b]):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is None  # graceful — does not raise


# ── U8: timeout (>500ms) → graceful None ──────────────────────────────────────

@pytest.mark.asyncio
async def test_u8_timeout_graceful_none():
    """Simulate a slow response that exceeds the 500ms budget."""
    async def slow_get(*args, **kwargs):
        await asyncio.sleep(2.0)  # well past the 0.5s cancel scope
        return _mk_response(status=200, json_body=[])

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__  = AsyncMock(return_value=None)
    client.get = AsyncMock(side_effect=slow_get)

    with patch("app.services.crm.customer_lookup.httpx.AsyncClient",
               return_value=client):
        ctx = await customer_lookup(STORE_ID, PHONE)

    assert ctx is None


# ── U9 (bonus, 4xx auth path) — exercises the lookup_auth_error branch ────────

@pytest.mark.asyncio
async def test_u9_supabase_4xx_auth_graceful_none():
    err_a = _mk_response(status=401)
    err_b = _mk_response(status=401)
    with _patch_client([err_a, err_b]):
        ctx = await customer_lookup(STORE_ID, PHONE)
    assert ctx is None


# ── _items_match / _item_multiset edge cases ──────────────────────────────────

class TestItemsMatch:
    def test_empty_both_match_but_caller_guards(self):
        assert _items_match({}, {}) is True
        # Caller (customer_lookup) requires non-empty multiset on recent[0]
        # before flipping usual_eligible — covered by U2 (visit_count=1).

    def test_order_invariant(self):
        a = {"items_json": [{"item_id": "A", "quantity": 1},
                            {"item_id": "B", "quantity": 1}]}
        b = {"items_json": [{"item_id": "B", "quantity": 1},
                            {"item_id": "A", "quantity": 1}]}
        assert _items_match(a, b) is True

    def test_quantity_aware_multiset(self):
        # 2x A vs A+A → equal multisets
        a = {"items_json": [{"item_id": "A", "quantity": 2}]}
        b = {"items_json": [{"item_id": "A", "quantity": 1},
                            {"item_id": "A", "quantity": 1}]}
        assert _items_match(a, b) is True

    def test_quantity_aware_mismatch(self):
        # 2x A vs 1x A → different multisets
        a = {"items_json": [{"item_id": "A", "quantity": 2}]}
        b = {"items_json": [{"item_id": "A", "quantity": 1}]}
        assert _items_match(a, b) is False

    def test_modifier_ignored(self):
        # Wave 1: size/modifier NOT compared. Same item_id, different size → match.
        a = {"items_json": [{"item_id": "A", "quantity": 1,
                             "selected_modifiers": [{"group": "size", "option": "L"}]}]}
        b = {"items_json": [{"item_id": "A", "quantity": 1,
                             "selected_modifiers": [{"group": "size", "option": "M"}]}]}
        assert _items_match(a, b) is True

    def test_variant_id_fallback_when_item_id_missing(self):
        a = {"items_json": [{"variant_id": "v1", "quantity": 1}]}
        b = {"items_json": [{"variant_id": "v1", "quantity": 1}]}
        assert _items_match(a, b) is True

    def test_multiset_returns_tuple(self):
        result = _item_multiset([{"item_id": "A", "quantity": 2}])
        assert isinstance(result, tuple)
        assert result == ("A", "A")
