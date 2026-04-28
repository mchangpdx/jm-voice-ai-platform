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
from datetime import datetime, timedelta
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

    # Phone must be 10-digit US OR 11-digit (1-prefix) OR already +E.164 with ≥10 digits.
    # 9th call exposed: STT cut user off after 7 digits, '97150337727' (11 chars, no +)
    # passed our normalize_phone_us but is invalid. Reject incomplete numbers up-front.
    # (전화번호 자릿수 부족 차단 — 9차 통화에서 7자리만 입력된 채 통과한 회귀 방지)
    phone_digits_only = re.sub(r"\D", "", str(args["customer_phone"]))
    if len(phone_digits_only) not in (10, 11):
        return False, "customer_phone must be 10 or 11 digits (US format)"
    if len(phone_digits_only) == 11 and not phone_digits_only.startswith("1"):
        return False, "11-digit phone must start with country code 1 (US)"

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


def format_time_12h(time_str: str) -> str:
    """Convert HH:MM 24-hour string to '7:00 PM' style (12-hour with AM/PM).
    (24시간제 HH:MM → '7:00 PM' 형식 12시간제 변환)
    """
    h, m = time_str.split(":")
    h_int = int(h)
    suffix = "AM" if h_int < 12 else "PM"
    h12 = h_int % 12 or 12
    return f"{h12}:{m} {suffix}"


def format_date_human(date_str: str) -> str:
    """Convert YYYY-MM-DD to 'Tuesday, April 28' (no year for short voice).
    (YYYY-MM-DD → 'Tuesday, April 28' 음성용 짧은 형식)
    """
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%A, %B %-d")


def normalize_phone_us(phone: str) -> str:
    """Normalize US phone to E.164 (+1XXXXXXXXXX). Idempotent on already-formatted strings.
    (미국 전화번호 E.164 정규화 — 이미 정규화된 문자열에는 영향 없음)

    Handles: '503-707-9566' / '(503) 707-9566' / '5037079566' / '15037079566'
             / '+15037079566' / '+1 503 707 9566'
    """
    if not phone:
        return phone
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) == 10:
        return f"+1{cleaned}"
    if len(cleaned) == 11 and cleaned.startswith("1"):
        return f"+{cleaned}"
    if phone.startswith("+"):
        return f"+{cleaned}"
    return phone  # leave as-is for unknown formats


# ── Async DB insert ──────────────────────────────────────────────────────────

async def insert_reservation(
    args: dict[str, Any],
    store_id: str,
    call_log_id: Optional[str] = None,
    tz: str = "America/Los_Angeles",
) -> dict[str, Any]:
    """Insert a reservation row in Supabase. Pure server-side; ignores any store_id in args.
    (Supabase에 예약 행 삽입. 서버 측 처리 — args의 store_id는 무시)

    Idempotency: if a row already exists for the same store + phone + reservation_time
    within the last 5 minutes, return that row's id instead of creating a duplicate.
    (중복 차단: 동일 store + phone + reservation_time이 5분 내 존재하면 기존 row 반환)

    Returns:
        {"success": True,  "reservation_id": int, "message": str, "idempotent": bool}
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

    # Normalize phone to E.164 so idempotency probe + analytics see consistent format
    # (E.164로 정규화 — idempotency 검사 + 분석에서 일관된 형식 보장)
    customer_phone_e164 = normalize_phone_us(args["customer_phone"])

    time_12h     = format_time_12h(args["reservation_time"])
    date_human   = format_date_human(args["reservation_date"])
    success_msg  = (
        f"Reservation confirmed for {args['customer_name']}, "
        f"party of {int(args['party_size'])}, on {date_human} at {time_12h}."
    )

    # NOTE: call_log_id is intentionally NOT inserted here. The reservations.call_log_id
    # column has a FK to call_logs.call_id, but the call_logs row is only created by the
    # post-call webhook AFTER the call ends. Linking happens via a separate backfill step.
    # (call_log_id는 의도적으로 INSERT 제외 — call_logs 행은 통화 종료 webhook에서 생성됨.
    #  통화 종료 후 customer_phone + reservation_time으로 매칭하여 별도 백필 처리)
    row = {
        "store_id":         store_id,                 # always server-resolved
        "customer_name":    args["customer_name"],
        "customer_phone":   customer_phone_e164,
        "party_size":       int(args["party_size"]),
        "reservation_time": reservation_time_iso,
        "status":           "confirmed",
        "notes":            args.get("notes", ""),
    }
    row = {k: v for k, v in row.items() if v is not None and v != ""}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Idempotency probe: same store + phone + time exists in last 5 min?
            # (중복 검사: 같은 store + phone + time이 5분 내 있는지)
            since_iso = (datetime.now(ZoneInfo("UTC")) - timedelta(minutes=5)).isoformat()
            probe = await client.get(
                f"{_REST}/reservations",
                headers=_SUPABASE_HEADERS,
                params={
                    "store_id":         f"eq.{store_id}",
                    "customer_phone":   f"eq.{customer_phone_e164}",
                    "reservation_time": f"eq.{reservation_time_iso}",
                    "created_at":       f"gte.{since_iso}",
                    "select":           "id",
                    "limit":            "1",
                },
            )
            if probe.status_code == 200 and probe.json():
                existing_id = probe.json()[0]["id"]
                log.info("Reservation idempotent hit: id=%s for phone=%s", existing_id, args["customer_phone"])
                return {
                    "success":        True,
                    "reservation_id": existing_id,
                    "message":        success_msg,
                    "idempotent":     True,
                }

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
        "message":        success_msg,
        "idempotent":     False,
    }
