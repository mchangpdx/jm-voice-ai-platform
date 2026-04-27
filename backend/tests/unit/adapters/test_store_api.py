# TDD: Store metrics & orders endpoint tests (스토어 지표 및 주문 엔드포인트 테스트)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_STORE_ID = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_OWNER_ID = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"

_MOCK_STORES       = [{"id": _STORE_ID, "name": "JM Cafe", "agency_id": "e4d0c104-659c-4d49-a63b-5c16bf2d83bf", "industry": "restaurant"}]
_MOCK_STORE_CONFIGS = [{"hourly_wage": 20.00, "timezone": "America/Los_Angeles", "is_override_busy": False, "override_until": None}]

# Call logs variants
_MOCK_CALL_LOGS_BUSY   = [{"call_status": "Successful", "duration": 180, "is_store_busy": True}]  * 3
_MOCK_CALL_LOGS_NO_BUSY = [{"call_status": "Successful", "duration": 180, "is_store_busy": False}] * 3

_MOCK_ORDERS = [
    {"id": 88, "customer_phone": "+15037079566", "customer_email": "cymeet@gmail.com",
     "total_amount": 10.99, "status": "paid", "created_at": "2026-04-23T23:14:00Z",
     "items": [{"name": "Cheese Pizza", "quantity": 1}]},
]


def _make_jwt(sub: str) -> str:
    return jwt.encode({"sub": sub}, settings.supabase_service_role_key, algorithm="HS256")


