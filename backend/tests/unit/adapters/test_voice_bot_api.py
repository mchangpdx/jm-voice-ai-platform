# TDD: AI Voice Bot settings endpoint tests (AI Voice Bot 설정 엔드포인트 테스트)
# Tests: GET /api/store/voice-bot, PATCH /api/store/voice-bot, GET /api/store/voice-bot/agent-status
#
# Phase 2-D migration: agent-status no longer hits the Retell API. The new
# AgentStatus shape is assembled from settings (model/voice) + stores DB
# (system_prompt_loaded) + bridge_transactions (last_call_at).
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_STORE_ID  = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_OWNER_ID  = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"

_MOCK_STORE = {
    "id":               _STORE_ID,
    "name":             "JM Cafe",
    "system_prompt":    "You are Aria, the AI voice assistant for JM Cafe.",
    "temporary_prompt": "Today's special: Matcha latte $5.",
    "business_hours":   None,
    "custom_knowledge": None,
    "is_active":        True,
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

def test_get_voice_bot_returns_prompts_and_deprecated_agent_id_none():
    mc = _mock_http(gets=[(200, [_MOCK_STORE])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    # retell_agent_id is deprecated post-OpenAI Realtime migration → always None
    assert data["retell_agent_id"] is None
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
    assert data["retell_agent_id"] is None


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

def test_agent_status_returns_openai_shape_with_last_call():
    """Agent status assembles model/voice from settings + system_prompt_loaded
    from store + last_call_at from bridge_transactions latest row.
    (model/voice는 설정값, system_prompt_loaded는 store, last_call_at은 bridge_tx 최신 행)
    """
    last_call_iso = "2026-05-09T12:34:56.000+00:00"
    mc = _mock_http(gets=[
        (200, [_MOCK_STORE]),
        (200, [{"created_at": last_call_iso}]),
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == settings.openai_realtime_model
    assert data["voice"] == settings.openai_realtime_voice
    assert data["system_prompt_loaded"] is True
    assert data["last_call_at"] == last_call_iso


def test_agent_status_no_calls_returns_last_call_none():
    mc = _mock_http(gets=[
        (200, [_MOCK_STORE]),
        (200, []),  # bridge_transactions empty
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_call_at"] is None
    assert data["system_prompt_loaded"] is True


def test_agent_status_no_system_prompt_marks_loaded_false():
    store_no_prompt = {**_MOCK_STORE, "system_prompt": None}
    mc = _mock_http(gets=[
        (200, [store_no_prompt]),
        (200, []),
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 200
    assert resp.json()["system_prompt_loaded"] is False


def test_agent_status_bridge_query_failure_falls_back_to_none():
    """If bridge_transactions query fails, last_call_at degrades to None
    rather than failing the entire endpoint.
    (bridge_transactions 쿼리 실패 시 endpoint 깨지지 않고 last_call_at=None로 graceful degrade)
    """
    mc = _mock_http(gets=[
        (200, [_MOCK_STORE]),
        (500, {"error": "internal"}),
    ])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 200
    assert resp.json()["last_call_at"] is None


def test_agent_status_no_store_returns_404():
    mc = _mock_http(gets=[(200, [])])
    with patch("httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/voice-bot/agent-status", headers=AUTH())
    assert resp.status_code == 404
