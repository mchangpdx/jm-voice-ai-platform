# Bridge Server — transactions repository
# (Bridge Server — 트랜잭션 레포지토리)
#
# Wraps Supabase REST for bridge_transactions + bridge_events.
# All state mutations go through advance_state() — direct UPDATE on the state
# column is forbidden by convention. advance_state() validates via state_machine
# and appends an audit row to bridge_events on every transition.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge.state_machine import State, transition

log = logging.getLogger(__name__)

_VERTICALS = {"restaurant", "kbbq", "home_services", "beauty", "auto_repair"}

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _post_event(
    client: httpx.AsyncClient,
    *,
    transaction_id: str,
    event_type:     str,
    source:         str,
    actor:          Optional[str] = None,
    from_state:     Optional[str] = None,
    to_state:       Optional[str] = None,
    payload_json:   Optional[dict] = None,
) -> None:
    """Append a row to bridge_events. Best-effort — never raises into caller path.
    (감사 이벤트 추가 — 실패해도 호출자 경로에 예외 전파하지 않음)
    """
    row = {
        "transaction_id": transaction_id,
        "event_type":     event_type,
        "source":         source,
        "actor":          actor,
        "from_state":     from_state,
        "to_state":       to_state,
        "payload_json":   payload_json or {},
    }
    row = {k: v for k, v in row.items() if v is not None}
    try:
        resp = await client.post(
            f"{_REST}/bridge_events",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            json=row,
        )
        if resp.status_code not in (200, 201, 204):
            log.warning("bridge_events INSERT failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("bridge_events INSERT exception: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

async def create_transaction(
    *,
    store_id:        str,
    vertical:        str,
    pos_object_type: str,
    pos_object_id:   str,
    customer_phone:  str,
    customer_name:   Optional[str] = None,
    customer_email:  Optional[str] = None,    # Phase 7-A.D Wave A.3 B.1 — pay-link audit trail
    total_cents:     int = 0,
    call_log_id:     Optional[str] = None,
    source:          str = "voice",
    actor:           Optional[str] = None,
    payment_lane:    Optional[str] = None,    # Phase 2-B.1.7b — fire_immediate | pay_first | None
    items_json:      Optional[list[dict[str, Any]]] = None,    # Phase 2-B.1.9 — resolved order lines for pay-link replay
) -> dict[str, Any]:
    """INSERT a new bridge_transactions row in state=pending and audit it.
    (state=pending 상태로 bridge_transactions 행 INSERT + 감사)

    Returns the inserted row dict (includes id, state, etc).

    payment_lane: routing decision for order flows (Phase 2-B.1.7b). Reservation
    flows pass None — the column is nullable for legacy/non-order rows.
    (예약 흐름은 None — 정책 비적용 행)

    customer_email: address used for the pay-link email send. Persisting this
    is required for post-call audit when NATO recital ↔ args drift produces
    wrong-address sends — without the column we only have rotated debug logs.
    (이메일 NATO drift 감사 — DB 영속화로 사후 추적 가능)
    """
    if vertical not in _VERTICALS:
        raise ValueError(f"unknown vertical: {vertical!r}; allowed={sorted(_VERTICALS)}")

    row = {
        "store_id":        store_id,
        "vertical":        vertical,
        "pos_object_type": pos_object_type,
        "pos_object_id":   pos_object_id,
        "customer_phone":  customer_phone,
        "customer_name":   customer_name,
        "customer_email":  (customer_email or None),   # empty string → NULL
        "total_cents":     int(total_cents),
        "state":           State.PENDING,
        "call_log_id":     call_log_id,
        "payment_lane":    payment_lane,
        "items_json":      items_json,
    }
    row = {k: v for k, v in row.items() if v is not None}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_REST}/bridge_transactions",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
            json=row,
        )
        if resp.status_code not in (200, 201):
            log.error("bridge_transactions INSERT failed %s: %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"create_transaction failed: {resp.status_code}")

        txn = resp.json()[0]

        # Append creation event (best-effort — does not roll back the INSERT on failure)
        await _post_event(
            client,
            transaction_id = txn["id"],
            event_type     = "transaction_created",
            source         = source,
            actor          = actor,
            to_state       = State.PENDING,
            payload_json   = {"vertical": vertical, "pos_object_id": pos_object_id},
        )

    return txn


async def advance_state(
    *,
    transaction_id: str,
    to_state:       str,
    source:         str,
    actor:          Optional[str] = None,
    extra_fields:   Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Validate + apply a state transition + audit it.
    (상태 전이 검증 + 적용 + 감사)

    Reads current state, runs state_machine.transition() (raises InvalidTransition
    on bad edge), PATCHes the row (skipped on noop self-transition), appends
    bridge_events row.

    extra_fields: optional fields to patch alongside state (e.g. paid_cents).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        # Read current state
        get_resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={"id": f"eq.{transaction_id}", "select": "id,state", "limit": "1"},
        )
        rows = get_resp.json() if get_resp.status_code == 200 else []
        if not rows:
            raise LookupError(f"bridge_transaction not found: {transaction_id}")
        from_state = rows[0]["state"]

        # Validate via state machine (raises InvalidTransition on bad edge)
        evt = transition(
            from_state=from_state,
            to_state=to_state,
            source=source,
            actor=actor or "",
        )

        is_noop = evt.get("noop", False)
        patched_row: dict[str, Any] = {"id": transaction_id, "state": to_state}

        if not is_noop:
            patch_payload: dict[str, Any] = {"state": to_state}
            if extra_fields:
                patch_payload.update(extra_fields)

            patch_resp = await client.patch(
                f"{_REST}/bridge_transactions",
                headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
                params={"id": f"eq.{transaction_id}"},
                json=patch_payload,
            )
            if patch_resp.status_code not in (200, 204):
                log.error("advance_state PATCH failed %s: %s",
                          patch_resp.status_code, patch_resp.text[:200])
                raise RuntimeError(f"advance_state patch failed: {patch_resp.status_code}")
            if patch_resp.status_code == 200 and patch_resp.json():
                patched_row = patch_resp.json()[0]

        # Always write audit event (including noop)
        await _post_event(
            client,
            transaction_id = transaction_id,
            event_type     = "state_transition",
            source         = source,
            actor          = actor,
            from_state     = from_state,
            to_state       = to_state,
            payload_json   = evt,
        )

    return patched_row


async def set_pos_object_id(transaction_id: str, pos_object_id: str) -> None:
    """Backfill pos_object_id on a bridge_transaction after POS create_pending.
    (POS 객체 생성 직후 bridge_transaction.pos_object_id 백필)

    Pure data link — no state change, no audit event (covered by adjacent
    state_transition events that already record the POS write).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{_REST}/bridge_transactions",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{transaction_id}"},
            json={"pos_object_id": str(pos_object_id)},
        )
    if resp.status_code not in (200, 204):
        log.warning("set_pos_object_id failed %s: %s", resp.status_code, resp.text[:200])


async def get_transaction(transaction_id: str) -> Optional[dict[str, Any]]:
    """Read a transaction by id. Returns None if not found.
    (id로 트랜잭션 조회 — 없으면 None)
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_REST}/bridge_transactions",
            headers=_SUPABASE_HEADERS,
            params={"id": f"eq.{transaction_id}", "limit": "1"},
        )
    if resp.status_code != 200:
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def update_items_and_total(
    *,
    transaction_id: str,
    items:          list[dict[str, Any]],
    total_cents:    int,
) -> None:
    """Replace items_json + total_cents on an in-flight bridge_transaction.
    (in-flight 트랜잭션의 items_json + total_cents 갱신 — modify_order 전용)

    State is NOT changed — modification is a content edit, lifecycle is
    separately governed by advance_state(). Caller is responsible for
    appending the corresponding 'items_modified' audit row via
    append_audit() so the event stream stays complete.
    """
    payload = {
        "items_json":  items,
        "total_cents": int(total_cents),
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{_REST}/bridge_transactions",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{transaction_id}"},
            json=payload,
        )
    if resp.status_code not in (200, 204):
        log.warning("update_items_and_total %s: %s",
                    resp.status_code, resp.text[:200])
        raise RuntimeError(
            f"update_items_and_total patch failed: {resp.status_code}"
        )


