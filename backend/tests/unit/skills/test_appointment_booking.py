"""Phase 3.1 — book_appointment tool unit tests.
(Phase 3.1 — book_appointment 단위 테스트)

Covers the two pure helpers (`validate_appointment_args`,
`combine_date_time`) plus the async `insert_appointment` happy + error
paths via a mocked httpx client. The tool def itself is also smoke-checked
for shape so the dispatcher (Phase 3.6) gets a stable contract.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.skills.appointment.booking import (
    BOOK_APPOINTMENT_TOOL_DEF,
    combine_date_time,
    insert_appointment,
    validate_appointment_args,
)


# ── Tool def shape ──────────────────────────────────────────────────────────


def test_tool_def_shape_is_gemini_compatible():
    """Mirrors the function_declarations shape used by other voice tools."""
    assert "function_declarations" in BOOK_APPOINTMENT_TOOL_DEF
    decls = BOOK_APPOINTMENT_TOOL_DEF["function_declarations"]
    assert len(decls) == 1
    fn = decls[0]
    assert fn["name"] == "book_appointment"
    assert "description" in fn
    params = fn["parameters"]
    # Required field set
    required = set(params["required"])
    assert required == {
        "user_explicit_confirmation",
        "service_name",
        "appointment_date",
        "appointment_time",
        "duration_min",
        "customer_name",
        "customer_phone",
    }
    # Optional fields are declared in properties
    props = params["properties"]
    for opt in ("stylist_preference", "price", "customer_email", "notes"):
        assert opt in props, f"optional field {opt} missing from properties"


# ── validate_appointment_args ──────────────────────────────────────────────


def _good_args(**overrides) -> dict:
    """Baseline args that pass validation. Override per test.
    (검증 통과하는 baseline — 각 test에서 override)
    """
    args = {
        "user_explicit_confirmation": True,
        "service_name":     "haircut",
        "appointment_date": "2026-05-20",
        "appointment_time": "14:00",
        "duration_min":     45,
        "customer_name":    "Sophia Lopez",
        "customer_phone":   "+15035551234",
        "price":            55.0,
    }
    args.update(overrides)
    return args


def test_valid_args_pass():
    ok, err = validate_appointment_args(_good_args())
    assert ok is True
    assert err is None


def test_missing_confirmation_fails():
    ok, err = validate_appointment_args(_good_args(user_explicit_confirmation=False))
    assert ok is False
    assert "user_explicit_confirmation" in err


def test_each_required_field_missing_fails():
    for field in ("service_name", "appointment_date", "appointment_time",
                  "duration_min", "customer_name", "customer_phone"):
        bad = _good_args()
        bad[field] = None
        ok, err = validate_appointment_args(bad)
        assert ok is False, f"missing {field} should fail"
        assert field in err, f"error should mention {field}"


def test_bad_date_format_fails():
    ok, err = validate_appointment_args(_good_args(appointment_date="2026/05/20"))
    assert ok is False
    assert "appointment_date" in err


def test_bad_time_format_fails():
    ok, err = validate_appointment_args(_good_args(appointment_time="2pm"))
    assert ok is False
    assert "appointment_time" in err


@pytest.mark.parametrize("dur,ok_expected", [
    (45, True),
    (60, True),
    (600, True),
    (0, False),
    (-5, False),
    (601, False),
    ("45", False),    # string rejected
])
def test_duration_bounds(dur, ok_expected):
    ok, _ = validate_appointment_args(_good_args(duration_min=dur))
    assert ok is ok_expected


def test_bad_phone_format_fails():
    ok, err = validate_appointment_args(_good_args(customer_phone="abc"))
    assert ok is False
    assert "customer_phone" in err


def test_negative_price_fails():
    ok, err = validate_appointment_args(_good_args(price=-10))
    assert ok is False
    assert "price" in err


def test_price_optional_when_zero():
    """price=0 is valid (consultation services price in person)."""
    ok, err = validate_appointment_args(_good_args(price=0))
    assert ok is True


# ── combine_date_time ──────────────────────────────────────────────────────


def test_combine_date_time_produces_utc_iso():
    """LA 2026-05-20 14:00 → UTC 2026-05-20T21:00:00+00:00 (PDT)."""
    out = combine_date_time("2026-05-20", "14:00", tz="America/Los_Angeles")
    assert out.startswith("2026-05-20T21:00:00")


def test_combine_date_time_handles_different_tz():
    """Eastern 09:00 → UTC 13:00 (EDT)."""
    out = combine_date_time("2026-05-20", "09:00", tz="America/New_York")
    assert out.startswith("2026-05-20T13:00:00")


# ── insert_appointment (mocked httpx) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_appointment_happy_path():
    """201 response → returns row, no exception."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 201
    mock_resp.json = lambda: [{
        "id": 42,
        "store_id": "store-uuid",
        "service_type": "haircut",
        "scheduled_at": "2026-05-20T21:00:00+00:00",
    }]
    with patch("app.skills.appointment.booking.httpx.AsyncClient") as ac_cls:
        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        ac_cls.return_value.__aenter__.return_value = client
        out = await insert_appointment(
            store_id="store-uuid",
            call_log_id="CA-test-001",
            args=_good_args(),
        )
    assert out["id"] == 42
    assert out["service_type"] == "haircut"


@pytest.mark.asyncio
async def test_insert_appointment_non_2xx_raises():
    """Supabase 4xx/5xx → RuntimeError. (4xx/5xx → orchestrator rollback)"""
    mock_resp = AsyncMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid scheduled_at"
    with patch("app.skills.appointment.booking.httpx.AsyncClient") as ac_cls:
        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        ac_cls.return_value.__aenter__.return_value = client
        with pytest.raises(RuntimeError, match="INSERT failed"):
            await insert_appointment(
                store_id="store-uuid",
                call_log_id="CA-test-001",
                args=_good_args(),
            )


@pytest.mark.asyncio
async def test_insert_appointment_empty_response_raises():
    """200 with empty array → RuntimeError (Supabase Prefer=return=representation contract)."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 201
    mock_resp.json = lambda: []
    with patch("app.skills.appointment.booking.httpx.AsyncClient") as ac_cls:
        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        ac_cls.return_value.__aenter__.return_value = client
        with pytest.raises(RuntimeError, match="no rows"):
            await insert_appointment(
                store_id="store-uuid",
                call_log_id="CA-test-001",
                args=_good_args(),
            )


@pytest.mark.asyncio
async def test_insert_appointment_uses_resolved_scheduled_at():
    """The async insert uses combine_date_time on the supplied date+time."""
    captured: dict = {}
    mock_resp = AsyncMock()
    mock_resp.status_code = 201
    mock_resp.json = lambda: [{"id": 1}]

    async def fake_post(url, headers=None, json=None):
        captured["url"]  = url
        captured["json"] = json
        return mock_resp

    with patch("app.skills.appointment.booking.httpx.AsyncClient") as ac_cls:
        client = AsyncMock()
        client.post = fake_post
        ac_cls.return_value.__aenter__.return_value = client
        await insert_appointment(
            store_id="s1",
            call_log_id="CL1",
            args=_good_args(appointment_date="2026-06-01", appointment_time="10:30"),
            store_timezone="America/Los_Angeles",
        )

    row = captured["json"][0]
    assert row["store_id"] == "s1"
    assert row["call_log_id"] == "CL1"
    assert row["service_type"] == "haircut"
    assert row["duration_min"] == 45
    assert row["status"] == "confirmed"
    # LA 10:30 → UTC 17:30 (PDT in June)
    assert row["scheduled_at"].startswith("2026-06-01T17:30:00")
