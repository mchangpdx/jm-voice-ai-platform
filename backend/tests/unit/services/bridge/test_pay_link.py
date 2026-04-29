# Phase 2-B.1.9 — Pay link flow TDD
# (Phase 2-B.1.9 — 결제 링크 흐름 TDD)
#
# settle_payment(transaction_id) is the Bridge entry point hit by the pay
# link route. It walks the state machine end-to-end depending on the lane
# the order was routed into:
#
#   pay_first:       PENDING → PAYMENT_SENT → PAID → POS create_pending →
#                    backfill pos_object_id → FULFILLED
#   fire_immediate:  FIRED_UNPAID → PAID (POS receipt already exists; just
#                    closes the loop on payment)
#
# Idempotency: hitting the same tx twice (double-click) returns success
# without re-running side effects.
#
# Failure modes:
#   - tx not found ⇒ status='not_found'
#   - already paid/fulfilled ⇒ status='already_paid' (idempotent success)
#   - already canceled/no_show ⇒ status='terminal_state' (refused)
#   - POS create_pending raises (pay_first only) ⇒ stay in PAID, signal
#     warning so reconciliation cron can retry the POS write-back

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── Not-found ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settle_payment_returns_not_found_when_tx_missing():
    from app.services.bridge.pay_link import settle_payment

    with patch("app.services.bridge.pay_link.transactions") as mock_tx:
        mock_tx.get_transaction = AsyncMock(return_value=None)
        res = await settle_payment(transaction_id="missing-uuid")

    assert res["success"] is False
    assert res["status"]  == "not_found"


# ── Idempotency on already-terminal states ────────────────────────────────────

@pytest.mark.asyncio
async def test_settle_payment_is_idempotent_when_already_paid():
    """Double-clicking the pay link returns success without re-processing.
    (이미 paid 상태면 부작용 없이 성공)
    """
    from app.services.bridge.pay_link import settle_payment

    with patch("app.services.bridge.pay_link.transactions") as mock_tx:
        mock_tx.get_transaction = AsyncMock(return_value={
            "id": "tx-1", "state": "paid", "payment_lane": "pay_first",
            "pos_object_id": "r-1", "store_id": "S",
        })
        mock_tx.advance_state = AsyncMock()
        res = await settle_payment(transaction_id="tx-1")

    assert res["success"] is True
    assert res["status"]  == "already_paid"
    mock_tx.advance_state.assert_not_called()


@pytest.mark.asyncio
async def test_settle_payment_is_idempotent_when_already_fulfilled():
    from app.services.bridge.pay_link import settle_payment

    with patch("app.services.bridge.pay_link.transactions") as mock_tx:
        mock_tx.get_transaction = AsyncMock(return_value={
            "id": "tx-1", "state": "fulfilled", "payment_lane": "pay_first",
            "pos_object_id": "r-1", "store_id": "S",
        })
        mock_tx.advance_state = AsyncMock()
        res = await settle_payment(transaction_id="tx-1")

    assert res["success"] is True
    assert res["status"]  == "already_paid"
    mock_tx.advance_state.assert_not_called()


@pytest.mark.asyncio
async def test_settle_payment_refuses_canceled_or_no_show():
    """A terminal write-off cannot be revived by the pay link.
    (terminal write-off은 결제 링크로 복구 불가)
    """
    from app.services.bridge.pay_link import settle_payment

    with patch("app.services.bridge.pay_link.transactions") as mock_tx:
        mock_tx.get_transaction = AsyncMock(return_value={
            "id": "tx-1", "state": "no_show", "payment_lane": "fire_immediate",
            "store_id": "S",
        })
        mock_tx.advance_state = AsyncMock()
        res = await settle_payment(transaction_id="tx-1")

    assert res["success"] is False
    assert res["status"]  == "terminal_state"
    mock_tx.advance_state.assert_not_called()


