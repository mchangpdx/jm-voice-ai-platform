"""modify_appointment — Gemini Function Calling tool for appointment updates.
(modify_appointment — 서비스 예약 변경용 Gemini Function Calling 도구)

Mirrors `services/bridge/flows.modify_reservation` (Phase 2-C.B3):
  - Full-payload contract — Gemini sends ALL mutable fields as a snapshot
  - Caller-id locates the most-recent confirmed appointment
  - 30-minute too-late guard (Option β — block last-minute schedule churn)
  - Diff-then-PATCH (only changed columns hit the DB)
  - Noop short-circuit when payload == current row

Target table: `appointments`.
Mutable columns: service_type, scheduled_at, duration_min, price, customer_name.
Notes / stylist columns intentionally omitted — current schema does not store
them. Add to the diff helper when those columns ship.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.skills.appointment.booking import combine_date_time

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"

# Reject modifications less than 30 minutes from the appointment slot —
# stylists need a hold window to prep / reschedule. Customers in that
# window should call the salon directly.
# (시술 30분 전 이내 변경 거부 — 스타일리스트 준비 시간 보장)
_MODIFY_CUTOFF_MINUTES = 30

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ── Tool definition ──────────────────────────────────────────────────────────


MODIFY_APPOINTMENT_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "modify_appointment",
            "description": (
                "Update a customer's just-booked appointment. "
                "FULL-PAYLOAD CONTRACT: send ALL mutable fields as a "
                "complete snapshot — for fields the customer is NOT changing, "
                "resend the original value (which you recited at booking). "
                "Caller-id locates the most-recent confirmed appointment; "
                "DO NOT include appointment_id or customer_phone in args. "
                "Only call AFTER the customer verbally confirms the updated "
                "appointment summary with an explicit 'yes'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set true ONLY after the customer says yes to your "
                            "updated appointment summary."
                        ),
                    },
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Service for the appointment. Send the SAME value "
                            "as before if unchanged."
                        ),
                    },
                    "appointment_date": {
                        "type": "string",
                        "description": "YYYY-MM-DD. Send the same value if unchanged.",
                    },
                    "appointment_time": {
                        "type": "string",
                        "description": "HH:MM 24-hour. Send the same value if unchanged.",
                    },
                    "duration_min": {
                        "type": "integer",
                        "description": (
                            "Estimated duration in minutes (1-600). Resend the "
                            "current value if unchanged. Call service_lookup "
                            "first if the service changed."
                        ),
                    },
                    "customer_name": {
                        "type": "string",
                        "description": (
                            "Full name on the appointment. Send the SAME value "
                            "if unchanged."
                        ),
                    },
                    "price": {
                        "type": "number",
                        "description": (
                            "Quoted price in USD. Resend the existing value "
                            "if unchanged; pull from service_lookup if the "
                            "service was swapped."
                        ),
                    },
                },
                "required": [
                    "user_explicit_confirmation",
                    "service_name",
                    "appointment_date",
                    "appointment_time",
                    "duration_min",
                    "customer_name",
                ],
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
    """Most-recent confirmed appointment for this caller.
    (이 caller의 가장 최근 confirmed appointment 1건)
    """
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


async def _update_appointment(
    *,
    appointment_id: int,
    diff:           dict[str, dict[str, Any]],
) -> bool:
    """PATCH only the changed columns. (변경된 컬럼만 PATCH)"""
    payload = {col: change["new"] for col, change in diff.items()}
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.patch(
            f"{_REST}/appointments",
            headers={**_SUPABASE_HEADERS, "Prefer": "return=minimal"},
            params={"id": f"eq.{appointment_id}"},
            json=payload,
        )
    if resp.status_code not in (200, 204):
        log.warning("_update_appointment %s: %s",
                    resp.status_code, resp.text[:200])
        return False
    return True


# ── Pure validator + diff (unit-testable) ────────────────────────────────────


def validate_modify_args(args: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate args before any DB call. (DB 호출 전 검증 — 순수 함수)"""
    if not args.get("user_explicit_confirmation"):
        return False, "user_explicit_confirmation must be true"

    for field in ("service_name", "appointment_date", "appointment_time",
                  "duration_min", "customer_name"):
        val = args.get(field)
        if val is None or val == "":
            return False, f"missing required field: {field}"

    if not _DATE_RE.match(str(args["appointment_date"])):
        return False, f"appointment_date must be YYYY-MM-DD (got {args['appointment_date']!r})"
    if not _TIME_RE.match(str(args["appointment_time"])):
        return False, f"appointment_time must be HH:MM 24-hour (got {args['appointment_time']!r})"

    duration = args["duration_min"]
    if not isinstance(duration, int) or duration <= 0 or duration > 600:
        return False, f"duration_min must be a positive integer ≤ 600 (got {duration!r})"

    price = args.get("price")
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        return False, f"price must be non-negative number (got {price!r})"

    return True, None


