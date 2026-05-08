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

import asyncio
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.services.bridge import transactions
from app.services.bridge.payments.factory import get_payment_adapter
from app.services.bridge.pos.factory import get_pos_adapter_for_store
from app.services.bridge.pos.supabase import SupabasePOSAdapter
from app.services.bridge.state_machine import State, can_transition
from app.services.menu.match import resolve_items_against_menu          # Phase 2-B.1.8
from app.services.policy.order_lanes import (                            # Phase 2-B.1.7b
    compute_lane_from_threshold,
    decide_lane,
    read_threshold_cents,
)
from app.skills.scheduler.reservation import (
    combine_date_time,
    format_date_human,
    format_time_12h,
    normalize_phone_us,
    validate_reservation_args,
)

# Module-level constant — placeholder name tokens that Gemini sometimes
# fills in when it has not actually captured a real customer name. Shared
# by the bridge validate-and-reject path AND the voice AUTO-FIRE recital
# builder (so the bot doesn't say "for unknown — is that right?"). Token
# matching only — substring matching would reject legitimate names that
# happen to contain a placeholder substring (e.g. 'Carmen' contains
# 'arme' but is not 'guest'). 'global' added 2026-05-03 after live
# observation in call_1df4b018.
# (placeholder 이름 토큰 — bridge + voice recital 양쪽에서 공유)
PLACEHOLDER_NAMES: frozenset[str] = frozenset({
    "anonymous", "customer", "guest",  "n/a",    "na",     "unknown",
    "no name",   "test",     "tester", "caller", "user",   "global",
})


def is_placeholder_name(raw_name: str) -> bool:
    """Return True if raw_name is empty, exactly a placeholder, or any
    word-token matches a placeholder.

    Token split treats every non-word character (whitespace AND
    punctuation like parentheses, quotes, hyphens, slashes) as a
    separator. Without this, Gemini's natural-language placeholders
    like '(customer name not provided)' bypass the guard because
    str.split() leaves '(customer' and 'provided)' as tokens that do
    not match the bare 'customer'/'provided' entries in the set. Live
    observed in call_0741f688 T9 — bot recited 'for (customer name not
    provided)' and bridge would have accepted the same value if Gemini
    had not been re-prompted for a real name on the next turn.

    Legitimate names with internal punctuation (O'Brien, Jean-Luc,
    Mary-Anne) are unaffected: their tokens (obrien, jean, luc, mary,
    anne) are not in PLACEHOLDER_NAMES.
    (placeholder 검사 — punctuation도 separator로 처리, '(customer ...)' 차단)
    """
    if not raw_name:
        return True
    name_lc = raw_name.strip().lower()
    if not name_lc:
        return True
    if name_lc in PLACEHOLDER_NAMES:
        return True
    tokens = [t for t in re.split(r"[\W_]+", name_lc) if t]
    if not tokens:
        return True
    if any(tok in PLACEHOLDER_NAMES for tok in tokens):
        return True
    # Reconstructed phrase catches compound entries like 'no name' wrapped
    # in punctuation ('<no name>', '[no-name]'). Single-token strings are
    # already handled above; this covers the multi-token compound case.
    # (compound placeholder — 토큰 재결합으로 'no name' 스타일 매칭)
    rejoined = " ".join(tokens)
    return rejoined in PLACEHOLDER_NAMES

log = logging.getLogger(__name__)

# Phase 7-A.D Wave A.3 — diagnostic timing log for create_order stage breakdown.
# Mirrors realtime_voice._dbg so per-stage timings appear inline with the call
# timeline in /tmp/realtime_debug.log. Temporary — remove once we identify the
# Loyverse latency root cause and ship a real fix.
# (create_order 단계별 측정용 임시 로그 — bottleneck 식별 후 제거 예정)
_PERF_LOG = "/tmp/realtime_debug.log"

