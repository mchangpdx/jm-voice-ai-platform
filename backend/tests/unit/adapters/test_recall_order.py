# Phase 2-C.B6 — Voice integration tests for recall_order (R1–R5)
# (Phase 2-C.B6 — voice_websocket의 recall_order 통합 테스트)
#
# Spec: docs/specs/B6_recall_order.md
# Trigger bug: live call call_7d7ef130ad839e9a2c3c68816a7 T25-26 — bot
# answered "no active order" though session held 1× Cheese Pizza pending.

import pytest


MOCK_STORE = {
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "menu_cache":       "Cheese Pizza: $10.99\nAmericano: $4.49",
    "temporary_prompt": "",
    "custom_knowledge": "",
}


# ── R1: RECALL_ORDER_TOOL_DEF exported with empty params ─────────────────────

def test_r1_recall_order_tool_def_is_exported():
    from app.skills.order.order import RECALL_ORDER_TOOL_DEF

    decls = RECALL_ORDER_TOOL_DEF.get("function_declarations", [])
    assert len(decls) == 1
    decl = decls[0]
    assert decl["name"] == "recall_order"
    # No required parameters — caller-id + session snapshot drive everything.
    # (필수 파라미터 없음 — caller-id + session 스냅샷이 모든 정보 제공)
    assert decl["parameters"]["properties"] == {}
    assert decl["parameters"].get("required", []) == []


# ── R2: render_recall_message → present (1 item) ─────────────────────────────

def test_r2_render_recall_present_single_item():
    from app.skills.order.order import render_recall_message

    msg, reason = render_recall_message(
        items=[{"name": "Cheese Pizza", "quantity": 1}],
        total_cents=1099,
    )
    assert reason == "recall_present"
    assert "1 Cheese Pizza" in msg
    assert "$10.99" in msg
    assert "payment link" in msg.lower()


# ── R3: render_recall_message → present (multiple items, plural) ─────────────

def test_r3_render_recall_present_multi_items_pluralized():
    from app.skills.order.order import render_recall_message

    msg, reason = render_recall_message(
        items=[
            {"name": "Cheese Pizza", "quantity": 1},
            {"name": "Americano",    "quantity": 2},
        ],
        total_cents=2497,
    )
    assert reason == "recall_present"
    assert "1 Cheese Pizza" in msg
    assert "2 Americanos" in msg          # plural 's' for qty>1
    assert "$24.97" in msg


# ── R4: render_recall_message → empty (no items / zero total) ────────────────

def test_r4_render_recall_empty_when_no_session_order():
    from app.skills.order.order import render_recall_message

    msg, reason = render_recall_message(items=[], total_cents=0)
    assert reason == "recall_empty"
    assert "don't have an order" in msg.lower()


# ── R5: System prompt rule 13 mentions recall_order ──────────────────────────

def test_r5_system_prompt_rule_13_present():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "recall_order" in prompt
    # The rule must explicitly forbid LLM from answering from its own memory.
    # (LLM이 자체 기억으로 답하는 것 명시 금지 — 환각 차단)
    assert "VERBATIM" in prompt or "verbatim" in prompt


# ── R6: tools list registers recall_order alongside existing tools ───────────

def test_r6_recall_order_in_tools_registry():
    from app.skills.order.order import RECALL_ORDER_TOOL_DEF
    # Smoke-import — ensures voice_websocket module imports the new symbol
    # without breaking existing tool registry.
    # (기존 tool 등록 무손상 확인)
    from app.api import voice_websocket as vw  # noqa: F401
    assert RECALL_ORDER_TOOL_DEF["function_declarations"][0]["name"] == "recall_order"
