# Bridge Server — high-level transaction flows (vertical-agnostic orchestration)
# (Bridge Server — 고수준 트랜잭션 흐름: 버티컬 무관 오케스트레이션)
#
# This module is the front door of the Bridge Server. Each flow function:
#   1. Validates inbound args
#   2. Normalizes inputs (phone E.164, date+time → ISO 8601)
#   3. Creates bridge_transaction (pending state)
#   4. Calls POS adapter to create the pending POS object
#   5. Calls payment adapter to create a session (NoOp gateway today, Maverick later)
#   6. Walks state machine through transitions, each writing audit events
#   7. On payment success, calls POS adapter to mark_paid (write-back)
#   8. Returns a structured result for the caller (voice_websocket → Gemini tool_response)
#
# Key design property: the orchestration code does NOT know which adapter is wired.
# When Maverick lands, only the factory (payments/factory.py) changes; this file is
# untouched. Same when Quantic POS lands.

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.payments.factory import get_payment_adapter
from app.services.bridge.pos.supabase import SupabasePOSAdapter
from app.services.bridge.state_machine import State
from app.skills.scheduler.reservation import (
    combine_date_time,
    format_date_human,
    format_time_12h,
    normalize_phone_us,
    validate_reservation_args,
)

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


# ── Adapter factory hooks (mockable in tests) ─────────────────────────────────

def get_pos_adapter():
    """Return the POS adapter for the current deployment.
    (현재 배포에 맞는 POS 어댑터 반환)

    Today: SupabasePOSAdapter (own tables).
    Future: QuanticPOSAdapter for restaurants once white-label closes.
    Patchable in tests.
    """
    return SupabasePOSAdapter()


# ── Idempotency probe ────────────────────────────────────────────────────────
# Phase 2-A.5 had this protection inside insert_reservation. Phase 2-B routed
# through the Bridge adapters, which dropped the probe — exposed by 8th call
# (3 duplicate transactions for one user "Yes"). Probe is now Bridge-level so
# every vertical inherits it, not just reservations.
# (8차 통화에서 노출된 회귀 — Bridge 레벨로 끌어올려 모든 버티컬에 적용)

async def _find_recent_duplicate(
    *,
    store_id:        str,
    customer_phone:  str,
    pos_object_type: str,
    unique_key:      str,           # vertical-specific dedup key (reservation_time / scheduled_at / ...)
    window_minutes:  int = 5,
) -> Optional[dict[str, Any]]:
    """Probe bridge_transactions for a recent successful match.
    (최근 성공한 매칭 조회)

    A "match" is: same store + customer_phone + pos_object_type + state in
    {paid, fulfilled} within the time window. Returns the row dict if found,
    None otherwise. Excludes failed/canceled — user is allowed to retry after
    a real failure.
    """
    since_iso = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":        f"eq.{store_id}",
                "customer_phone":  f"eq.{customer_phone}",
                "pos_object_type": f"eq.{pos_object_type}",
                "state":           "in.(paid,fulfilled)",
                "created_at":      f"gte.{since_iso}",
                "select":          "id,pos_object_id,state,created_at",
                "order":           "created_at.desc",
                "limit":           "1",
            },
        )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    return rows[0] if rows else None


# ── Restaurant: create_reservation ────────────────────────────────────────────

