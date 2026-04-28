# Reservation skill — TDD tests for Gemini Function Calling integration
# (예약 스킬 — Gemini Function Calling 통합 TDD 테스트)
#
# Strategy: stable first, scalable later (CLAUDE.md guidance).
# - One tool: make_reservation
# - Server-side resolution of store_id / call_log_id (never trusted from args)
# - user_explicit_confirmation lock: prevents phantom bookings

import pytest
from unittest.mock import AsyncMock, patch


STORE_ID    = "7c425fcb-91c7-4eb7-982a-591c094ba9c9"
CALL_LOG_ID = "call_test_abc"

VALID_ARGS = {
    "user_explicit_confirmation": True,
    "customer_name":   "Michael Chang",
    "customer_phone":  "+15037079566",
    "reservation_date": "2026-04-30",
    "reservation_time": "19:00",
    "party_size":       4,
    "notes":            "window seat please",
}


# ── Tool definition ───────────────────────────────────────────────────────────

def test_tool_def_name_is_make_reservation():
    from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF
    fns = RESERVATION_TOOL_DEF["function_declarations"]
    names = [f["name"] for f in fns]
    assert "make_reservation" in names


def test_tool_def_required_fields_match_schema():
    from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF
    fn = next(f for f in RESERVATION_TOOL_DEF["function_declarations"]
              if f["name"] == "make_reservation")
    required = set(fn["parameters"]["required"])
    expected = {
        "user_explicit_confirmation", "customer_name", "customer_phone",
        "reservation_date", "reservation_time", "party_size",
    }
    assert required == expected


def test_tool_def_does_not_require_email():
    """Our reservations table has no email column — keep tool surface minimal."""
    from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF
    fn = next(f for f in RESERVATION_TOOL_DEF["function_declarations"]
              if f["name"] == "make_reservation")
    assert "customer_email" not in fn["parameters"]["required"]


def test_tool_def_does_not_expose_store_id():
    """store_id MUST be resolved server-side — never accept from Gemini."""
    from app.skills.scheduler.reservation import RESERVATION_TOOL_DEF
    fn = next(f for f in RESERVATION_TOOL_DEF["function_declarations"]
              if f["name"] == "make_reservation")
    props = fn["parameters"]["properties"]
    assert "store_id" not in props


# ── validate_args ─────────────────────────────────────────────────────────────

def test_validate_passes_for_complete_args():
    from app.skills.scheduler.reservation import validate_reservation_args
    ok, err = validate_reservation_args(VALID_ARGS)
    assert ok is True
    assert err == ""


def test_validate_rejects_unconfirmed():
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {**VALID_ARGS, "user_explicit_confirmation": False}
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "confirm" in err.lower()


def test_validate_rejects_missing_required():
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {k: v for k, v in VALID_ARGS.items() if k != "customer_phone"}
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "customer_phone" in err


def test_validate_rejects_party_size_zero():
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {**VALID_ARGS, "party_size": 0}
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "party_size" in err.lower()


def test_validate_rejects_bad_date_format():
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {**VALID_ARGS, "reservation_date": "April 30"}
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "date" in err.lower()


def test_validate_rejects_bad_time_format():
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {**VALID_ARGS, "reservation_time": "7pm"}
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "time" in err.lower()


def test_validate_rejects_phone_with_too_few_digits():
    """9th call regression: STT cut off after 7 digits, '97150337727' (no +) was
    accepted by normalize_phone_us as as-is. Validator MUST reject incomplete."""
    from app.skills.scheduler.reservation import validate_reservation_args
    for bad_phone in ["971503", "9715033", "97150337", "971503377"]:  # 6, 7, 8, 9 digits
        args = {**VALID_ARGS, "customer_phone": bad_phone}
        ok, err = validate_reservation_args(args)
        assert ok is False, f"expected reject for {bad_phone!r}"
        assert "phone" in err.lower()


