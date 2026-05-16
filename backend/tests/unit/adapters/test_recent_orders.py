# N1 (2026-05-17) — recent_orders tool: cross-call cancel/modify entry point.
# (N1 — 통화 간 cancel/modify 진입점 recent_orders tool 테스트)
#
# Memory: n1_n2_diagnosis_2026-05-16.md — recall_order is in-call snapshot
# only (Phase 5 #25), so prior-call cancel attempts (live trigger
# CAc450b27d 2026-05-15) had no entry path. recent_orders fills the gap
# without weakening the recall_order invariant.

from __future__ import annotations

import pytest


MOCK_STORE = {
    "name":             "JM Taco",
    "system_prompt":    "You are Sofia, the friendly AI for JM Taco.",
    "business_hours":   "Mon-Sun 11am-9pm",
    "menu_cache":       "Burrito al Pastor: $12.00",
    "temporary_prompt": "",
    "custom_knowledge": "",
}


# ── T1: RECENT_ORDERS_TOOL_DEF exported with empty params ────────────────────

def test_t1_recent_orders_tool_def_is_exported() -> None:
    from app.skills.order.order import RECENT_ORDERS_TOOL_DEF

    decls = RECENT_ORDERS_TOOL_DEF.get("function_declarations", [])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["name"] == "recent_orders"
    # Same invariant as recall_order — caller_phone is server-injected,
    # so the LLM contract carries no required params. Prevents the LLM
    # from inventing a phone string when the system already has one.
    assert decl["parameters"]["properties"] == {}
    assert decl["parameters"].get("required", []) == []


# ── T2: render — none ────────────────────────────────────────────────────────

def test_t2_render_recent_none() -> None:
    from app.skills.order.order import render_recent_orders_message

    msg, reason, candidates = render_recent_orders_message([])
    assert reason == "recent_none"
    assert candidates == []
    assert "don't see any recent orders" in msg.lower()
    assert "new one" in msg.lower()


# ── T3: render — single match, formatted with items + total + minutes-ago ───

def test_t3_render_recent_single() -> None:
    from datetime import datetime, timedelta, timezone
    from app.skills.order.order import render_recent_orders_message

    eight_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=8)).isoformat()
    rows = [{
        "id":          "tx-1",
        "state":       "pending",
        "total_cents": 2300,
        "items_json":  [{"name": "Burrito al Pastor", "quantity": 1}],
        "created_at":  eight_min_ago,
    }]
    msg, reason, candidates = render_recent_orders_message(rows)
    assert reason == "recent_single"
    assert len(candidates) == 1
    assert candidates[0]["id"] == "tx-1"
    assert "1 Burrito al Pastor" in msg
    assert "$23.00" in msg
    assert "8 minutes ago" in msg
    assert "cancel" in msg.lower()


# ── T4: render — single match plural items + zero-minute snap ────────────────

def test_t4_render_recent_single_plural_and_fresh() -> None:
    from datetime import datetime, timezone
    from app.skills.order.order import render_recent_orders_message

    # created_at == now → minutes diff = 0; renderer snaps to "1 minute ago"
    # so the spoken line stays natural.
    rows = [{
        "id":          "tx-2",
        "state":       "fired_unpaid",
        "total_cents": 2497,
        "items_json":  [
            {"name": "Taco al Pastor", "quantity": 3},
            {"name": "Mexican Coke",    "quantity": 2},
        ],
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }]
    msg, reason, _ = render_recent_orders_message(rows)
    assert reason == "recent_single"
    assert "3 Taco al Pastors" in msg
    assert "2 Mexican Cokes" in msg
    assert "1 minute ago" in msg  # snap from 0 → 1 for spoken naturalness


# ── T5: render — multi-match summary stops at 3 lines ────────────────────────

