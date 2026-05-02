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


# ── Issue Ω fix — idempotency must respect cancelled reservations ──────────
# Live observed: call_bd9ad08677aecaefe028934ca58 T23 — second
# make_reservation in the same call silently deduped to the prior
# (already cancelled) bridge_transaction because state_machine has no
# FULFILLED→CANCELED transition, so bridge_transactions.state stays
# 'fulfilled' even after cancel_reservation flips reservations.status to
# 'cancelled'. The probe matched the stale 'fulfilled' tx and returned
# idempotent=True without inserting a new reservations row.
# Fix: when the idempotency probe hits, verify the linked reservation's
# status is 'confirmed'. If cancelled (or missing), bypass idempotency
# and proceed with actual creation.

@pytest.mark.asyncio
async def test_create_reservation_bypasses_idempotency_when_linked_reservation_cancelled():
    """Idempotency probe finds a recent matching bridge_transaction whose
    LINKED reservations row has been cancelled — must bypass dedup and
    create a brand-new reservation. Live regression from call_bd9ad08."""
    from app.services.bridge import flows

    # Probe returns a stale 'fulfilled' bridge_transaction (Aaron's, after
    # T17 cancel_reservation). pos_object_id points at the now-cancelled
    # reservations row.
    stale_tx = {
        "id":              "TXN-AARON",
        "pos_object_id":   "252",
        "state":           "fulfilled",
        "created_at":      "2026-05-02T19:37:14+00:00",
    }

    # The fix: a new helper looks up reservations.status by id. When it
    # returns 'cancelled', create_reservation must NOT short-circuit on
    # the probe hit.
    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="999")
    pos_adapter.mark_paid      = AsyncMock(return_value=None)

    payment_adapter = MagicMock()
    payment_adapter.is_enabled = MagicMock(return_value=False)
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "noop_abc",
        "amount_cents": 0,
    })

    fake_create  = AsyncMock(return_value={"id": "TXN-MICHAEL", "state": "pending"})
    fake_advance = AsyncMock(side_effect=[
        {"id": "TXN-MICHAEL", "state": "payment_sent"},
        {"id": "TXN-MICHAEL", "state": "paid"},
        {"id": "TXN-MICHAEL", "state": "fulfilled"},
    ])

    with patch("app.services.bridge.flows._find_recent_duplicate",
               new=AsyncMock(return_value=stale_tx)), \
         patch("app.services.bridge.flows._fetch_reservation_status",
               new=AsyncMock(return_value="cancelled")), \
         patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    # New transaction created, NOT idempotent return
    assert result["success"] is True
    assert result.get("idempotent") is not True
    assert result["transaction_id"] == "TXN-MICHAEL"
    # POS create_pending was actually called (proof we bypassed the probe)
    pos_adapter.create_pending.assert_awaited_once()
    fake_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_reservation_still_dedupes_when_linked_reservation_confirmed():
    """Negative control — when the linked reservation is still confirmed,
    idempotency probe MUST short-circuit (existing behavior preserved).
    Without this we'd regress the original 8th-call duplicate-tx fix."""
    from app.services.bridge import flows

    active_tx = {
        "id":            "TXN-ACTIVE",
        "pos_object_id": "300",
        "state":         "fulfilled",
        "created_at":    "2026-05-02T19:37:14+00:00",
    }

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()
    pos_adapter.mark_paid      = AsyncMock()
    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock()
    fake_create = AsyncMock()

    with patch("app.services.bridge.flows._find_recent_duplicate",
               new=AsyncMock(return_value=active_tx)), \
         patch("app.services.bridge.flows._fetch_reservation_status",
               new=AsyncMock(return_value="confirmed")), \
         patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    # Idempotent short-circuit fired
    assert result["success"] is True
    assert result.get("idempotent") is True
    assert result["transaction_id"] == "TXN-ACTIVE"
    # No new transaction / POS write happened
    fake_create.assert_not_awaited()
    pos_adapter.create_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_reservation_bypasses_idempotency_when_linked_reservation_missing():
    """Defensive — if the linked reservations row is missing entirely
    (race condition or DB inconsistency), prefer to create rather than
    trust the stale bridge_transaction. Same bypass branch as cancelled."""
    from app.services.bridge import flows

    stale_tx = {
        "id":            "TXN-ORPHAN",
        "pos_object_id": "999",
        "state":         "fulfilled",
        "created_at":    "2026-05-02T19:37:14+00:00",
    }

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="1000")
    pos_adapter.mark_paid      = AsyncMock(return_value=None)
    payment_adapter = MagicMock()
    payment_adapter.is_enabled = MagicMock(return_value=False)
    payment_adapter.create_session = AsyncMock(return_value={
        "paid": True, "pay_url": None, "session_id": "noop", "amount_cents": 0,
    })
    fake_create  = AsyncMock(return_value={"id": "TXN-NEW", "state": "pending"})
    fake_advance = AsyncMock(side_effect=[
        {"id": "TXN-NEW", "state": "payment_sent"},
        {"id": "TXN-NEW", "state": "paid"},
        {"id": "TXN-NEW", "state": "fulfilled"},
    ])

    with patch("app.services.bridge.flows._find_recent_duplicate",
               new=AsyncMock(return_value=stale_tx)), \
         patch("app.services.bridge.flows._fetch_reservation_status",
               new=AsyncMock(return_value=None)), \
         patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.transactions.advance_state",      new=fake_advance), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result.get("idempotent") is not True
    fake_create.assert_awaited_once()


