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
_TEST_API_URL = "https://solink.example.com"
_TEST_API_KEY = "solink-bearer-key"

_SAMPLE_EVENT = {
    "event_type": "motion_detected",
    "camera_id": "cam-001",
    "location": "Front Entrance",
    "timestamp": "2026-04-25T14:30:00Z",
}


@pytest.mark.asyncio
async def test_solink_relay_event_posts_correct_request():
    """SolinkRelay.relay_event() posts to {api_url}/events with correct headers and body.
    (SolinkRelay.relay_event()가 올바른 URL, 헤더, 바디로 POST 요청을 보내야 함)
    """
    from app.adapters.solink.solink_relay import SolinkRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
        relay = SolinkRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY, timeout=8)
        result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    # Verify POST was called to /events endpoint (POST 요청이 /events 엔드포인트로 전송됐는지 확인)
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args

    assert f"{_TEST_API_URL}/events" in call_kwargs[0] or call_kwargs[1].get("url") == f"{_TEST_API_URL}/events"

    # Check headers include Authorization and X-Tenant-ID (Authorization 및 X-Tenant-ID 헤더 확인)
    posted_headers = call_kwargs[1].get("headers", {}) or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
    # Access via args or kwargs depending on how post is called
    all_call_args = mock_client.post.call_args
    headers = all_call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == f"Bearer {_TEST_API_KEY}"
    assert headers.get("X-Tenant-ID") == _TEST_TENANT_ID


@pytest.mark.asyncio
async def test_solink_relay_event_returns_relay_id_and_queued_at():
    """relay_event() returns a dict with relay_id (UUID) and queued_at (ISO timestamp).
    (relay_event()는 relay_id(UUID)와 queued_at(ISO 타임스탬프)를 포함한 딕셔너리를 반환해야 함)
    """
    from app.adapters.solink.solink_relay import SolinkRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
        relay = SolinkRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
        result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    # Validate return shape (반환 구조 검증)
    assert "relay_id" in result
    assert "queued_at" in result

    # relay_id must be a valid UUID string (relay_id는 유효한 UUID 문자열이어야 함)
    uuid.UUID(result["relay_id"])  # Raises ValueError if not a valid UUID

    # queued_at must end with Z (ISO 8601 UTC) (queued_at은 Z로 끝나야 함)
    assert result["queued_at"].endswith("Z")


@pytest.mark.asyncio
async def test_solink_relay_event_handles_timeout_gracefully():
    """relay_event() catches httpx.TimeoutException and logs it — does not raise.
    (relay_event()는 TimeoutException을 잡아 로깅하고 예외를 전파하지 않아야 함)
    """
    from app.adapters.solink.solink_relay import SolinkRelay

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Connection timed out"))

    with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
        with patch("app.adapters.solink.solink_relay.logger") as mock_logger:
            relay = SolinkRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
            result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    # Must log the error (에러를 로깅해야 함)
    mock_logger.error.assert_called_once()

    # Must still return relay_id and queued_at (여전히 relay_id와 queued_at을 반환해야 함)
    assert "relay_id" in result
    assert "queued_at" in result


@pytest.mark.asyncio
async def test_solink_relay_event_handles_http_status_error_gracefully():
    """relay_event() catches httpx.HTTPStatusError and logs it — does not raise.
    (relay_event()는 HTTPStatusError를 잡아 로깅하고 예외를 전파하지 않아야 함)
    """
    from app.adapters.solink.solink_relay import SolinkRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.solink.solink_relay.httpx.AsyncClient", return_value=mock_client):
        with patch("app.adapters.solink.solink_relay.logger") as mock_logger:
            relay = SolinkRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
            result = await relay.relay_event(_SAMPLE_EVENT, _TEST_TENANT_ID)

    # Must log the error (에러를 로깅해야 함)
    mock_logger.error.assert_called_once()

    # Must still return relay_id and queued_at (여전히 relay_id와 queued_at을 반환해야 함)
    assert "relay_id" in result
    assert "queued_at" in result