def _perf(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} [perf] {msg}"
    try:
        print(line, file=sys.stderr, flush=True)
        with open(_PERF_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

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

async def _fetch_reservation_status(
    *,
    reservation_id: int,
) -> Optional[str]:
    """Fetch the current status of a single reservations row by id.
    (reservations 단일 row의 현재 상태 조회)

    Used by create_reservation's idempotency probe to verify that a
    matched bridge_transaction's linked reservation hasn't been
    cancelled out from under it. Returns the status string or None
    when the row is missing / probe fails.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/reservations",
            headers=_SUPABASE_HEADERS,
            params={
                "id":     f"eq.{reservation_id}",
                "select": "status",
                "limit":  "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_fetch_reservation_status %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    if not rows:
        return None
    return (rows[0].get("status") or "").strip() or None


async def _fetch_reservation(
    *,
    reservation_id: int,
) -> Optional[dict[str, Any]]:
    """Fetch a single reservations row by id.
    (reservations 단일 row 조회 — name/party/time까지 포함)

    Used by create_reservation's idempotent return path so the
    customer-facing success message reflects the ACTUAL booking (Issue
    Π fix), not the new tool args that may differ from what's stored.
    Returns None when the row is missing / probe fails so callers can
    fall back gracefully.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/reservations",
            headers=_SUPABASE_HEADERS,
            params={
                "id":     f"eq.{reservation_id}",
                "select": "id,customer_name,customer_phone,party_size,"
                          "reservation_time,status,notes",
                "limit":  "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_fetch_reservation %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


def _success_message_from_row(row: dict[str, Any]) -> str:
    """Build the customer-facing confirmation string from an existing
    reservations row (source of truth) instead of from new tool args.
    (실제 DB row에서 confirmation 멘트 생성 — idempotent return 시 사용)

    Used by the idempotent return path so the spoken confirmation
    matches what's actually in the DB (Issue Π fix from
    call_ebdc036d11951a04336d44c8856 T13). Falls back to a minimal
    message when the row is missing required fields.
    """
    customer = (row.get("customer_name") or "").strip() or "you"
    try:
        party = int(row.get("party_size") or 0)
    except (TypeError, ValueError):
        party = 0
    raw_iso = row.get("reservation_time") or ""
    try:
        dt = datetime.fromisoformat(raw_iso.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        date_str = local.strftime("%A, %B %-d")
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        time_str = f"{hour}:{local.minute:02d} {ampm}"
        return (f"Reservation confirmed for {customer}, "
                f"party of {party}, on {date_str} at {time_str}.")
    except Exception:
        return f"Reservation confirmed for {customer}, party of {party}."


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
        # Issue Ω fix — verify the linked reservation is still 'confirmed'
        # before honoring the idempotency hit. cancel_reservation can flip
        # reservations.status to 'cancelled' while bridge_transactions.state
        # stays 'fulfilled' (state_machine has no FULFILLED→CANCELED edge).
        # Without this guard, a second make_reservation in the same call
        # silently dedupes to the cancelled tx and never inserts a new
        # reservations row. Live observed in call_bd9ad08677aecaefe028934ca58
        # T23 (2026-05-02 12:40 PT) — Michael's reservation was reported
        # confirmed but never persisted; T28 cancel then targeted a stale
        # leftover row instead of Michael's.
        # (취소된 예약의 idempotency hit 회피 — bridge_transactions.state는
        #  fulfilled로 남지만 reservations.status가 cancelled면 신규로 진행)
        pos_obj_id_str = (existing.get("pos_object_id") or "").strip()
        try:
            pos_obj_id = int(pos_obj_id_str) if pos_obj_id_str else None
        except ValueError:
            pos_obj_id = None
        linked_row: Optional[dict[str, Any]] = None
        if pos_obj_id is not None:
            linked_status = await _fetch_reservation_status(reservation_id=pos_obj_id)
            if linked_status is None or linked_status.lower() != "confirmed":
                log.info("Idempotency bypass — bridge_tx=%s linked reservation %s status=%s",
                         existing["id"], pos_obj_id, linked_status)
                existing = None
            else:
                # Issue Π fix — fetch the full row so the success message
                # reflects what's ACTUALLY booked, not the new tool args
                # which may differ (live: call_ebdc036d T13 — Gemini retried
                # with different name/party/time and the bot read those out
                # as if confirmed, while DB row was untouched).
                # (실제 DB row 데이터로 멘트 빌드 — args와 다르면 args가 거짓)
                linked_row = await _fetch_reservation(reservation_id=pos_obj_id)
    if existing:
        log.info("Idempotent hit: reusing transaction=%s pos_object_id=%s",
                 existing["id"], existing.get("pos_object_id"))
        if linked_row:
            message = _success_message_from_row(linked_row)
        else:
            # Defensive — row fetch failed (network blip / race). Fall back
            # to the args-based message so the call doesn't go silent.
            # (row fetch 실패 시 args fallback — 무음 방지)
            message = _success_message(args, customer, party_size)
        return {
            "success":        True,
            "transaction_id": existing["id"],
            "pos_object_id":  existing.get("pos_object_id", ""),
            "state":          existing.get("state", State.FULFILLED),
            "message":        message,
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

async def _fire_pos_async(
    *,
    store_id:    str,
    txn_id:      str,
    resolved:    list[dict[str, Any]],
    customer:    str,
    phone_e164:  str,
    t0_total:    float,
) -> None:
    """Background POS injection — Phase 7-A.D Wave A.3 Plan D.

    Decouples adapter.create_pending + set_pos_object_id + advance_state
    from the voice hot path. Caller (create_order fire_immediate branch)
    fires this via asyncio.create_task and returns to voice immediately;
    this coroutine then drives bridge_transactions to its terminal state
    (FIRED_UNPAID on success, FAILED on POS error) without blocking the
    customer's response. (background task — voice 응답 후 POS 실행)

    Failure semantics: any exception advances to FAILED so the broadened
    idempotency probe excludes the row on subsequent calls. Bridge-side
    state update failures are logged but not re-raised — by then the
    customer is gone from the call and the kitchen state (whatever it is)
    is now an operator concern. This coroutine MUST NOT raise into the
    asyncio loop — wrapping each step in try/except keeps the task quiet.
    (모든 예외는 흡수 — operator alert + daily reconcile로 복구)
    """
    _t2 = time.monotonic()
    try:
        adapter = await get_pos_adapter_for_store(store_id)
    except Exception as exc:
        log.error("POS adapter lookup failed (background) tx=%s: %s", txn_id, exc)
        try:
            await transactions.advance_state(
                transaction_id = txn_id,
                to_state       = State.FAILED,
                source         = "voice",
                actor          = "pos_adapter:lookup_failed_async",
                extra_fields   = {},
            )
        except Exception as inner:
            log.error("FAILED transition write also failed tx=%s: %s", txn_id, inner)
        return
    _perf(f"create_order adapter_lookup_done txid={txn_id[:8]} ms={(time.monotonic()-_t2)*1000:.0f}")

    _t3 = time.monotonic()
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
        _perf(f"create_order pos_create_done txid={txn_id[:8]} pos_id={pos_object_id} ms={(time.monotonic()-_t3)*1000:.0f}")
    except Exception as exc:
        log.error("POS create_pending failed (background) tx=%s: %s", txn_id, exc)
        try:
            await transactions.advance_state(
                transaction_id = txn_id,
                to_state       = State.FAILED,
                source         = "voice",
                actor          = "pos_adapter:create_pending_failed_async",
                extra_fields   = {},
            )
        except Exception as inner:
            log.error("FAILED transition write also failed tx=%s: %s", txn_id, inner)
        return

    _t4 = time.monotonic()
    try:
        await transactions.set_pos_object_id(txn_id, pos_object_id)
    except Exception as exc:
        log.error("set_pos_object_id failed (background) tx=%s pos_id=%s: %s — "
                  "Loyverse has the receipt; bridge row is drifted, needs reconcile.",
                  txn_id, pos_object_id, exc)
    _perf(f"create_order set_pos_id_done txid={txn_id[:8]} ms={(time.monotonic()-_t4)*1000:.0f}")

    _t5 = time.monotonic()
    try:
        await transactions.advance_state(
            transaction_id = txn_id,
            to_state       = State.FIRED_UNPAID,
            source         = "voice",
            actor          = "tool_call:create_order:async",
            extra_fields   = {"fired_at": datetime.now(timezone.utc).isoformat()},
        )
    except Exception as exc:
        log.error("advance_state(FIRED_UNPAID) failed (background) tx=%s: %s — "
                  "Loyverse receipt %s exists; needs reconcile.",
                  txn_id, exc, pos_object_id)
    _perf(f"create_order advance_state_done txid={txn_id[:8]} ms={(time.monotonic()-_t5)*1000:.0f} BG_TOTAL_ms={(time.monotonic()-t0_total)*1000:.0f}")


async def create_order(
    *,
    store_id:       str,
    args:           dict[str, Any],
    call_log_id:    Optional[str] = None,
    modifier_index: dict[tuple[str, str], dict[str, Any]] | None = None,
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
    if digits_only in _PLACEHOLDER_DIGITS or len(digits_only) < 10:
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           f"customer_phone looks invalid: {raw_phone!r}",
                "ai_script_hint":  "validation_failed"}
    # Reject the name when it is empty, the whole string matches a
    # placeholder, or ANY whitespace-separated token matches a
    # placeholder (e.g. 'Unknown Customer' → tokens ['unknown',
    # 'customer'] → both in set → reject). Live observed in
    # call_838fa514 where 'Unknown Customer' slipped past the
    # exact-match check. Module-level PLACEHOLDER_NAMES is shared
    # with voice_websocket recital builder so the bot doesn't say
    # "for unknown — is that right?" before this validate fires.
    # (이름 placeholder 차단 — voice recital과 공유, 토큰 단위)
    if is_placeholder_name(raw_name):
        return {"success":         False,
                "status":          "rejected",
                "reason":          "validation_failed",
                "error":           f"customer_name looks invalid: {raw_name!r}",
                "ai_script_hint":  "validation_failed"}

    phone_e164 = normalize_phone_us(raw_phone)
    customer   = raw_name

    # ── 2. Parallel reads — menu enrichment + idempotency probe + lane threshold ─
    # Wave A.3 Step 2: these three reads have no inter-dependencies before
    # the early-exit decision point, so asyncio.gather lets us pay max(latency)
    # instead of sum(latency). Combined with Step 1's modifier_index reuse,
    # the create_order hot path shrinks from ~9 sequential round-trips to
    # ~3 parallel + idempotent-short-circuit + 1 INSERT + 1 POS call.
    # (병렬 read — menu / 멱등성 / 정책 임계값 동시 호출. 의존성 없음)
    #
    # Note: when the idempotency probe hits (rare — same caller redials
    # within 5 min), the resolve + threshold work is wasted. The savings on
    # the common non-idempotent path far outweigh that occasional waste.
    _t0 = time.monotonic()  # Wave A.3 diag — stage breakdown
    resolved, existing, threshold_cents = await asyncio.gather(
        resolve_items_against_menu(
            store_id       = store_id,
            items          = raw_items,
            modifier_index = modifier_index,
        ),
        _find_recent_duplicate(
            store_id        = store_id,
            customer_phone  = phone_e164,
            pos_object_type = "order",
            unique_key      = "",   # orders dedup on store+phone+type only
        ),
        read_threshold_cents(store_id),
    )
    _perf(f"create_order gather_done ms={(time.monotonic()-_t0)*1000:.0f}")

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
    # Phase 7-A.C: prefer effective_price (base + Σ price_delta from
    # selected_modifiers) when present. Falls back to base `price` for legacy
    # lines that didn't go through the modifier resolver. Never trust the
    # caller-supplied price field.
    # (effective_price 우선 — modifier price_delta 반영. 미존재 시 base price)
    total_cents = sum(
        int(round(float(r.get("effective_price") or r["price"]) * 100))
        * int(r["quantity"])
        for r in resolved
    )

    # ── 5. Idempotency short-circuit (probe ran in step 2 above) ──────────
    # Mirrors the reservation flow — same store + phone + 'order' in a
    # 5-min window returns the existing transaction.
    # (5분 윈도우 idempotency — 예약 흐름과 동일 패턴)
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
    # threshold_cents was read in parallel (step 2). Apply the pure-compute
    # half here without paying another round-trip.
    # (정책 임계값은 step 2에서 read — 여기서는 순수 계산만)
    decision = compute_lane_from_threshold(
        threshold_cents = threshold_cents,
        total_cents     = total_cents,
    )
    lane     = decision["lane"]    # 'fire_immediate' | 'pay_first'

    # ── 7. Open the bridge transaction with payment_lane + items recorded ─
    # items_json carries the resolved line items so the pay_link route can
    # replay them into Loyverse after the customer pays without re-querying
    # menu_items (price + variant could drift between order and payment).
    # (items_json — pay_link 시점에 메뉴 재조회 없이 영수증 재구성 가능)
    # Wave A.3 B.1: persist customer_email so post-call audit can prove which
    # address the pay-link email reached. Live 2026-05-08: 10 of 11 sends went
    # to NATO-drift-corrupted addresses (cymeet/cyeet/cyeemt) and the DB row
    # had email=NULL — no way to recover the destination after log rotation.
    # Empty/missing strings normalize to None (column is nullable).
    # (이메일 NATO drift 감사용 — DB에 영속화)
    raw_email      = (args.get("customer_email") or "").strip()
    customer_email = raw_email or None

    _t1 = time.monotonic()
    txn = await transactions.create_transaction(
        store_id        = store_id,
        vertical        = "restaurant",
        pos_object_type = "order",
        pos_object_id   = "",                    # backfilled after POS create
        customer_phone  = phone_e164,
        customer_name   = customer,
        customer_email  = customer_email,
        total_cents     = total_cents,
        call_log_id     = call_log_id,
        actor           = "tool_call:create_order",
        payment_lane    = lane,
        items_json      = resolved,
    )
    txn_id = txn["id"]
    _perf(f"create_order tx_insert_done txid={txn_id[:8]} ms={(time.monotonic()-_t1)*1000:.0f}")

    # ── 8. Lane branch ───────────────────────────────────────────────────
    if lane == "fire_immediate":
        # Wave A.3 Plan D — POS create_pending + state advance run in a
        # background asyncio task so the voice handler can respond to the
        # caller in ~500ms instead of ~3000ms. Live measurement 2026-05-08:
        # adapter.create_pending alone took 2484ms of the 3029ms total.
        #
        # Trade-off: when this task fails, the bot has already told the
        # customer "placing your order now" — the FAILED bridge_transactions
        # row is the operator-side recovery signal (manager_alert + daily
        # reconcile). Loyverse failure is rare in practice (webhook freeze
        # pattern keeps the integration stable), so the latency win
        # dominates the false-confirmation risk.
        # (POS는 background task — voice 응답 6× 단축. 실패 시 FAILED state로 operator 복구)
        asyncio.create_task(_fire_pos_async(
            store_id    = store_id,
            txn_id      = txn_id,
            resolved    = resolved,
            customer    = customer,
            phone_e164  = phone_e164,
            t0_total    = _t0,
        ))
        _perf(f"create_order fire_async_dispatched txid={txn_id[:8]} TOTAL_ms={(time.monotonic()-_t0)*1000:.0f}")

        return {
            "success":         True,
            "transaction_id":  txn_id,
            # pos_object_id is "" here — the background task will backfill
            # it via set_pos_object_id once Loyverse responds. Voice handler
            # callers MUST NOT depend on this field being populated.
            "pos_object_id":   "",
            "lane":            lane,
            # State is PENDING at the moment of return — the advance to
            # FIRED_UNPAID happens in the background after POS confirms.
            "state":           State.PENDING,
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


# ── B2 cancel_order: settled-state probe (read-only) ──────────────────────────
# Sister probe to _find_modifiable_order. Used ONLY by cancel_order, and ONLY
# when the in-flight probe returned None — gives the bot a precise refusal
# line ('that order is already cancelled' / 'already paid, transferring to
# manager') instead of the generic 'no order to cancel'. Adds at most one
# extra HTTP round-trip on cancel attempts that miss; no extra cost on the
# happy path.
# (취소 의도지만 in-flight 없을 때만 호출 — 정확한 거절 멘트용)
async def _find_recent_settled_order(
    *,
    store_id:       str,
    customer_phone: str,
    window_minutes: int = 5,
) -> Optional[dict[str, Any]]:
    """Locate the single most-recent SETTLED order for this caller within
    the window. Settled = canceled / paid / fulfilled / refunded / no_show
    / failed. Returns None when nothing found.
    (terminal 상태의 최근 주문 1건 조회 — cancel 시 정확 안내용)
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
                "state":           "in.(canceled,paid,fulfilled,refunded,no_show,failed)",
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
        log.warning("_find_recent_settled_order %s: %s",
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
    modifier_index:    dict[tuple[str, str], dict[str, Any]] | None = None,
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
    # Wave A.3: pre-loaded modifier_index from realtime_voice (same call) is
    # forwarded so the modify path also skips the modifier REST round-trip.
    # (modify 경로도 사전 로드된 modifier_index 사용 — REST 우회)
    resolved = await resolve_items_against_menu(
        store_id       = store_id,
        items          = raw_items,
        modifier_index = modifier_index,
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

    # 5. Compute the new total. Same arithmetic as create_order — prefer
    # effective_price (base + modifier delta) over base price; fall back to
    # base for legacy items without modifier resolution. (Phase 7-A.D)
    # (effective_price 우선 — modifier 변경 시 정확한 새 total)
    new_total = sum(
        int(round(float(r.get("effective_price") or r["price"]) * 100))
        * int(r["quantity"])
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
        # Phase 7-A.D — include sorted modifier signature in the key so a
        # genuine modifier swap (e.g. oat milk → almond milk) is NOT
        # collapsed to no_op. Without this guard the customer's mid-call
        # change would be silently discarded.
        # (modifier 시그니처 포함 — milk swap이 no_op로 처리되는 것 차단)
        out: list[tuple] = []
        for it in items or []:
            nm  = (it.get("name") or "").strip().lower()
            qty = int(it.get("quantity") or 0)
            mods = sorted(
                (str(m.get("group", "")), str(m.get("option", "")))
                for m in (it.get("selected_modifiers") or [])
                if isinstance(m, dict)
            )
            if nm and qty > 0:
                out.append((nm, qty, tuple(mods)))
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


# ── B2: cancel_order (Phase 2-C.2) ────────────────────────────────────────────
# Per spec backend/docs/specs/B2_cancel_order.md.
# Transitions the most-recent in-flight transaction (PENDING / PAYMENT_SENT /
# FIRED_UNPAID) for a given (store_id, caller_phone) to CANCELED, writes one
# state_transition audit row via transactions.advance_state, and returns a
# result dict for the Voice Engine. Items / total / lane preserved (we keep
# the historical record). Pay link route refuses payment for terminal states
# already (pay_link.py:84 short-circuit), so no extra cleanup needed there.
# Live: call_faba29762 — without this tool the bot hallucinated 'I've gone
# ahead and cancelled that for you' on a still-live FIRED_UNPAID order.
# (B2 — 결제 전 또는 fired_unpaid 주문 취소. 키친 통보는 V1 스크립트로 안내, V2에서 Loyverse void)


async def cancel_order(
    *,
    store_id:          str,
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Cancel an in-flight pickup order.
    (in-flight 주문 취소 — Phase 2-C.B2)

    No args from Gemini beyond user_explicit_confirmation — the order is
    located via caller-id, and items/phone are not needed (cancel operates
    on the transaction as a whole). Returns a dict the Voice Engine
    consumes to choose its TTS reply via CANCEL_ORDER_SCRIPT_BY_HINT.
    """
    # 1. Locate the in-flight target (PENDING / PAYMENT_SENT / FIRED_UNPAID).
    target = await _find_modifiable_order(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )

    # 2. Miss — fall back to settled probe so the customer hears a precise
    #    refusal instead of the generic 'no order to cancel'.
    if not target:
        settled = await _find_recent_settled_order(
            store_id       = store_id,
            customer_phone = caller_phone_e164,
        )
        if settled:
            sstate = settled.get("state")
            if sstate == State.CANCELED:
                return {
                    "success":         False,
                    "transaction_id":  settled.get("id"),
                    "state":           sstate,
                    "reason":          "cancel_already_canceled",
                    "ai_script_hint":  "cancel_already_canceled",
                }
            if sstate in (State.PAID, State.FULFILLED, State.REFUNDED, State.NO_SHOW):
                return {
                    "success":         False,
                    "transaction_id":  settled.get("id"),
                    "state":           sstate,
                    "reason":          "cancel_already_paid",
                    "ai_script_hint":  "cancel_already_paid",
                }
            # FAILED or any other terminal: fall through to no_target.
        return {
            "success":         False,
            "reason":          "cancel_no_target",
            "ai_script_hint":  "cancel_no_target",
        }

    # 3. State machine guard. _find_modifiable_order returns one of
    #    pending/payment_sent/fired_unpaid (all three allow → canceled
    #    in state_machine), so this branch is defensive — should never
    #    fire under the current state graph. If a future state is added
    #    to the SQL filter without updating the state machine, this
    #    catches it instead of letting advance_state raise.
    # (방어적 가드 — SQL/state_machine 불일치 발생 시 안전 종료)
    prior_state = target["state"]
    if not can_transition(prior_state, State.CANCELED):
        log.error(
            "cancel_order: cannot transition tx=%s %s → canceled",
            target["id"], prior_state,
        )
        return {
            "success":         False,
            "transaction_id":  target["id"],
            "state":           prior_state,
            "reason":          "cancel_failed",
            "ai_script_hint":  "cancel_failed",
        }

    # 4. Persist via state machine. transactions.advance_state writes the
    #    bridge_events audit row. Wrap in try so a DB blip yields a
    #    customer-facing manager-transfer line instead of crashing the
    #    voice path (same pattern as modify_order's POS-injection guard).
    # (DB blip 시 manager transfer로 graceful — 음성 경로 절대 raise 금지)
    try:
        await transactions.advance_state(
            transaction_id = target["id"],
            to_state       = State.CANCELED,
            source         = "voice",
            actor          = "tool_call:cancel_order",
            extra_fields   = {},
        )
    except Exception as exc:
        log.error("cancel_order: advance_state failed tx=%s: %s",
                  target["id"], exc)
        return {
            "success":         False,
            "transaction_id":  target["id"],
            "state":           prior_state,
            "reason":          "cancel_failed",
            "ai_script_hint":  "cancel_failed",
        }

    # 5. Success. Items / total / lane preserved for the voice handler's
    #    session snapshot. ai_script_hint differs for FIRED_UNPAID — the
    #    bot tells the customer to notify staff at the counter since V1
    #    doesn't auto-void Loyverse (deferred to V2).
    # (kitchen 안내 분기 — V1은 사람이 보완)
    return {
        "success":         True,
        "transaction_id":  target["id"],
        "lane":            target.get("payment_lane"),
        "state":           State.CANCELED,
        "prior_state":     prior_state,
        "total_cents":     int(target.get("total_cents") or 0),
        "items":           target.get("items_json") or [],
        "ai_script_hint":  ("cancel_success_fired"
                            if prior_state == State.FIRED_UNPAID
                            else "cancel_success"),
    }


# ── B3: modify_reservation (Phase 2-C.B3) ─────────────────────────────────────
# Per spec backend/docs/specs/B3_modify_reservation.md.
#
# modify_reservation updates the most-recent confirmed reservation for the
# same caller. Unlike modify_order (which lives in bridge_transactions), the
# reservation aggregate lives in the legacy `reservations` table from Phase
# 2-A make_reservation. v1 modifies that table directly to keep the change
# footprint small. Future migration to bridge_transactions is out of scope.
#
# Customer decisions locked 2026-05-02:
#   1. 30-minute cutoff for reservation_too_late
#   2. Full payload contract (Gemini sends all 5 mutable fields)
#   3. Email fallback only (Twilio TCR pending)
#   4. Most-recent policy: ORDER BY created_at DESC LIMIT 1


_RESERVATION_MODIFY_CUTOFF_MINUTES = 30
_RESERVATION_PARTY_MAX             = 20


async def _find_modifiable_reservation(
    *,
    store_id:       str,
    customer_phone: str,
) -> Optional[dict[str, Any]]:
    """Locate the single most-recent confirmed reservation for this caller.
    (이 caller의 최근 confirmed 예약 1건 조회 — modify 대상 식별)

    Most-recent policy: ORDER BY created_at DESC LIMIT 1. Only status =
    'confirmed' is targetable; cancelled / fulfilled / no_show are
    excluded so the bot doesn't accidentally modify a settled booking.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/reservations",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":       f"eq.{store_id}",
                "customer_phone": f"eq.{customer_phone}",
                "status":         "eq.confirmed",
                "select":         "id,store_id,customer_name,customer_phone,"
                                  "party_size,reservation_time,status,notes,"
                                  "created_at",
                "order":          "created_at.desc",
                "limit":          "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_find_modifiable_reservation %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def _is_within_business_hours(
    *,
    store_id:             str,
    reservation_time_iso: str,
) -> bool:
    """Check whether a target reservation_time falls inside the store's
    business hours.

    v1 placeholder: returns True. The actual business_hours field on
    `stores` is free-form text ('Mon-Sat 7am-9pm'), and parsing it
    deterministically is out of scope for B3 v1 — make_reservation
    today does not enforce this either. Tests mock this helper, so
    the bridge contract is preserved when the parser lands in v2.
    (TODO v2: parse stores.business_hours and compare against
    reservation_time_iso in store-local TZ.)
    """
    return True


async def _update_reservation(
    *,
    reservation_id: int,
    diff:           dict[str, dict[str, Any]],
) -> bool:
    """Apply the diff'd fields to the reservations row. (변경 필드만 UPDATE)

    diff shape: {<column>: {"old": <prior>, "new": <new>}}. We PATCH only
    the columns whose new value differs from old — Supabase `.update()`
    via REST PATCH with `Prefer: return=minimal`.
    """
    if not diff:
        return False
    payload = {col: change["new"] for col, change in diff.items()}
    # Touch updated_at so audit/dashboards see the modify (DB has no trigger).
    # Live: Phase 5 scenario 7 — modify succeeded but row's updated_at stayed
    # equal to created_at, masking the change in saas-platform views.
    # (B3 modify 후 updated_at 명시 갱신 — DB trigger 없음)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.patch(
            f"{_REST}/reservations",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{reservation_id}"},
            json=payload,
        )
    if resp.status_code not in (200, 204):
        log.warning("_update_reservation %s: %s",
                    resp.status_code, resp.text[:200])
        return False
    return True


async def modify_reservation(
    *,
    store_id:          str,
    args:              dict[str, Any],
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Update the most-recent confirmed reservation for this caller.
    (이 caller의 가장 최근 confirmed 예약 수정 — Phase 2-C.B3)

    args (Gemini tool args, full payload):
        customer_name:    str  — same as before if unchanged
        reservation_date: YYYY-MM-DD
        reservation_time: HH:MM (24-h)
        party_size:       int (1-20)
        notes:            str  (optional, default '')
        user_explicit_confirmation: bool  (caller-side gate)

    Failure modes (each gets ai_script_hint):
        no_reservation_to_modify  → reservation_no_target
        reservation_too_late      → reservation_too_late (< 30 min)
        outside_business_hours    → outside_business_hours
        party_too_large           → party_too_large (> 20)
        validation_failed         → bad name / date / party_size <= 0
        reservation_noop          → full payload == current row (no diff)
    """
    # 1. Validate party_size first (cheap, no DB).
    try:
        party = int(args.get("party_size") or 0)
    except (TypeError, ValueError):
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          "party_size must be an integer",
            "ai_script_hint": "validation_failed",
        }
    if party <= 0:
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          "party_size must be at least 1",
            "ai_script_hint": "validation_failed",
        }

    # 2. Reject placeholder customer_name.
    raw_name = (args.get("customer_name") or "").strip()
    if is_placeholder_name(raw_name):
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          f"customer_name looks invalid: {raw_name!r}",
            "ai_script_hint": "validation_failed",
        }

    # 3. Combine date+time → ISO. Bad format → validation_failed.
    try:
        new_time_iso = combine_date_time(
            args.get("reservation_date") or "",
            args.get("reservation_time") or "",
        )
    except Exception as exc:
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          f"could not parse date/time: {exc}",
            "ai_script_hint": "validation_failed",
        }

    # 4. Locate target reservation (most-recent confirmed only).
    target = await _find_modifiable_reservation(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )
    if not target:
        return {
            "success":        False,
            "reason":         "no_reservation_to_modify",
            "error":          "no confirmed reservation for this caller",
            "ai_script_hint": "reservation_no_target",
        }

    # 5. State guard — < 30 min from now is too late.
    cutoff = datetime.now(timezone.utc) + timedelta(
        minutes=_RESERVATION_MODIFY_CUTOFF_MINUTES
    )
    try:
        new_time_dt = datetime.fromisoformat(new_time_iso.replace("Z", "+00:00"))
    except Exception as exc:
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          f"bad reservation_time iso: {exc}",
            "ai_script_hint": "validation_failed",
        }
    if new_time_dt < cutoff:
        return {
            "success":        False,
            "reason":         "reservation_too_late",
            "reservation_id": target["id"],
            "ai_script_hint": "reservation_too_late",
        }

    # 6. Party-size upper bound — reject before DB UPDATE.
    if party > _RESERVATION_PARTY_MAX:
        return {
            "success":        False,
            "reason":         "party_too_large",
            "reservation_id": target["id"],
            "ai_script_hint": "party_too_large",
        }

    # 7. Cross-check business hours for the new time.
    if not await _is_within_business_hours(
        store_id             = store_id,
        reservation_time_iso = new_time_iso,
    ):
        return {
            "success":        False,
            "reason":         "outside_business_hours",
            "reservation_id": target["id"],
            "ai_script_hint": "outside_business_hours",
        }

    # 8. Compute diff. Compare each mutable field against the current row.
    new_notes = args.get("notes") or ""
    diff: dict[str, dict[str, Any]] = {}
    if raw_name != (target.get("customer_name") or ""):
        diff["customer_name"] = {
            "old": target.get("customer_name") or "",
            "new": raw_name,
        }
    # ISO string equality is too fragile across timezone-suffix and
    # microsecond representations (e.g. '2026-05-02T20:11:55.291951+00:00'
    # vs '2026-05-02T13:11:00-07:00' represent the same instant). Compare
    # at the datetime level (truncated to minute precision — reservations
    # are slot-based, sub-minute differences are noise) so a noop
    # full-payload re-fire is recognized as such regardless of how
    # Postgres or the client formats the value.
    # (분 단위 비교 — 같은 슬롯이면 noop으로 처리)
    cur_time_raw = target.get("reservation_time") or ""
    try:
        cur_time_dt = datetime.fromisoformat(cur_time_raw.replace("Z", "+00:00"))
        cur_minute  = cur_time_dt.replace(second=0, microsecond=0)
        new_minute  = new_time_dt.replace(second=0, microsecond=0)
        same_instant = cur_minute == new_minute
    except Exception:
        same_instant = (cur_time_raw == new_time_iso)
    if not same_instant:
        diff["reservation_time"] = {
            "old": cur_time_raw,
            "new": new_time_iso,
        }
    if party != int(target.get("party_size") or 0):
        diff["party_size"] = {
            "old": int(target.get("party_size") or 0),
            "new": party,
        }
    if new_notes != (target.get("notes") or ""):
        diff["notes"] = {
            "old": target.get("notes") or "",
            "new": new_notes,
        }

    # 9. Noop short-circuit if nothing actually changed.
    if not diff:
        return {
            "success":        True,
            "reservation_id": target["id"],
            "diff":           {},
            "ai_script_hint": "reservation_noop",
        }

    # 10. Apply UPDATE.
    ok = await _update_reservation(
        reservation_id = target["id"],
        diff           = diff,
    )
    if not ok:
        return {
            "success":        False,
            "reason":         "update_failed",
            "reservation_id": target["id"],
            "ai_script_hint": "validation_failed",
        }

    log.warning("reservation_modified id=%s diff=%s",
                target["id"], list(diff.keys()))

    # 11. Build new_summary for the customer-facing script.
    new_party = party
    new_summary = (
        f"party of {new_party}, "
        f"{format_date_human(args['reservation_date'])} at "
        f"{format_time_12h(args['reservation_time'])}"
    )

    return {
        "success":        True,
        "reservation_id": target["id"],
        "diff":           diff,
        "new_summary":    new_summary,
        "ai_script_hint": "modify_success",
    }


