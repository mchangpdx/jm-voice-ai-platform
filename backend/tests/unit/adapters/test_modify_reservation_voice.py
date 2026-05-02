# B3 — Voice integration TDD for modify_reservation
# (B3 — voice_websocket의 modify_reservation 통합 테스트)
#
# Per spec backend/docs/specs/B3_modify_reservation.md, sections 6-7.
#
# Tests written BEFORE implementation. Red until:
#   - voice_websocket.py adds the AUTO-FIRE recital branch
#   - voice_websocket.py adds the dispatcher branch calling
#     bridge_flows.modify_reservation
#   - skills/scheduler/reservation.py exports MODIFY_RESERVATION_TOOL_DEF
#   - skills/order/order.py exports MODIFY_RESERVATION_SCRIPT_BY_HINT
#   - voice_websocket.build_system_prompt rule 4 mentions modify_reservation
#     and the INFO UPDATES carve-out

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_STORE = {
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "menu_cache":       "Cafe Latte: $5.99\nCheese Pizza: $11.99",
    "temporary_prompt": "Matcha latte is sold out today.",
    "custom_knowledge": "Free WiFi",
}


# ── V1: tool def is exported and well-formed ─────────────────────────────────

def test_modify_reservation_tool_def_is_exported():
    """MODIFY_RESERVATION_TOOL_DEF must exist and declare the full-payload
    contract: 5 required fields + user_explicit_confirmation."""
    from app.skills.scheduler.reservation import MODIFY_RESERVATION_TOOL_DEF

    decls = MODIFY_RESERVATION_TOOL_DEF.get("function_declarations", [])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["name"] == "modify_reservation"
    params = decl["parameters"]["properties"]
    for field in ("user_explicit_confirmation",
                  "customer_name",
                  "reservation_date",
                  "reservation_time",
                  "party_size"):
        assert field in params, f"missing required arg: {field}"
    # Full-payload contract — these 5 fields must be required by the schema
    required = decl["parameters"].get("required", [])
    for field in ("user_explicit_confirmation",
                  "customer_name",
                  "reservation_date",
                  "reservation_time",
                  "party_size"):
        assert field in required, f"{field} must be required for full-payload"


# ── V2: script map is exported and covers all hints ─────────────────────────

def test_modify_reservation_script_map_is_exported():
    """MODIFY_RESERVATION_SCRIPT_BY_HINT must cover every ai_script_hint
    the bridge can return."""
    from app.skills.order.order import MODIFY_RESERVATION_SCRIPT_BY_HINT

    expected_hints = {
        "modify_success",
        "reservation_no_target",
        "reservation_too_late",
        "reservation_noop",
        "outside_business_hours",
        "party_too_large",
        "validation_failed",
    }
    missing = expected_hints - set(MODIFY_RESERVATION_SCRIPT_BY_HINT.keys())
    assert not missing, f"missing script hints: {missing}"
    # Each script must be a non-empty customer-facing line
    for hint, script in MODIFY_RESERVATION_SCRIPT_BY_HINT.items():
        assert isinstance(script, str) and len(script) > 0, f"{hint} has empty script"


# ── V3: system prompt rule 4 mentions modify_reservation + carve-out ────────

def test_build_system_prompt_rule4_mentions_modify_reservation():
    """Rule 4 must extend to cover modify_reservation, including the
    INFO UPDATES carve-out (email/phone updates do NOT trigger
    modify_reservation — same as rule 6 for orders)."""
    from app.api.voice_websocket import build_system_prompt

    prompt = build_system_prompt(MOCK_STORE)
    assert "modify_reservation" in prompt
    # Rule 4 should mention the full-payload contract
    assert "full" in prompt.lower() and "payload" in prompt.lower()
    # INFO UPDATES carve-out — same wording family as rule 6
    # (either "INFO UPDATES" or an explicit "email/phone updates" line)
    assert ("INFO UPDATES" in prompt
            or "email/phone updates" in prompt.lower()
            or "email or phone update" in prompt.lower())


# ── V4: AUTO-FIRE recital builder for modify_reservation ────────────────────

def test_modify_reservation_recital_format():
    """The AUTO-FIRE recital builder must produce a reservation summary
    pulling all four mutable fields from tool_args, with a 12-h time and
    a human date. Placeholder names fall back to 'you' (INVARIANTS I2).

    Importable helper expected at app.api.voice_websocket._build_modify_reservation_recital.
    """
    from app.api.voice_websocket import _build_modify_reservation_recital

    args = {
        "customer_name":    "Aaron Chang",
        "reservation_date": "2026-05-08",
        "reservation_time": "19:30",
        "party_size":       4,
    }
    recital = _build_modify_reservation_recital(args)
    assert "Aaron Chang" in recital
    assert "party of 4" in recital
    # 12-h time formatted (PM)
    assert "7:30" in recital
    assert "PM" in recital or "pm" in recital.lower()
    # Human date contains the month name
    assert "May" in recital
    assert "is that right" in recital.lower()


def test_modify_reservation_recital_falls_back_to_you_on_placeholder():
    """Placeholder customer_name → recital uses 'you' (INVARIANTS I2)."""
    from app.api.voice_websocket import _build_modify_reservation_recital

    args = {
        "customer_name":    "Customer",   # placeholder
        "reservation_date": "2026-05-08",
        "reservation_time": "19:30",
        "party_size":       4,
    }
    recital = _build_modify_reservation_recital(args)
    assert " you" in recital  # word-boundary match — "for you" or "to you"
    assert "Customer" not in recital
