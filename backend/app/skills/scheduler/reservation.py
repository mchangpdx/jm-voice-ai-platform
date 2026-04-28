# skills/scheduler/reservation.py — Gemini Function Calling tool for reservations
# (skills/scheduler/reservation.py — 예약용 Gemini Function Calling 도구)
#
# Architecture (CLAUDE.md guidance: stable first, scalable later):
#   - One tool: make_reservation
#   - Server-side resolution of store_id and call_log_id (never trusted from Gemini args)
#   - user_explicit_confirmation lock (prevents phantom bookings)
#   - Pure helpers (validate_reservation_args, combine_date_time) are unit-testable
#   - insert_reservation is async, awaits Supabase REST insert, returns dict result
#
# Reservation flow (예약 흐름):
#   Gemini collects 6 fields → recites summary → user says "yes"
#   → Gemini calls make_reservation with user_explicit_confirmation=true
#   → server validates → combines date+time → INSERT → returns reservation_id

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_SUPABASE_HEADERS = {
    "apikey":        settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type":  "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


# ── Tool definition for Gemini Function Calling ──────────────────────────────
# (Gemini Function Calling용 도구 정의)
#
# Shape mirrors google.ai.generativelanguage.Tool — passed via genai.GenerativeModel(tools=[...]).
# (google.ai.generativelanguage.Tool 형식을 따름 — genai.GenerativeModel(tools=[...])로 전달)

RESERVATION_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "make_reservation",
            "description": (
                "Place a confirmed table reservation. "
                "BEFORE calling this tool you MUST: "
                "(a) collect all six required fields from the customer, "
                "(b) recite the full reservation summary back to the customer, "
                "(c) receive an explicit verbal 'yes' from the customer. "
                "Only then set user_explicit_confirmation=true. "
                "Never call this tool without verbal confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally said 'yes' "
                            "to your reservation summary. False or missing = do not call."
                        ),
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name of the customer making the reservation.",
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "Phone number for confirmation (digits and + only).",
                    },
                    "reservation_date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (e.g. 2026-04-30).",
                    },
                    "reservation_time": {
                        "type": "string",
                        "description": "Time in HH:MM 24-hour format (e.g. 19:00 for 7 PM).",
                    },
                    "party_size": {
                        "type": "integer",
                        "description": "Number of guests, must be at least 1.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional special requests (allergies, seating, etc.).",
                    },
                },
                "required": [
                    "user_explicit_confirmation",
                    "customer_name",
                    "customer_phone",
                    "reservation_date",
                    "reservation_time",
                    "party_size",
                ],
            },
        }
    ]
}


# ── Pure validators (no I/O, fully unit-tested) ─────────────────────────────

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_reservation_args(args: dict[str, Any]) -> tuple[bool, str]:
    """Validate Gemini-supplied reservation args before any DB call.
    (DB 호출 전 Gemini가 전달한 예약 인수 검증)

    Returns (ok, error_message). On error, callers should send the message back
    to Gemini as a function_response so it can apologize naturally to the customer.
    """
    if not args.get("user_explicit_confirmation"):
        return False, "user has not yet confirmed the reservation summary verbally"

    required = ["customer_name", "customer_phone",
                "reservation_date", "reservation_time", "party_size"]
    for field in required:
        if field not in args or args[field] in (None, ""):
            return False, f"missing required field: {field}"

    if not _DATE_RE.match(str(args["reservation_date"])):
        return False, "reservation_date must be YYYY-MM-DD format"

    if not _TIME_RE.match(str(args["reservation_time"])):
        return False, "reservation_time must be HH:MM 24-hour format"

    try:
        size = int(args["party_size"])
    except (TypeError, ValueError):
        return False, "party_size must be an integer"
    if size < 1:
        return False, "party_size must be at least 1"

    return True, ""


def combine_date_time(date_str: str, time_str: str, tz: str = "America/Los_Angeles") -> str:
    """Combine YYYY-MM-DD + HH:MM into a tz-aware ISO 8601 string.
    (YYYY-MM-DD + HH:MM을 시간대 인식 ISO 8601 문자열로 결합)
    """
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    aware = naive.replace(tzinfo=ZoneInfo(tz))
    return aware.isoformat()


# ── Async DB insert ──────────────────────────────────────────────────────────

async def insert_reservation(
    args: dict[str, Any],
    store_id: str,
    call_log_id: Optional[str] = None,
    tz: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Insert a reservation row in Supabase. Pure server-side; ignores any store_id in args.
    (Supabase에 예약 행 삽입. 서버 측 처리 — args의 store_id는 무시)

    Returns:
        {"success": True,  "reservation_id": int, "message": str}
        {"success": False, "error": str}
    """
    ok, err = validate_reservation_args(args)
    if not ok:
        log.warning("Reservation rejected: %s", err)
        return {"success": False, "error": err}

    try:
        reservation_time_iso = combine_date_time(
            args["reservation_date"], args["reservation_time"], tz=tz
        )
    except Exception as exc:  # malformed date/time despite regex
        return {"success": False, "error": f"could not parse date/time: {exc}"}

    # NOTE: call_log_id is intentionally NOT inserted here. The reservations.call_log_id
    # column has a FK to call_logs.call_id, but the call_logs row is only created by the
    # post-call webhook AFTER the call ends. Linking happens via a separate backfill step.
    # (call_log_id는 의도적으로 INSERT 제외 — call_logs 행은 통화 종료 webhook에서 생성됨.
    #  통화 종료 후 customer_phone + reservation_time으로 매칭하여 별도 백필 처리)
    row = {
        "store_id":         store_id,                 # always server-resolved
        "customer_name":    args["customer_name"],
        "customer_phone":   args["customer_phone"],
        "party_size":       int(args["party_size"]),
        "reservation_time": reservation_time_iso,
        "status":           "confirmed",
        "notes":            args.get("notes", ""),
    }
    row = {k: v for k, v in row.items() if v is not None and v != ""}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_REST}/reservations",
                headers={**_SUPABASE_HEADERS, "Prefer": "return=representation"},
                json=row,
            )
    except Exception as exc:
        log.error("Reservation insert HTTP error: %s", exc)
        return {"success": False, "error": f"network error: {exc}"}

    if resp.status_code not in (200, 201):
        log.error("Reservation insert failed %s: %s", resp.status_code, resp.text[:200])
        return {"success": False, "error": f"db error: {resp.text[:120]}"}

    rows = resp.json()
    new_id = rows[0]["id"] if rows else None

    return {
        "success":        True,
        "reservation_id": new_id,
        "message": (
            f"Reservation confirmed for {row['customer_name']}, "
            f"party of {row['party_size']} on {args['reservation_date']} at {args['reservation_time']}."
        ),
    }