# ── Issue Π fix — idempotent return must speak the EXISTING row's data ─────
# Live observed: call_ebdc036d11951a04336d44c8856 T13 — second
# make_reservation in same call (with DIFFERENT args: customer_name 'C Y Meet'
# vs original 'Sofia Chang', party 1 vs 4) hit idempotency hold (linked row
# still confirmed) but the bot then read out the NEW args as if they were
# the booking, while the DB row was untouched. The customer hears confirmation
# of a reservation that doesn't exist as described.
# Fix: when idempotency holds, build the success message from the LINKED
# reservations row (source of truth), not from the new tool args.

@pytest.mark.asyncio
async def test_create_reservation_idempotent_message_uses_existing_row_not_args():
    """Idempotent hit must read back the ACTUAL row, not the new args."""
    from app.services.bridge import flows

    existing_tx = {
        "id":            "TXN-ORIGINAL",
        "pos_object_id": "300",
        "state":         "fulfilled",
        "created_at":    "2026-05-02T19:37:14+00:00",
    }
    # The LINKED reservation — original booking data
    linked_row = {
        "id":               300,
        "customer_name":    "Sofia Chang",
        "customer_phone":   "+15037079566",
        "party_size":       4,
        "reservation_time": "2026-05-09T02:30:00+00:00",   # Fri May 8 7:30 PM PT
        "status":           "confirmed",
        "notes":            "",
    }
    # NEW args — Gemini retried with hallucinated different name/party/time
    different_args = {
        "user_explicit_confirmation": True,
        "customer_name":   "C Y Meet",
        "customer_phone":  "+15037079566",
        "reservation_date":"2026-05-02",   # today
        "reservation_time":"14:19",         # current wall-clock — hallucination
        "party_size":      1,
    }

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()
    pos_adapter.mark_paid      = AsyncMock()
    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock()
    fake_create = AsyncMock()

    with patch("app.services.bridge.flows._find_recent_duplicate",
               new=AsyncMock(return_value=existing_tx)), \
         patch("app.services.bridge.flows._fetch_reservation_status",
               new=AsyncMock(return_value="confirmed")), \
         patch("app.services.bridge.flows._fetch_reservation",
               new=AsyncMock(return_value=linked_row)), \
         patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=different_args, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result.get("idempotent") is True
    msg = result["message"]
    # The message MUST reflect the EXISTING row, NOT the new args
    assert "Sofia Chang" in msg
    assert "party of 4" in msg
    assert "May 8" in msg
    assert "7:30 PM" in msg or "7:30 pm" in msg.lower()
    # Negative — args values must NOT leak in
    assert "C Y Meet" not in msg
    assert "party of 1" not in msg
    assert "May 2" not in msg


@pytest.mark.asyncio
async def test_create_reservation_idempotent_falls_back_to_args_when_row_fetch_fails():
    """Defensive — if the row fetch fails (network blip), the idempotent
    return path must still speak SOMETHING coherent. Falls back to the
    args-based message (existing behavior). No crash."""
    from app.services.bridge import flows

    existing_tx = {
        "id":            "TXN-ORIGINAL",
        "pos_object_id": "300",
        "state":         "fulfilled",
        "created_at":    "2026-05-02T19:37:14+00:00",
    }

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()
    pos_adapter.mark_paid      = AsyncMock()
    payment_adapter = MagicMock()
    payment_adapter.create_session = AsyncMock()
    fake_create = AsyncMock()

    with patch("app.services.bridge.flows._find_recent_duplicate",
               new=AsyncMock(return_value=existing_tx)), \
         patch("app.services.bridge.flows._fetch_reservation_status",
               new=AsyncMock(return_value="confirmed")), \
         patch("app.services.bridge.flows._fetch_reservation",
               new=AsyncMock(return_value=None)), \
         patch("app.services.bridge.flows.transactions.create_transaction", new=fake_create), \
         patch("app.services.bridge.flows.get_pos_adapter",     return_value=pos_adapter), \
         patch("app.services.bridge.flows.get_payment_adapter", return_value=payment_adapter):

        result = await flows.create_reservation(
            store_id=STORE_ID, args=VALID_RESERVATION_ARGS, call_log_id=CALL_LOG_ID,
        )

    assert result["success"] is True
    assert result.get("idempotent") is True
    msg = result["message"]
    # Falls back to args-based message — must still mention the customer
    assert "Michael Chang" in msg or "party of" in msg
