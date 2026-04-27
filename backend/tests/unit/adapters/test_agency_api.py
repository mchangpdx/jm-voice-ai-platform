# TDD: Agency API endpoint tests (에이전시 API 엔드포인트 테스트)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_AGENCY_ID       = "e4d0c104-659c-4d49-a63b-5c16bf2d83bf"
_AGENCY_OWNER_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
_CAFE_STORE_ID   = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_HOME_STORE_ID   = "d25ff657-b6cc-5ce9-bee6-28d4e487dd6c"
_OTHER_STORE_ID  = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_STORE_OWNER_ID  = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"

_MOCK_AGENCY = [{"id": _AGENCY_ID, "name": "JM Agency"}]
_MOCK_STORES = [
    {"id": _CAFE_STORE_ID, "name": "JM Cafe",         "industry": "restaurant"},
    {"id": _HOME_STORE_ID, "name": "JM Home Services", "industry": "home_services"},
]
_MOCK_CFG     = [{"hourly_wage": 20.0, "timezone": "America/Los_Angeles"}]
_MOCK_CALLS_R = [{"call_id": "cl-001", "call_status": "Successful", "duration": 180, "is_store_busy": True}]
_MOCK_CALLS_H = [{"call_id": "cl-002", "call_status": "Successful", "duration": 240, "is_store_busy": True}]
_MOCK_ORDERS  = [{"total_amount": 25.00, "status": "paid"}]
_MOCK_JOBS    = [{"call_log_id": "cl-002", "job_value": 400.00, "status": "booked"}]


def _make_jwt(sub: str) -> str:
    return jwt.encode({"sub": sub}, settings.supabase_service_role_key, algorithm="HS256")


def _mock_get(responses: list):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__  = AsyncMock(return_value=None)
    side_effects = []
    for status, body in responses:
        m = MagicMock()
        m.status_code = status
        m.json.return_value = body
        side_effects.append(m)
    mock_client.get = AsyncMock(side_effect=side_effects)
    return mock_client


# ── GET /api/agency/me ────────────────────────────────────────────────────────

def test_agency_me_returns_agency_info():
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([(200, _MOCK_AGENCY)])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "JM Agency"


# ── GET /api/agency/stores ────────────────────────────────────────────────────

def test_agency_stores_returns_list():
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, _MOCK_STORES),
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/stores", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {s["industry"] for s in data} == {"restaurant", "home_services"}


def test_agency_stores_403_non_agency_user():
    token = _make_jwt(_STORE_OWNER_ID)
    mock = _mock_get([(200, [])])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/stores", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ── GET /api/agency/overview ──────────────────────────────────────────────────

def test_agency_overview_aggregates_correctly():
    """
    Mock GET call order (must match agency.py exactly):
    1. agencies          2. stores
    3. store_configs (cafe)   4. call_logs (cafe)   5. orders (cafe)
    6. store_configs (home)   7. call_logs (home)   8. jobs (home)
    """
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, _MOCK_STORES),
        (200, _MOCK_CFG),
        (200, _MOCK_CALLS_R),
        (200, _MOCK_ORDERS),
        (200, _MOCK_CFG),
        (200, _MOCK_CALLS_H),
        (200, _MOCK_JOBS),
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/overview?period=month", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agency_name"] == "JM Agency"
    assert data["totals"]["store_count"] == 2
    assert data["totals"]["total_calls"] == 2
    assert len(data["stores"]) == 2
    assert {s["industry"] for s in data["stores"]} == {"restaurant", "home_services"}


def test_agency_overview_missing_auth():
    resp = client.get("/api/agency/overview?period=month")
    assert resp.status_code == 401


def test_agency_overview_period_filter():
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, [_MOCK_STORES[0]]),
        (200, _MOCK_CFG),
        (200, []),
        (200, []),
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/overview?period=today", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["totals"]["total_calls"] == 0


# ── GET /api/agency/store/{store_id}/metrics ──────────────────────────────────

def test_agency_store_metrics_restaurant():
    """
    Mock GET call order:
    1. agencies  2. stores (access check)
    3. store_configs  4. call_logs  5. orders
    """
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, [_MOCK_STORES[0]]),
        (200, _MOCK_CFG),
        (200, _MOCK_CALLS_R),
        (200, _MOCK_ORDERS),
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            f"/api/agency/store/{_CAFE_STORE_ID}/metrics?period=month",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["industry"] == "restaurant"
    assert data["primary_revenue_label"] == "Peak Hour Revenue"
    assert data["conversion_label"] == "Lead Conversion Rate"
    assert data["avg_value_label"] == "Avg Ticket"


def test_agency_store_metrics_home_services():
    """
    Mock GET call order:
    1. agencies  2. stores (access check)
    3. store_configs  4. call_logs (cl-002, is_store_busy=True)  5. jobs (cl-002, booked, $400)
    FTR = 1 field job × $400 = $400
    """
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, [_MOCK_STORES[1]]),
        (200, _MOCK_CFG),
        (200, _MOCK_CALLS_H),
        (200, _MOCK_JOBS),
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            f"/api/agency/store/{_HOME_STORE_ID}/metrics?period=month",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["industry"] == "home_services"
    assert data["primary_revenue_label"] == "Field Time Revenue"
    assert data["conversion_label"] == "Job Booking Rate"
    assert data["avg_value_label"] == "Avg Job Value"
    assert data["primary_revenue"] == 400.0


def test_agency_store_metrics_cross_agency_forbidden():
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, []),   # store not found under this agency
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            f"/api/agency/store/{_OTHER_STORE_ID}/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
