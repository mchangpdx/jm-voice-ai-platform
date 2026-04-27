# TDD: Store settings & busy schedule endpoint tests (스토어 설정 및 바쁜 스케줄 엔드포인트 테스트)
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.main import app

client = TestClient(app)

_STORE_ID = "c14ee546-a5bb-4bd8-add5-17c3f376cc6b"
_OWNER_ID = "b36f6adf-55f1-4b95-96b1-30f60c91a5ca"
_SCHEDULE_ID = "d72f1234-aaaa-bbbb-cccc-000000000001"

_MOCK_STORES = [{"id": _STORE_ID, "name": "JM Cafe", "agency_id": "e4d0c104-659c-4d49-a63b-5c16bf2d83bf"}]
_MOCK_CONFIGS = [{"id": "cfg-001", "store_id": _STORE_ID, "hourly_wage": 20.00,
                  "timezone": "America/Los_Angeles", "is_override_busy": False, "override_until": None}]
_MOCK_SCHEDULES = [
    {"id": _SCHEDULE_ID, "store_id": _STORE_ID, "day_of_week": 1,
     "start_time": "12:00:00", "end_time": "14:00:00"},
]


def _make_jwt(sub: str) -> str:
    return jwt.encode({"sub": sub}, settings.supabase_service_role_key, algorithm="HS256")


def _mock_client(gets=None, patches=None, posts=None, deletes=None):
    """Flexible mock for httpx.AsyncClient with per-method side effects."""
    mc = AsyncMock()
    mc.__aenter__ = AsyncMock(return_value=mc)
    mc.__aexit__  = AsyncMock(return_value=None)

    def _responses(pairs):
        effects = []
        for status, body in (pairs or []):
            m = MagicMock()
            m.status_code = status
            m.json.return_value = body
            effects.append(m)
        return effects

    mc.get    = AsyncMock(side_effect=_responses(gets))
    mc.patch  = AsyncMock(side_effect=_responses(patches))
    mc.post   = AsyncMock(side_effect=_responses(posts))
    mc.delete = AsyncMock(side_effect=_responses(deletes))
    return mc


AUTH = lambda: {"Authorization": f"Bearer {_make_jwt(_OWNER_ID)}"}


# ── GET /api/store/settings ───────────────────────────────────────────────────

def test_get_settings_returns_config_and_schedules():
    mc = _mock_client(gets=[
        (200, _MOCK_STORES),
        (200, _MOCK_CONFIGS),
        (200, _MOCK_SCHEDULES),
    ])
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/settings", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["hourly_wage"] - 20.00) < 0.01
    assert data["timezone"] == "America/Los_Angeles"
    assert data["is_override_busy"] is False
    assert len(data["busy_schedules"]) == 1
    assert data["busy_schedules"][0]["day_of_week"] == 1


def test_get_settings_returns_defaults_when_no_config():
    """If no store_configs row exists, endpoint returns default values."""
    mc = _mock_client(gets=[
        (200, _MOCK_STORES),
        (200, []),       # no store_configs
        (200, []),       # no schedules
    ])
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.get("/api/store/settings", headers=AUTH())
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["hourly_wage"] - 20.00) < 0.01
    assert data["timezone"] == "America/Los_Angeles"


# ── PATCH /api/store/settings ─────────────────────────────────────────────────

def test_patch_settings_updates_hourly_wage():
    updated = [{**_MOCK_CONFIGS[0], "hourly_wage": 22.50}]
    mc = _mock_client(
        gets=[(200, _MOCK_STORES), (200, _MOCK_CONFIGS)],
        patches=[(200, updated)],
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.patch(
            "/api/store/settings",
            json={"hourly_wage": 22.50},
            headers=AUTH(),
        )
    assert resp.status_code == 200
    assert abs(resp.json()["hourly_wage"] - 22.50) < 0.01


# ── POST /api/store/busy-schedule ─────────────────────────────────────────────

def test_post_busy_schedule_creates_entry():
    new_sched = {"id": "new-id", "store_id": _STORE_ID, "day_of_week": 5,
                 "start_time": "18:00:00", "end_time": "21:00:00"}
    mc = _mock_client(
        gets=[(200, _MOCK_STORES)],
        posts=[(201, [new_sched])],
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.post(
            "/api/store/busy-schedule",
            json={"day_of_week": 5, "start_time": "18:00", "end_time": "21:00"},
            headers=AUTH(),
        )
    assert resp.status_code == 201
    assert resp.json()["day_of_week"] == 5


# ── DELETE /api/store/busy-schedule/{id} ──────────────────────────────────────

def test_delete_busy_schedule_removes_entry():
    mc = _mock_client(
        gets=[(200, _MOCK_STORES), (200, _MOCK_SCHEDULES)],
        deletes=[(204, None)],
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.delete(f"/api/store/busy-schedule/{_SCHEDULE_ID}", headers=AUTH())
    assert resp.status_code == 204


def test_delete_busy_schedule_returns_404_if_not_owned():
    """Schedule belonging to a different store must return 404."""
    mc = _mock_client(
        gets=[(200, _MOCK_STORES), (200, [])],  # empty = not found for this store
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.delete(f"/api/store/busy-schedule/{_SCHEDULE_ID}", headers=AUTH())
    assert resp.status_code == 404


# ── POST /api/store/busy-override ─────────────────────────────────────────────

def test_busy_override_activate_with_duration():
    mc = _mock_client(
        gets=[(200, _MOCK_STORES), (200, _MOCK_CONFIGS)],
        patches=[(200, [{**_MOCK_CONFIGS[0], "is_override_busy": True}])],
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.post(
            "/api/store/busy-override",
            json={"active": True, "duration_minutes": 60},
            headers=AUTH(),
        )
    assert resp.status_code == 200
    assert resp.json()["is_override_busy"] is True


def test_busy_override_deactivate():
    mc = _mock_client(
        gets=[(200, _MOCK_STORES), (200, _MOCK_CONFIGS)],
        patches=[(200, [{**_MOCK_CONFIGS[0], "is_override_busy": False, "override_until": None}])],
    )
    with patch("app.api.settings.httpx.AsyncClient", return_value=mc):
        resp = client.post(
            "/api/store/busy-override",
            json={"active": False},
            headers=AUTH(),
        )
    assert resp.status_code == 200
    assert resp.json()["is_override_busy"] is False
