# Tests for JWT tenant resolver dependency (JWT 테넌트 리졸버 의존성 테스트)
# TDD: tests written before implementation (TDD: 구현 전 테스트 작성)

import os
import time

import pytest
from fastapi import HTTPException
from jose import jwt

# Inject required env vars before importing module under test, but ONLY if a
# real .env is missing — otherwise the placeholder host bleeds into other test
# files via os.environ (the Settings singleton then resolves placeholder URLs
# and downstream HTTP modules cache _REST against a non-resolving host).
# (모듈 임포트 전 필수 env 주입 — .env가 없을 때만; 있으면 .env 로딩 우선)
_TEST_SECRET = "test-supabase-service-role-key"
_TEST_TENANT_ID = "a1b2c3d4-0000-0000-0000-000000000001"

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if not os.path.isfile(os.path.join(_BACKEND_ROOT, ".env")):
    os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", _TEST_SECRET)
    os.environ.setdefault("GEMINI_API_KEY", "placeholder-gemini-key")


def _make_token(sub: str, secret: str, exp_offset: int = 3600) -> str:
    # Create a signed HS256 JWT with given sub and expiry offset in seconds
    # (주어진 sub와 만료 오프셋(초)으로 서명된 HS256 JWT 생성)
    payload = {"sub": sub, "exp": int(time.time()) + exp_offset}
    return jwt.encode(payload, secret, algorithm="HS256")


def _make_expired_token(sub: str, secret: str) -> str:
    # Create an already-expired JWT (만료된 JWT 생성)
    payload = {"sub": sub, "exp": int(time.time()) - 10}
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.asyncio
async def test_get_tenant_id_valid_token(monkeypatch):
    # A valid Bearer token should return the sub claim as tenant_id
    # (유효한 Bearer 토큰은 sub 클레임을 tenant_id로 반환해야 함)
    # Patch the live Settings singleton so JWT validation uses _TEST_SECRET.
    # Why setattr (not setenv + reload): module reload reads from a possibly
    # mutated config singleton, and setenv alone won't update an already-loaded
    # Settings instance. setattr on the singleton is deterministic and avoids
    # the cross-file env pollution that broke earlier suite-wide runs.
    # (Settings 싱글톤을 직접 패치 — env 변경 + reload 패턴은 isolation 깨짐)
    import sys
    monkeypatch.setattr(sys.modules["app.core.config"].settings,
                        "supabase_service_role_key", _TEST_SECRET)
    from app.core.auth import get_tenant_id

    token = _make_token(_TEST_TENANT_ID, _TEST_SECRET)
    result = await get_tenant_id(authorization=f"Bearer {token}")

    assert result == _TEST_TENANT_ID


@pytest.mark.asyncio
async def test_get_tenant_id_missing_header_raises_401():
    # Missing Authorization header must raise HTTP 401
    # (Authorization 헤더 누락 시 HTTP 401 발생해야 함)
    from app.core.auth import get_tenant_id

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant_id(authorization=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_tenant_id_invalid_token_raises_401():
    # A garbage / non-JWT string must raise HTTP 401
    # (잘못된 토큰 문자열은 HTTP 401을 발생시켜야 함)
    from app.core.auth import get_tenant_id

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant_id(authorization="Bearer this.is.garbage")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_tenant_id_expired_token_raises_401(monkeypatch):
    # An expired JWT must raise HTTP 401 with WWW-Authenticate: Bearer
    # (만료된 JWT는 WWW-Authenticate: Bearer와 함께 HTTP 401을 발생시켜야 함)
    import sys
    monkeypatch.setattr(sys.modules["app.core.config"].settings,
                        "supabase_service_role_key", _TEST_SECRET)
    from app.core.auth import get_tenant_id

    expired_token = _make_expired_token(_TEST_TENANT_ID, _TEST_SECRET)

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant_id(authorization=f"Bearer {expired_token}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"
