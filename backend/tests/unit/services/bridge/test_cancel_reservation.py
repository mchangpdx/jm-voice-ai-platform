# B4 — flows.cancel_reservation TDD
# (B4 — flows.cancel_reservation 테스트 우선 작성)
#
# Per spec backend/docs/specs/B4_cancel_reservation.md.
#
# cancel_reservation(store_id, caller_phone_e164, call_log_id) cancels
# the most-recent confirmed reservation for the same caller phone:
#   - reuses _find_modifiable_reservation (status='confirmed', LIMIT 1)
#   - falls back to _find_recent_reservation_any_status to detect
#     already-cancelled rows (precise hint instead of generic no_target)
#   - applies status='cancelled' via _update_reservation_status
#   - Option α: NO too-late guard (cancel always allowed once a row exists)
#
# Tests written BEFORE the implementation — should fail until
# flows.cancel_reservation lands. RED → implementation → GREEN.

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


CALLER = "+15035551234"
STORE  = "STORE_UUID"


def _reservation(
    *,
    res_id:               int = 42,
    status:               str = "confirmed",
    party_size:           int = 4,
    customer_name:        str = "Aaron Chang",
    notes:                str = "",
    minutes_ahead:        int = 120,
    created_seconds_ago:  int = 30,
):
    """Helper — one reservations row shape the bridge probe returns."""
    res_time = (
        datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    ).isoformat()
    return {
        "id":               res_id,
        "store_id":         STORE,
        "customer_name":    customer_name,
        "customer_phone":   CALLER,
        "party_size":       party_size,
        "reservation_time": res_time,
        "status":           status,
        "notes":            notes,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(seconds=created_seconds_ago)
        ).isoformat(),
    }


# ── T1: no reservation under caller's phone — both probes empty ──────────────

@pytest.mark.asyncio
async def test_cancel_reservation_no_target_when_both_probes_empty():
    """Modifiable probe + recent-any-status probe both return None →
    reason=cancel_reservation_no_target, no PATCH attempted."""
    from app.services.bridge import flows

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=None)) as mod_probe, \
         patch.object(flows, "_find_recent_reservation_any_status",
                      new=AsyncMock(return_value=None)) as any_probe, \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock()) as upd:
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "cancel_reservation_no_target"
    assert res["ai_script_hint"] == "cancel_reservation_no_target"
    mod_probe.assert_awaited_once()
    any_probe.assert_awaited_once()
    upd.assert_not_called()


# ── T2: already cancelled — modifiable probe empty, any-status returns cancelled

@pytest.mark.asyncio
async def test_cancel_reservation_already_canceled_returns_precise_hint():
    """When the most recent row is already 'cancelled', return the
    cancel_reservation_already_canceled hint instead of generic no_target."""
    from app.services.bridge import flows

    cancelled_row = _reservation(status="cancelled")

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_reservation_any_status",
                      new=AsyncMock(return_value=cancelled_row)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock()) as upd:
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "cancel_reservation_already_canceled"
    assert res["ai_script_hint"] == "cancel_reservation_already_canceled"
    assert res["reservation_id"] == cancelled_row["id"]
    upd.assert_not_called()


# ── T3: happy path — confirmed row → cancelled ───────────────────────────────

@pytest.mark.asyncio
async def test_cancel_reservation_happy_path():
    """Confirmed reservation → status='cancelled', summary returned."""
    from app.services.bridge import flows

    target = _reservation(status="confirmed", party_size=4, minutes_ahead=180)

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=target)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock(return_value=True)) as upd:
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "cancel_reservation_success"
    assert res["reservation_id"] == target["id"]
    assert res["prior_status"] == "confirmed"
    # Summary is non-empty and human-readable
    assert isinstance(res.get("cancelled_summary"), str)
    assert len(res["cancelled_summary"]) > 0
    assert "party of 4" in res["cancelled_summary"]
    upd.assert_awaited_once()
    # PATCH must target status='cancelled'
    call_kwargs = upd.await_args.kwargs
    assert call_kwargs.get("new_status") == "cancelled"
    assert call_kwargs.get("reservation_id") == target["id"]


# ── T4: most-recent policy — only newest confirmed row is targeted ───────────

@pytest.mark.asyncio
async def test_cancel_reservation_targets_most_recent_only():
    """When multiple confirmed reservations exist for the caller, the
    probe returns only the newest one (ORDER BY created_at DESC LIMIT 1).
    cancel_reservation cancels that newest row and no other."""
    from app.services.bridge import flows

    newer = _reservation(res_id=99, party_size=2, created_seconds_ago=10)

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=newer)) as probe, \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock(return_value=True)) as upd:
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["reservation_id"] == 99
    probe.assert_awaited_once()
    upd.assert_awaited_once()


# ── T5: idempotent re-hit — second call returns already_canceled ─────────────

@pytest.mark.asyncio
async def test_cancel_reservation_idempotent_second_call_already_canceled():
    """First cancel succeeds; second cancel sees the row as 'cancelled'
    via the secondary probe and returns the precise hint."""
    from app.services.bridge import flows

    confirmed = _reservation(status="confirmed", res_id=42)

    # First call: succeeds and cancels.
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=confirmed)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock(return_value=True)):
        res1 = await flows.cancel_reservation(
            store_id=STORE, caller_phone_e164=CALLER, call_log_id=None,
        )
    assert res1["success"] is True
    assert res1["ai_script_hint"] == "cancel_reservation_success"

    # Second call: row is now cancelled — modifiable probe returns None,
    # any-status probe returns the cancelled row.
    cancelled_now = {**confirmed, "status": "cancelled"}
    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=None)), \
         patch.object(flows, "_find_recent_reservation_any_status",
                      new=AsyncMock(return_value=cancelled_now)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock()) as upd2:
        res2 = await flows.cancel_reservation(
            store_id=STORE, caller_phone_e164=CALLER, call_log_id=None,
        )
    assert res2["success"] is False
    assert res2["ai_script_hint"] == "cancel_reservation_already_canceled"
    upd2.assert_not_called()


# ── T6: DB PATCH failure → cancel_reservation_failed ────────────────────────

@pytest.mark.asyncio
async def test_cancel_reservation_failed_when_patch_returns_false():
    """If _update_reservation_status returns False (PATCH failed),
    return cancel_reservation_failed with the row id for diagnostics."""
    from app.services.bridge import flows

    target = _reservation(status="confirmed", res_id=77)

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=target)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock(return_value=False)):
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is False
    assert res["reason"] == "cancel_reservation_failed"
    assert res["ai_script_hint"] == "cancel_reservation_failed"
    assert res["reservation_id"] == target["id"]


# ── T7: too-late allowed (Option α) — reservation 5 min away → still cancellable

@pytest.mark.asyncio
async def test_cancel_reservation_allows_too_late_window():
    """Decision α (locked 2026-05-02): no 30-min cutoff for cancel.
    A reservation only 5 min away (which B3 modify_reservation would
    reject as reservation_too_late) MUST still be cancellable so the
    customer can free the slot."""
    from app.services.bridge import flows

    very_soon = _reservation(status="confirmed", minutes_ahead=5)

    with patch.object(flows, "_find_modifiable_reservation",
                      new=AsyncMock(return_value=very_soon)), \
         patch.object(flows, "_update_reservation_status",
                      new=AsyncMock(return_value=True)):
        res = await flows.cancel_reservation(
            store_id=STORE,
            caller_phone_e164=CALLER,
            call_log_id=None,
        )

    assert res["success"] is True
    assert res["ai_script_hint"] == "cancel_reservation_success"
