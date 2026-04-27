# TDD: Reservations + Analytics endpoint tests (예약 및 분석 엔드포인트 테스트)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_STORE_ID = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_OWNER_ID = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"

_MOCK_STORES = [{"id": _STORE_ID, "name": "JM Cafe", "agency_id": "e4d0c104-659c-4d49-a63b-5c16bf2d83bf"}]
_MOCK_CFG   = [{"hourly_wage": 20.0, "timezone": "America/Los_Angeles"}]

_MOCK_RESERVATIONS = [
    {
        "id": 1, "store_id": _STORE_ID, "call_log_id": "abc-123",
        "customer_name": "Alex Johnson", "customer_phone": "+15031234567",
        "party_size": 4, "reservation_time": "2026-04-28T19:00:00+00:00",
        "status": "confirmed", "notes": "Birthday dinner",
        "created_at": "2026-04-26T10:00:00+00:00",
    },
    {
        "id": 2, "store_id": _STORE_ID, "call_log_id": "def-456",
        "customer_name": "Maria Rodriguez", "customer_phone": "+15032345678",
        "party_size": 2, "reservation_time": "2026-04-27T18:00:00+00:00",
        "status": "pending", "notes": None,
        "created_at": "2026-04-26T11:00:00+00:00",
    },
]


def _make_jwt(sub: str) -> str:
    return jwt.encode({"sub": sub}, settings.supabase_service_role_key, algorithm="HS256")


def _mock_get(responses: list):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    side_effects = []
    for status, body in responses:
        m = MagicMock()
        m.status_code = status
        m.json.return_value = body
        side_effects.append(m)
    mock_client.get  = AsyncMock(side_effect=side_effects)
    mock_client.patch = AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=[])))
    return mock_client


# ── GET /api/store/reservations ───────────────────────────────────────────────

def test_reservations_returns_list():
    token = _make_jwt(_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),        # store_configs timezone fetch
        (200, _MOCK_RESERVATIONS),
    ])
    with patch("app.api.reservations.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/store/reservations", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["customer_name"] == "Alex Johnson"
    assert data["items"][0]["party_size"] == 4


def test_reservations_filters_by_status():
    token = _make_jwt(_OWNER_ID)
    confirmed = [r for r in _MOCK_RESERVATIONS if r["status"] == "confirmed"]
    mock = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),        # store_configs timezone fetch
        (200, confirmed),
    ])
    with patch("app.api.reservations.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            "/api/store/reservations?status=confirmed",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["status"] == "confirmed"


def test_reservations_invalid_status_returns_400():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.reservations.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get(
            "/api/store/reservations?status=unknown",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


def test_reservations_invalid_period_returns_400():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.reservations.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get(
            "/api/store/reservations?period=yearly",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


# ── PATCH /api/store/reservations/{id} ───────────────────────────────────────

def test_reservations_patch_updates_status():
    token = _make_jwt(_OWNER_ID)
    updated = [{**_MOCK_RESERVATIONS[0], "status": "seated"}]
    mock = _mock_get([(200, _MOCK_STORES)])
    mock.patch = AsyncMock(
        return_value=MagicMock(status_code=200, json=MagicMock(return_value=updated))
    )
    with patch("app.api.reservations.httpx.AsyncClient", return_value=mock):
        resp = client.patch(
            "/api/store/reservations/1",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "seated"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "seated"


def test_reservations_patch_invalid_status_returns_400():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.reservations.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.patch(
            "/api/store/reservations/1",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "ghost"},
        )
    assert resp.status_code == 400


# ── GET /api/store/analytics ─────────────────────────────────────────────────

_MOCK_CALL_LOGS_ANALYTICS = [
    {"call_status": "Successful",   "duration": 240, "is_store_busy": True,
     "sentiment": "Positive", "start_time": "2026-04-25T19:30:00+00:00"},
    {"call_status": "Unsuccessful", "duration": 60,  "is_store_busy": False,
     "sentiment": "Neutral",  "start_time": "2026-04-25T14:00:00+00:00"},
    {"call_status": "Successful",   "duration": 180, "is_store_busy": True,
     "sentiment": "Negative", "start_time": "2026-04-24T20:00:00+00:00"},
]

_MOCK_ORDERS_ANALYTICS = [
    {"total_amount": 25.50, "status": "paid",    "created_at": "2026-04-25T19:45:00+00:00"},
    {"total_amount": 18.00, "status": "paid",    "created_at": "2026-04-24T20:10:00+00:00"},
    {"total_amount": 30.00, "status": "pending", "created_at": "2026-04-24T14:30:00+00:00"},
]


def test_analytics_returns_expected_shape():
    token = _make_jwt(_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, _MOCK_CALL_LOGS_ANALYTICS),
        (200, []),   # second page of call_logs (pagination)
        (200, _MOCK_ORDERS_ANALYTICS),
        (200, []),   # second page of orders
    ])
    with patch("app.api.analytics.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            "/api/store/analytics?period=month",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_calls" in data
    assert "hourly_distribution" in data
    assert "daily_revenue" in data
    assert "sentiment_breakdown" in data
    assert "summary" in data


def test_analytics_invalid_period_returns_400():
    token = _make_jwt(_OWNER_ID)
    with patch("app.api.analytics.httpx.AsyncClient", return_value=_mock_get([(200, _MOCK_STORES)])):
        resp = client.get(
            "/api/store/analytics?period=yearly",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


def test_analytics_sentiment_counts_correctly():
    token = _make_jwt(_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, _MOCK_CALL_LOGS_ANALYTICS),
        (200, []),
        (200, _MOCK_ORDERS_ANALYTICS),
        (200, []),
    ])
    with patch("app.api.analytics.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            "/api/store/analytics?period=month",
            headers={"Authorization": f"Bearer {token}"},
        )
    s = resp.json()["sentiment_breakdown"]
    assert s.get("Positive", 0) == 1
    assert s.get("Neutral",  0) == 1
    assert s.get("Negative", 0) == 1