async def create_reservation(
    *,
    store_id:      str,
    args:          dict[str, Any],
    call_log_id:   Optional[str] = None,
    deposit_cents: int = 0,
) -> dict[str, Any]:
    """Top-level reservation flow for the restaurant vertical.
    (식당 버티컬 예약 최상위 흐름)

    args: Gemini tool args (must include user_explicit_confirmation, customer_name,
          customer_phone, reservation_date, reservation_time, party_size).
    deposit_cents: 0 today (free reservation). When deposits become standard, the
          caller passes the deposit amount; the gateway is then required.

    Returns:
        {success, transaction_id, pos_object_id, state, message, [error]}
    """
    # 1. Validate args (anti-phantom-booking gate)
    ok, err = validate_reservation_args(args)
    if not ok:
        return {"success": False, "error": err}

    # 2. Normalize
    phone_e164 = normalize_phone_us(args["customer_phone"])
    res_iso    = combine_date_time(args["reservation_date"], args["reservation_time"])
    customer   = args["customer_name"]
    party_size = int(args["party_size"])

    # 2b. Idempotency probe — short-circuit if same store+phone+reservation already
    # succeeded in last 5 min. Spec §3.1; regression-locked by 8th-call duplicates.
    # (idempotency 검사 — 5분 내 동일 예약 있으면 단축 회로)
    existing = await _find_recent_duplicate(
        store_id        = store_id,
        customer_phone  = phone_e164,
        pos_object_type = "reservation",
        unique_key      = res_iso,
    )
    if existing:
        log.info("Idempotent hit: reusing transaction=%s pos_object_id=%s",
                 existing["id"], existing.get("pos_object_id"))
        return {
            "success":        True,
            "transaction_id": existing["id"],
            "pos_object_id":  existing.get("pos_object_id", ""),
            "state":          existing.get("state", State.FULFILLED),
            "message":        _success_message(args, customer, party_size),
            "idempotent":     True,
        }

    # 3. Open the bridge transaction (state=pending, audit row written)
    txn = await transactions.create_transaction(
        store_id        = store_id,
        vertical        = "restaurant",
        pos_object_type = "reservation",
        pos_object_id   = "",          # filled after POS create
        customer_phone  = phone_e164,
        customer_name   = customer,
        total_cents     = deposit_cents,
        call_log_id     = call_log_id,
        actor           = "tool_call:create_reservation",
    )
    txn_id = txn["id"]

    # 4. POS pending object
    pos = get_pos_adapter()
    try:
        pos_object_id = await pos.create_pending(
            vertical="restaurant",
            store_id=store_id,
            payload={
                "customer_name":    customer,
                "customer_phone":   phone_e164,
                "party_size":       party_size,
                "reservation_time": res_iso,
                "notes":            args.get("notes", ""),
            },
        )
    except Exception as exc:
        log.error("POS create_pending failed: %s", exc)
        await transactions.advance_state(
            transaction_id=txn_id,
            to_state=State.FAILED,
            source="voice",
            actor="tool_call:create_reservation",
        )
        return {"success": False, "error": f"POS create failed: {exc}"}

    # 4b. Backfill bridge_transaction.pos_object_id (Bridge ↔ POS link)
    await transactions.set_pos_object_id(txn_id, pos_object_id)

    # 5. Payment session (NoOp today; Maverick later)
    payments = get_payment_adapter()
    session = await payments.create_session(
        amount_cents=deposit_cents,
        transaction_id=txn_id,
        purpose="full" if deposit_cents == 0 else "deposit",
    )

    # 6. Advance state: pending → payment_sent
    await transactions.advance_state(
        transaction_id=txn_id,
        to_state=State.PAYMENT_SENT,
        source="voice",
        actor="payment_adapter:create_session",
    )

    if not session.get("paid"):
        # Gateway could not collect (NoOp + non-zero amount, or real gateway failure).
        # Caller is responsible for surfacing the error to the customer.
        reason = session.get("reason", "payment_session_not_paid")
        await transactions.advance_state(
            transaction_id=txn_id,
            to_state=State.FAILED,
            source="voice",
            actor="payment_adapter",
        )
        return {
            "success": False,
            "transaction_id": txn_id,
            "pos_object_id":  pos_object_id,
            "error": f"payment gateway not configured ({reason})",
        }

    # 7. Payment succeeded → advance payment_sent → paid → fulfilled
    await transactions.advance_state(
        transaction_id=txn_id,
        to_state=State.PAID,
        source="voice" if not payments.is_enabled() else "webhook",
        actor="payment_adapter:succeeded",
    )

    # 8. POS write-back (mark confirmed/scheduled)
    try:
        await pos.mark_paid(vertical="restaurant", object_id=pos_object_id)
    except Exception as exc:
        log.error("POS mark_paid failed (state=paid but POS not updated): %s", exc)
        # Stay in 'paid' state; reconciliation cron will retry.
        return {
            "success": True,
            "transaction_id": txn_id,
            "pos_object_id":  pos_object_id,
            "state":          State.PAID,
            "warning":        "POS write-back deferred to reconciliation",
            "message": _success_message(args, customer, party_size),
        }

    # 9. Final transition → fulfilled
    await transactions.advance_state(
        transaction_id=txn_id,
        to_state=State.FULFILLED,
        source="voice",
        actor="pos_adapter:mark_paid",
    )

    return {
        "success":        True,
        "transaction_id": txn_id,
        "pos_object_id":  pos_object_id,
        "state":          State.FULFILLED,
        "message":        _success_message(args, customer, party_size),
    }


def _success_message(args: dict[str, Any], customer: str, party_size: int) -> str:
    """Customer-facing confirmation string spoken back via voice / sent via SMS.
    (음성/SMS로 고객에게 전달되는 확인 메시지)
    """
    return (
        f"Reservation confirmed for {customer}, "
        f"party of {party_size}, on {format_date_human(args['reservation_date'])} "
        f"at {format_time_12h(args['reservation_time'])}."
    )
