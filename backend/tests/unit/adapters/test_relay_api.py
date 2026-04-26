# Tests for Relay Bridge FastAPI router endpoints (릴레이 브리지 FastAPI 라우터 엔드포인트 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import os
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

# Inject required env vars before importing app modules (앱 모듈 임포트 전 환경 변수 주입)
_TEST_SECRET = "test-supabase-service-role-key"
_TEST_TENANT_ID = "a1b2c3d4-0000-0000-0000-000000000001"

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = _TEST_SECRET  # Always set for auth to work (항상 설정)
os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")

_VALID_SOLINK_PAYLOAD = {
    "event_type": "motion_detected",
    "camera_id": "cam-001",
    "location": "Front Entrance",
    "timestamp": "2026-04-25T14:30:00Z",
}

_VALID_LOYVERSE_PAYLOAD = {
    "items": [
        {"variant_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479", "quantity": 2},
    ],
    "table_number": "Table 5",
    "note": "No onions please",
}


def _make_auth_header() -> dict:
    """Generate a valid Bearer token Authorization header for test requests.
    (테스트 요청용 유효한 Bearer 토큰 Authorization 헤더 생성)
    """
    payload = {"sub": _TEST_TENANT_ID, "exp": int(time.time()) + 3600}
    token = jwt.encode(payload, _TEST_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_relay_ack(relay_id: str | None = None) -> dict:
    """Create a fake relay result returned by the mocked relay classes.
    (모의 릴레이 클래스가 반환하는 가짜 릴레이 결과 생성)
    """
    rid = relay_id or str(uuid.uuid4())
    return {"relay_id": rid, "queued_at": "2026-04-25T14:30:00.000Z"}


@pytest.fixture
def app():
    """Create FastAPI app instance with relay router included.
    (릴레이 라우터가 포함된 FastAPI 앱 인스턴스 생성)
    """
    # Reload modules to pick up env vars set above (위에서 설정한 환경 변수 반영을 위해 모듈 리로드)
    import importlib
    import sys

    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("app."):
            del sys.modules[mod_name]

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.relay import router as relay_router
    test_app.include_router(relay_router)

    return test_app


@pytest.mark.asyncio
async def test_relay_solink_event_returns_202_with_relay_ack(app):
    """POST /api/relay/solink/event with valid JWT returns 202 RelayAck.
    (유효한 JWT로 POST /api/relay/solink/event 요청 시 202 RelayAck 반환)
    """
    fake_ack = _make_relay_ack()

    with patch("app.api.relay.SolinkRelay") as MockSolinkRelay:
        mock_instance = AsyncMock()
        mock_instance.relay_event = AsyncMock(return_value=fake_ack)
        MockSolinkRelay.return_value = mock_instance

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/relay/solink/event",
                json=_VALID_SOLINK_PAYLOAD,
                headers=_make_auth_header(),
            )

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert "relay_id" in data
    assert "queued_at" in data
    # relay_id must be a valid UUID (relay_id는 유효한 UUID여야 함)
    uuid.UUID(data["relay_id"])


@pytest.mark.asyncio
async def test_relay_loyverse_order_returns_202_with_order_ack(app):
    """POST /api/relay/loyverse/order with valid JWT returns 202 LoyverseOrderAck.
    (유효한 JWT로 POST /api/relay/loyverse/order 요청 시 202 LoyverseOrderAck 반환)
    """
    fake_ack = {**_make_relay_ack(), "loyverse_receipt_id": None}

    with patch("app.api.relay.LoyverseRelay") as MockLoyverseRelay:
        mock_instance = AsyncMock()
        mock_instance.relay_order = AsyncMock(return_value=fake_ack)
        MockLoyverseRelay.return_value = mock_instance

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/relay/loyverse/order",
                json=_VALID_LOYVERSE_PAYLOAD,
                headers=_make_auth_header(),
            )

    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] is True
    assert "relay_id" in data
    assert "loyverse_receipt_id" in data
    assert "queued_at" in data
    assert data["loyverse_receipt_id"] is None  # Filled async — None at 202 time (비동기 처리 전 None)


@pytest.mark.asyncio
async def test_relay_solink_event_missing_auth_returns_401(app):
    """POST /api/relay/solink/event without Authorization header returns 401.
    (Authorization 헤더 없이 요청 시 401 반환)
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/relay/solink/event",
            json=_VALID_SOLINK_PAYLOAD,
            # No Authorization header (Authorization 헤더 없음)
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_relay_loyverse_order_missing_auth_returns_401(app):
    """POST /api/relay/loyverse/order without Authorization header returns 401.
    (Authorization 헤더 없이 요청 시 401 반환)
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/relay/loyverse/order",
            json=_VALID_LOYVERSE_PAYLOAD,
            # No Authorization header (Authorization 헤더 없음)
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_relay_solink_event_invalid_body_returns_422(app):
    """POST /api/relay/solink/event with invalid body returns 422.
    (잘못된 바디로 POST 요청 시 422 반환)
    """
    invalid_payload = {
        # Missing required fields: event_type, camera_id, location, timestamp
        # (필수 필드 누락: event_type, camera_id, location, timestamp)
        "metadata": {"some": "data"},
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/relay/solink/event",
            json=invalid_payload,
            headers=_make_auth_header(),
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_relay_loyverse_order_invalid_body_returns_422(app):
    """POST /api/relay/loyverse/order with invalid body returns 422.
    (잘못된 바디로 POST 요청 시 422 반환)
    """
    invalid_payload = {
        # Missing required 'items' field (필수 'items' 필드 누락)
        "table_number": "Table 5",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/relay/loyverse/order",
            json=invalid_payload,
            headers=_make_auth_header(),
        )

    assert response.status_code == 422