def test_t5_render_recent_multi_caps_summary_at_three() -> None:
    from datetime import datetime, timedelta, timezone
    from app.skills.order.order import render_recent_orders_message

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id":          f"tx-{i}",
            "state":       "pending",
            "total_cents": 1000 + i,
            "items_json":  [{"name": f"Item {i}", "quantity": 1}],
            "created_at":  (now - timedelta(minutes=i + 1)).isoformat(),
        }
        for i in range(4)
    ]
    msg, reason, candidates = render_recent_orders_message(rows)
    assert reason == "recent_multi"
    assert len(candidates) == 4
    # Spoken summary holds at most 3 lines (separated by ';'), so the
    # LLM doesn't dump a 5-line wall of items to the caller.
    summary_chunks = msg.split(";")
    assert len(summary_chunks) <= 3
    assert "4 recent orders" in msg


# ── T6: render — items_json missing falls back gracefully ────────────────────

def test_t6_render_recent_single_with_missing_items() -> None:
    from datetime import datetime, timezone
    from app.skills.order.order import render_recent_orders_message

    rows = [{
        "id":          "tx-blank",
        "state":       "pending",
        "total_cents": 500,
        "items_json":  None,
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }]
    msg, reason, _ = render_recent_orders_message(rows)
    # No items in summary but reason is still single — the renderer falls
    # back to "your order" so the caller hears something coherent.
    assert reason == "recent_single"
    assert "your order" in msg
    assert "$5.00" in msg


# ── T7: System prompt rule 13 references recent_orders cross-call path ──────

def test_t7_system_prompt_rule_13_mentions_recent_orders() -> None:
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    # Cross-call entry must exist + the recall_order in-call invariant must
    # not have been removed when we added the cross-call branch.
    assert "recent_orders" in prompt
    assert "recall_order" in prompt
    # Hallucination guard preserved.
    assert "NEVER invent" in prompt or "never invent" in prompt.lower()


# ── T7b: Rule 13 lists the live-regression cancel phrases ──────────────────
# Live trigger 2026-05-16 — CA438ad0 / CAec46977 / CAbfdc4e: LLM heard
# "cancel the earlier one" / "cancel only one" / "the all my order" but
# paraphrased cancel_no_target text instead of calling recent_orders.
# Rule 13 must cover these phrasings or the LLM keeps drifting back to
# the cancel_order branch.

def test_t7b_rule_13_covers_live_cancel_phrasings() -> None:
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    # At least one representative live phrasing must be in the rule body
    # so the LLM has explicit pattern-match anchors during inference.
    assert "cancel the earlier one" in prompt
    assert "cancel only one" in prompt
    # The "first 3 turns before items have been recited" gate is what
    # forces cancel_order → recent_orders routing during the greeting
    # phase, before any in-call order exists.
    assert "first 3 turns" in prompt
    assert "ALWAYS call recent_orders FIRST" in prompt


# ── T7c: cancel_order tool description routes empty-snapshot calls away ────

def test_t7c_cancel_order_description_routes_empty_snapshot_to_recent_orders() -> None:
    from app.skills.order.order import CANCEL_ORDER_TOOL_DEF

    desc = CANCEL_ORDER_TOOL_DEF["function_declarations"][0]["description"]
    # PRECONDITION (a) requires an in-call create_order success — this is
    # the hard guard that prevents the LLM from firing cancel_order on a
    # caller's first turn before any order has been placed.
    assert "create_order has succeeded earlier in THIS call" in desc
    # And the description must explicitly hand cross-call cancel attempts
    # off to recent_orders so the LLM has a clear branch instead of a
    # dead-end "I don't see an active order" reply.
    assert "call recent_orders FIRST" in desc


# ── T7d: cancel_order PRECONDITION (a) accepts recent_orders single ───────
# Live trigger CAea87a1a8 (2026-05-17) — the agent wasted a turn on a
# redundant "Just to confirm" recital after recent_orders had already
# spoken the items + total. cancel_order's PRECONDITION (a) must now
# accept BOTH in-call create_order success AND a recent_orders single
# match so the LLM doesn't insist on a duplicate recital.

