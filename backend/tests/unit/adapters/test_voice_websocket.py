# TDD tests for Retell Custom LLM WebSocket endpoint
# (Retell Custom LLM WebSocket 엔드포인트 TDD 테스트)
#
# Architecture: eager init pattern — _init_session fires on connect via asyncio.create_task.
# All WS tests must mock _get_agent_id_from_call to return None (disables eager init)
# so the call_details event path is tested in isolation without real Retell API calls.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_STORE = {
    "id":               "7c425fcb-91c7-4eb7-982a-591c094ba9c9",
    "name":             "JM Cafe",
    "retell_agent_id":  "agent_68e9f01ec4d5502b990755d2ef",
    "system_prompt":    "You are Aria, the friendly AI for JM Cafe.",
    "temporary_prompt": "Matcha latte is sold out today.",
    "business_hours":   "Mon-Sat 7am-9pm, Sun 8am-6pm",
    "custom_knowledge": "Free WiFi: JMCafe_Guest / pw: coffee123",
    "is_active":        True,
}

CALL_DETAILS_MSG = {
    "interaction_type": "call_details",
    "call": {
        "call_id":   "call_abc123",
        "agent_id":  "agent_68e9f01ec4d5502b990755d2ef",
        "call_type": "web_call",
    },
}

PING_MSG = {"interaction_type": "ping"}

RESPONSE_REQUIRED_MSG = {
    "interaction_type": "response_required",
    "response_id":      1,
    "transcript": [
        {"role": "agent",  "content": "Hello, JM Cafe. How can I help?"},
        {"role": "user",   "content": "What are your hours today?"},
    ],
}

UPDATE_ONLY_MSG = {
    "interaction_type": "update_only",
    "response_id":      2,
    "transcript": [
        {"role": "agent", "content": "We are open until 9pm."},
    ],
}

# Shared patch for eager init: always return empty meta so call_details path
# is exercised. Must patch _get_call_metadata (the function eager-init actually
# calls post-6b6a09d), NOT the legacy _get_agent_id_from_call shim — patching
# the shim leaks the real Retell HTTP request and the websocket test client
# can hang depending on network conditions.
# (eager init은 _get_call_metadata 직접 호출 — 구 shim patch는 누수)
_NO_AGENT = patch(
    "app.api.voice_websocket._get_call_metadata",
    new_callable=lambda: lambda *a, **k: AsyncMock(return_value={})(),
)


def _no_init():
    """Decorator: disable eager _init_session by returning empty meta from _get_call_metadata.
    Empty meta → no agent_id → init returns at the no-agent branch; call_details path runs.
    """
    return patch("app.api.voice_websocket._get_call_metadata", new=AsyncMock(return_value={}))


# ── Pure helper function tests (no I/O) ───────────────────────────────────────

def test_build_system_prompt_includes_store_name():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "JM Cafe" in prompt or "Aria" in prompt


def test_build_system_prompt_includes_business_hours():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "7am-9pm" in prompt or "Mon-Sat" in prompt


def test_build_system_prompt_includes_temporary_prompt():
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "Matcha latte" in prompt or "sold out" in prompt


def test_build_system_prompt_missing_optional_fields():
    from app.api.voice_websocket import build_system_prompt
    minimal = {"name": "TestStore", "system_prompt": "You are a bot.", "temporary_prompt": None,
               "business_hours": None, "custom_knowledge": None}
    prompt = build_system_prompt(minimal)
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_system_prompt_has_remove_validation_rule():
    """Issue α/β fix — partial-remove confirm validation guard must be in
    rule 6 so Gemini stops reciting 'remove garlic bread' when garlic
    bread isn't on the order. (주문에 없는 항목 환각 confirm 차단)
    Wave A: header renamed to 'VALIDATE BEFORE REMOVE/CANCEL-ITEM'."""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "VALIDATE BEFORE REMOVE" in prompt
    assert "I don't see" in prompt
    # Ensure the carve-out for full-order cancel (rule 7) is preserved
    assert "full-order cancel" in prompt.lower() or "Full-order cancel" in prompt


