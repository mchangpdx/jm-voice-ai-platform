# Tests for LoyverseRelay adapter (LoyverseRelay 어댑터 테스트)
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
_TEST_API_URL = "https://api.loyverse.com/v1.0"
_TEST_API_KEY = "loyverse-bearer-token"

_SAMPLE_ORDER = {
    "items": [
        {"variant_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "quantity": 2},
    ],
    "table_number": "Table 5",
    "note": "No onions please",
}


@pytest.mark.asyncio
async def test_loyverse_relay_order_posts_to_receipts():
    """LoyverseRelay.relay_order() posts to {api_url}/receipts with correct headers.
    (LoyverseRelay.relay_order()가 올바른 URL과 헤더로 /receipts에 POST해야 함)
    """
    from app.adapters.loyverse.loyverse_relay import LoyverseRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.loyverse.loyverse_relay.httpx.AsyncClient", return_value=mock_client):
        relay = LoyverseRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY, timeout=8)
        result = await relay.relay_order(_SAMPLE_ORDER, _TEST_TENANT_ID)

    # Verify POST was called (POST 호출 확인)
    mock_client.post.assert_called_once()
    all_call_args = mock_client.post.call_args

    # Verify target URL ends with /receipts (대상 URL이 /receipts로 끝나는지 확인)
    positional_url = all_call_args[0][0] if all_call_args[0] else all_call_args.kwargs.get("url", "")
    assert positional_url.endswith("/receipts"), f"Expected URL to end with /receipts, got: {positional_url}"

    # Check headers (헤더 확인)
    headers = all_call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == f"Bearer {_TEST_API_KEY}"
    assert headers.get("X-Tenant-ID") == _TEST_TENANT_ID


@pytest.mark.asyncio
async def test_loyverse_relay_order_returns_correct_shape():
    """relay_order() returns relay_id, loyverse_receipt_id (None initially), and queued_at.
    (relay_order()는 relay_id, loyverse_receipt_id(초기에는 None), queued_at을 반환해야 함)
    """
    from app.adapters.loyverse.loyverse_relay import LoyverseRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.loyverse.loyverse_relay.httpx.AsyncClient", return_value=mock_client):
        relay = LoyverseRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
        result = await relay.relay_order(_SAMPLE_ORDER, _TEST_TENANT_ID)

    # Validate return shape (반환 구조 검증)
    assert "relay_id" in result
    assert "loyverse_receipt_id" in result
    assert "queued_at" in result

    # relay_id must be a valid UUID string (relay_id는 유효한 UUID 문자열이어야 함)
    uuid.UUID(result["relay_id"])

    # loyverse_receipt_id starts as None (fire-and-forget) (초기에는 None)
    assert result["loyverse_receipt_id"] is None

    # queued_at must end with Z (UTC ISO 8601) (queued_at은 Z로 끝나야 함)
    assert result["queued_at"].endswith("Z")


@pytest.mark.asyncio
async def test_loyverse_relay_order_handles_timeout_gracefully():
    """relay_order() catches httpx.TimeoutException and logs it — does not raise.
    (relay_order()는 TimeoutException을 잡아 로깅하고 예외를 전파하지 않아야 함)
    """
    from app.adapters.loyverse.loyverse_relay import LoyverseRelay

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))

    with patch("app.adapters.loyverse.loyverse_relay.httpx.AsyncClient", return_value=mock_client):
        with patch("app.adapters.loyverse.loyverse_relay.logger") as mock_logger:
            relay = LoyverseRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
            result = await relay.relay_order(_SAMPLE_ORDER, _TEST_TENANT_ID)

    # Must log the error (에러를 로깅해야 함)
    mock_logger.error.assert_called_once()

    # Must still return correct shape (올바른 구조를 반환해야 함)
    assert "relay_id" in result
    assert "loyverse_receipt_id" in result
    assert "queued_at" in result


@pytest.mark.asyncio
async def test_loyverse_relay_order_handles_http_status_error_gracefully():
    """relay_order() catches httpx.HTTPStatusError and logs it — does not raise.
    (relay_order()는 HTTPStatusError를 잡아 로깅하고 예외를 전파하지 않아야 함)
    """
    from app.adapters.loyverse.loyverse_relay import LoyverseRelay

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "422 Unprocessable Entity",
            request=MagicMock(),
            response=MagicMock(status_code=422),
        )
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.adapters.loyverse.loyverse_relay.httpx.AsyncClient", return_value=mock_client):
        with patch("app.adapters.loyverse.loyverse_relay.logger") as mock_logger:
            relay = LoyverseRelay(api_url=_TEST_API_URL, api_key=_TEST_API_KEY)
            result = await relay.relay_order(_SAMPLE_ORDER, _TEST_TENANT_ID)

    # Must log the error (에러를 로깅해야 함)
    mock_logger.error.assert_called_once()

    # Must still return correct shape (올바른 구조를 반환해야 함)
    assert "relay_id" in result
    assert result["loyverse_receipt_id"] is None
