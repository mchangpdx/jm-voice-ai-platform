# Issue Σ — make_reservation AUTO-FIRE recital must include full summary
# (Issue Σ — make_reservation recital은 party/date/time을 모두 포함해야 함)
#
# Live observed: call_ebdc036d11951a04336d44c8856 T2 (14:19:39) — bot
# fell back to "Just to confirm a reservation for Sofia Chang — is that
# right?" without party/date/time. Customer cannot meaningfully confirm
# what they cannot hear. Tool args were complete; the recital builder
# was the limiting factor.
# Fix: _build_make_reservation_recital mirrors _build_modify_reservation_recital
# — speaks the full reservation summary.
#
# Also covers Issue Φ — rule 4 MAKE block must reference the
# RESERVATION_TIME TRUTHFULNESS GATE so Gemini doesn't default to
# current wall-clock when date/time aren't in the transcript.

import pytest


MOCK_STORE = {
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "menu_cache":       "Cafe Latte: $5.99",
    "temporary_prompt": "",
    "custom_knowledge": "",
}


# ── Issue Σ — make_reservation recital includes party + date + time ─────────

def test_build_make_reservation_recital_includes_full_summary():
    """Recital must speak name + party + date + time so the customer can
    actually confirm. Stub recitals (just the name) leave the customer
    blind to what they're agreeing to."""
    from app.api.voice_websocket import _build_make_reservation_recital

    args = {
        "customer_name":    "Aaron Chang",
        "reservation_date": "2026-05-08",
        "reservation_time": "19:30",
        "party_size":       4,
    }
    recital = _build_make_reservation_recital(args)
    assert "Aaron Chang" in recital
    assert "party of 4" in recital
    assert "May" in recital and "8" in recital
    assert "7:30" in recital
    assert "PM" in recital or "pm" in recital.lower()
    assert "is that right" in recital.lower()


def test_build_make_reservation_recital_falls_back_to_you_on_placeholder():
    """Placeholder name → 'you' (mirrors INVARIANT I2 behavior used in
    modify_reservation recital)."""
    from app.api.voice_websocket import _build_make_reservation_recital

    args = {
        "customer_name":    "Customer",   # placeholder
        "reservation_date": "2026-05-08",
        "reservation_time": "19:30",
        "party_size":       4,
    }
    recital = _build_make_reservation_recital(args)
    assert " you" in recital
    assert "Customer" not in recital


def test_build_make_reservation_recital_handles_missing_party():
    """If Gemini omits party_size, recital must not crash and must not
    fabricate a number — it should produce a recital the customer can
    catch as missing data."""
    from app.api.voice_websocket import _build_make_reservation_recital

    args = {
        "customer_name":    "Aaron Chang",
        "reservation_date": "2026-05-08",
        "reservation_time": "19:30",
        # party_size intentionally absent
    }
    recital = _build_make_reservation_recital(args)
    # No crash + still mentions name + still asks for confirmation
    assert "Aaron Chang" in recital
    assert "is that right" in recital.lower()


# ── Issue Φ — rule 4 MAKE block has RESERVATION_TIME TRUTHFULNESS GATE ─────

def test_system_prompt_rule4_make_has_truthfulness_gate():
    """Rule 4 MAKE block must instruct Gemini that reservation_date and
    reservation_time MUST come from the transcript, never defaulted to
    today's date or current wall-clock. Live regression: call_ebdc036d
    T13 — bot fired make with date='2026-05-02' time='14:19' (today,
    current time) when those weren't in the transcript.

    This must apply to BOTH MAKE and MODIFY (separate blocks). MODIFY
    already had the GATE since commit af590fa (Issue ω). This test
    locks the MAKE-side gate so it can't silently drop."""
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    # The full GATE phrase must appear at least twice (MAKE + MODIFY).
    # If only one instance is present, the MAKE-side guard is missing
    # (MODIFY already had it via Issue ω commit af590fa).
    gate_count = prompt.count("RESERVATION_TIME TRUTHFULNESS GATE")
    assert gate_count >= 2, (
        f"Expected RESERVATION_TIME TRUTHFULNESS GATE in BOTH MAKE and "
        f"MODIFY blocks; found only {gate_count} occurrence(s). MAKE-side "
        f"gate is the fix for Issue Φ."
    )
    # Sanity — the wall-clock prohibition wording is present somewhere
    lower = prompt.lower()
    assert "wall-clock" in lower or "current time" in lower