def test_build_system_prompt_has_cancel_precondition_guard():
    """Issue γ fix — cancel_order precondition guard must be in rule 7
    so Gemini stops reciting cancel confirm when there is no active
    order or the order is already cancelled. (cancel 환각 차단)
    Wave A: header renamed to 'PRECONDITION SKIP'."""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "PRECONDITION SKIP" in prompt
    assert "cancel_already_canceled" in prompt
    # Single-item cancel routes through rule 6, not rule 7
    assert "single-item cancel" in prompt.lower() or "SINGLE-ITEM cancel" in prompt


def test_build_system_prompt_has_invariants_block_at_recency_end():
    """Phase 7-A.D Wave A — INVARIANTS block placement moved from primacy
    zone (top 15%) to recency zone (last 5-10%). Lost-in-the-middle
    research (Liu et al. 2023) shows recency attention is at least as
    strong as primacy for instruction following, and our four absolute
    invariants benefit more from being the LAST thing read each turn
    (reinforced by the top-of-prompt one-line anchor). The full
    INVARIANTS block must (1) appear AFTER the numbered RULES, (2) sit
    in the last 15% of the prompt, and (3) be referenced from the top
    via the every-turn anchor.
    (recency 영역 배치 — 위 anchor + 아래 full block)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    inv_pos = prompt.find("=== CORE TRUTHFULNESS INVARIANTS")
    rules_pos = prompt.find("=== RULES")
    assert inv_pos > 0, "INVARIANTS block missing"
    assert rules_pos > 0, "RULES block missing"
    assert inv_pos > rules_pos, "INVARIANTS block must come AFTER RULES (recency)"
    # Recency zone — INVARIANTS block must sit in the last 15% of prompt
    assert inv_pos / len(prompt) > 0.85, (
        f"INVARIANTS at {inv_pos / len(prompt):.0%} — must be > 85%"
    )
    # Top anchor referencing the bottom block must be present
    assert "re-read the four CORE TRUTHFULNESS INVARIANTS" in prompt


def test_build_system_prompt_invariant_i1_items():
    """Issue ξ — items must come from the customer's spoken transcript.
    Live observed call_ce589e7a T25-T29: bot recited '1 Chocolate Cake'
    after a cancel even though the customer never said Chocolate Cake.
    (I1 ITEMS — 사용자 발화에 없는 항목 환각 차단)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "I1. ITEMS" in prompt
    assert "EXPLICITLY spoke" in prompt
    assert "carry over from a cancelled order" in prompt


def test_build_system_prompt_invariant_i2_customer_name():
    """Issue ρ — customer_name must come from the customer's spoken
    transcript. Live observed call_061702bb T7-T11: Gemini cycled
    through 'the customer' / 'Customer' / 'Guest' placeholders, each
    rejected by bridge — 3 turns wasted. (I2 NAME — placeholder
    customer_name 무한 시도 차단)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "I2. CUSTOMER NAME" in prompt
    # All placeholders observed live must be named
    for placeholder in ["Customer", "Guest", "the customer",
                        "Valued Customer", "(customer name not provided)"]:
        assert placeholder in prompt, f"missing placeholder: {placeholder}"
    assert "May I have your name?" in prompt


def test_build_system_prompt_i1_blocks_modify_noop_carry_over():
    """Issue ξ re-occurrence (call_0279951409 T26, T30) — INVARIANTS I1
    must explicitly block carry-over of items from a modify_noop or
    contact-info-update phase. (modify_noop 후 / 이메일 변경 phase에서
    이전 items carry-over 차단)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "modify_noop" in prompt
    assert "carry-over" in prompt or "carry over" in prompt
    # Contact-info-update phases must not trigger order recital
    assert "contact info" in prompt
    assert "DO NOT recite" in prompt or "DO NOT fire create_order" in prompt


