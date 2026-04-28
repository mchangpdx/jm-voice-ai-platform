# Bridge Server — transactions repository
# (Bridge Server — 트랜잭션 레포지토리)
#
# Wraps Supabase REST for bridge_transactions + bridge_events.
# All state mutations go through advance_state() — direct UPDATE on the state
# column is forbidden by convention. advance_state() validates via state_machine
# and appends an audit row to bridge_events on every transition.

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.bridge.state_machine import State, transition

log = logging.getLogger(__name__)

_VERTICALS = {"restaurant", "home_services", "beauty", "auto_repair"}

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
    total_cents:     int = 0,
    call_log_id:     Optional[str] = None,
    source:          str = "voice",
    actor:           Optional[str] = None,
) -> dict[str, Any]:
    """INSERT a new bridge_transactions row in state=pending and audit it.
    (state=pending 상태로 bridge_transactions 행 INSERT + 감사)

    Returns the inserted row dict (includes id, state, etc).
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
        "total_cents":     int(total_cents),
        "state":           State.PENDING,
        "call_log_id":     call_log_id,
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