def test_t7d_cancel_order_accepts_recent_orders_single_as_precondition() -> None:
    from app.skills.order.order import CANCEL_ORDER_TOOL_DEF

    desc = CANCEL_ORDER_TOOL_DEF["function_declarations"][0]["description"]
    # OR branch lets the cross-call path satisfy PRECONDITION (a).
    assert "recent_orders just" in desc
    assert "recent_single" in desc
    # And the duplicate-recital exception must call out the no-second-line
    # rule so the LLM has an unambiguous branch.
    assert "do NOT add a second" in desc


# ── T7e: System prompt rule 13 has the CONFIRM SHORTCUT branch ────────────

def test_t7e_rule_13_has_confirm_shortcut_after_recent_single() -> None:
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    assert "CONFIRM SHORTCUT" in prompt
    # Must cover at least 3 of the 5 supported languages so multilingual
    # confirm patterns (Korean / Spanish / English) don't fall through.
    assert "yes cancel" in prompt
    assert "취소" in prompt
    assert "cancela" in prompt


# ── T8: tool registry includes recent_orders without breaking others ─────────

def test_t8_recent_orders_registered_in_realtime_tools() -> None:
    from app.api.realtime_voice import OPENAI_REALTIME_TOOLS

    names = {t.get("name") for t in OPENAI_REALTIME_TOOLS}
    assert "recent_orders" in names
    # Ensure existing tools survived the registration.
    for kept in (
        "create_order", "modify_order", "cancel_order",
        "make_reservation", "modify_reservation", "cancel_reservation",
        "allergen_lookup", "recall_order", "transfer_to_manager",
    ):
        assert kept in names, f"existing tool {kept} dropped from registry"


# ── T9: bridge.recent_for_phone — state filter + lookback param shape ────────
#       Mocks the Supabase HTTP call so the test runs offline.

@pytest.mark.asyncio
async def test_t9_recent_for_phone_query_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.bridge import transactions as bt

    captured: dict = {}

    class FakeResp:
        status_code = 200
        def json(self) -> list[dict]:
            return [
                {"id": "tx-A", "state": "pending", "total_cents": 1000,
                 "items_json": [], "created_at": "2026-05-17T00:00:00+00:00"},
            ]

    class FakeClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        async def get(self, _url: str, *, headers, params):  # type: ignore[no-untyped-def]
            captured["params"] = params
            return FakeResp()

    monkeypatch.setattr(bt.httpx, "AsyncClient", FakeClient)

    rows = await bt.recent_for_phone(
        store_id="store-xyz", caller_phone="+15035551234", lookback_min=30,
    )
    assert len(rows) == 1
    p = captured["params"]
    assert p["store_id"]       == "eq.store-xyz"
    assert p["customer_phone"] == "eq.+15035551234"
    # Actionable states only — terminal/complete states excluded. Parse
    # the `in.(a,b,c)` syntax so substring overlap (fired_unpaid contains
    # "paid") doesn't mask a real misconfig.
    assert p["state"].startswith("in.(") and p["state"].endswith(")")
    state_set = set(p["state"][4:-1].split(","))
    assert state_set == {"pending", "payment_sent", "fired_unpaid"}
    assert p["order"]     == "created_at.desc"
    assert p["limit"]     == "5"


# ── T10: bridge.recent_for_phone — empty caller_phone short-circuits ─────────

@pytest.mark.asyncio
async def test_t10_recent_for_phone_empty_phone_returns_empty() -> None:
    from app.services.bridge import transactions as bt
    # No monkeypatch — the function must short-circuit before any HTTP call.
    assert await bt.recent_for_phone(store_id="store-xyz", caller_phone="") == []
    assert await bt.recent_for_phone(store_id="", caller_phone="+15035551234") == []
