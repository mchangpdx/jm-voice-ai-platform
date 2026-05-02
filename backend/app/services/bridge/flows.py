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
from app.services.bridge.pos.factory import get_pos_adapter_for_store
from app.services.bridge.pos.supabase import SupabasePOSAdapter
from app.services.bridge.state_machine import State
from app.services.menu.match import resolve_items_against_menu          # Phase 2-B.1.8
from app.services.policy.order_lanes import decide_lane                 # Phase 2-B.1.7b
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
    """Probe bridge_transactions for a recent in-flight or completed match.
    (최근 진행중/성공 매칭 조회 — 동일 통화 5번 호출 collapse 핵심)

    A "match" is: same store + customer_phone + pos_object_type within the
    time window, in any non-failure state. Returns the row dict if found.
    Excludes failed/canceled/refunded/no_show — those mean the user is
    allowed to retry. Includes pending/payment_sent/fired_unpaid/paid/
    fulfilled — those mean an active or completed order/reservation
    already exists, so a duplicate must short-circuit to it.

    Why this list (not 'state in (paid,fulfilled)' alone): pay_first orders
    sit in 'pending' until the customer taps the SMS link. If we only
    matched paid/fulfilled, every spoken yes during a single call would
    create a new transaction row — exactly the bug we hit on call
    call_d59f895b… (5 dup pending rows for one Yeah-loop).
    """
    since_iso = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    # PostgREST has no "not.in.(...)" via params shorthand, so we list the
    # in-scope states explicitly. Order matters: most-likely state first
    # gives the planner a small win on the customer_phone+state index.
    # (PostgREST 호환을 위해 in-list 명시)
    in_flight_or_done = "pending,payment_sent,fired_unpaid,paid,fulfilled"
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":        f"eq.{store_id}",
                "customer_phone":  f"eq.{customer_phone}",
                "pos_object_type": f"eq.{pos_object_type}",
                "state":           f"in.({in_flight_or_done})",
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


# ── Restaurant: create_order (Phase 2-B.1.8) ──────────────────────────────────
# Voice Engine entry point for food/drink orders. Lane decision (fire_immediate
# vs pay_first) lives in app.services.policy.order_lanes.decide_lane and is
# applied here. Pay link wiring is the responsibility of Phase 2-B.1.9.

