# B3 — flows.modify_reservation TDD
# (B3 — flows.modify_reservation 테스트 우선 작성)
#
# Per spec backend/docs/specs/B3_modify_reservation.md.
#
# modify_reservation(store_id, args, caller_phone_e164, call_log_id) updates
# the most-recent confirmed reservation for the same caller phone (status =
# 'confirmed', ORDER BY created_at DESC LIMIT 1), enforcing:
#   - 30-min cutoff (reservation_too_late)
#   - business_hours window for new time
#   - 1 <= party_size <= 20
#   - placeholder customer_name rejection (is_placeholder_name)
#   - full payload contract (all 5 mutable fields present, bridge computes diff)
#
# Tests written BEFORE the implementation — all should fail until
# flows.modify_reservation lands. RED → implementation → GREEN.

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


CALLER  = "+15035551234"
STORE   = "STORE_UUID"
DEFAULT_TZ = "America/Los_Angeles"


def _future_dt_iso(minutes_ahead: int = 90) -> tuple[str, str, str]:
    """Return (date YYYY-MM-DD, time HH:MM, full ISO string) for now + N min."""
    from zoneinfo import ZoneInfo
    target = datetime.now(ZoneInfo(DEFAULT_TZ)) + timedelta(minutes=minutes_ahead)
    return (
        target.strftime("%Y-%m-%d"),
        target.strftime("%H:%M"),
        target.astimezone(timezone.utc).isoformat(),
    )


def _reservation(
    status: str = "confirmed",
    party_size: int = 4,
    reservation_time_iso: str | None = None,
    customer_name: str = "Aaron Chang",
    notes: str = "",
):
    """Helper — one reservations row shape the bridge probe returns."""
    if reservation_time_iso is None:
        _, _, reservation_time_iso = _future_dt_iso(minutes_ahead=120)
    return {
        "id":               42,
        "store_id":         STORE,
        "customer_name":    customer_name,
        "customer_phone":   CALLER,
        "party_size":       party_size,
        "reservation_time": reservation_time_iso,
        "status":           status,
        "notes":            notes,
        "created_at":       (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
    }


def _full_args(
    customer_name: str = "Aaron Chang",
    reservation_date: str | None = None,
    reservation_time: str | None = None,
    party_size: int = 4,
    notes: str = "",
    user_explicit_confirmation: bool = True,
):
    """Build a full-payload modify_reservation tool args dict."""
    if reservation_date is None or reservation_time is None:
        d, t, _ = _future_dt_iso(minutes_ahead=120)
        reservation_date = reservation_date or d
        reservation_time = reservation_time or t
    return {
        "customer_name":              customer_name,
        "reservation_date":           reservation_date,
        "reservation_time":           reservation_time,
        "party_size":                 party_size,
        "notes":                      notes,
        "user_explicit_confirmation": user_explicit_confirmation,
    }


# ── T1: no active reservation under the caller's phone ───────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_when_no_target():
    """Probe returns nothing → reason=no_reservation_to_modify."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=None)) as probe:
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "no_reservation_to_modify"
    assert res["ai_script_hint"] == "reservation_no_target"
    probe.assert_awaited_once()


# ── T2: reservation in cancelled state — most-recent confirmed only ──────────

@pytest.mark.asyncio
async def test_modify_reservation_ignores_cancelled():
    """Reservations with status != 'confirmed' must not be returned by the
    probe. We model this by having _find_modifiable_reservation return None
    when only cancelled rows exist."""
    from app.services.bridge import flows

    # Probe filters on status='confirmed' so a cancelled-only state returns None
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=None)):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "no_reservation_to_modify"


# ── T3: reservation_time < now + 30 min ──────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_too_late():
    """New reservation_time within 30 minutes from now → reservation_too_late."""
    from app.services.bridge import flows

    d, t, _ = _future_dt_iso(minutes_ahead=10)  # 10 min away — too late
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(reservation_date=d, reservation_time=t),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "reservation_too_late"
    assert res["ai_script_hint"] == "reservation_too_late"


# ── T4: party_size > 20 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_party_too_large():
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(party_size=25),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "party_too_large"
    assert res["ai_script_hint"] == "party_too_large"


# ── T5: party_size <= 0 → validation_failed ──────────────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_party_zero():
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(party_size=0),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "validation_failed"
    assert res["ai_script_hint"] == "validation_failed"


# ── T6: outside business hours ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_outside_business_hours():
    """If new reservation_time falls outside store business_hours, reject.
    We mock the business-hours check directly to keep the test deterministic."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())), \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=False)):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "outside_business_hours"
    assert res["ai_script_hint"] == "outside_business_hours"


# ── T7: noop — full payload identical to current row ─────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_noop_when_no_diff():
    """Full payload with all fields equal to current → reservation_noop, no UPDATE."""
    from app.services.bridge import flows

    d, t, iso = _future_dt_iso(minutes_ahead=120)
    current = _reservation(
        party_size=4,
        reservation_time_iso=iso,
        customer_name="Aaron Chang",
        notes="",
    )
    args = _full_args(
        customer_name="Aaron Chang",
        reservation_date=d,
        reservation_time=t,
        party_size=4,
        notes="",
    )

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=current)), \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=True)), \
         patch.object(flows, "_update_reservation",
                      new=AsyncMock()) as upd:
        res = await flows.modify_reservation(
            store_id=STORE,
            args=args,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "reservation_noop"
    upd.assert_not_called()


# ── T8: party_size only changed → success, diff carries party_size ───────────

@pytest.mark.asyncio
async def test_modify_reservation_changes_only_party_size():
    from app.services.bridge import flows

    d, t, iso = _future_dt_iso(minutes_ahead=120)
    current = _reservation(party_size=4, reservation_time_iso=iso, customer_name="Aaron Chang")

    args = _full_args(
        customer_name="Aaron Chang",
        reservation_date=d,
        reservation_time=t,
        party_size=6,  # changed
    )

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=current)), \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=True)), \
         patch.object(flows, "_update_reservation",
                      new=AsyncMock(return_value=True)) as upd:
        res = await flows.modify_reservation(
            store_id=STORE,
            args=args,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "modify_success"
    assert "party_size" in res["diff"]
    assert res["diff"]["party_size"]["old"] == 4
    assert res["diff"]["party_size"]["new"] == 6
    # Untouched fields must NOT appear in the diff
    assert "customer_name" not in res["diff"]
    upd.assert_awaited_once()


# ── T9: placeholder customer_name → validation_failed ────────────────────────

@pytest.mark.parametrize(
    "placeholder",
    ["Customer", "Guest", "(unknown)", "Valued Customer", "the customer"],
)
@pytest.mark.asyncio
async def test_modify_reservation_rejects_placeholder_name(placeholder):
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(customer_name=placeholder),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "validation_failed"
    assert res["ai_script_hint"] == "validation_failed"


# ── T10: most-recent policy — only the LATEST confirmed row is targeted ─────

@pytest.mark.asyncio
async def test_modify_reservation_targets_most_recent_only():
    """When multiple confirmed reservations exist for the same caller, the
    probe must return only the most recent (ORDER BY created_at DESC LIMIT 1)."""
    from app.services.bridge import flows

    # Simulate two confirmed reservations; probe returns the newer one.
    older = _reservation()
    older["id"] = 1
    older["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    newer = _reservation(party_size=2)
    newer["id"] = 99
    newer["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()

    # Probe is responsible for the LIMIT 1 — we model that here.
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=newer)) as probe, \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=True)), \
         patch.object(flows, "_update_reservation",
                      new=AsyncMock(return_value=True)) as upd:
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(party_size=5),  # change to force a diff
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["reservation_id"] == 99  # newer, NOT older
    probe.assert_awaited_once()
    upd.assert_awaited_once()


