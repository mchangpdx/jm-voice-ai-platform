"""cancel_appointment — Gemini Function Calling tool for appointment cancels.
(cancel_appointment — 서비스 예약 취소용 Gemini Function Calling 도구)

Mirrors `services/bridge/flows.cancel_reservation` (Phase 2-C.B4):
  - Caller-id only schema — no phone/name/id payload (kills hallucination class)
  - No time cutoff blocking cancel — option α (freeing the slot beats blocking)
  - Distinct hint for already-cancelled vs no-target-at-all
  - Most-recent confirmed row is the cancel target

Added vs reservation cancel — late-cancel policy:
  Returns `ai_script_hint='cancel_appointment_late_cancel'` when the
  appointment is less than 24h away, plus `hours_until_appointment` so
  the voice handler can surface the store's late-fee phrasing from
  pricing_policy.yaml. The cancel itself is still applied — the fee is
  policy, the slot release is operational.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Industry-standard salon / spa late-cancel window — surfaced as a hint to the
# voice handler, not enforced as a block. (24시간 — late-cancel fee 안내 기준)
_LATE_CANCEL_WINDOW_HOURS = 24


# ── Tool definition ──────────────────────────────────────────────────────────


CANCEL_APPOINTMENT_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "cancel_appointment",
            "description": (
                "Cancel a customer's just-booked appointment. "
                "Use ONLY when the customer EXPLICITLY says 'cancel my "
                "appointment', 'cancel that booking', or accepts a cancel "
                "offer after the late-fee notice. "
                "PRECONDITIONS: "
                "(a) the customer has clearly stated cancel intent for "
                "    THE APPOINTMENT (not an order), "
                "(b) you have recited 'Just to confirm — you want to "
                "    cancel your [service] on [date] at [time] — is that "
                "    right?' using the appointment summary from this "
                "    call's most recent book_appointment or "
                "    modify_appointment, "
                "(c) the customer has said an explicit verbal yes to "
                "    that recital. "
                "Do NOT pass customer_phone, customer_name, "
                "appointment_id, or any other field — the system "
                "identifies the target via the inbound caller ID. "
                "NEVER say 'I've cancelled that for you' without "
                "actually calling this tool. If no active appointment "
                "exists, the bridge will respond accordingly and you "
                "must NOT retry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set true ONLY after the customer has verbally "
                            "said 'yes' to your cancel-appointment recital. "
                            "False or missing = do not call."
                        ),
                    },
                },
                "required": ["user_explicit_confirmation"],
            },
        }
    ]
}


# ── Internal helpers (REST) ──────────────────────────────────────────────────


async def _find_modifiable_appointment(
    *,
    store_id:       str,
    customer_phone: str,
) -> Optional[dict[str, Any]]:
    """Most-recent confirmed appointment for this caller."""
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/appointments",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":       f"eq.{store_id}",
                "customer_phone": f"eq.{customer_phone}",
                "status":         "eq.confirmed",
                "select":         "id,store_id,service_type,scheduled_at,"
                                  "duration_min,price,customer_name,"
                                  "customer_phone,status,created_at",
                "order":          "created_at.desc",
                "limit":          "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_find_modifiable_appointment %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def _find_recent_appointment_any_status(
    *,
    store_id:       str,
    customer_phone: str,
) -> Optional[dict[str, Any]]:
    """Most-recent appointment regardless of status — used to detect
    already-cancelled rows for a precise error hint.
    (상태 무관 가장 최근 appointment — already_canceled 구분용)
    """
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            f"{_REST}/appointments",
            headers=_SUPABASE_HEADERS,
            params={
                "store_id":       f"eq.{store_id}",
                "customer_phone": f"eq.{customer_phone}",
                "select":         "id,scheduled_at,status,customer_name,"
                                  "service_type,created_at",
                "order":          "created_at.desc",
                "limit":          "1",
            },
        )
    if resp.status_code != 200:
        log.warning("_find_recent_appointment_any_status %s: %s",
                    resp.status_code, resp.text[:200])
        return None
    rows = resp.json()
    return rows[0] if rows else None


async def _update_appointment_status(
    *,
    appointment_id: int,
    new_status:     str,
) -> bool:
    """PATCH the single status column."""
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.patch(
            f"{_REST}/appointments",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{appointment_id}"},
            json={"status": new_status},
        )
    if resp.status_code not in (200, 204):
        log.warning("_update_appointment_status %s: %s",
                    resp.status_code, resp.text[:200])
        return False
    return True


# ── Pure helper (unit-testable) ──────────────────────────────────────────────


def hours_until(scheduled_at_iso: str, *, now: Optional[datetime] = None) -> float:
    """Hours from `now` (default UTC now) until scheduled_at_iso.
    Returns negative if scheduled_at is in the past.
    (남은 시간 — late-cancel 판단용 순수 함수)

    Returns 0.0 on parse failure so callers don't crash.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(scheduled_at_iso.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    return (dt - now).total_seconds() / 3600.0


