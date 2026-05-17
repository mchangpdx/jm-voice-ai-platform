"""Phase 3.3 — modify_appointment tool unit tests.
(Phase 3.3 — modify_appointment 단위 테스트)

Covers:
  - Tool def shape (Gemini function_declarations contract)
  - validate_modify_args (pure validator)
  - compute_diff (pure differ — happy / noop / minute-level scheduled_at)
  - modify_appointment async flow:
      * no target → appointment_no_target
      * too-late (< 30 min) → appointment_too_late
      * noop → modify_appointment_noop
      * PATCH 4xx → validation_failed
      * happy path → modify_appointment_success
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.skills.appointment.modify import (
    MODIFY_APPOINTMENT_TOOL_DEF,
    compute_diff,
    modify_appointment,
    validate_modify_args,
)


# ── Tool def shape ──────────────────────────────────────────────────────────


def test_tool_def_shape_is_gemini_compatible():
    assert "function_declarations" in MODIFY_APPOINTMENT_TOOL_DEF
    decls = MODIFY_APPOINTMENT_TOOL_DEF["function_declarations"]
    assert len(decls) == 1
    fn = decls[0]
    assert fn["name"] == "modify_appointment"
    params = fn["parameters"]
    assert set(params["required"]) == {
        "user_explicit_confirmation",
        "service_name",
        "appointment_date",
        "appointment_time",
        "duration_min",
        "customer_name",
    }
    # No customer_phone / appointment_id in the schema — caller-id only.
    assert "customer_phone" not in params["properties"]
    assert "appointment_id" not in params["properties"]


# ── validator ──────────────────────────────────────────────────────────────


def _good_args(**overrides) -> dict:
    args = {
        "user_explicit_confirmation": True,
        "service_name":     "haircut",
        "appointment_date": "2099-05-20",
        "appointment_time": "14:00",
        "duration_min":     45,
        "customer_name":    "Sophia Lopez",
        "price":            55.0,
    }
    args.update(overrides)
    return args


def test_validate_happy():
    ok, err = validate_modify_args(_good_args())
    assert ok is True and err is None


def test_validate_no_confirmation():
    ok, err = validate_modify_args(_good_args(user_explicit_confirmation=False))
    assert ok is False
    assert "user_explicit_confirmation" in err


@pytest.mark.parametrize("field", [
    "service_name", "appointment_date", "appointment_time",
    "duration_min", "customer_name",
])
def test_validate_required_missing(field):
    bad = _good_args()
    bad[field] = None
    ok, err = validate_modify_args(bad)
    assert ok is False and field in err


def test_validate_bad_date():
    ok, err = validate_modify_args(_good_args(appointment_date="05/20/2099"))
    assert ok is False and "appointment_date" in err


def test_validate_bad_time():
    ok, err = validate_modify_args(_good_args(appointment_time="2pm"))
    assert ok is False and "appointment_time" in err


@pytest.mark.parametrize("dur,ok_expected", [
    (1, True), (45, True), (600, True),
    (0, False), (-1, False), (601, False),
    ("45", False),
])
def test_validate_duration_bounds(dur, ok_expected):
    ok, _ = validate_modify_args(_good_args(duration_min=dur))
    assert ok is ok_expected


def test_validate_negative_price():
    ok, err = validate_modify_args(_good_args(price=-1))
    assert ok is False and "price" in err


# ── compute_diff ───────────────────────────────────────────────────────────


def _current_row(**overrides) -> dict:
    row = {
        "id":             42,
        "service_type":   "haircut",
        "scheduled_at":   "2099-05-20T21:00:00+00:00",  # LA 14:00 → UTC 21:00 (PDT)
        "duration_min":   45,
        "price":          55.0,
        "customer_name":  "Sophia Lopez",
        "status":         "confirmed",
    }
    row.update(overrides)
    return row


def test_diff_empty_when_payload_equals_current():
    args = _good_args()
    diff = compute_diff(
        args=args,
        current=_current_row(),
        new_scheduled_at_iso="2099-05-20T21:00:00+00:00",
    )
    assert diff == {}


def test_diff_picks_up_service_change():
    diff = compute_diff(
        args=_good_args(service_name="color"),
        current=_current_row(),
        new_scheduled_at_iso="2099-05-20T21:00:00+00:00",
    )
    assert "service_type" in diff
    assert diff["service_type"] == {"old": "haircut", "new": "color"}
    assert "customer_name" not in diff


def test_diff_minute_precision_collapses_iso_noise():
    """Same instant via different ISO formatting must be noop."""
    diff = compute_diff(
        args=_good_args(),
        current=_current_row(scheduled_at="2099-05-20T14:00:00-07:00"),
        new_scheduled_at_iso="2099-05-20T21:00:00+00:00",
    )
    assert "scheduled_at" not in diff


def test_diff_catches_time_change():
    diff = compute_diff(
        args=_good_args(appointment_time="15:00"),
        current=_current_row(),
        new_scheduled_at_iso="2099-05-20T22:00:00+00:00",
    )
    assert "scheduled_at" in diff


def test_diff_catches_duration_and_price_changes():
    diff = compute_diff(
        args=_good_args(duration_min=60, price=70),
        current=_current_row(),
        new_scheduled_at_iso="2099-05-20T21:00:00+00:00",
    )
    assert diff["duration_min"] == {"old": 45, "new": 60}
    assert diff["price"] == {"old": 55.0, "new": 70.0}


# ── async modify_appointment ───────────────────────────────────────────────


def _patch_find(target):
    """Patch _find_modifiable_appointment to return `target`."""
    return patch(
        "app.skills.appointment.modify._find_modifiable_appointment",
        new=AsyncMock(return_value=target),
    )


def _patch_update(ok: bool):
    return patch(
        "app.skills.appointment.modify._update_appointment",
        new=AsyncMock(return_value=ok),
    )


def _future_args(minutes_ahead: int = 120) -> dict:
    """Build args where appointment_time is `minutes_ahead` minutes from now (LA)."""
    when = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    return _good_args(
        appointment_date=when.strftime("%Y-%m-%d"),
        appointment_time=when.strftime("%H:%M"),
    )


@pytest.mark.asyncio
async def test_no_target_returns_no_target_hint():
    with _patch_find(None):
        out = await modify_appointment(
            store_id="s1",
            args=_future_args(120),
            caller_phone_e164="+15035551234",
            store_timezone="UTC",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "appointment_no_target"


@pytest.mark.asyncio
async def test_too_late_blocks_modify():
    """Appointment in 10 minutes → too late (< 30 min cutoff)."""
    args = _future_args(10)
    with _patch_find(_current_row(scheduled_at="2099-05-20T21:00:00+00:00")):
        out = await modify_appointment(
            store_id="s1",
            args=args,
            caller_phone_e164="+15035551234",
            store_timezone="UTC",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "appointment_too_late"
    assert out["appointment_id"] == 42


@pytest.mark.asyncio
async def test_noop_when_payload_matches_current():
    """Same instant + same fields → noop, no UPDATE issued."""
    args = _future_args(120)  # 2h ahead in UTC
    # combine_date_time(args, tz=UTC) will yield args date+time as UTC.
    # Build a current row whose scheduled_at matches that UTC instant.
    when = datetime.strptime(
        f"{args['appointment_date']} {args['appointment_time']}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=timezone.utc)
    current = _current_row(scheduled_at=when.isoformat())
    update_spy = AsyncMock(return_value=True)
    with _patch_find(current), patch(
        "app.skills.appointment.modify._update_appointment", new=update_spy
    ):
        out = await modify_appointment(
            store_id="s1",
            args=args,
            caller_phone_e164="+15035551234",
            store_timezone="UTC",
        )
    assert out["success"] is True
    assert out["ai_script_hint"] == "modify_appointment_noop"
    assert out["diff"] == {}
    update_spy.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_returns_diff_and_success_hint():
    args = _future_args(120)
    current = _current_row(
        service_type="color",   # different from args (haircut)
        scheduled_at="2099-05-20T21:00:00+00:00",
        duration_min=45,
        price=55.0,
    )
    with _patch_find(current), _patch_update(True):
        out = await modify_appointment(
            store_id="s1",
            args=args,
            caller_phone_e164="+15035551234",
            store_timezone="UTC",
        )
    assert out["success"] is True
    assert out["ai_script_hint"] == "modify_appointment_success"
    assert out["appointment_id"] == 42
    assert "service_type" in out["diff"]
    assert out["diff"]["service_type"]["new"] == "haircut"


@pytest.mark.asyncio
async def test_update_failed_returns_validation_failed():
    args = _future_args(120)
    current = _current_row(service_type="color")
    with _patch_find(current), _patch_update(False):
        out = await modify_appointment(
            store_id="s1",
            args=args,
            caller_phone_e164="+15035551234",
            store_timezone="UTC",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "validation_failed"
    assert out["reason"] == "update_failed"


@pytest.mark.asyncio
async def test_validation_failed_short_circuits_without_db():
    """Bad confirmation → no DB call at all."""
    with patch(
        "app.skills.appointment.modify._find_modifiable_appointment"
    ) as find_spy:
        out = await modify_appointment(
            store_id="s1",
            args=_good_args(user_explicit_confirmation=False),
            caller_phone_e164="+15035551234",
        )
        find_spy.assert_not_called()
    assert out["success"] is False
    assert out["ai_script_hint"] == "validation_failed"