# ── B4: cancel_reservation (Phase 2-C.B4) ─────────────────────────────────────
# Per spec backend/docs/specs/B4_cancel_reservation.md.
#
# cancel_reservation transitions a confirmed reservation to status='cancelled'
# for the most-recent row matching the caller-id. Reuses _find_modifiable_reservation
# (status='confirmed' filter) and adds two helpers:
#   - _find_recent_reservation_any_status: returns the most recent row regardless
#     of status, used to detect already-cancelled rows for a precise error hint.
#   - _update_reservation_status: minimal single-column PATCH (vs B3's diff helper).
#
# Customer decisions locked 2026-05-02:
#   1. Option α — always allow cancel (no 30-min cutoff). Reservations have no
#      kitchen-fire-style irreversible side effect; freeing the slot is a win.
#   2. Caller-id only schema — no phone/name/id in args; kills hallucination class.
#   3. fulfilled / no_show collapse into cancel_reservation_no_target in V1.
# (취소는 30분 컷오프 없음 — 슬롯 회수가 우선)


async def _find_recent_reservation_any_status(
    *,
    store_id:       str,
    customer_phone: str,
) -> Optional[dict[str, Any]]:
    """Locate the single most-recent reservation regardless of status.
    (이 caller의 가장 최근 예약 1건 조회 — 상태 무관)

    Used as a secondary probe when _find_modifiable_reservation returns
    None, so the bridge can return cancel_reservation_already_canceled
    instead of the generic no_target hint.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/reservations",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":       f"eq.{store_id}",
                "customer_phone": f"eq.{customer_phone}",
                "select":         "id,store_id,customer_name,customer_phone,"
                                  "party_size,reservation_time,status,notes,"
                                  "created_at",
                "order":          "created_at.desc",
                "limit":          "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_find_recent_reservation_any_status %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def _update_reservation_status(
    *,
    reservation_id: int,
    new_status:     str,
) -> bool:
    """Patch a single status column on a reservations row. (status만 PATCH)

    Distinct from _update_reservation (which takes a diff dict shaped
    like {col: {old, new}}) so cancel callers don't have to construct a
    fake diff. Same Supabase REST shape and headers.
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.patch(
            f"{_REST}/reservations",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{reservation_id}"},
            json={"status": new_status},
        )
    if resp.status_code not in (200, 204):
        log.warning("_update_reservation_status %s: %s",
                    resp.status_code, resp.text[:200])
        return False
    return True


