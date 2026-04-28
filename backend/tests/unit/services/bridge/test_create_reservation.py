# Bridge Server — high-level create_reservation() flow TDD tests
# (Bridge Server — 고수준 create_reservation() 흐름 TDD 테스트)
#
# This is the wrapper that takes Gemini's reservation tool args and orchestrates
# the entire bridge flow: bridge_transaction creation → POS pending →
# payment session → state transitions → POS mark_paid (NoOp gateway today).
#
# Tomorrow's Maverick adapter swap requires ZERO changes here — only the factory.

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


STORE_ID    = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
CALL_LOG_ID = "call_test_xyz"

VALID_RESERVATION_ARGS = {
    "user_explicit_confirmation": True,
    "customer_name":   "Michael Chang",
    "customer_phone":  "+15037079566",
    "reservation_date": "2026-04-30",
    "reservation_time": "19:00",
    "party_size":       4,
}


@pytest.mark.asyncio
async def test_create_reservation_zero_amount_runs_full_state_machine_to_fulfilled():
    """With amount=0 and NoOp gateway, transaction goes pending→payment_sent→paid→fulfilled.
    POS create_pending + mark_paid both called. State machine emits 4 events."""
    from app.services.bridge import flows

    # Mocks for collaborators
    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="999")
    pos_adapter.mark_paid      = AsyncMock(return_value=None)

    payment_adapter = MagicMock()
    payment_adapter.is_enabled = MagicMock(return_value=False)
    payment_adapter.create_session = AsyncMock(return_value={
        "paid":         True,
        "pay_url":      None,
        "session_id":   "noop_abc",
        "amount_cents": 0,
    })

    # transactions.create_transaction mock
    fake_create   = AsyncMock(return_value={"id": "TXN-1", "state": "pending"})
    fake_advance  = AsyncMock(side_effect=[
        {"id": "TXN-1", "state": "payment_sent"},
        {"id": "TXN-1", "state": "paid"},
        {"id": "TXN-1", "state": "fulfilled"},
    ])

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id    = STORE_ID,
            args        = VALID_RESERVATION_ARGS,
            call_log_id = CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result["transaction_id"] == "TXN-1"
    assert result["pos_object_id"]  == "999"
    assert result["state"]          == "fulfilled"

    # POS create_pending called with vertical=restaurant
    pos_adapter.create_pending.assert_awaited_once()
    assert pos_adapter.create_pending.call_args.kwargs["vertical"] == "restaurant"

    # POS mark_paid called once (after payment success)
    pos_adapter.mark_paid.assert_awaited_once_with(
        vertical="restaurant", object_id="999"
    )

    # State machine advanced 3 times (pending→payment_sent→paid→fulfilled)
    assert fake_advance.await_count == 3


@pytest.mark.asyncio
async def test_create_reservation_rejects_unconfirmed_args_before_any_db_call():
    from app.services.bridge import flows

    args = {**VALID_RESERVATION_ARGS, "user_explicit_confirmation": False}

    fake_create = AsyncMock()
    pos_adapter = MagicMock(); pos_adapter.create_pending = AsyncMock()

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.get_pos_adapter", return_value=pos_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=args, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is False
    assert "confirm" in result["error"].lower()
    fake_create.assert_not_called()
    pos_adapter.create_pending.assert_not_called()


@pytest.mark.asyncio
async def test_create_reservation_normalizes_phone_to_e164():
    """Phone arrives as '503-707-9566' from voice; bridge normalizes before any write."""
    from app.services.bridge import flows

    args = {**VALID_RESERVATION_ARGS, "customer_phone": "503-707-9566"}

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="1")
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "n", "amount_cents": 0,
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-1", "state": "pending"})
    fake_advance = AsyncMock(return_value={"state": "fulfilled"})

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        await flows.create_reservation(
            store_id=STORE_ID, args=args, call_log_id=CALL_LOG_ID,
        )

    # transaction created with E.164 phone
    create_call = fake_create.await_args_list[0]
    assert create_call.kwargs["customer_phone"] == "+15037079566"

    # POS pending payload also gets E.164 phone
    pos_payload = pos_adapter.create_pending.call_args.kwargs["payload"]
    assert pos_payload["customer_phone"] == "+15037079566"


@pytest.mark.asyncio
async def test_create_reservation_combines_date_time_into_iso_for_pos():
    from app.services.bridge import flows

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="1")
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "n", "amount_cents": 0,
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-1", "state": "pending"})
    fake_advance = AsyncMock()

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    pos_payload = pos_adapter.create_pending.call_args.kwargs["payload"]
    # 2026-04-30 19:00 LA = 2026-04-30T19:00:00-07:00 (April → PDT)
    assert pos_payload["reservation_time"].startswith("2026-04-30T19:00:00")


@pytest.mark.asyncio
async def test_create_reservation_message_uses_12_hour_format():
    """Spoken response back to customer must use 7:00 PM, not 19:00."""
    from app.services.bridge import flows

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="1")
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "n", "amount_cents": 0,
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-1", "state": "pending"})
    fake_advance = AsyncMock()

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    assert "7:00 PM" in result["message"]
    assert "19:00"   not in result["message"]


@pytest.mark.asyncio
async def test_create_reservation_gateway_failure_marks_transaction_failed():
    """If payment_adapter returns paid=False (no gateway, non-zero amount), bridge
    advances transaction to failed and surfaces clear error to caller."""
    from app.services.bridge import flows

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="1")
    pos_adapter.mark_paid      = AsyncMock()

    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock(return_value={
        "paid":   False,
        "pay_url": None,
        "session_id": None,
        "amount_cents": 1000,
        "reason": "no_payment_gateway_configured",
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-1", "state": "pending"})
    fake_advance = AsyncMock()

    args = {**VALID_RESERVATION_ARGS}

    with patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        # Force non-zero amount so gateway is required
        result = await flows.create_reservation(
            store_id=STORE_ID, args=args, call_log_id=CALL_LOG_ID, deposit_cents=1000,
        )

    assert result["success"] is False
    assert "gateway" in result["error"].lower() or "configured" in result["error"].lower()
    # POS mark_paid NOT called
    pos_adapter.mark_paid.assert_not_called()
    # Transaction advanced to 'failed' (one of the advance_state calls)
    assert any("failed" in str(c.kwargs.get("to_state", "")) for c in fake_advance.await_args_list)