def _mock_get(responses: list):
    """Returns an AsyncMock httpx client that returns responses in order for each .get() call."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    side_effects = []
    for status, body in responses:
        m = MagicMock()
        m.status_code = status
        m.json.return_value = body
        side_effects.append(m)

    mock_client.get = AsyncMock(side_effect=side_effects)
    return mock_client


# ── /me endpoint ─────────────────────────────────────────────────────────────

def test_store_me_returns_store_info():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get("/api/store/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "JM Cafe"
    assert data["id"] == _STORE_ID


def test_store_me_returns_industry():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get("/api/store/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["industry"] == "restaurant"


def test_store_me_returns_404_if_no_store():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([(200, [])])):
        resp = client.get("/api/store/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


# ── /metrics — KPI calculation ───────────────────────────────────────────────

def test_store_metrics_fallback_mcrr_when_no_busy_data():
    """No is_store_busy data → fallback MCRR = 3 × 0.20 × 1.0 × 10.99 = $6.59"""
    token = _make_jwt(_OWNER_ID)
    mock_orders_paid = [{"total_amount": 10.99, "status": "paid"}] * 2
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_STORE_CONFIGS),
        (200, _MOCK_CALL_LOGS_NO_BUSY),
        (200, mock_orders_paid),
    ])):
        resp = client.get("/api/store/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 3
    assert data["successful_calls"] == 3
    assert abs(data["lcs"] - 3.00) < 0.01            # (540s/3600) × $20
    assert abs(data["mcrr"] - 6.59) < 0.01           # fallback: 3 × 0.20 × 1.0 × 10.99
    assert abs(data["upselling_value"] - 2.25) < 0.01
    assert abs(data["lcr"] - 100.0) < 0.01
    assert abs(data["total_ai_revenue"] - 21.98) < 0.01
    assert data["using_real_busy_data"] is False


def test_store_metrics_real_mcrr_from_busy_calls():
    """3 busy+successful calls × $10.99 avg ticket = $32.97 MCRR"""
    token = _make_jwt(_OWNER_ID)
    mock_orders_paid = [{"total_amount": 10.99, "status": "paid"}] * 2
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_STORE_CONFIGS),
        (200, _MOCK_CALL_LOGS_BUSY),
        (200, mock_orders_paid),
    ])):
        resp = client.get("/api/store/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["mcrr"] - 32.97) < 0.01          # real: 3 × $10.99
    assert data["using_real_busy_data"] is True


def test_store_metrics_uses_store_config_hourly_wage():
    """Store hourly_wage=25.00 → LCS = (540s/3600) × $25 = $3.75"""
    token = _make_jwt(_OWNER_ID)
    high_wage_cfg = [{"hourly_wage": 25.00, "timezone": "America/Los_Angeles", "is_override_busy": False, "override_until": None}]
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, high_wage_cfg),
        (200, _MOCK_CALL_LOGS_NO_BUSY),
        (200, []),
    ])):
        resp = client.get("/api/store/metrics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["lcs"] - 3.75) < 0.01
    assert abs(data["hourly_wage"] - 25.00) < 0.01


# ── /metrics — period filter ──────────────────────────────────────────────────

def test_store_metrics_today_filter_passes_created_at_param():
    """period=today must attach a created_at gte filter to call_logs and orders queries."""
    token = _make_jwt(_OWNER_ID)
    mock_client = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_STORE_CONFIGS),
        (200, []),
        (200, []),
    ])
    with patch("app.api.store.httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/api/store/metrics?period=today", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # call 0=stores, 1=store_configs, 2=call_logs, 3=orders
    call_logs_params = mock_client.get.call_args_list[2].kwargs.get("params", {})
    orders_params    = mock_client.get.call_args_list[3].kwargs.get("params", {})
    # call_logs filters by start_time (actual call time); orders filter by created_at
    assert "start_time" in call_logs_params
    assert call_logs_params["start_time"].startswith("gte.")
    assert "created_at" in orders_params


def test_store_metrics_all_period_has_no_date_filter():
    """period=all must NOT add a created_at filter."""
    token = _make_jwt(_OWNER_ID)
    mock_client = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_STORE_CONFIGS),
        (200, _MOCK_CALL_LOGS_NO_BUSY),
        (200, []),
    ])
    with patch("app.api.store.httpx.AsyncClient", return_value=mock_client):
        resp = client.get("/api/store/metrics?period=all", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    call_logs_params = mock_client.get.call_args_list[2].kwargs.get("params", {})
    assert "start_time" not in call_logs_params


def test_store_metrics_invalid_period_returns_400():
    """Unsupported period values must return HTTP 400."""
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get("/api/store/metrics?period=yesterday", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


# ── /orders ───────────────────────────────────────────────────────────────────

def test_store_orders_returns_recent_orders():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_ORDERS),
    ])):
        resp = client.get("/api/store/orders", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 1
    assert orders[0]["status"] == "paid"
    assert orders[0]["total_amount"] == 10.99


# ── /call-logs endpoint ───────────────────────────────────────────────────────

_MOCK_CALL_LOG_ITEMS = [
    {
        "call_id": "call_abc123",
        "store_id": _STORE_ID,
        "start_time": "2026-04-20T14:30:00+00:00",
        "customer_phone": "+15037079566",
        "duration": 120,
        "sentiment": "Positive",
        "call_status": "Successful",
        "cost": 1.20,
        "recording_url": "https://cdn.example.com/rec.wav",
        "summary": "Customer ordered a latte.",
        "is_store_busy": True,
    },
    {
        "call_id": "call_def456",
        "store_id": _STORE_ID,
        "start_time": "2026-04-19T10:00:00+00:00",
        "customer_phone": "+15037079567",
        "duration": 30,
        "sentiment": "Neutral",
        "call_status": "Unsuccessful",
        "cost": 0.50,
        "recording_url": None,
        "summary": "Call dropped.",
        "is_store_busy": False,
    },
]


_MOCK_CFG = [{"timezone": "America/Los_Angeles"}]


def test_call_logs_returns_paginated_results():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, _MOCK_CALL_LOG_ITEMS),
    ])):
        resp = client.get("/api/store/call-logs?period=all&page=1&limit=20",
                          headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] == 2
    assert body["page"] == 1
    assert len(body["items"]) == 2
    assert body["items"][0]["call_id"] == "call_abc123"


def test_call_logs_filters_by_status():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, [_MOCK_CALL_LOG_ITEMS[0]]),  # backend returns only Successful
    ])):
        resp = client.get("/api/store/call-logs?status=Successful",
                          headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(item["call_status"] == "Successful" for item in body["items"])


def test_call_logs_invalid_period_returns_400():
    token = _make_jwt(_OWNER_ID)
    resp = client.get("/api/store/call-logs?period=yesterday",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


def test_call_logs_pagination_second_page():
    token = _make_jwt(_OWNER_ID)
    # 25 items total, page=2, limit=20 → 5 items
    many = [_MOCK_CALL_LOG_ITEMS[0]] * 25
    with patch("app.api.store.httpx.AsyncClient", return_value=_mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, many),
    ])):
        resp = client.get("/api/store/call-logs?page=2&limit=20",
                          headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 25
    assert body["page"] == 2
    assert len(body["items"]) == 5
