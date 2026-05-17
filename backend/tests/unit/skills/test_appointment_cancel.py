"""Phase 3.4 — cancel_appointment tool unit tests.
(Phase 3.4 — cancel_appointment 단위 테스트)

Covers:
  - Tool def shape (caller-id only — only user_explicit_confirmation in args)
  - hours_until pure helper
  - cancel_appointment flow:
      * no target ever → cancel_appointment_no_target
      * already cancelled → cancel_appointment_already_canceled
      * ≥ 24h → cancel_appointment_success
      * < 24h → cancel_appointment_late_cancel (still applied, fee hint)
      * PATCH 4xx → cancel_appointment_failed
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.skills.appointment.cancel import (
    CANCEL_APPOINTMENT_TOOL_DEF,
    cancel_appointment,
    hours_until,
)


# ── Tool def shape ──────────────────────────────────────────────────────────


def test_tool_def_caller_id_only():
    """Schema must NOT accept customer_phone / appointment_id / customer_name."""
    decls = CANCEL_APPOINTMENT_TOOL_DEF["function_declarations"]
    assert len(decls) == 1
    fn = decls[0]
    assert fn["name"] == "cancel_appointment"
    params = fn["parameters"]
    assert params["required"] == ["user_explicit_confirmation"]
    props = params["properties"]
    # The whole point of caller-id-only is that NOTHING else is in the schema.
    assert set(props.keys()) == {"user_explicit_confirmation"}


# ── hours_until ────────────────────────────────────────────────────────────


def test_hours_until_future():
    now    = datetime(2099, 5, 20, 12, 0, tzinfo=timezone.utc)
    when   = (now + timedelta(hours=48)).isoformat()
    assert hours_until(when, now=now) == pytest.approx(48.0)


def test_hours_until_past_is_negative():
    now    = datetime(2099, 5, 20, 12, 0, tzinfo=timezone.utc)
    when   = (now - timedelta(hours=3)).isoformat()
    assert hours_until(when, now=now) == pytest.approx(-3.0)


def test_hours_until_parse_failure_returns_zero():
    assert hours_until("not an iso") == 0.0
    assert hours_until("") == 0.0


def test_hours_until_handles_zulu_suffix():
    now  = datetime(2099, 5, 20, 12, 0, tzinfo=timezone.utc)
    when = "2099-05-21T12:00:00Z"
    assert hours_until(when, now=now) == pytest.approx(24.0)


# ── Patches ────────────────────────────────────────────────────────────────


def _patch_find_confirmed(target):
    return patch(
        "app.skills.appointment.cancel._find_modifiable_appointment",
        new=AsyncMock(return_value=target),
    )


def _patch_find_any(recent):
    return patch(
        "app.skills.appointment.cancel._find_recent_appointment_any_status",
        new=AsyncMock(return_value=recent),
    )


def _patch_status_update(ok: bool):
    return patch(
        "app.skills.appointment.cancel._update_appointment_status",
        new=AsyncMock(return_value=ok),
    )


def _row(**overrides) -> dict:
    base = {
        "id":            7,
        "service_type":  "haircut",
        "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
        "customer_name": "Sophia Lopez",
        "status":        "confirmed",
    }
    base.update(overrides)
    return base


# ── No target paths ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_target_anywhere_returns_no_target():
    with _patch_find_confirmed(None), _patch_find_any(None):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "cancel_appointment_no_target"


@pytest.mark.asyncio
async def test_already_cancelled_returns_specific_hint():
    cancelled = _row(status="cancelled", id=99)
    with _patch_find_confirmed(None), _patch_find_any(cancelled):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "cancel_appointment_already_canceled"
    assert out["appointment_id"] == 99


@pytest.mark.asyncio
async def test_no_confirmed_but_recent_fulfilled_collapses_to_no_target():
    """fulfilled / no_show / anything-not-cancelled all collapse to no_target."""
    fulfilled = _row(status="fulfilled", id=88)
    with _patch_find_confirmed(None), _patch_find_any(fulfilled):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["ai_script_hint"] == "cancel_appointment_no_target"


# ── Success paths ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_success_far_future():
    """≥ 24h → success hint, no late-fee flag."""
    far = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    target = _row(scheduled_at=far)
    with _patch_find_confirmed(target), _patch_status_update(True):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["success"] is True
    assert out["ai_script_hint"] == "cancel_appointment_success"
    assert out["is_late_cancel"] is False
    assert out["hours_until_appointment"] > 24


@pytest.mark.asyncio
async def test_cancel_late_window_returns_late_hint_but_still_succeeds():
    """< 24h → success, late_cancel hint + flag, fee policy left to voice handler."""
    near = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    target = _row(scheduled_at=near)
    with _patch_find_confirmed(target), _patch_status_update(True):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["success"] is True
    assert out["ai_script_hint"] == "cancel_appointment_late_cancel"
    assert out["is_late_cancel"] is True
    assert out["late_cancel_window_hours"] == 24


@pytest.mark.asyncio
async def test_patch_failure_returns_cancel_failed():
    target = _row()
    with _patch_find_confirmed(target), _patch_status_update(False):
        out = await cancel_appointment(
            store_id="s1", caller_phone_e164="+15035551234",
        )
    assert out["success"] is False
    assert out["ai_script_hint"] == "cancel_appointment_failed"
    assert out["appointment_id"] == 7
