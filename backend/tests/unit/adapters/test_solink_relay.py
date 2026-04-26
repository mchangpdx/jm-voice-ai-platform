# Tests for SolinkRelay adapter (SolinkRelay 어댑터 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Inject required env vars before importing app modules (앱 모듈 임포트 전 환경 변수 주입)
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")

_TEST_TENANT_ID = "a1b2c3d4-0000-0000-0000-000000000001"
_TEST_API_URL = "https://api-prod-us-west-2.solinkcloud.com/v2"
_TEST_TOKEN_URL = "https://api-prod-us-west-2.solinkcloud.com/v2/oauth/token"
_TEST_AUDIENCE = "https://prod.solinkcloud.com/"
_TEST_CLIENT_ID = "test-client-id"
_TEST_CLIENT_SECRET = "test-client-secret"
_TEST_API_KEY = "test-x-api-key"
_MOCK_ACCESS_TOKEN = "mock-access-token"

_SAMPLE_EVENT = {
    "event_type": "motion_detected",
    "camera_id": "cam-001",
    "location": "Front Entrance",
    "timestamp": "2026-04-25T14:30:00Z",
}


def _make_relay(timeout: int = 8):
    """Construct SolinkRelay with test credentials (테스트 자격증명으로 SolinkRelay 생성)."""
    from app.adapters.solink.solink_relay import SolinkRelay

    return SolinkRelay(
        api_url=_TEST_API_URL,
        token_url=_TEST_TOKEN_URL,
        audience=_TEST_AUDIENCE,
        client_id=_TEST_CLIENT_ID,
        client_secret=_TEST_CLIENT_SECRET,
        api_key=_TEST_API_KEY,
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_solink_relay_event_posts_correct_request():
    """relay_event() calls the Solink events endpoint with correct Bearer token and X-Tenant-ID.
    (relay_event()가 올바른 Bearer 토큰과 X-Tenant-ID로 Solink 이벤트 엔드포인트를 호출해야 함)
    """
    mock_event_response = MagicMock()
    mock_event_response.raise_for_status = MagicMock()

    relay = _make_relay()

    # Patch _get_access_token so we don't need a real token server (실제 토큰 서버 불필요)
    with patch.object(relay, "_get_access_token", new=AsyncMock(return_value=_MOCK_ACCESS_TOKEN)):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_event_response)

        with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
            result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    # Verify POST was called to the /events endpoint (POST 요청이 /events 엔드포인트로 전송됐는지 확인)
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    posted_url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
    assert posted_url == f"{_TEST_API_URL}/events"

    # Verify Bearer token and X-Tenant-ID headers (Bearer 토큰 및 X-Tenant-ID 헤더 확인)
    headers = call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == f"Bearer {_MOCK_ACCESS_TOKEN}"
    assert headers.get("X-Tenant-ID") == _TEST_TENANT_ID
    assert headers.get("x-api-key") == _TEST_API_KEY


@pytest.mark.asyncio
async def test_solink_relay_event_returns_relay_id_and_queued_at():
    """relay_event() returns a dict with relay_id (UUID) and queued_at (ISO UTC timestamp).
    (relay_event()는 relay_id(UUID)와 queued_at(ISO UTC 타임스탬프)를 반환해야 함)
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    relay = _make_relay()

    with patch.object(relay, "_get_access_token", new=AsyncMock(return_value=_MOCK_ACCESS_TOKEN)):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
            result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    assert "relay_id" in result
    assert "queued_at" in result
    uuid.UUID(result["relay_id"])        # Must be a valid UUID (유효한 UUID여야 함)
    assert result["queued_at"].endswith("Z")  # ISO 8601 UTC (UTC ISO 8601)


@pytest.mark.asyncio
async def test_solink_relay_event_handles_timeout_gracefully():
    """relay_event() catches TimeoutException and logs it — never raises to caller.
    (relay_event()는 TimeoutException을 잡아 로깅하고 호출자에게 예외를 전파하지 않아야 함)
    """
    relay = _make_relay()

    with patch.object(relay, "_get_access_token", new=AsyncMock(return_value=_MOCK_ACCESS_TOKEN)):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))

        with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
            with patch("app.adapters.solink.solink_relay.logger") as mock_logger:
                result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    mock_logger.error.assert_called()          # Error must be logged (오류 로깅 필수)
    assert "relay_id" in result                 # Must still return tracking info (추적 정보 반환 필수)
    assert "queued_at" in result


@pytest.mark.asyncio
async def test_solink_relay_event_handles_http_status_error_gracefully():
    """relay_event() catches HTTPStatusError and logs it — never raises to caller.
    (relay_event()는 HTTPStatusError를 잡아 로깅하고 호출자에게 예외를 전파하지 않아야 함)
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    )

    relay = _make_relay()

    with patch.object(relay, "_get_access_token", new=AsyncMock(return_value=_MOCK_ACCESS_TOKEN)):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
            with patch("app.adapters.solink.solink_relay.logger") as mock_logger:
                result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    mock_logger.error.assert_called()
    assert "relay_id" in result
    assert "queued_at" in result