def _format_appointment_summary(row: dict[str, Any]) -> str:
    """Build the human-readable cancelled summary from an appointments row.
    (취소된 appointment 요약 — service on <date> at <time>)
    """
    from zoneinfo import ZoneInfo
    raw_iso = row.get("scheduled_at") or ""
    service = row.get("service_type") or "appointment"
    try:
        dt = datetime.fromisoformat(raw_iso.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo("America/Los_Angeles"))
        date_str = local.strftime("%A, %B %-d")
        hour = local.hour % 12 or 12
        ampm = "AM" if local.hour < 12 else "PM"
        time_str = f"{hour}:{local.minute:02d} {ampm}"
        return f"{service} on {date_str} at {time_str}"
    except Exception:
        return service


# ── Public flow ──────────────────────────────────────────────────────────────


async def cancel_appointment(
    *,
    store_id:          str,
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
) -> dict[str, Any]:
    """Cancel the most-recent confirmed appointment for this caller.
    (이 caller의 가장 최근 confirmed appointment 취소 — Phase 3.4)

    Failure modes (each gets ai_script_hint):
        cancel_appointment_no_target           → no row at all (or not confirmed)
        cancel_appointment_already_canceled    → row exists with status='cancelled'
        cancel_appointment_failed              → DB PATCH failed

    Success hints:
        cancel_appointment_success             → ≥ 24h until appointment
        cancel_appointment_late_cancel         → < 24h, late-fee policy applies
    """
    target = await _find_modifiable_appointment(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )

    if not target:
        recent = await _find_recent_appointment_any_status(
            store_id       = store_id,
            customer_phone = caller_phone_e164,
        )
        if recent and (recent.get("status") or "").lower() == "cancelled":
            return {
                "success":         False,
                "reason":          "cancel_appointment_already_canceled",
                "appointment_id":  recent["id"],
                "ai_script_hint":  "cancel_appointment_already_canceled",
            }
        return {
            "success":        False,
            "reason":         "cancel_appointment_no_target",
            "ai_script_hint": "cancel_appointment_no_target",
        }

    ok = await _update_appointment_status(
        appointment_id = target["id"],
        new_status     = "cancelled",
    )
    if not ok:
        log.error("cancel_appointment: PATCH failed id=%s", target["id"])
        return {
            "success":        False,
            "reason":         "cancel_appointment_failed",
            "appointment_id": target["id"],
            "ai_script_hint": "cancel_appointment_failed",
        }

    log.warning("appointment_cancelled id=%s prior_status=%s",
                target["id"], target.get("status"))

    hours_left = hours_until(target.get("scheduled_at") or "")
    is_late    = hours_left < _LATE_CANCEL_WINDOW_HOURS

    return {
        "success":                  True,
        "appointment_id":           target["id"],
        "prior_status":             target.get("status"),
        "cancelled_summary":        _format_appointment_summary(target),
        "hours_until_appointment":  round(hours_left, 2),
        "is_late_cancel":           is_late,
        "late_cancel_window_hours": _LATE_CANCEL_WINDOW_HOURS,
        "ai_script_hint":           (
            "cancel_appointment_late_cancel" if is_late
            else "cancel_appointment_success"
        ),
    }


__all__ = [
    "CANCEL_APPOINTMENT_TOOL_DEF",
    "cancel_appointment",
    "hours_until",
]