async def update_call_metrics(
    *,
    transaction_id:     str,
    call_duration_ms:   int,
    crm_returning:      Optional[bool] = None,
    crm_visit_count:    Optional[int]  = None,
    crm_usual_offered:  Optional[bool] = None,
    crm_usual_accepted: Optional[bool] = None,
) -> None:
    """Persist Wave 1 CRM call metrics on a finalized bridge_transaction.
    (Wave 1 CRM — 통화 종료 시 AHT 및 재방문 분석 필드 영속화)

    Called from realtime_voice's WebSocket close handler as a background
    task (asyncio.create_task) — must never raise into the caller, since
    by definition the call has already ended and a thrown exception would
    only pollute logs without changing user impact. Failures are warn-logged
    with the keyword [perf] call_end_persist_failed for grep-based
    monitoring (Wave A.3 pattern).

    Skips silently if transaction_id is empty (mid-call hangup before
    create_order populated session_state['active_tx_id']).
    """
    if not transaction_id:
        log.info("[perf] call_end no_tx_skip_update aht_ms=%d", call_duration_ms)
        return

    payload: dict[str, Any] = {
        "call_duration_ms": int(call_duration_ms),
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }
    if crm_returning      is not None: payload["crm_returning"]      = bool(crm_returning)
    if crm_visit_count    is not None: payload["crm_visit_count"]    = int(crm_visit_count)
    if crm_usual_offered  is not None: payload["crm_usual_offered"]  = bool(crm_usual_offered)
    if crm_usual_accepted is not None: payload["crm_usual_accepted"] = bool(crm_usual_accepted)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(
                f"{_REST}/bridge_transactions",
                headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
                params={"id": f"eq.{transaction_id}"},
                json=payload,
            )
        if resp.status_code not in (200, 204):
            log.warning(
                "[perf] call_end_persist_failed tx=%s status=%d body=%s",
                transaction_id, resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        log.warning(
            "[perf] call_end_persist_failed tx=%s exc=%s",
            transaction_id, exc,
        )


async def append_audit(
    *,
    transaction_id: str,
    event_type:     str,
    source:         str,
    actor:          str,
    payload:        Optional[dict[str, Any]] = None,
    from_state:     Optional[str] = None,
    to_state:       Optional[str] = None,
) -> None:
    """Write a non-state-transition audit row to bridge_events.
    (상태 전이가 없는 도메인 이벤트 기록 — modify, refund, note 등 공용)

    Used by domain commands that mutate a transaction's content but not
    its lifecycle (e.g. modify_order's 'items_modified'). Lifecycle
    moves still go through advance_state() which writes its own
    'state_transition' rows. _post_event takes a client positionally so
    callers can batch events on a single connection — we open a fresh
    one per audit since modify is fire-once per call.
    (_post_event는 client를 positional로 요구 — 1회성 audit이라 새 client 사용)
    """
    async with httpx.AsyncClient(timeout=10) as client:
        await _post_event(
            client,
            transaction_id = transaction_id,
            event_type     = event_type,
            source         = source,
            actor          = actor,
            from_state     = from_state,
            to_state       = to_state,
            payload_json   = payload or {},
        )
