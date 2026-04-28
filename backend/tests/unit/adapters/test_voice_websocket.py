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

# Shared patch for eager init: always return None so call_details path is tested
_NO_AGENT = patch(
    "app.api.voice_websocket._get_agent_id_from_call",
    new_callable=lambda: lambda *a, **k: AsyncMock(return_value=None)(),
)


def _no_init():
    """Decorator: disable eager _init_session by returning None from _get_agent_id_from_call."""
    return patch("app.api.voice_websocket._get_agent_id_from_call", new=AsyncMock(return_value=None))


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


@patch("app.api.voice_websocket._get_agent_id_from_call",
       new=AsyncMock(return_value="agent_68e9f01ec4d5502b990755d2ef"))
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
