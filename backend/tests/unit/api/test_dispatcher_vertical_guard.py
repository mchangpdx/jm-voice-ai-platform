"""C2 fix (2026-05-18) — dispatcher vertical-aware tool guard.
(C2 fix — cross-vertical tool 호출 차단 회귀 가드)

Live trigger: JM Beauty Salon Call CA218629c6 (cancel flow) fired
`recent_orders` — an ORDER_KIND_TOOLS tool — on a SERVICE_KIND store.
The OpenAI tools list was correct (SERVICE_KIND_TOOLS only) but the LLM
hallucinated the call based on lingering prompt mentions of recent_orders
(5× in the pre-C1 prompt). C1 fixed the prompt; this test anchors C2:
even if a future prompt regression re-introduces the leak, the dispatcher
itself rejects any tool that isn't in the store's vertical surface.

The guard is defense-in-depth — it never replaces the OpenAI-side filter,
only catches leaks if/when one slips through.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# realtime_voice imports openai which isn't installed in the unit-test
# sandbox — stub it the same way test_realtime_tool_dispatch does.
sys.modules.setdefault("openai", MagicMock(AsyncOpenAI=MagicMock))

from app.api.realtime_voice import _dispatch_tool_call


_BEAUTY_STORE = {
    "id":            "beauty-uuid",
    "name":          "Test Beauty Salon",
    "industry":      "beauty",
    "vertical_kind": "service",
    "is_active":     True,
}

_CAFE_STORE = {
    "id":            "cafe-uuid",
    "name":          "Test Cafe",
    "industry":      "cafe",
    "vertical_kind": "order",
    "is_active":     True,
}


def _session(store: dict) -> dict:
    """Minimal session_state — only the store_row key matters for the guard."""
    return {
        "store_row":      store,
        "call_log_id":    "CA-test",
        "last_order_items": [],
        "last_order_total": 0,
    }


# ── Cross-vertical leak — service store + order tool ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_tool", [
    "create_order",        # Call CAdb staff hallucination class
    "modify_order",
    "cancel_order",
    "make_reservation",    # restaurant table reservation
    "modify_reservation",
    "cancel_reservation",
    "recall_order",
    "recent_orders",       # live regression Call CA218629c6
])
async def test_service_store_blocks_order_tools(blocked_tool):
    """Order-vertical tool called on a SERVICE store → BLOCKED with
    `tool_not_available_for_vertical`. The dispatcher never touches the
    tool handler, so no DB write / external call can leak.
    (Beauty/spa 매장에서 order tool 호출 시 차단)"""
    out = await _dispatch_tool_call(
        tool_name         = blocked_tool,
        tool_args         = {},
        store_id          = _BEAUTY_STORE["id"],
        store_name        = _BEAUTY_STORE["name"],
        caller_phone_e164 = "+15035551234",
        session_state     = _session(_BEAUTY_STORE),
    )
    assert out["success"] is False
    assert out["reason"] == "tool_not_available_for_vertical"
    assert out["ai_script_hint"] == "tool_not_available_for_vertical"
    assert blocked_tool in out["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_tool", [
    "book_appointment",
    "modify_appointment",
    "cancel_appointment",
    "service_lookup",
    "list_stylists",
])
async def test_order_store_blocks_service_tools(blocked_tool):
    """SERVICE_KIND tool called on an ORDER store → BLOCKED. Even though
    no live regression exists for this direction (order verticals don't
    have appointment vocabulary in their prompt), the guard MUST be
    symmetric — otherwise the audit story 'tools are vertical-scoped'
    has a one-sided hole.
    (반대 방향도 대칭 차단 — 가드 무결성)"""
    out = await _dispatch_tool_call(
        tool_name         = blocked_tool,
        tool_args         = {},
        store_id          = _CAFE_STORE["id"],
        store_name        = _CAFE_STORE["name"],
        caller_phone_e164 = "+15035551234",
        session_state     = _session(_CAFE_STORE),
    )
    assert out["success"] is False
    assert out["reason"] == "tool_not_available_for_vertical"


# ── Allowed tools must still route normally (no blanket regression) ─────


@pytest.mark.asyncio
async def test_service_store_allows_unknown_tool_through_to_default_branch():
    """A tool that IS in SERVICE_KIND_TOOLS (transfer_to_manager) must
    NOT be blocked — the guard only rejects tools outside the vertical
    surface. We assert the dispatcher gets past the guard; transfer
    actually runs the underlying handler so we patch it lightly.
    (service tool은 guard 통과)"""
    from unittest.mock import AsyncMock, patch
    with patch("app.api.realtime_voice.transfer_to_manager",
               new=AsyncMock(return_value={
                   "success": True,
                   "message": "ok",
                   "ai_script_hint": "manager_handoff",
               })):
        out = await _dispatch_tool_call(
            tool_name         = "transfer_to_manager",
            tool_args         = {"reason": "customer_requested"},
            store_id          = _BEAUTY_STORE["id"],
            store_name        = _BEAUTY_STORE["name"],
            caller_phone_e164 = "+15035551234",
            session_state     = _session(_BEAUTY_STORE),
        )
    # If guard fired, reason would be 'tool_not_available_for_vertical'.
    assert out.get("reason") != "tool_not_available_for_vertical"


# ── Missing store_row → fall back to ORDER list (safe default) ──────────


@pytest.mark.asyncio
async def test_missing_store_row_falls_back_to_order_surface():
    """A degenerate session with no store_row should NOT crash the guard.
    get_tool_defs_for_store({}) returns ORDER_KIND_TOOLS by default, so an
    order tool stays allowed and a service tool gets blocked. This guards
    against a future refactor that forgets to populate session_state.
    (store_row 누락 시 안전 fallback — ORDER 기준)"""
    bare_session = {"call_log_id": "CA-test"}

    # service tool on missing-store session → blocked (defaults to ORDER)
    out_svc = await _dispatch_tool_call(
        tool_name         = "book_appointment",
        tool_args         = {},
        store_id          = "x",
        store_name        = "x",
        caller_phone_e164 = "+15035551234",
        session_state     = bare_session,
    )
    assert out_svc["reason"] == "tool_not_available_for_vertical"


# ── Unknown tool name (typo / hallucination) — uniformly blocked ────────


@pytest.mark.asyncio
async def test_unknown_tool_name_blocked_on_any_vertical():
    """A completely unknown tool name must be blocked regardless of
    vertical so a typo'd LLM call never falls through to the default
    `unsupported tool` branch (which used to be reachable past the
    routing if-chain).
    (오타/환각 이름 — 어느 vertical이든 일관 차단)"""
    for store in (_BEAUTY_STORE, _CAFE_STORE):
        out = await _dispatch_tool_call(
            tool_name         = "totally_made_up_tool",
            tool_args         = {},
            store_id          = store["id"],
            store_name        = store["name"],
            caller_phone_e164 = "+15035551234",
            session_state     = _session(store),
        )
        assert out["reason"] == "tool_not_available_for_vertical"
        assert "totally_made_up_tool" in out["error"]
