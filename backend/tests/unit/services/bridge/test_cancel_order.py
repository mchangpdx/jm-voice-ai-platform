# B2 — flows.cancel_order TDD
# (B2 — flows.cancel_order 테스트 우선 작성)
#
# Per spec backend/docs/specs/B2_cancel_order.md.
#
# cancel_order(store_id, caller_phone_e164, call_log_id) transitions
# the most-recent in-flight transaction (state ∈ {PENDING, PAYMENT_SENT,
# FIRED_UNPAID}) for the same caller phone to CANCELED, writes one
# state_transition audit row, and returns a result dict for the Voice
# Engine.
#
# Tests written BEFORE implementation — all should fail until
# flows.cancel_order lands.

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


CALLER = "+15035551234"
STORE  = "STORE_UUID"


def _tx(state="pending", lane="pay_first", items=None, total=599):
    """Helper — one bridge_transactions row in the shape the probe returns."""
    return {
        "id":             "tx-1",
        "store_id":       STORE,
        "vertical":       "restaurant",
        "pos_object_type":"order",
        "pos_object_id":  "",
        "customer_phone": CALLER,
        "customer_name":  "Aaron Chang",
        "state":          state,
        "payment_lane":   lane,
        "total_cents":    total,
        "items_json":     items or [{"name": "Cafe Latte", "quantity": 1, "price": 5.99}],
    }