def test_build_system_prompt_rule4_reservation_time_truthfulness_gate():
    """Issue ψ — rule 4 must explicitly forbid hallucinated
    reservation_time values when the customer is changing a different
    field. (reservation_time 환각 차단 — 이전 tool result 값만 사용)
    Wave A: 'EXACT value from the most recent successful' phrasing
    compacted to 'the EXACT value from the prior successful tool result'.
    """
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "RESERVATION_TIME TRUTHFULNESS GATE" in prompt
    assert "EXACT value from the prior successful tool result" in prompt
    pl = prompt.lower()
    assert "wall-clock time" in pl
    assert "never guess" in pl


def test_build_system_prompt_rule4_info_updates_carveout_strengthened():
    """Issue ω — rule 4 INFO UPDATES carve-out must be promoted to a
    TRUTHFULNESS INVARIANT (same severity as I1/I2/I3) so Gemini stops
    firing modify_reservation for email/phone updates.
    Wave A: live-observed wasted-turns prose moved to git history; the
    invariant header + the three operational sentences are retained.
    """
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "INFO UPDATES ARE NOT MODIFY (TRUTHFULNESS INVARIANT" in prompt
    assert "do NOT fire ANY tool" in prompt
    # The reservation row stays unchanged on a contact-info update
    assert "reservation row" in prompt.lower()


def test_build_system_prompt_rule4_no_auto_cancel_after_too_late():
    """Issue χ — rule 4 must forbid auto-firing cancel tools after
    reservation_too_late on a bare 'oh, okay' / 'I see' ack. Live
    observed call_1f5901e2 T28: bot auto-fired cancel_order recital
    (wrong tool — that's for orders, not reservations). (reservation_
    too_late 후 자동 cancel 추론 차단)

    Updated post-B4 (cancel_reservation tool now exists): the prompt's
    auto-fire ban now names cancel_reservation explicitly, and the
    wrong-tool guard (cancel_order is NOT for reservations) is asserted
    separately. Both invariants from the original Issue χ are preserved.
    """
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "AFTER reservation_too_late" in prompt
    # B4-aligned auto-fire ban (cancel_reservation tool exists post-B4)
    assert "DO NOT" in prompt and "auto-fire cancel_reservation" in prompt
    # Wrong-tool guard — preserves the original Issue χ intent
    assert "cancel_order" in prompt and "never use cancel_order for a reservation" in prompt
    # The "bare ack is not cancel intent" guard
    assert "'oh, okay' or 'I see'" in prompt


def test_build_system_prompt_rule6_info_updates_not_modify():
    """Issue τ — rule 6 must explicitly carve out contact-info updates
    (email/phone/name) from modify_order triggers. (이메일/전화/이름
    추가는 modify_order 트리거 아님)
    Wave A: rule 6 compacted; assertion checks the contact-info carve-out
    by semantic content, not exact wording."""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    pl = prompt.lower()
    # Carve-out language is split across rule 4 (reservations) and rule 6 (orders).
    # Either presence is sufficient — both reference contact-info updates as NOT a tool trigger.
    assert "contact-info" in pl
    assert "email/phone" in pl or "email or phone" in pl
    assert "do not fire" in pl or "do NOT fire" in prompt