def test_validate_accepts_10_or_11_digit_phone_in_various_formats():
    from app.skills.scheduler.reservation import validate_reservation_args
    for good_phone in ["5037079566", "503-707-9566", "(503) 707-9566",
                       "+15037079566", "1-503-707-9566", "15037079566"]:
        args = {**VALID_ARGS, "customer_phone": good_phone}
        ok, err = validate_reservation_args(args)
        assert ok is True, f"expected accept for {good_phone!r}, got {err}"


def test_validate_rejects_11_digit_with_wrong_country_code():
    """11-digit phone where first digit is NOT 1 (e.g. our 9th-call '97150337727'
    that came from STT misread — looks like 11 chars but wrong shape)."""
    from app.skills.scheduler.reservation import validate_reservation_args
    args = {**VALID_ARGS, "customer_phone": "97150337727"}  # the actual 9th-call value
    ok, err = validate_reservation_args(args)
    assert ok is False
    assert "phone" in err.lower() or "country" in err.lower()


# ── combine_date_time ─────────────────────────────────────────────────────────

def test_combine_produces_iso_8601_with_tz():
    from app.skills.scheduler.reservation import combine_date_time
    iso = combine_date_time("2026-04-30", "19:00", tz="America/Los_Angeles")
    assert iso.startswith("2026-04-30T19:00:00")
    # PDT is UTC-7 (April after DST starts)
    assert iso.endswith("-07:00")


def test_combine_handles_utc():
    from app.skills.scheduler.reservation import combine_date_time
    iso = combine_date_time("2026-04-30", "19:00", tz="UTC")
    assert iso == "2026-04-30T19:00:00+00:00"


# ── insert_reservation (DB integration, mocked) ───────────────────────────────

@pytest.mark.asyncio
async def test_insert_reservation_success_returns_id_and_message():
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 999}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        result = await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

    assert result["success"] is True
    assert result["reservation_id"] == 999
    assert "Michael Chang" in result["message"] or "confirmed" in result["message"].lower()


@pytest.mark.asyncio
async def test_insert_reservation_rejects_unconfirmed_without_db_call():
    from app.skills.scheduler import reservation as r

    args = {**VALID_ARGS, "user_explicit_confirmation": False}

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = AsyncMock()

        result = await r.insert_reservation(args, STORE_ID, CALL_LOG_ID)

    assert result["success"] is False
    assert "confirm" in result["error"].lower()
    instance.post.assert_not_called()


@pytest.mark.asyncio
async def test_insert_reservation_uses_server_side_store_id():
    """Even if args contain a different store_id, server uses its own."""
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    args_with_fake = {**VALID_ARGS, "store_id": "ATTACKER_STORE_ID"}

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        await r.insert_reservation(args_with_fake, STORE_ID, CALL_LOG_ID)

        sent_payload = instance.post.call_args.kwargs["json"]
        assert sent_payload["store_id"] == STORE_ID


@pytest.mark.asyncio
async def test_insert_reservation_combines_date_and_time_into_reservation_time():
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

        sent_payload = instance.post.call_args.kwargs["json"]
        assert sent_payload["reservation_time"].startswith("2026-04-30T19:00:00")
        # date + time keys should NOT be in DB row
        assert "reservation_date" not in sent_payload


