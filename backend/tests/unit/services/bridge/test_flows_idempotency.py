# Bridge Server — flows-level idempotency TDD tests
# (Bridge Server — flows 레벨 idempotency TDD 테스트)
#
# Phase 2-A.5 had idempotency at the reservation insert layer (insert_reservation).
# Phase 2-B routed through Bridge → SupabasePOSAdapter → plain INSERT, dropping
# the protection. 8th live call exposed this: 3 duplicate transactions + 3
# duplicate reservations created from a single user "Yes."
#
# This test file LOCKS the protection at the Bridge level (flows.create_reservation):
#   - same store + customer_phone + reservation_time within 5 min → return existing
#   - existing transaction is reused (no new POS create, no duplicate state machine run)
#   - response message is still spoken back (caller cannot tell the difference)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


STORE_ID    = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
CALL_LOG_ID = "call_test_idempotent"

VALID_RESERVATION_ARGS = {
    "user_explicit_confirmation": True,
    "customer_name":   "Michael Chang",
    "customer_phone":  "+15037079566",
    "reservation_date": "2026-04-30",
    "reservation_time": "19:00",
    "party_size":       4,
}


@pytest.mark.asyncio
async def test_idempotent_call_returns_existing_transaction_no_new_pos_create():
    """Second call within 5 min for same store+phone+time → reuses existing
    transaction, NO new POS create, NO new state machine run, NO new bridge_events
    explosion. Same success message returned to caller."""
    from app.services.bridge import flows

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock()

    fake_create  = AsyncMock()
    fake_advance = AsyncMock()

    # The probe finds an existing transaction — adapter must short-circuit
    fake_probe = AsyncMock(return_value={
        "id":            "EXISTING-TXN-ID",
        "pos_object_id": "999",
        "state":         "fulfilled",
    })

    # Issue Ω fix — probe hit must verify the linked reservation is still
    # 'confirmed'. Mock the helper so the original short-circuit behavior
    # under test is preserved.
    fake_status = AsyncMock(return_value="confirmed")

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows._find_recent_duplicate", new=fake_probe), \
         patch("app.services.bridge.flows._fetch_reservation_status", new=fake_status), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result["transaction_id"] == "EXISTING-TXN-ID"
    assert result["pos_object_id"]  == "999"
    assert result.get("idempotent") is True
    assert "7:00 PM" in result["message"]      # message still composed for the caller

    # CRITICAL: no side effects beyond the probe
    fake_create.assert_not_called()
    fake_advance.assert_not_called()
    pos_adapter.create_pending.assert_not_called()
    pos_adapter.mark_paid.assert_not_called()
    payment_adapter.create_session.assert_not_called()


@pytest.mark.asyncio
async def test_no_duplicate_means_full_flow_runs():
    """When probe returns None, full 11-step flow runs as before."""
    from app.services.bridge import flows

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="999")
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.is_enabled = MagicMock(return_value=False)
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "n", "amount_cents": 0,
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-NEW", "state": "pending"})
    fake_advance = AsyncMock()
    fake_set_pos = AsyncMock()
    fake_probe   = AsyncMock(return_value=None)

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.transactions.set_pos_object_id",  new=fake_set_pos), \
         patch("app.services.bridge.flows._find_recent_duplicate", new=fake_probe), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result["transaction_id"] == "TXN-NEW"
    assert result.get("idempotent") is False or result.get("idempotent") is None
    fake_create.assert_called_once()
    pos_adapter.create_pending.assert_awaited_once()
    pos_adapter.mark_paid.assert_awaited_once()


# ── _find_recent_duplicate (probe primitive) ──────────────────────────────────

@pytest.mark.asyncio
async def test_probe_returns_match_within_window():
    """Probe queries bridge_transactions for store+phone+pos_object_type+
    reservation-time matching, within last 5 min. Returns the row dict if found."""
    from app.services.bridge import flows

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.json = lambda: [{"id": "EXISTING", "pos_object_id": "999", "state": "fulfilled"}]

    with patch("app.services.bridge.flows.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        result = await flows._find_recent_duplicate(
            store_id        = STORE_ID,
            customer_phone  = "+15037079566",
            pos_object_type = "reservation",
            unique_key      = "2026-04-30T19:00:00-07:00",
            window_minutes  = 5,
        )

    assert result == {"id": "EXISTING", "pos_object_id": "999", "state": "fulfilled"}

    # Probe query parameters
    params = instance.get.call_args.kwargs["params"]
    assert params["store_id"]        == f"eq.{STORE_ID}"
    assert params["customer_phone"]  == "eq.+15037079566"
    assert params["pos_object_type"] == "eq.reservation"


@pytest.mark.asyncio
async def test_probe_returns_none_on_empty_result():
    from app.services.bridge import flows

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.json = lambda: []

    with patch("app.services.bridge.flows.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        result = await flows._find_recent_duplicate(
            store_id="x", customer_phone="+1503", pos_object_type="reservation",
            unique_key="2026-04-30T19:00:00-07:00", window_minutes=5,
        )
    assert result is None


@pytest.mark.asyncio
async def test_probe_excludes_failed_and_canceled_states():
    """A failed/canceled transaction should NOT count as an idempotent hit —
    user wants a real reservation now after a previous failure."""
    from app.services.bridge import flows

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.json = lambda: []

    with patch("app.services.bridge.flows.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=fake_resp)

        await flows._find_recent_duplicate(
            store_id="x", customer_phone="+1503", pos_object_type="reservation",
            unique_key="2026-04-30T19:00:00-07:00", window_minutes=5,
        )

    params = instance.get.call_args.kwargs["params"]
    # Must filter on state — only paid/fulfilled count as "real existing"
    assert "state" in params
    state_filter = params["state"]
    assert "paid" in state_filter or "fulfilled" in state_filter
    # Must NOT count failed/canceled as idempotent matches
    assert "failed"   not in state_filter
    assert "canceled" not in state_filter