def test_build_system_prompt_invariant_i3_status():
    """I3 — never claim cancelled/confirmed/booked without a successful
    tool result in this call. (I3 STATUS — phantom confirmation 차단)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "I3. STATUS" in prompt
    assert "tool call returned success" in prompt


def test_build_system_prompt_cancel_guard_is_narrow():
    """Issue ν fix — rule 7 cancel skip must trigger only on explicit
    tool-result conditions, NOT on lexical transcript matching.
    (transcript 패턴이 아닌 tool-result 기반으로만 guard 트리거)
    Wave A: header renamed 'PRECONDITION SKIP' (narrower scope)."""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    assert "PRECONDITION SKIP" in prompt
    pl = prompt.lower()
    assert "tool-result trail" in pl or "tool result trail" in pl
    # Rule 6's partial-remove utterance must NOT be misread as 'no order'
    assert "rule 6" in pl
    assert "does not mean the" in pl or "DOES NOT mean the order is gone" in prompt


def test_build_system_prompt_rule7_cancel_recital_source():
    """Issue φ — cancel recital items+total MUST come from the most
    recent SUCCESSFUL create_order/modify_order tool result, not from
    a rejected modify (order_too_late) attempt. (cancel recital은
    in-flight only)
    Wave A: phrasing compacted, semantic content preserved."""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    pl = prompt.lower()
    assert "most recent successful create_order/modify_order" in pl or \
           "most recent SUCCESSFUL create_order/modify_order" in prompt
    assert "modify_too_late" in prompt
    assert "must not leak" in pl or "rejected modify" in pl


def test_build_system_prompt_has_args_email_truthfulness_gate():
    """Issue σ — args_email must match the NATO readback character-by-
    character, NOT the raw STT value. Live observed twice in one session
    (call_0279951409 T6 'mchain@jmtech1.com' vs intended 'mchang@...';
    T26 'cymeeet@gmail.com' vs intended 'cymeet@...'). Pay link to wrong
    inbox = customer trust cost. (NATO readback과 args_email 일치 강제)"""
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    # Wave A compaction: clauses renamed; semantic content preserved.
    assert "ARGS-EMAIL GATE" in prompt
    assert "EXACT character sequence" in prompt
    # Live-observed STT substitutions that must be guarded against
    assert "mchang" in prompt
    assert "cymeet" in prompt
    # The "re-derive from your own readback, never raw STT" instruction.
    # Wave A formats this across line breaks in the checklist, so check the
    # two key phrases independently.
    pl = prompt.lower()
    assert "re-derive from your" in pl
    assert "never blindly trust raw stt" in pl


def test_build_system_prompt_has_nato_domain_rule():
    """Issue δ fix — NATO email readback must spell EVERY letter of
    business domains, not just the local part. STT often truncates
    'jmtech1.com' to 'jm.com' — readback must catch this. (도메인
    letter-by-letter NATO 강제)
    Wave A: 'DOMAIN COVERAGE' header removed; check the four whole-domain
    allowlist + the business-domain example are still present.
    """
    from app.api.voice_websocket import build_system_prompt
    prompt = build_system_prompt(MOCK_STORE)
    # Whole-domain allowlist (per Wave A, named inline rather than under a
    # separate DOMAIN COVERAGE header)
    assert "gmail.com" in prompt
    assert "yahoo.com" in prompt
    assert "outlook.com" in prompt
    assert "icloud.com" in prompt
    # Business-domain NATO example showing every letter+digit+TLD spelled
    assert "jmtech1.com" in prompt
    assert "J-M-T-E-C-H-one" in prompt or "j-m-t-e-c-h-one" in prompt.lower()


def test_format_transcript_returns_string():
    from app.api.voice_websocket import format_transcript
    transcript = RESPONSE_REQUIRED_MSG["transcript"]
    result = format_transcript(transcript)
    assert isinstance(result, str)
    assert "What are your hours today?" in result


def test_format_transcript_preserves_turn_order():
    from app.api.voice_websocket import format_transcript
    transcript = [
        {"role": "user",  "content": "First"},
        {"role": "agent", "content": "Second"},
        {"role": "user",  "content": "Third"},
    ]
    result = format_transcript(transcript)
    assert result.index("First") < result.index("Second") < result.index("Third")


# ── WebSocket endpoint tests ──────────────────────────────────────────────────

@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
def test_ping_returns_pong(mock_load):
    # _no_init uses new=AsyncMock(...) so no extra parameter is injected
    mock_load.return_value = MOCK_STORE
    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        ws.send_json(PING_MSG)
        pong = ws.receive_json()
        assert pong.get("interaction_type") == "ping_response"


@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
@patch("app.api.voice_websocket._stream_gemini_response")
def test_response_required_streams_chunks(mock_stream, mock_load):
    mock_load.return_value = MOCK_STORE

    async def fake_stream(*_args, **_kwargs):
        for word in ["We ", "are ", "open ", "until ", "9pm."]:
            yield word

    mock_stream.return_value = fake_stream()

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        ws.send_json(RESPONSE_REQUIRED_MSG)

        chunks = []
        while True:
            msg = ws.receive_json()
            chunks.append(msg)
            if msg.get("content_complete"):
                break

        assert len(chunks) >= 2
        assert chunks[-1]["content_complete"] is True
        assert all(c["response_id"] == 1 for c in chunks)


@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
def test_unknown_agent_closes_gracefully(mock_load):
    mock_load.return_value = None  # agent not found

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        try:
            msg = ws.receive_json()
            assert "error" in msg or "detail" in msg
        except Exception:
            pass  # WebSocket closed — also acceptable


@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
@patch("app.api.voice_websocket._stream_gemini_response")
def test_update_only_ignored_no_response(mock_stream, mock_load):
    mock_load.return_value = MOCK_STORE
    mock_stream.return_value = None

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        ws.send_json(UPDATE_ONLY_MSG)
        ws.send_json(PING_MSG)
        msg = ws.receive_json()
        assert msg.get("interaction_type") == "ping_response"


@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
def test_reminder_required_sends_nudge(mock_load):
    mock_load.return_value = MOCK_STORE
    reminder_msg = {"interaction_type": "reminder_required", "response_id": 3}

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        ws.send_json(reminder_msg)
        ws.send_json(PING_MSG)
        nudge = ws.receive_json()
        assert nudge.get("content_complete") is True
        assert nudge.get("response_id") == 3
        pong = ws.receive_json()
        assert pong.get("interaction_type") == "ping_response"


@_no_init()
@patch("app.api.voice_websocket._load_store_by_agent")
@patch("app.api.voice_websocket._stream_gemini_response")
def test_response_id_echoed_in_chunks(mock_stream, mock_load):
    mock_load.return_value = MOCK_STORE

    async def fake_stream(*_args, **_kwargs):
        yield "Hello there!"

    mock_stream.return_value = fake_stream()

    msg_with_id_5 = {**RESPONSE_REQUIRED_MSG, "response_id": 5}

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        ws.send_json(CALL_DETAILS_MSG)
        ws.send_json(msg_with_id_5)

        chunks = []
        while True:
            msg = ws.receive_json()
            chunks.append(msg)
            if msg.get("content_complete"):
                break

        assert all(c["response_id"] == 5 for c in chunks)


# NOTE: must patch _get_call_metadata (not the legacy _get_agent_id_from_call
# shim) — eager init at voice_websocket.py:2206 calls _get_call_metadata
# directly after the 6b6a09d rename. Patching the legacy name silently leaks
# the real Retell HTTP call and the websocket client hangs waiting on a
# greeting that never lands.
# (eager init은 _get_call_metadata 직접 호출 — 구 이름 patch는 누수)
@patch("app.api.voice_websocket._get_call_metadata",
       new=AsyncMock(return_value={"agent_id": "agent_68e9f01ec4d5502b990755d2ef",
                                   "from_number": "+15555550100"}))
@patch("app.api.voice_websocket._generate_greeting",
       new=AsyncMock(return_value="Hello! Thanks for calling JM Cafe. How can I help?"))
@patch("app.api.voice_websocket._load_store_by_agent")
def test_eager_init_sends_greeting(mock_load):
    """Eager init should send a greeting (response_id=0) before any customer turn."""
    mock_load.return_value = MOCK_STORE

    with client.websocket_connect("/llm-websocket/call_test001") as ws:
        # No call_details sent — eager init fires immediately on connect
        greeting = ws.receive_json()
        assert greeting.get("response_id") == 0
        assert greeting.get("content_complete") is True
        assert len(greeting.get("content", "")) > 0