@pytest.mark.asyncio
async def test_insert_reservation_handles_db_failure_gracefully():
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 500
    fake_resp.text = "internal server error"

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        result = await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

    assert result["success"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_insert_reservation_sets_status_confirmed():
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

        sent_payload = instance.post.call_args.kwargs["json"]
        assert sent_payload["status"] == "confirmed"
        assert sent_payload["customer_name"]  == "Michael Chang"
        assert sent_payload["customer_phone"] == "+15037079566"
        assert sent_payload["party_size"]     == 4


# ── Time format helpers ──────────────────────────────────────────────────────

def test_format_time_12h_pm():
    from app.skills.scheduler.reservation import format_time_12h
    assert format_time_12h("19:00") == "7:00 PM"
    assert format_time_12h("13:30") == "1:30 PM"
    assert format_time_12h("12:00") == "12:00 PM"


def test_format_time_12h_am():
    from app.skills.scheduler.reservation import format_time_12h
    assert format_time_12h("08:30") == "8:30 AM"
    assert format_time_12h("00:00") == "12:00 AM"
    assert format_time_12h("00:15") == "12:15 AM"


def test_format_date_human():
    from app.skills.scheduler.reservation import format_date_human
    # 2026-04-28 was a Tuesday in Gregorian — verify weekday format
    s = format_date_human("2026-04-28")
    assert "April" in s
    assert "28" in s


# ── Phone normalization ──────────────────────────────────────────────────────

def test_normalize_phone_10_digits_to_e164():
    from app.skills.scheduler.reservation import normalize_phone_us
    assert normalize_phone_us("5037079566")    == "+15037079566"
    assert normalize_phone_us("503-707-9566")  == "+15037079566"
    assert normalize_phone_us("(503) 707-9566") == "+15037079566"


def test_normalize_phone_already_e164_unchanged():
    from app.skills.scheduler.reservation import normalize_phone_us
    assert normalize_phone_us("+15037079566") == "+15037079566"


def test_normalize_phone_11_digit_us_prefix():
    from app.skills.scheduler.reservation import normalize_phone_us
    assert normalize_phone_us("15037079566") == "+15037079566"


def test_normalize_phone_passes_unknown_format():
    from app.skills.scheduler.reservation import normalize_phone_us
    # Non-US, non-standard — return as-is
    assert normalize_phone_us("") == ""


@pytest.mark.asyncio
async def test_insert_reservation_normalizes_phone_in_db_payload():
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    args = {**VALID_ARGS, "customer_phone": "503-707-9566"}

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        await r.insert_reservation(args, STORE_ID, CALL_LOG_ID)

        sent_payload = instance.post.call_args.kwargs["json"]
        assert sent_payload["customer_phone"] == "+15037079566"


# ── Idempotency + 12-hour message ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_reservation_message_uses_12_hour_time():
    """Spoken response back to customer must use 7:00 PM, not 19:00."""
    from app.skills.scheduler import reservation as r

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        result = await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

    assert "7:00 PM" in result["message"]
    assert "19:00" not in result["message"]


@pytest.mark.asyncio
async def test_insert_reservation_idempotent_returns_existing_id():
    """Second call within 5 min for same store+phone+time returns same id, no duplicate INSERT."""
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: [{"id": 999}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock()  # should never be called

        result = await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

    assert result["success"] is True
    assert result["reservation_id"] == 999
    assert result["idempotent"] is True
    instance.post.assert_not_called()


@pytest.mark.asyncio
async def test_insert_reservation_inserts_when_no_idempotent_match():
    """Probe returns empty → POST runs normally."""
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_post = AsyncMock()
    fake_post.status_code = 201
    fake_post.json = lambda: [{"id": 42}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_post)

        result = await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

    assert result["success"] is True
    assert result["reservation_id"] == 42
    assert result["idempotent"] is False
    instance.post.assert_called_once()


@pytest.mark.asyncio
async def test_insert_reservation_skips_call_log_id_for_fk_safety():
    """FK constraint reservations.call_log_id → call_logs.call_id fails mid-call,
    because call_logs row is only created by post-call webhook. Backfill happens later.
    """
    from app.skills.scheduler import reservation as r

    fake_probe = AsyncMock()
    fake_probe.status_code = 200
    fake_probe.json = lambda: []

    fake_resp = AsyncMock()
    fake_resp.status_code = 201
    fake_resp.json = lambda: [{"id": 1}]

    with patch("app.skills.scheduler.reservation.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get  = AsyncMock(return_value=fake_probe)
        instance.post = AsyncMock(return_value=fake_resp)

        await r.insert_reservation(VALID_ARGS, STORE_ID, CALL_LOG_ID)

        sent_payload = instance.post.call_args.kwargs["json"]
        assert "call_log_id" not in sent_payload