async def create_order(
    *,
    store_id:    str,
    args:        dict[str, Any],
    call_log_id: Optional[str] = None,
) -> dict[str, Any]:
    """Top-level order flow for the restaurant vertical.
    (식당 버티컬 주문 최상위 흐름)

    args keys:
        items:           [{name, quantity}, ...]   required
        customer_phone:  E.164 string              required (pay link target)
        customer_name:   optional human name
        notes:           optional free text

    Returns a dict the Voice Engine consumes to choose its TTS reply:
        success, status, lane, total_cents, state, transaction_id, pos_object_id,
        items, ai_script_hint ('fire_immediate'|'pay_first'|'rejected')
    """
    # ── 1. Validate ───────────────────────────────────────────────────────
    # Every early return ships an ai_script_hint so the voice handler can pick
    # a customer-facing line via ORDER_SCRIPT_BY_HINT — without it the agent
    # falls through to a generic "team member will follow up" line.
    # (early return마다 ai_script_hint 동봉 — 음성 멘트 일관성)
    # Gemini SDK returns function-call args as proto RepeatedComposite,
    # not Python list, so isinstance(_, list) returns False even when
    # the model passed a populated items array. Coerce to a plain list
    # of dicts before any downstream validation or catalog resolution.
    # (Gemini args는 RepeatedComposite — list 변환 후 검증)
    raw_items_proto = args.get("items") or []
    raw_items: list = []
    try:
        for it in raw_items_proto:
            raw_items.append(dict(it) if not isinstance(it, dict) else it)
    except TypeError:
        raw_items = []

    if len(raw_items) == 0:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           "items list is empty — no order to place",
                "ai_script_hint":  "validation_failed"}

    if not args.get("customer_phone"):
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           "customer_phone is required to send a payment link",
                "ai_script_hint":  "validation_failed"}

    # Anti-hallucination guard: Gemini fills required fields with placeholders
    # when the customer hasn't actually provided them, e.g. phone='+10000000000'
    # or name='Anonymous'. Reject those so the model has to ask the customer
    # for real values instead of writing junk into bridge_transactions.
    # (Gemini 환각 차단 — placeholder phone/name 거부)
    raw_phone   = (args.get("customer_phone") or "").strip()
    raw_name    = (args.get("customer_name")  or "").strip()
    digits_only = "".join(c for c in raw_phone if c.isdigit())

    _PLACEHOLDER_DIGITS = {
        "10000000000", "0000000000", "1111111111", "5555555555",
        "1234567890",  "12345678901","9999999999", "9876543210",
    }
    _PLACEHOLDER_NAMES = {
        "anonymous", "customer", "guest", "n/a", "na", "unknown",
        "no name",   "test",     "tester","caller", "user",
    }
    if digits_only in _PLACEHOLDER_DIGITS or len(digits_only) < 10:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           f"customer_phone looks invalid: {raw_phone!r}",
                "ai_script_hint":  "validation_failed"}
    # Reject the name when:
    #   (a) it is empty,
    #   (b) the whole string matches a placeholder (e.g. 'Anonymous'),
    #   (c) ANY whitespace-separated token matches a placeholder
    #       (e.g. 'Unknown Customer' → tokens ['unknown','customer'] →
    #       both in set → reject). Live observed in call_838fa514…
    #       where 'Unknown Customer' slipped past the exact-match check.
    # We explicitly do NOT use substring matching — that would reject
    # legitimate names that happen to contain a placeholder substring
    # ('Carmen' contains 'arme' but not the token 'guest').
    # (이름 placeholder 차단 강화 — 토큰 단위 매칭으로 'Unknown Customer' 차단)
    name_lc = raw_name.lower()
    name_tokens = [t for t in name_lc.split() if t]
    if (
        not raw_name
        or name_lc in _PLACEHOLDER_NAMES
        or any(tok in _PLACEHOLDER_NAMES for tok in name_tokens)
    ):
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           f"customer_name looks invalid: {raw_name!r}",
                "ai_script_hint":  "validation_failed"}

    phone_e164 = normalize_phone_us(raw_phone)
    customer   = raw_name

    # ── 2. Resolve items against menu_items (catalog enrichment) ──────────
    resolved = await resolve_items_against_menu(
        store_id=store_id,
        items=raw_items,
    )

    # ── 3. Refusal gates: unknown items first, then sold_out ──────────────
    unknown = [r for r in resolved if r.get("missing")]
    if unknown:
        return {
            "success":         False,
            "status":          "rejected",
            "reason":          "unknown_item",
            "unavailable":     unknown,
            "ai_script_hint":  "rejected",
        }

    sold_out = [r for r in resolved if not r.get("sufficient_stock", True)]
    if sold_out:
        return {
            "success":         False,
            "status":          "rejected",
            "reason":          "sold_out",
            "unavailable":     sold_out,
            "ai_script_hint":  "rejected",
        }

    # ── 4. Total — derived from real catalog prices, not from caller args ─
    total_cents = sum(
        int(round(float(r["price"]) * 100)) * int(r["quantity"])
        for r in resolved
    )

    # ── 5. Idempotency probe — same store + phone + 'order' in 5-min window
    # short-circuits to the existing transaction. Mirrors the reservation flow.
    # (5분 윈도우 idempotency — 예약 흐름과 동일 패턴)
    existing = await _find_recent_duplicate(
        store_id        = store_id,
        customer_phone  = phone_e164,
        pos_object_type = "order",
        unique_key      = "",       # orders dedup on store+phone+type only
    )
    if existing:
        log.info("Idempotent order hit: tx=%s pos_object_id=%s",
                 existing["id"], existing.get("pos_object_id"))
        # Pull lane/total/items from the existing row so this branch returns
        # the same shape as the non-idempotent success branches below
        # (lines ~563 and ~578). Without these, voice_websocket logged
        # 'lane=None' on every idempotent re-hit and the modify-cycle
        # session snapshot ('last_order_items', 'last_order_total') saw
        # None, breaking the closing-summary recap line. Live: call_770ec863…
        # 22:48:26 created the symptom — the script still fired correctly
        # via ai_script_hint, but downstream debug + recap broke.
        # (idempotent return shape를 정상 분기와 일치 — lane/total/items 추가)
        return {
            "success":        True,
            "idempotent":     True,
            "transaction_id": existing["id"],
            "pos_object_id":  existing.get("pos_object_id", ""),
            "state":          existing.get("state", State.PENDING),
            "lane":           existing.get("payment_lane"),
            "total_cents":    int(existing.get("total_cents") or 0),
            "items":          existing.get("items_json") or [],
            "ai_script_hint": "fire_immediate"
                              if existing.get("state") == State.FIRED_UNPAID
                              else "pay_first",
        }

    # ── 6. Lane decision (policy engine) ─────────────────────────────────
    decision = await decide_lane(store_id=store_id, total_cents=total_cents)
    lane     = decision["lane"]    # 'fire_immediate' | 'pay_first'

    # ── 7. Open the bridge transaction with payment_lane + items recorded ─
    # items_json carries the resolved line items so the pay_link route can
    # replay them into Loyverse after the customer pays without re-querying
    # menu_items (price + variant could drift between order and payment).
    # (items_json — pay_link 시점에 메뉴 재조회 없이 영수증 재구성 가능)
    txn = await transactions.create_transaction(
        store_id        = store_id,
        vertical        = "restaurant",
        pos_object_type = "order",
        pos_object_id   = "",                    # backfilled after POS create
        customer_phone  = phone_e164,
        customer_name   = customer,
        total_cents     = total_cents,
        call_log_id     = call_log_id,
        actor           = "tool_call:create_order",
        payment_lane    = lane,
        items_json      = resolved,
    )
    txn_id = txn["id"]

    # ── 8. Lane branch ───────────────────────────────────────────────────
    if lane == "fire_immediate":
        # Try to inject into POS now; if the adapter raises, leave the
        # transaction in PENDING so an operator can recover. Critical
        # invariant: this branch must never raise out to the voice path.
        # (POS 실패 시 PENDING 유지 — 음성 경로 보호)
        adapter = await get_pos_adapter_for_store(store_id)
        try:
            pos_object_id = await adapter.create_pending(
                vertical="restaurant",
                store_id=store_id,
                payload={
                    "pos_object_type": "order",
                    "items":           resolved,
                    "customer_name":   customer,
                    "customer_phone":  phone_e164,
                    "bridge_tx_id":    txn_id,
                },
            )
        except Exception as exc:
            log.error("POS create_pending failed for tx=%s: %s", txn_id, exc)
            # Advance to FAILED so the idempotency probe in subsequent
            # turns excludes this row. Otherwise a PENDING tx stays
            # eligible for re-match and the next yes returns success=True
            # with a 'pay_first' script the customer never actually got
            # a link for. Audit row is written via advance_state.
            # (POS 실패 → FAILED 전이 — idempotency 거짓 성공 차단)
            try:
                await transactions.advance_state(
                    transaction_id = txn_id,
                    to_state       = State.FAILED,
                    source         = "voice",
                    actor          = "pos_adapter:create_pending_failed",
                    extra_fields   = {},
                )
            except Exception as inner:
                log.error("FAILED transition write also failed tx=%s: %s",
                          txn_id, inner)
            return {
                "success":        False,
                "transaction_id": txn_id,
                "lane":           lane,
                "state":          State.FAILED,
                "error":          f"POS injection failed: {exc}",
                "ai_script_hint": "pos_failure",
            }

        # POS receipt created. Backfill link, advance state, stamp fired_at.
        # The Loyverse side already booked revenue and decremented inventory;
        # if the bridge-side state UPDATE fails (e.g. CHECK constraint drift,
        # connectivity blip), we MUST NOT bubble the exception to the voice
        # layer — that would leave the customer in dead silence after the
        # kitchen already received the order. Treat the bridge-side advance
        # as best-effort: log + emit a recovery audit hint via _BRIDGE_DRIFT
        # so reconcile_pos_drift.py can fix the row offline. The customer
        # still gets the fire_immediate script, which is accurate (kitchen
        # has the order, pay link is sent).
        # (Loyverse는 이미 매출/재고 처리 — bridge UPDATE 실패해도 침묵 금지)
        try:
            await transactions.set_pos_object_id(txn_id, pos_object_id)
        except Exception as exc:
            log.error("set_pos_object_id failed tx=%s pos_id=%s: %s — "
                      "Loyverse has the receipt; bridge row is drifted, "
                      "needs reconcile.", txn_id, pos_object_id, exc)
        try:
            await transactions.advance_state(
                transaction_id = txn_id,
                to_state       = State.FIRED_UNPAID,
                source         = "voice",
                actor          = "tool_call:create_order",
                extra_fields   = {"fired_at": datetime.now(timezone.utc).isoformat()},
            )
        except Exception as exc:
            log.error("advance_state(FIRED_UNPAID) failed tx=%s: %s — "
                      "Loyverse receipt %s already exists; needs reconcile.",
                      txn_id, exc, pos_object_id)

        return {
            "success":         True,
            "transaction_id":  txn_id,
            "pos_object_id":   pos_object_id,
            "lane":            lane,
            "state":           State.FIRED_UNPAID,
            "total_cents":     total_cents,
            "items":           resolved,
            "ai_script_hint":  "fire_immediate",
        }

    # ── pay_first: leave the transaction in PENDING. Phase 2-B.1.9 pay link
    # route picks it up on customer click → advances PAYMENT_SENT → PAID and
    # injects to POS. We don't call the POS adapter here.
    # (pay_first: PENDING 유지 — pay link route가 결제 후 POS 인젝션)
    return {
        "success":         True,
        "transaction_id":  txn_id,
        "pos_object_id":   "",
        "lane":            lane,
        "state":           State.PENDING,
        "total_cents":     total_cents,
        "items":           resolved,
        "ai_script_hint":  "pay_first",
    }


