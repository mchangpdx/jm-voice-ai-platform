# TDD: AI Voice Bot settings endpoint tests (AI Voice Bot 설정 엔드포인트 테스트)
# Tests: GET /api/store/voice-bot, PATCH /api/store/voice-bot, GET /api/store/voice-bot/agent-status
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_STORE_ID  = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_OWNER_ID  = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"
_AGENT_ID  = "agent_68e9f01ec4d5502b990755d2ef"

_MOCK_STORE = {
    "id":               _STORE_ID,
    "name":             "JM Cafe",
    "retell_agent_id":  _AGENT_ID,
    "system_prompt":    "You are Aria, the AI voice assistant for JM Cafe.",
    "temporary_prompt": "Today's special: Matcha latte $5.",
}

_MOCK_RETELL_AGENT = {
    "agent_id":   _AGENT_ID,
    "agent_name": "CAFE-JM-Aria",
    "voice_id":   "retell-Grace",
    "response_engine": {
        "type":              "custom-llm",
        "llm_websocket_url": "wss://example.ngrok.dev/llm-websocket",
    },
}


def _make_jwt(sub: str) -> str:
    return jwt.encode({"sub": sub}, settings.supabase_service_role_key, algorithm="HS256")


def _mock_http(gets=None, patches=None):
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__  = AsyncMock(return_value=None)

    def _side(pairs):
        effects = []
        for status, body in (pairs or []):
            m = MagicMock()
            m.status_code = status
            m.json.return_value = body
            effects.append(m)
        return effects

    mc.get   = AsyncMock(side_effect=_side(gets))
    mc.patch = AsyncMock(side_effect=_side(patches))
    return mc


AUTH = lambda: {"Authorization": f"Bearer {_make_jwt(_OWNER_ID)}"}


# ── GET /api/store/voice-bot ──────────────────────────────────────────────────

def test_get_voice_bot_returns_prompts_and_agent_id():
    mc = _mock_http(gets=[(200, [_MOCK_STORE])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert data["retell_agent_id"] == _AGENT_ID
    assert data["system_prompt"] == _MOCK_STORE["system_prompt"]
    assert data["temporary_prompt"] == _MOCK_STORE["temporary_prompt"]
    assert data["store_name"] == "JM Cafe"


def test_get_voice_bot_no_store_returns_404():
    mc = _mock_http(gets=[(200, [])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot", headers=AUTH())
    assert resp.status_code == 404


def test_get_voice_bot_no_auth_returns_401():
    resp = client.get("/api/store/voice-bot")
    assert resp.status_code == 401


# ── PATCH /api/store/voice-bot ────────────────────────────────────────────────

def test_patch_voice_bot_updates_both_prompts():
    updated = {**_MOCK_STORE, "system_prompt": "New persona.", "temporary_prompt": "New daily."}
    mc = _mock_http(
        gets=[(200, [_MOCK_STORE])],
        patches=[(200, [updated])],
    )
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.patch(
            "/api/store/voice-bot",
            json={"system_prompt": "New persona.", "temporary_prompt": "New daily."},
            headers=AUTH(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["system_prompt"] == "New persona."
    assert data["temporary_prompt"] == "New daily."


def test_patch_voice_bot_partial_update_temporary_only():
    updated = {**_MOCK_STORE, "temporary_prompt": "Only daily changed."}
    mc = _mock_http(
        gets=[(200, [_MOCK_STORE])],
        patches=[(200, [updated])],
    )
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.patch(
            "/api/store/voice-bot",
            json={"temporary_prompt": "Only daily changed."},
            headers=AUTH(),
        )
    assert resp.status_code == 200
    assert resp.json()["temporary_prompt"] == "Only daily changed."


def test_patch_voice_bot_empty_body_returns_400():
    mc = _mock_http(gets=[(200, [_MOCK_STORE])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.patch("/api/store/voice-bot", json={}, headers=AUTH())
    assert resp.status_code == 400


# ── GET /api/store/voice-bot/agent-status ─────────────────────────────────────

def test_get_agent_status_returns_retell_info():
    mc = _mock_http(gets=[
        (200, [_MOCK_STORE]),
        (200, _MOCK_RETELL_AGENT),
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == _AGENT_ID
    assert data["agent_name"] == "CAFE-JM-Aria"
    assert data["voice_id"] == "retell-Grace"


def test_get_agent_status_no_agent_id_returns_404():
    store_no_agent = {**_MOCK_STORE, "retell_agent_id": None}
    mc = _mock_http(gets=[(200, [store_no_agent])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 404


def test_get_agent_status_retell_api_failure_returns_502():
    mc = _mock_http(gets=[
        (200, [_MOCK_STORE]),
        (401, {"error": "Unauthorized"}),
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 502
