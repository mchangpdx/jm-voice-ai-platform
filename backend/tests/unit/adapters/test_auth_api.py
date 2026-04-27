# TDD: Auth login endpoint tests (인증 로그인 엔드포인트 테스트)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_SUPABASE_SUCCESS = {
    "access_token": "test.jwt.token",
    "token_type": "bearer",
    "user": {"email": "jmcafe@test.com"},
}


def _mock_httpx(status_code: int, body: dict):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)
    return mock_client


def test_login_returns_token_on_success():
    with patch("app.api.auth.httpx.AsyncClient", return_value=_mock_httpx(200, _SUPABASE_SUCCESS)):
        resp = client.post("/api/auth/login", json={"email": "jmcafe@test.com", "password": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "test.jwt.token"
    assert data["token_type"] == "bearer"


def test_login_returns_401_on_invalid_credentials():
    error_body = {"error": "invalid_grant", "error_description": "Invalid login credentials"}
    with patch("app.api.auth.httpx.AsyncClient", return_value=_mock_httpx(400, error_body)):
        resp = client.post("/api/auth/login", json={"email": "bad@test.com", "password": "wrong"})
    assert resp.status_code == 401


def test_login_missing_password_returns_422():
    resp = client.post("/api/auth/login", json={"email": "jmcafe@test.com"})
    assert resp.status_code == 422


def test_login_missing_email_returns_422():
    resp = client.post("/api/auth/login", json={"password": "test"})
    assert resp.status_code == 422
