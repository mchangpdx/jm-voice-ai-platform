"""book_appointment — Gemini Function Calling tool for service appointments.
(book_appointment — 서비스 예약용 Gemini Function Calling 도구)

Architecture mirrors `skills/scheduler/reservation.py`:
  - One tool: book_appointment
  - Server-side resolution of store_id + call_log_id (never from Gemini args)
  - user_explicit_confirmation lock (prevents phantom bookings)
  - Pure helpers (validate_appointment_args, combine_date_time) → unit-testable
  - insert_appointment is async, awaits Supabase REST insert

Target table: `appointments` (already exists, populated by gen_beauty_demo.py).
Service-kind verticals (beauty, future auto_repair / home_services) use this
path instead of bridge_transactions because the appointment schema fits
the domain natively (service_type, scheduled_at, duration_min, price).

Flow:
  Gemini collects 5-6 fields → recites summary → user says "yes"
  → Gemini calls book_appointment with user_explicit_confirmation=true
  → server validates → combines date+time → INSERT → returns appointment_id
"""
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


# ── Tool definition (Voice Engine ↔ Gemini / OpenAI Realtime) ────────────────


BOOK_APPOINTMENT_TOOL_DEF: dict = {
    "function_declarations": [
        {
            "name": "book_appointment",
            "description": (
                "Book a confirmed service appointment for the customer. "
                "BEFORE calling this tool you MUST: "
                "(a) collect every required field (service name, date, time, "
                "duration estimate, customer name, customer phone), "
                "(b) recite the full booking summary back to the customer "
                "(service + stylist if any + date + time + duration + price), "
                "(c) receive an explicit verbal 'yes' from the customer. "
                "Only then set user_explicit_confirmation=true. "
                "Never call this tool without verbal confirmation. "
                "Service names must come from the store's service catalog — "
                "call service_lookup first if unsure of duration or price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_explicit_confirmation": {
                        "type": "boolean",
                        "description": (
                            "Set to true ONLY after the customer has verbally said 'yes' "
                            "to your booking summary. False or missing = do not call."
                        ),
                    },
                    "service_name": {
                        "type": "string",
                        "description": (
                            "Service the customer wants (e.g. 'haircut', 'color', "
                            "'manicure'). Use the service catalog naming; the system "
                            "fuzzy-matches against the store's menu_items where "
                            "service_kind is not null."
                        ),
                    },
                    "appointment_date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (e.g. 2026-05-20).",
                    },
                    "appointment_time": {
                        "type": "string",
                        "description": "Time in HH:MM 24-hour format (e.g. 14:00 for 2 PM).",
                    },
                    "duration_min": {
                        "type": "integer",
                        "description": (
                            "Estimated duration in minutes. Pull from service_lookup "
                            "result. Required so the scheduler can hold the right slot."
                        ),
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name as spoken by the customer (STT verbatim).",
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "Phone number (digits and + only). Usually caller ID.",
                    },
                    "stylist_preference": {
                        "type": "string",
                        "description": (
                            "Optional stylist name the customer asked for (e.g. 'Maria'). "
                            "Empty string or 'any' if no preference."
                        ),
                    },
                    "price": {
                        "type": "number",
                        "description": (
                            "Quoted price in USD (no tip). Use the value returned by "
                            "service_lookup. May be 0 if pricing requires in-person "
                            "consultation (rare)."
                        ),
                    },
                    "customer_email": {
                        "type": "string",
                        "description": (
                            "Optional email for the booking confirmation while SMS "
                            "delivery is being verified. NATO-verified letter by letter."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes (allergies, preferred style, etc.).",
                    },
                },
                "required": [
                    "user_explicit_confirmation",
                    "service_name",
                    "appointment_date",
                    "appointment_time",
                    "duration_min",
                    "customer_name",
                    "customer_phone",
                ],
            },
        }
    ]
}


# ── Pure helpers (unit-testable) ─────────────────────────────────────────────


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")


def validate_appointment_args(args: dict) -> tuple[bool, Optional[str]]:
    """Validate book_appointment args. Returns (ok, error_message).
    (book_appointment args 검증 — 순수 함수, 단위 테스트 가능)
    """
    if not args.get("user_explicit_confirmation"):
        return False, "user_explicit_confirmation must be true"

    for required in (
        "service_name", "appointment_date", "appointment_time",
        "duration_min", "customer_name", "customer_phone",
    ):
        if not args.get(required) and args.get(required) != 0:
            return False, f"missing required field: {required}"

    date_s = args["appointment_date"]
    time_s = args["appointment_time"]

    if not _DATE_RE.match(date_s):
        return False, f"appointment_date must be YYYY-MM-DD (got {date_s!r})"
    if not _TIME_RE.match(time_s):
        return False, f"appointment_time must be HH:MM 24-hour (got {time_s!r})"

    duration = args["duration_min"]
    if not isinstance(duration, int) or duration <= 0 or duration > 600:
        return False, f"duration_min must be a positive integer ≤ 600 (got {duration!r})"

    phone = args["customer_phone"]
    if not _PHONE_RE.match(phone):
        return False, f"customer_phone invalid (got {phone!r})"

    price = args.get("price", 0)
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        return False, f"price must be non-negative number (got {price!r})"

    return True, None


def combine_date_time(
    date_s: str,
    time_s: str,
    *,
    tz: str = "America/Los_Angeles",
) -> str:
    """Combine YYYY-MM-DD + HH:MM into an ISO 8601 UTC string.
    (date + time → 매장 timezone 적용 → UTC ISO 변환)

    Mirrors `reservation.combine_date_time` so behavior stays consistent
    across reservation and appointment paths.
    """
    naive = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M")
    aware = naive.replace(tzinfo=ZoneInfo(tz))
    return aware.astimezone(ZoneInfo("UTC")).isoformat()


# ── Async insert ─────────────────────────────────────────────────────────────


async def insert_appointment(
    *,
    store_id:        str,
    call_log_id:     str,
    args:            dict,
    store_timezone:  str = "America/Los_Angeles",
) -> dict:
    """INSERT into `appointments`. Returns the inserted row.
    (appointments INSERT — store_id/call_log_id은 server-side resolution)

    Caller is responsible for validating args via `validate_appointment_args`
    BEFORE calling this. Caller is also responsible for fuzzy-matching
    service_name against the menu_items catalog (passes the resolved
    service_type here).
    """
    scheduled_at = combine_date_time(
        args["appointment_date"],
        args["appointment_time"],
        tz=store_timezone,
    )

    row = {
        "store_id":       store_id,
        "call_log_id":    call_log_id,
        "service_type":   args["service_name"],
        "scheduled_at":   scheduled_at,
        "duration_min":   int(args["duration_min"]),
        "price":          float(args.get("price") or 0),
        "customer_name":  args["customer_name"],
        "customer_phone": args["customer_phone"],
        "status":         "confirmed",
    }

    headers = {**_SUPABASE_HEADERS, "Prefer": "return=representation"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_REST}/appointments",
            headers=headers,
            json=[row],
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"appointments INSERT failed: {resp.status_code} {resp.text[:300]}"
        )
    inserted = resp.json() or []
    if not inserted:
        raise RuntimeError("appointments INSERT returned no rows")
    log.info(
        "appointment.book ok store=%s service=%s at=%s id=%s",
        store_id, row["service_type"], scheduled_at, inserted[0].get("id"),
    )
    return inserted[0]


__all__ = [
    "BOOK_APPOINTMENT_TOOL_DEF",
    "combine_date_time",
    "insert_appointment",
    "validate_appointment_args",
]
