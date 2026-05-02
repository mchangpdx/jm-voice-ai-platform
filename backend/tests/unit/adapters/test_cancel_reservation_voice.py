# B4 — Voice integration TDD for cancel_reservation
# (B4 — voice_websocket의 cancel_reservation 통합 테스트)
#
# Per spec backend/docs/specs/B4_cancel_reservation.md, sections 6-7.
#
# Tests written BEFORE implementation. Red until:
#   - skills/scheduler/reservation.py exports CANCEL_RESERVATION_TOOL_DEF
#   - skills/order/order.py exports CANCEL_RESERVATION_SCRIPT_BY_HINT
#   - voice_websocket.py adds the AUTO-FIRE recital branch
#     (_build_cancel_reservation_recital helper) reading
#     session["last_reservation_summary"]
#   - voice_websocket build_system_prompt rule 4 mentions
#     cancel_reservation and the Issue χ guard wording is updated
#   - voice_websocket sets session["last_reservation_summary"] on
#     successful make_reservation / modify_reservation

from unittest.mock import patch

import pytest


MOCK_STORE = {
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "menu_cache":       "Cafe Latte: $5.99\nCheese Pizza: $11.99",
    "temporary_prompt": "Matcha latte is sold out today.",
    "custom_knowledge": "Free WiFi",
}


# ── V1: tool def is exported with caller-id-only schema ──────────────────────

def test_cancel_reservation_tool_def_is_exported():
    """CANCEL_RESERVATION_TOOL_DEF must exist with ONLY
    user_explicit_confirmation as a parameter (no phone/name/id).
    The caller-id schema kills the phone-hallucination class."""
    from app.skills.scheduler.reservation import CANCEL_RESERVATION_TOOL_DEF

    decls = CANCEL_RESERVATION_TOOL_DEF.get("function_declarations", [])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["name"] == "cancel_reservation"

    params = decl["parameters"]["properties"]
    # Only user_explicit_confirmation — no PII fields by design
    assert "user_explicit_confirmation" in params
    for forbidden in ("customer_phone", "customer_name",
                      "reservation_id", "reservation_date",
                      "reservation_time", "party_size"):
        assert forbidden not in params, (
            f"{forbidden} must NOT be in cancel_reservation schema "
            "(caller-id only)"
        )

    required = decl["parameters"].get("required", [])
    assert required == ["user_explicit_confirmation"]


# ── V2: script map is exported and covers all hints ─────────────────────────

def test_cancel_reservation_script_map_is_exported():
    """CANCEL_RESERVATION_SCRIPT_BY_HINT must cover every ai_script_hint
    the bridge can return."""
    from app.skills.order.order import CANCEL_RESERVATION_SCRIPT_BY_HINT

    expected_hints = {
        "cancel_reservation_success",
        "cancel_reservation_no_target",
        "cancel_reservation_already_canceled",
        "cancel_reservation_failed",
    }
    missing = expected_hints - set(CANCEL_RESERVATION_SCRIPT_BY_HINT.keys())
    assert not missing, f"missing script hints: {missing}"
    for hint, script in CANCEL_RESERVATION_SCRIPT_BY_HINT.items():
        assert isinstance(script, str) and len(script) > 0, (
            f"{hint} has empty script"
        )


# ── V3: AUTO-FIRE recital builder uses session.last_reservation_summary ─────

def test_cancel_reservation_recital_uses_session_summary():
    """_build_cancel_reservation_recital pulls the reservation summary
    from session['last_reservation_summary'] (populated by the most
    recent make_reservation / modify_reservation success)."""
    from app.api.voice_websocket import _build_cancel_reservation_recital

    session = {"last_reservation_summary": "party of 4 on Sunday, May 8 at 7:30 PM"}
    recital = _build_cancel_reservation_recital(session)

    assert "cancel" in recital.lower()
    assert "party of 4" in recital
    assert "May 8" in recital
    assert "7:30" in recital
    assert "is that right" in recital.lower()


def test_cancel_reservation_recital_falls_back_when_session_empty():
    """No session summary (cancel attempted before any make/modify in
    this call) → recital still asks for explicit confirmation, but
    with a generic 'your reservation' phrase."""
    from app.api.voice_websocket import _build_cancel_reservation_recital

    recital_none = _build_cancel_reservation_recital(None)
    recital_empty = _build_cancel_reservation_recital({})
    recital_blank = _build_cancel_reservation_recital(
        {"last_reservation_summary": ""}
    )

    for rec in (recital_none, recital_empty, recital_blank):
        assert "cancel" in rec.lower()
        assert "your reservation" in rec.lower()
        assert "is that right" in rec.lower()


# ── V4: system prompt rule 4 updates Issue χ wording + adds cancel_reservation

def test_build_system_prompt_mentions_cancel_reservation():
    """Rule 4 must reference cancel_reservation and the Issue χ wording
    must NOT still say 'B4 pending' / 'does not exist yet'."""
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    assert "cancel_reservation" in prompt
    # Old Issue χ caveat should be gone now that the tool exists
    lower_prompt = prompt.lower()
    assert "b4 pending" not in lower_prompt
    assert "does not exist yet" not in lower_prompt


# ── V5: last_reservation_summary builder helper formats correctly ───────────

def test_format_reservation_summary_for_session():
    """Helper that builds the session summary string from tool_args
    after a successful make_reservation / modify_reservation. Must be
    a human-readable single line covering party + date + time.

    Helper expected at app.api.voice_websocket._format_reservation_summary_for_session.
    """
    from app.api.voice_websocket import _format_reservation_summary_for_session

    summary = _format_reservation_summary_for_session(
        party_size=4,
        reservation_date="2026-05-08",
        reservation_time="19:30",
    )
    assert "party of 4" in summary
    assert "May" in summary
    assert "8" in summary
    assert "7:30" in summary
    assert "PM" in summary or "pm" in summary.lower()
