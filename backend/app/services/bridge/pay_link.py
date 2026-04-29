# Phase 2-B.1.9 — Pay link settlement flow
# (Phase 2-B.1.9 — 결제 링크 정산 흐름)
#
# settle_payment(transaction_id) is called by the pay link route when the
# customer taps the SMS link and the (mock) payment gateway confirms the
# charge succeeded. It walks the state machine to the appropriate terminal
# state for each lane.
#
# Why a separate module from flows.py: flows.py is the voice-side entry
# point; this module is the post-payment-side entry point. They share data
# (bridge_transactions row) but have very different mental models — separate
# files keep the audit trail readable when something goes wrong.

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.pos.factory import get_pos_adapter_for_store
from app.services.bridge.state_machine import State

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}
_REST = f"{settings.supabase_url}/rest/v1"


_TERMINAL_REJECT_STATES = {
    State.CANCELED,
    State.NO_SHOW,
    State.FAILED,
    State.REFUNDED,
}

_ALREADY_PAID_STATES = {
    State.PAID,
    State.FULFILLED,
}


async def fetch_order_items_for_tx(transaction_id: str) -> list[dict[str, Any]]:
    """Read bridge_transactions.items_json for the given tx.
    (저장된 items_json 조회)

    Returns [] when the row is missing or has no items recorded — caller
    is expected to handle the empty case (skip POS injection rather than
    inject an empty receipt).
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "id":     f"eq.{transaction_id}",
                "select": "items_json",
                "limit":  "1",
            },
        )
    if resp.status_code != 200:
        return []
    rows = resp.json() or []
    if not rows:
        return []
    items = rows[0].get("items_json")
    return items if isinstance(items, list) else []


async def settle_payment(*, transaction_id: str) -> dict[str, Any]:
    """Settle a payment for a bridge transaction. Lane-aware state walk.
    (트랜잭션 결제 정산 — lane별 상태 전이)

    Returns one of:
        {success: True,  status: 'paid'}                 — full happy path
        {success: True,  status: 'paid_pos_pending'}     — pay_first POS retry deferred
        {success: True,  status: 'already_paid'}         — idempotent re-tap
        {success: False, status: 'not_found'}            — bad link
        {success: False, status: 'terminal_state'}       — canceled / no_show
    """
    txn = await transactions.get_transaction(transaction_id)
    if not txn:
        return {"success": False, "status": "not_found"}

    state = txn.get("state")

    # ── Idempotency: already-paid is a happy path on a re-tap ────────────
    if state in _ALREADY_PAID_STATES:
        return {
            "success":       True,
            "status":        "already_paid",
            "transaction_id": txn["id"],
            "pos_object_id":  txn.get("pos_object_id", ""),
        }

    # ── Refusal: terminal write-off cannot be revived by the link ────────
    if state in _TERMINAL_REJECT_STATES:
        return {
            "success":       False,
            "status":        "terminal_state",
            "transaction_id": txn["id"],
            "from_state":    state,
        }

    lane     = txn.get("payment_lane")
    store_id = txn["store_id"]

    # ── fire_immediate lane: receipt already at the kitchen ──────────────
    # FIRED_UNPAID → PAID. Only the state transition runs; no POS call —
    # the receipt was injected at order time. mark_paid is called so the
    # POS write-back closes the loop (Loyverse no-ops mark_paid today).
    # (fire_immediate: state 전이만, POS 재호출 없음)
    if state == State.FIRED_UNPAID:
        adapter = await get_pos_adapter_for_store(store_id)
        await transactions.advance_state(
            transaction_id = transaction_id,
            to_state       = State.PAID,
            source         = "webhook",
            actor          = "pay_link:fire_immediate",
        )
        try:
            await adapter.mark_paid(
                vertical=txn.get("vertical", "restaurant"),
                object_id=txn.get("pos_object_id") or "",
            )
        except Exception as exc:
            # Non-fatal — adapter may simply not implement mark_paid yet
            # (Loyverse v1 is a no-op). Log and move on.
            log.warning("mark_paid skipped: %s", exc)
        return {
            "success":       True,
            "status":        "paid",
            "transaction_id": txn["id"],
            "pos_object_id":  txn.get("pos_object_id", ""),
            "lane":           lane,
        }

    # ── pay_first lane: full state walk ──────────────────────────────────
    # PENDING → PAYMENT_SENT → PAID → POS create_pending → backfill →
    # FULFILLED. POS failure after PAID stays in PAID (do not roll back
    # money) so reconciliation can retry the receipt write later.
    # (pay_first: 결제 후에야 POS 인젝션 — 실패해도 PAID 유지)
    await transactions.advance_state(
        transaction_id = transaction_id,
        to_state       = State.PAYMENT_SENT,
        source         = "webhook",
        actor          = "pay_link:pay_first",
    )
    await transactions.advance_state(
        transaction_id = transaction_id,
        to_state       = State.PAID,
        source         = "webhook",
        actor          = "pay_link:pay_first",
    )

    items = await fetch_order_items_for_tx(transaction_id)
    adapter = await get_pos_adapter_for_store(store_id)
    try:
        pos_object_id = await adapter.create_pending(
            vertical=txn.get("vertical", "restaurant"),
            store_id=store_id,
            payload={
                "pos_object_type": "order",
                "items":           items,
                "customer_name":   txn.get("customer_name") or "",
                "customer_phone":  txn.get("customer_phone") or "",
                "bridge_tx_id":    transaction_id,
            },
        )
    except Exception as exc:
        log.error("pay_first POS injection deferred for tx=%s: %s",
                  transaction_id, exc)
        return {
            "success":       True,
            "status":        "paid_pos_pending",
            "transaction_id": txn["id"],
            "lane":           lane,
            "warning":        "POS write-back deferred to reconciliation",
        }

    # POS write-back happened — backfill + mark_paid + advance to FULFILLED
    await transactions.set_pos_object_id(transaction_id, pos_object_id)
    try:
        await adapter.mark_paid(
            vertical=txn.get("vertical", "restaurant"),
            object_id=pos_object_id,
        )
    except Exception as exc:
        log.warning("mark_paid skipped: %s", exc)

    await transactions.advance_state(
        transaction_id = transaction_id,
        to_state       = State.FULFILLED,
        source         = "webhook",
        actor          = "pay_link:pay_first",
    )

    return {
        "success":       True,
        "status":        "paid",
        "transaction_id": txn["id"],
        "pos_object_id":  pos_object_id,
        "lane":           lane,
    }