# ── T1: Happy path PENDING → CANCELED ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_pending_succeeds():
    """Most-recent tx in PENDING → state_machine allows transition →
    advance_state called → success."""
    from app.services.bridge import flows

    pending_row = _tx(state="pending", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=pending_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is True
    assert res["state"]          == "canceled"
    assert res["prior_state"]    == "pending"
    assert res["ai_script_hint"] == "cancel_success"
    txns_mod.advance_state.assert_awaited_once()
    # The state machine call must use the right to_state + actor source
    kwargs = txns_mod.advance_state.await_args.kwargs
    assert kwargs["to_state"] == "canceled"
    assert kwargs["source"]   == "voice"
    assert kwargs["actor"]    == "tool_call:cancel_order"


# ── T2: Happy path PAYMENT_SENT → CANCELED ───────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_payment_sent_succeeds():
    """tx in PAYMENT_SENT (link tapped, callback not yet) → cancel ok."""
    from app.services.bridge import flows

    ps_row = _tx(state="payment_sent", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=ps_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is True
    assert res["prior_state"]    == "payment_sent"
    assert res["ai_script_hint"] == "cancel_success"


# ── T3: Happy path FIRED_UNPAID → CANCELED (kitchen alert script) ────────────

@pytest.mark.asyncio
async def test_cancel_order_fired_unpaid_uses_kitchen_alert_script():
    """FIRED_UNPAID cancel succeeds, but ai_script_hint='cancel_success_fired'
    so the bot tells the customer to notify staff at the counter (V1 doesn't
    auto-void Loyverse)."""
    from app.services.bridge import flows

    fired_row = _tx(state="fired_unpaid", lane="fire_immediate")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=fired_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is True
    assert res["prior_state"]    == "fired_unpaid"
    assert res["ai_script_hint"] == "cancel_success_fired"


# ── T4: No in-flight, no settled → cancel_no_target ──────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_no_target_when_no_recent_orders():
    """Both probes empty → cancel_no_target, no DB write."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_settled_order",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is False
    assert res["reason"]         == "cancel_no_target"
    assert res["ai_script_hint"] == "cancel_no_target"
    txns_mod.advance_state.assert_not_called()


# ── T5: Already cancelled — settled probe returns CANCELED row ───────────────

@pytest.mark.asyncio
async def test_cancel_order_detects_already_canceled():
    """In-flight probe empty, settled probe returns CANCELED row →
    cancel_already_canceled hint, no DB write."""
    from app.services.bridge import flows

    canceled_row = _tx(state="canceled", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_settled_order",
                      new=AsyncMock(return_value=canceled_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is False
    assert res["reason"]         == "cancel_already_canceled"
    assert res["ai_script_hint"] == "cancel_already_canceled"
    txns_mod.advance_state.assert_not_called()


# ── T6: Already paid (PAID) — manager transfer suggestion ────────────────────

@pytest.mark.asyncio
async def test_cancel_order_detects_already_paid():
    """Settled probe returns PAID row → cancel_already_paid hint."""
    from app.services.bridge import flows

    paid_row = _tx(state="paid", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_settled_order",
                      new=AsyncMock(return_value=paid_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is False
    assert res["reason"]         == "cancel_already_paid"
    assert res["state"]          == "paid"
    assert res["ai_script_hint"] == "cancel_already_paid"
    txns_mod.advance_state.assert_not_called()


# ── T7: Already fulfilled — same script as paid ──────────────────────────────

@pytest.mark.parametrize("terminal_state", ["fulfilled", "refunded", "no_show"])
@pytest.mark.asyncio
async def test_cancel_order_detects_other_terminal_states(terminal_state):
    """FULFILLED/REFUNDED/NO_SHOW also route to cancel_already_paid script
    (the customer-facing line — manager transfer — is the right call for
    all post-payment terminal states)."""
    from app.services.bridge import flows

    settled_row = _tx(state=terminal_state, lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_settled_order",
                      new=AsyncMock(return_value=settled_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is False
    assert res["reason"]         == "cancel_already_paid"
    assert res["ai_script_hint"] == "cancel_already_paid"
    txns_mod.advance_state.assert_not_called()


# ── T8: advance_state raises → cancel_failed (no crash) ──────────────────────

@pytest.mark.asyncio
async def test_cancel_order_handles_advance_state_failure():
    """DB write blip during state transition → graceful cancel_failed,
    customer hears the manager-transfer line, no exception bubbles."""
    from app.services.bridge import flows

    pending_row = _tx(state="pending", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=pending_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock(side_effect=Exception("DB blip"))
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]        is False
    assert res["reason"]         == "cancel_failed"
    assert res["ai_script_hint"] == "cancel_failed"
    assert res["transaction_id"] == "tx-1"


# ── T9: state machine refuses (defensive — should never fire in prod) ────────

@pytest.mark.asyncio
async def test_cancel_order_handles_invalid_transition_defensively():
    """If somehow a row leaks through with a state that can't transition to
    canceled (e.g. a future state added without updating the SQL filter),
    we return cancel_failed instead of crashing. Defensive — should not
    fire under current state machine."""
    from app.services.bridge import flows

    # Inject a state the machine treats as terminal — paid only allows
    # transitions to fulfilled/refunded.
    paid_row = _tx(state="paid", lane="pay_first")

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=paid_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    # Either cancel_failed (defensive guard fired) OR we never call
    # advance_state — both prove no invalid transition was attempted.
    assert res["success"] is False
    assert res["reason"]  == "cancel_failed"
    txns_mod.advance_state.assert_not_called()


# ── T10: Invariants — items + total preserved on success ─────────────────────

@pytest.mark.asyncio
async def test_cancel_order_preserves_items_and_total_in_return():
    """Cancellation does NOT mutate items or total — the historical record
    stays. Return dict carries items + total from the existing row so the
    voice handler can quote them in the script if needed."""
    from app.services.bridge import flows

    items = [
        {"name": "Cafe Latte", "quantity": 2, "price": 5.99},
        {"name": "Croissant",  "quantity": 1, "price": 3.50},
    ]
    pending_row = _tx(state="pending", lane="pay_first",
                       items=items, total=1548)

    with patch.object(flows, "_find_modifiable_order",
                      new=AsyncMock(return_value=pending_row)), \
         patch.object(flows, "transactions") as txns_mod:
        txns_mod.advance_state = AsyncMock()
        res = await flows.cancel_order(
            store_id          = STORE,
            caller_phone_e164 = CALLER,
            call_log_id       = None,
        )

    assert res["success"]      is True
    assert res["items"]        == items
    assert res["total_cents"]  == 1548
    assert res["lane"]         == "pay_first"
    assert res["transaction_id"] == "tx-1"