# ── T11: idempotent re-hit — second call sees a noop ─────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_idempotent_second_call_is_noop():
    """After a successful modify, a re-fire with the same args must noop
    because the row now matches the args (zero diff)."""
    from app.services.bridge import flows

    d, t, iso = _future_dt_iso(minutes_ahead=120)
    # First call's "current" row has the old party size
    first_current = _reservation(party_size=4, reservation_time_iso=iso)
    args = _full_args(reservation_date=d, reservation_time=t, party_size=6)

    # First call: party 4 → 6 should succeed
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=first_current)), \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=True)), \
         patch.object(flows, "_update_reservation",
                      new=AsyncMock(return_value=True)):
        res1 = await flows.modify_reservation(
            store_id=STORE, args=args, caller_phone_e164=CALLER, call_log_id=None,
        )

    assert res1["success"] is True
    assert res1["ai_script_hint"] == "modify_success"

    # Second call: probe now returns the post-update row → diff is empty
    second_current = _reservation(party_size=6, reservation_time_iso=iso)
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=second_current)), \
         patch.object(flows, "_is_within_business_hours",
                      new=AsyncMock(return_value=True)), \
         patch.object(flows, "_update_reservation",
                      new=AsyncMock()) as upd2:
        res2 = await flows.modify_reservation(
            store_id=STORE, args=args, caller_phone_e164=CALLER, call_log_id=None,
        )

    assert res2["success"] is True
    assert res2["ai_script_hint"] == "reservation_noop"
    upd2.assert_not_called()


# ── T12: bad date format — validation_failed ────────────────────────────────

@pytest.mark.asyncio
async def test_modify_reservation_rejects_bad_date_format():
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=_reservation())):
        res = await flows.modify_reservation(
            store_id=STORE,
            args=_full_args(reservation_date="tomorrow"),
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "validation_failed"
    assert res["ai_script_hint"] == "validation_failed"