def compute_diff(
    *,
    args:    dict[str, Any],
    current: dict[str, Any],
    new_scheduled_at_iso: str,
) -> dict[str, dict[str, Any]]:
    """Diff Gemini payload vs current row.
    (Gemini payload vs 현재 row diff — 변경된 컬럼만 반환)

    `new_scheduled_at_iso` is the caller-resolved ISO string (post
    combine_date_time) so this helper stays pure and tz-free.
    """
    diff: dict[str, dict[str, Any]] = {}

    raw_service = (args.get("service_name") or "").strip()
    if raw_service != (current.get("service_type") or ""):
        diff["service_type"] = {
            "old": current.get("service_type") or "",
            "new": raw_service,
        }

    raw_name = (args.get("customer_name") or "").strip()
    if raw_name != (current.get("customer_name") or ""):
        diff["customer_name"] = {
            "old": current.get("customer_name") or "",
            "new": raw_name,
        }

    # Time diff at minute precision — ISO equality is fragile across
    # tz-suffix and microsecond representations.
    # (분 단위 비교 — 같은 슬롯이면 noop)
    cur_iso = current.get("scheduled_at") or ""
    try:
        cur_dt  = datetime.fromisoformat(cur_iso.replace("Z", "+00:00"))
        new_dt  = datetime.fromisoformat(new_scheduled_at_iso.replace("Z", "+00:00"))
        same    = cur_dt.replace(second=0, microsecond=0) == new_dt.replace(second=0, microsecond=0)
    except Exception:
        same = (cur_iso == new_scheduled_at_iso)
    if not same:
        diff["scheduled_at"] = {"old": cur_iso, "new": new_scheduled_at_iso}

    new_dur = int(args["duration_min"])
    if new_dur != int(current.get("duration_min") or 0):
        diff["duration_min"] = {
            "old": int(current.get("duration_min") or 0),
            "new": new_dur,
        }

    if "price" in args and args["price"] is not None:
        new_price = float(args["price"])
        cur_price = float(current.get("price") or 0)
        if new_price != cur_price:
            diff["price"] = {"old": cur_price, "new": new_price}

    return diff


# ── Public flow ──────────────────────────────────────────────────────────────


async def modify_appointment(
    *,
    store_id:          str,
    args:              dict[str, Any],
    caller_phone_e164: str,
    call_log_id:       Optional[str] = None,
    store_timezone:    str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Update the most-recent confirmed appointment for this caller.
    (이 caller의 가장 최근 confirmed appointment 변경 — Phase 3.3)

    Failure modes (each gets ai_script_hint):
        validation_failed              → bad input shape
        no_appointment_to_modify       → appointment_no_target
        appointment_too_late           → < 30 min cutoff
        update_failed                  → DB PATCH 4xx/5xx
        modify_appointment_noop        → diff is empty
    """
    ok, err = validate_modify_args(args)
    if not ok:
        log.warning("modify_appointment rejected: %s", err)
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          err,
            "ai_script_hint": "validation_failed",
        }

    try:
        new_iso = combine_date_time(
            args["appointment_date"],
            args["appointment_time"],
            tz=store_timezone,
        )
    except Exception as exc:
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          f"could not parse date/time: {exc}",
            "ai_script_hint": "validation_failed",
        }

    target = await _find_modifiable_appointment(
        store_id       = store_id,
        customer_phone = caller_phone_e164,
    )
    if not target:
        return {
            "success":        False,
            "reason":         "no_appointment_to_modify",
            "ai_script_hint": "appointment_no_target",
        }

    cutoff = datetime.now(timezone.utc) + timedelta(minutes=_MODIFY_CUTOFF_MINUTES)
    try:
        new_dt = datetime.fromisoformat(new_iso.replace("Z", "+00:00"))
    except Exception as exc:
        return {
            "success":        False,
            "reason":         "validation_failed",
            "error":          f"bad scheduled_at iso: {exc}",
            "ai_script_hint": "validation_failed",
        }
    if new_dt < cutoff:
        return {
            "success":         False,
            "reason":          "appointment_too_late",
            "appointment_id":  target["id"],
            "ai_script_hint":  "appointment_too_late",
        }

    diff = compute_diff(args=args, current=target, new_scheduled_at_iso=new_iso)

    if not diff:
        return {
            "success":        True,
            "appointment_id": target["id"],
            "diff":           {},
            "ai_script_hint": "modify_appointment_noop",
        }

    ok = await _update_appointment(appointment_id=target["id"], diff=diff)
    if not ok:
        return {
            "success":        False,
            "reason":         "update_failed",
            "appointment_id": target["id"],
            "ai_script_hint": "validation_failed",
        }

    log.warning("appointment_modified id=%s diff=%s",
                target["id"], list(diff.keys()))

    return {
        "success":        True,
        "appointment_id": target["id"],
        "diff":           diff,
        "ai_script_hint": "modify_appointment_success",
    }


__all__ = [
    "MODIFY_APPOINTMENT_TOOL_DEF",
    "compute_diff",
    "modify_appointment",
    "validate_modify_args",
]