# ── pay_first lane: full happy path ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_settle_payment_pay_first_full_path():
    """pay_first lane:
      PENDING → PAYMENT_SENT → PAID → POS create → backfill → FULFILLED
    POS adapter is called HERE (not at order time) and pos_object_id is
    written back to bridge_transactions.
    (pay_first 전체 경로 — POS 호출은 결제 후)
    """
    from app.services.bridge.pay_link import settle_payment

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(return_value="receipt-9001")
    pos_adapter.mark_paid      = AsyncMock()

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw["to_state"])
        return {"state": kw["to_state"]}

    fake_tx = {
        "id": "tx-2", "state": "pending", "payment_lane": "pay_first",
        "store_id": "S",
        "vertical": "restaurant",
        "customer_phone":  "+15035550100",
        "customer_name":   "Michael",
        "total_cents":     2500,
        "pos_object_id":   "",
    }

    with patch("app.services.bridge.pay_link.transactions") as mock_tx, \
         patch("app.services.bridge.pay_link.get_pos_adapter_for_store",
               new=AsyncMock(return_value=pos_adapter)), \
         patch("app.services.bridge.pay_link.fetch_order_items_for_tx",
               new=AsyncMock(return_value=[
                   {"name": "Combo", "variant_id": "v-99", "item_id": "i-99",
                    "price": 25.00, "quantity": 1},
               ])):

        mock_tx.get_transaction    = AsyncMock(return_value=fake_tx)
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock(side_effect=fake_advance)

        res = await settle_payment(transaction_id="tx-2")

    assert res["success"] is True
    assert res["status"]  == "paid"
    assert res["pos_object_id"] == "receipt-9001"
    # State machine traversed in order
    assert advance_calls == ["payment_sent", "paid", "fulfilled"]
    pos_adapter.create_pending.assert_awaited_once()
    pos_adapter.mark_paid.assert_awaited_once()
    mock_tx.set_pos_object_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_settle_payment_pay_first_pos_failure_stays_paid():
    """pay_first POS injection fails after payment lands. We do NOT roll back
    the payment — money is collected. Stay in PAID and surface a warning so
    reconciliation cron can retry.
    (결제 후 POS 실패 — PAID 유지, reconciliation으로 재시도)
    """
    from app.services.bridge.pay_link import settle_payment

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock(side_effect=RuntimeError("Loyverse 502"))
    pos_adapter.mark_paid      = AsyncMock()

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw["to_state"])
        return {"state": kw["to_state"]}

    fake_tx = {
        "id": "tx-3", "state": "pending", "payment_lane": "pay_first",
        "store_id": "S", "vertical": "restaurant",
        "customer_phone": "+15035550100", "customer_name": "Michael",
        "total_cents": 2500, "pos_object_id": "",
    }

    with patch("app.services.bridge.pay_link.transactions") as mock_tx, \
         patch("app.services.bridge.pay_link.get_pos_adapter_for_store",
               new=AsyncMock(return_value=pos_adapter)), \
         patch("app.services.bridge.pay_link.fetch_order_items_for_tx",
               new=AsyncMock(return_value=[
                   {"name": "Combo", "variant_id": "v", "item_id": "i",
                    "price": 25.00, "quantity": 1},
               ])):

        mock_tx.get_transaction    = AsyncMock(return_value=fake_tx)
        mock_tx.set_pos_object_id  = AsyncMock()
        mock_tx.advance_state      = AsyncMock(side_effect=fake_advance)

        res = await settle_payment(transaction_id="tx-3")

    # Payment went through but fulfillment is deferred
    assert res["success"] is True
    assert res["status"]  == "paid_pos_pending"
    # Walked to PAID but not FULFILLED
    assert "paid" in advance_calls
    assert "fulfilled" not in advance_calls


# ── fire_immediate lane: closes the loop ──────────────────────────────────────

@pytest.mark.asyncio
async def test_settle_payment_fire_immediate_advances_to_paid():
    """fire_immediate: receipt already exists from order time. Pay link
    transitions FIRED_UNPAID → PAID (no second POS call).
    (fire_immediate: 결제만 마감, POS 재호출 없음)
    """
    from app.services.bridge.pay_link import settle_payment

    pos_adapter = MagicMock()
    pos_adapter.create_pending = AsyncMock()
    pos_adapter.mark_paid      = AsyncMock()

    advance_calls: list = []

    async def fake_advance(**kw):
        advance_calls.append(kw["to_state"])
        return {"state": kw["to_state"]}

    fake_tx = {
        "id": "tx-4", "state": "fired_unpaid", "payment_lane": "fire_immediate",
        "store_id": "S", "vertical": "restaurant",
        "pos_object_id": "receipt-1042",
    }

    with patch("app.services.bridge.pay_link.transactions") as mock_tx, \
         patch("app.services.bridge.pay_link.get_pos_adapter_for_store",
               new=AsyncMock(return_value=pos_adapter)):

        mock_tx.get_transaction = AsyncMock(return_value=fake_tx)
        mock_tx.advance_state   = AsyncMock(side_effect=fake_advance)

        res = await settle_payment(transaction_id="tx-4")

    assert res["success"] is True
    assert res["status"]  == "paid"
    assert advance_calls  == ["paid"]   # single transition; no double POS
    pos_adapter.create_pending.assert_not_called()