# ── B1: modify_order (Phase 2-C) ──────────────────────────────────────────────
# Per spec backend/docs/specs/B1_modify_order.md.
# Replaces items_json + total_cents on the most-recent in-flight order
# for a given (store_id, caller_phone). Lifecycle state is invariant
# under modification; an 'items_modified' audit row is appended.
# (B1 — 결제 전 in-flight 주문의 items 교체. state 불변, audit row 추가)


async def _find_modifiable_order(
    *,
    store_id:           str,
    customer_phone:     str,
    window_minutes:     int = 5,
) -> Optional[dict[str, Any]]:
    """Locate the single most-recent in-flight order for this caller.
    (이 caller의 최근 in-flight 주문 1건 조회 — modify 대상 식별)

    State filter widened to also include FIRED_UNPAID. PENDING and
    PAYMENT_SENT are the truly modifiable states — items are still
    editable end-to-end. FIRED_UNPAID is included only so the caller
    (modify_order at the order_too_late branch) can return a precise
    'modify_too_late' script ('The kitchen has already started that
    order…') instead of the misleading 'no_order_to_modify' line.
    PAID and FULFILLED stay excluded — those calls are settled
    business and should not surface as an active in-flight order.
    Returns full row including items_json + total_cents so the caller
    can build a 'before' snapshot for the audit payload. Live:
    call_6b935ab0 16:05 — small order routed fire_immediate, transitioned
    to FIRED_UNPAID, customer's modify attempt landed on no_order_to_modify
    instead of the order_too_late explanation.
    (fired_unpaid 포함 — modify_too_late 정확 안내용; PENDING/PAYMENT_SENT는 그대로 modify 가능)
    """
    since_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":        f"eq.{store_id}",
                "customer_phone":  f"eq.{customer_phone}",
                "pos_object_type": "eq.order",
                "state":           "in.(pending,payment_sent,fired_unpaid)",
                "created_at":      f"gte.{since_iso}",
                "select":          "id,store_id,vertical,pos_object_type,"
                                   "pos_object_id,customer_phone,customer_name,"
                                   "state,payment_lane,total_cents,items_json,"
                                   "created_at,updated_at",
                "order":           "created_at.desc",
                "limit":           "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_find_modifiable_order %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def modify_order(
    *,
    store_id:          str,
    args:              dict[str, Any],
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Update the items on an in-flight order.
    (in-flight 주문의 items 교체 — Phase 2-C.B1)

    args (Gemini tool args) carries:
        items: list[{name, quantity}]   required, replaces current list
        notes: str                      optional, ignored for now

    caller_phone_e164 is the carrier-authenticated phone — it's how we
    locate the target transaction and match its customer_phone column.

    Returns a dict shaped like create_order's return so the Voice Engine
    handler can pick a script via ORDER_SCRIPT_BY_HINT / dedicated
    MODIFY_ORDER_SCRIPT_BY_HINT.
    """
    # 1. Coerce items off Gemini's proto.RepeatedComposite into a list of
    #    plain dicts (same trick as create_order — isinstance(_, list)
    #    fails on the proto type).
    raw_items_proto = args.get("items") or []
    raw_items: list = []
    try:
        for it in raw_items_proto:
            raw_items.append(dict(it) if not isinstance(it, dict) else it)
    except TypeError:
        raw_items = []

    if len(raw_items) == 0:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           "items list is empty — nothing to modify",
                "ai_script_hint":  "validation_failed"}

    # 2. Locate the target.
    target = await _find_modifiable_order(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )
    if not target:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "no_order_to_modify",
                "error":           "no in-flight order for this caller",
                "ai_script_hint":  "modify_no_target"}

    # 3. State guard. We only allow PENDING + PAYMENT_SENT here —
    #    anything else means the kitchen has fired or the customer has
    #    paid, both of which take modification off the table.
    if target["state"] not in (State.PENDING, State.PAYMENT_SENT):
        return {"success":         False,
                "status":          "rejected",
                "reason":          "order_too_late",
                "transaction_id":  target["id"],
                "state":           target["state"],
                "ai_script_hint":  "modify_too_late"}

    # 4. Resolve the new items against the live menu catalogue.
    resolved = await resolve_items_against_menu(
        store_id = store_id,
        items    = raw_items,
    )
    unknown = [r for r in resolved if r.get("missing")]
    if unknown:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "unknown_item",
                "unavailable":     unknown,
                "transaction_id":  target["id"],
                "ai_script_hint":  "rejected"}

    sold_out = [r for r in resolved if not r.get("sufficient_stock", True)]
    if sold_out:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "sold_out",
                "unavailable":     sold_out,
                "transaction_id":  target["id"],
                "ai_script_hint":  "rejected"}

    # 5. Compute the new total. Same arithmetic as create_order.
    new_total = sum(
        int(round(float(r["price"]) * 100)) * int(r["quantity"])
        for r in resolved
    )
    old_total = int(target.get("total_cents") or 0)

    # 5b. No-op short-circuit. If the resolved new items are identical
    # (same names + quantities, order-insensitive) to what's already on
    # the transaction, skip the UPDATE + audit row and return a dedicated
    # 'modify_noop' hint. Without this, the voice handler would re-enter
    # the recital cycle when Gemini reflexively re-fires modify_order on
    # benign acks ("okay", "thank you"), and the customer hears
    # "Updated — your total is $X.XX" repeated indefinitely (live
    # observed in call_feede2b9... — 4 modify calls, 0 actual changes).
    # (no-op 단축 회로 — 같은 items 반복 modify 호출은 무한 loop의 연료)
    def _items_key(items: list[dict]) -> list[tuple]:
        out: list[tuple] = []
        for it in items or []:
            nm  = (it.get("name") or "").strip().lower()
            qty = int(it.get("quantity") or 0)
            if nm and qty > 0:
                out.append((nm, qty))
        return sorted(out)

    old_key = _items_key(target.get("items_json") or [])
    new_key = _items_key(resolved)
    # log.warning so the line reaches /tmp/backend.log (log.info is
    # silenced under uvicorn's default logger config). One-liner per
    # modify call; harmless in volume given the cooldown gate above.
    # (warning 레벨 — log.info는 uvicorn에서 silent)
    log.warning("modify_order compare tx=%s old=%s new=%s match=%s",
                target["id"], old_key, new_key, old_key == new_key)
    if old_key == new_key:
        log.warning("modify_order no-op for tx=%s — items unchanged",
                    target["id"])
        return {
            "success":         True,
            "transaction_id":  target["id"],
            "lane":            target.get("payment_lane"),
            "state":           target["state"],
            "total_cents":     old_total,
            "items":           target.get("items_json") or [],
            "ai_script_hint":  "modify_noop",
        }

    # 6. Persist the content edit + audit row. Both go through
    #    transactions.* so the unit tests can patch the module.
    await transactions.update_items_and_total(
        transaction_id = target["id"],
        items          = resolved,
        total_cents    = new_total,
    )
    await transactions.append_audit(
        transaction_id = target["id"],
        event_type     = "items_modified",
        source         = "voice",
        actor          = "tool_call:modify_order",
        from_state     = target["state"],
        to_state       = target["state"],
        payload        = {
            "old_items": target.get("items_json") or [],
            "new_items": resolved,
            "old_total": old_total,
            "new_total": new_total,
            "call_log_id": call_log_id,
        },
    )

    return {
        "success":         True,
        "transaction_id":  target["id"],
        "lane":            target.get("payment_lane"),
        "state":           target["state"],
        "total_cents":     new_total,
        "items":           resolved,
        "ai_script_hint":  "modify_success",
    }