def _format_reservation_summary(row: dict[str, Any]) -> str:
    """Build the human-readable cancelled summary from a reservations row.
    (취소된 예약 요약 — party of N on <date> at <time>)

    Pulled from the row (not from tool args) because cancel_reservation
    has no payload — the source of truth is the row the bridge looked up.
    """
    party = int(row.get("party_size") or 0)
    raw_iso = row.get("reservation_time") or ""
    try:
        dt = datetime.fromisoformat(raw_iso.replace("Z", "+00:00"))
        # Convert to store-local TZ for human display. v1 follows the
        # same default the rest of the project uses.
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        date_str = local.strftime("%A, %B %-d")
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        time_str = f"{hour}:{local.minute:02d} {ampm}"
        return f"party of {party} on {date_str} at {time_str}"
    except Exception:
        return f"party of {party}"


async def cancel_reservation(
    *,
    store_id:          str,
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Cancel the most-recent confirmed reservation for this caller.
    (이 caller의 가장 최근 confirmed 예약 취소 — Phase 2-C.B4)

    No too-late guard (Option α): the 30-min cutoff that B3
    modify_reservation enforces does NOT apply here — a reservation
    that can no longer be modified should still be cancellable so the
    customer is not stranded and the restaurant can reclaim the slot.

    Failure modes (each gets ai_script_hint):
        cancel_reservation_no_target          → no row at all
        cancel_reservation_already_canceled   → row exists with status='cancelled'
        cancel_reservation_failed             → DB PATCH failed
    """
    # 1. Locate target — most-recent confirmed only.
    target = await _find_modifiable_reservation(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )

    # 2. Secondary probe — when no confirmed row exists, look for any
    #    recent row to give a precise 'already cancelled' hint.
    if not target:
        recent = await _find_recent_reservation_any_status(
            store_id       = store_id,
            customer_phone = caller_phone_e164,
        )
        if recent and (recent.get("status") or "").lower() == "cancelled":
            return {
                "success":        False,
                "reason":         "cancel_reservation_already_canceled",
                "reservation_id": recent["id"],
                "ai_script_hint": "cancel_reservation_already_canceled",
            }
        # fulfilled / no_show / nothing-at-all all collapse here in V1.
        return {
            "success":        False,
            "reason":         "cancel_reservation_no_target",
            "ai_script_hint": "cancel_reservation_no_target",
        }

    # 3. PATCH status → 'cancelled'.
    ok = await _update_reservation_status(
        reservation_id = target["id"],
        new_status     = "cancelled",
    )
    if not ok:
        log.error("cancel_reservation: PATCH failed id=%s", target["id"])
        return {
            "success":        False,
            "reason":         "cancel_reservation_failed",
            "reservation_id": target["id"],
            "ai_script_hint": "cancel_reservation_failed",
        }

    log.warning("reservation_cancelled id=%s prior_status=%s",
                target["id"], target.get("status"))

    return {
        "success":           True,
        "reservation_id":    target["id"],
        "prior_status":      target.get("status"),
        "cancelled_summary": _format_reservation_summary(target),
        "ai_script_hint":    "cancel_reservation_success",
    }
