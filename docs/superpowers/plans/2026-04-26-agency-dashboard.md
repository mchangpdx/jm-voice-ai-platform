# Agency Dashboard + Industry Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-store Agency Dashboard for `jmagency@test.com` supporting `restaurant` (JM Cafe) and `home_services` (JM Home Services) verticals with industry-aware KPI rendering.

**Architecture:** Layer 3 Knowledge modules (`restaurant.py` / `home_services.py`) expose a shared `VerticalMetrics` TypedDict contract. Agency API fetches store data, dispatches to the correct knowledge module based on `stores.industry`, and returns industry-aware metrics. Frontend renders a store card grid with labels resolved from `verticalLabels.ts`. `store.py` is left unchanged — restaurant.py duplicates its KPI logic intentionally to avoid risk to the existing 71 passing tests.

**Tech Stack:** FastAPI + Supabase PostgREST + httpx (backend); React 18 + TypeScript + CSS Modules + React Router v6 (frontend); pytest + AsyncMock (TDD)

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `backend/tests/unit/adapters/test_agency_api.py` | TDD: 8 tests for agency endpoints — written FIRST |
| `backend/app/knowledge/__init__.py` | Package marker (empty) |
| `backend/app/knowledge/base.py` | `VerticalMetrics` TypedDict + industry constants |
| `backend/app/knowledge/restaurant.py` | PHRC/LCS/LCR/UV calculator |
| `backend/app/knowledge/home_services.py` | FTR/JBR/LCS/LRR calculator |
| `backend/app/api/agency.py` | `/api/agency/*` endpoints |
| `backend/scripts/gen_home_services_demo.py` | Synthetic: 300 call_logs + 180 jobs for JM Home Services |
| `frontend/src/core/verticalLabels.ts` | Industry → icon + label mapping |
| `frontend/src/views/agency/Layout.tsx` | Agency sidebar + `<Outlet />` |
| `frontend/src/views/agency/Layout.module.css` | Agency layout styles |
| `frontend/src/views/agency/Overview.tsx` | Aggregated KPIs + store card grid |
| `frontend/src/views/agency/Overview.module.css` | Overview page styles |
| `frontend/src/views/agency/StoreDetail.tsx` | Per-store KPI view in agency context |
| `frontend/src/views/agency/StoreDetail.module.css` | StoreDetail styles |

### Modified Files
| File | Change |
|------|--------|
| `backend/app/main.py` | Add `agency_router` |
| `frontend/src/App.tsx` | Replace `AgencyDashboard` placeholder with `/agency/*` nested routes |

---

## Task 1: Write Failing TDD Tests (Red Phase)

**Files:**
- Create: `backend/tests/unit/adapters/test_agency_api.py`

- [ ] **Step 1.1: Create test file**

```python
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
_MOCK_CFG        = [{"hourly_wage": 20.0, "timezone": "America/Los_Angeles"}]
_MOCK_CALLS_R    = [{"call_id": "cl-001", "call_status": "Successful", "duration": 180, "is_store_busy": True}]
_MOCK_CALLS_H    = [{"call_id": "cl-002", "call_status": "Successful", "duration": 240, "is_store_busy": True}]
_MOCK_ORDERS     = [{"total_amount": 25.00, "status": "paid"}]
_MOCK_JOBS       = [{"call_log_id": "cl-002", "job_value": 400.00, "status": "booked"}]


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
        (200, _MOCK_AGENCY),   # agencies lookup
        (200, _MOCK_STORES),   # stores for agency
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/stores", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {s["industry"] for s in data} == {"restaurant", "home_services"}


def test_agency_stores_403_non_agency_user():
    token = _make_jwt(_STORE_OWNER_ID)
    mock = _mock_get([(200, [])])   # no agency found for this user
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/stores", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ── GET /api/agency/overview ──────────────────────────────────────────────────

def test_agency_overview_aggregates_correctly():
    """
    Mock GET call order (must match agency.py implementation exactly):
    1. agencies                     (resolve agency)
    2. stores                       (get all stores)
    3. store_configs (cafe)
    4. call_logs (cafe, page 1)
    5. orders (cafe)
    6. store_configs (home_svc)
    7. call_logs (home_svc, page 1)
    8. jobs (home_svc)
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
        (200, [_MOCK_STORES[0]]),   # only cafe
        (200, _MOCK_CFG),
        (200, []),                   # no calls today
        (200, []),                   # no orders today
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get("/api/agency/overview?period=today", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["totals"]["total_calls"] == 0


# ── GET /api/agency/store/{store_id}/metrics ──────────────────────────────────

def test_agency_store_metrics_restaurant():
    """
    Mock GET call order:
    1. agencies
    2. stores (access check: id=eq.{cafe_id}&agency_id=eq.{agency_id})
    3. store_configs
    4. call_logs (page 1)
    5. orders
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
    1. agencies
    2. stores (access check: id=eq.{home_id}&agency_id=eq.{agency_id})
    3. store_configs
    4. call_logs (page 1) — is_store_busy=True on cl-002
    5. jobs — call_log_id=cl-002, status=booked → FTR = $400
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
    assert data["primary_revenue"] == 400.0   # 1 field-call job × $400


def test_agency_store_metrics_cross_agency_forbidden():
    token = _make_jwt(_AGENCY_OWNER_ID)
    mock = _mock_get([
        (200, _MOCK_AGENCY),
        (200, []),   # store not found under this agency → 403
    ])
    with patch("app.api.agency.httpx.AsyncClient", return_value=mock):
        resp = client.get(
            f"/api/agency/store/{_OTHER_STORE_ID}/metrics",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
```

- [ ] **Step 1.2: Run tests to confirm they all FAIL (Red)**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/adapters/test_agency_api.py -v
```

Expected: All 9 tests FAIL with `404 Not Found` (routes don't exist yet). This confirms the tests are wired correctly.

- [ ] **Step 1.3: Commit Red tests**

```bash
git add backend/tests/unit/adapters/test_agency_api.py
git commit -m "test(agency): add 9 failing TDD tests for agency API (Red)"
```

---

## Task 2: Database Migrations (Supabase SQL Editor)

**Note:** Run these SQL statements in Supabase Dashboard → SQL Editor. These are one-time migrations.

- [ ] **Step 2.1: Add `industry` column + update JM Cafe + insert JM Home Services**

Run in Supabase SQL Editor:

```sql
-- Add industry column with restaurant default (기존 스토어 하위 호환성 유지)
ALTER TABLE stores ADD COLUMN IF NOT EXISTS industry TEXT NOT NULL DEFAULT 'restaurant';

-- Explicitly mark JM Cafe as restaurant
UPDATE stores SET industry = 'restaurant' WHERE name = 'JM Cafe';

-- Add owner_id to agencies if not already present (에이전시 오너 연결)
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS owner_id UUID;

-- Update agency name to "JM Agency"
UPDATE agencies SET name = 'JM Agency' WHERE name = 'JM Tech One';
-- (if name was already JM Agency, this is a no-op)

-- Set jmagency@test.com as agency owner
UPDATE agencies
SET owner_id = (SELECT id FROM auth.users WHERE email = 'jmagency@test.com')
WHERE name = 'JM Agency';

-- Verify
SELECT id, name, industry FROM stores;
SELECT id, name, owner_id FROM agencies;
```

Expected output:
- stores: JM Cafe | restaurant
- agencies: JM Agency | <uuid of jmagency@test.com>

- [ ] **Step 2.2: Insert JM Home Services store**

```sql
-- Insert JM Home Services under JM Agency
INSERT INTO stores (name, agency_id, industry, owner_id)
SELECT
  'JM Home Services',
  id,
  'home_services',
  NULL   -- no independent login in Phase 2-A
FROM agencies
WHERE name = 'JM Agency';

-- Verify
SELECT id, name, industry, agency_id FROM stores;
```

Expected: 2 stores — JM Cafe (restaurant) and JM Home Services (home_services).

- [ ] **Step 2.3: Create `jobs` table**

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id             SERIAL PRIMARY KEY,
  store_id       UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
  call_log_id    TEXT REFERENCES call_logs(call_id),
  job_type       TEXT NOT NULL CHECK (job_type IN ('paint', 'repair', 'carpet', 'cleaning')),
  scheduled_date DATE,
  job_value      DECIMAL(10,2) NOT NULL DEFAULT 0,
  status         TEXT NOT NULL CHECK (status IN ('quoted', 'booked', 'completed', 'cancelled')),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enable RLS (consistent with rest of DB)
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

-- Allow service_role to bypass RLS
GRANT ALL ON TABLE jobs TO service_role;
GRANT ALL ON SEQUENCE jobs_id_seq TO service_role;

-- Verify
SELECT table_name FROM information_schema.tables WHERE table_name = 'jobs';
```

---

## Task 3: Knowledge Layer — `base.py`

**Files:**
- Create: `backend/app/knowledge/__init__.py`
- Create: `backend/app/knowledge/base.py`

- [ ] **Step 3.1: Create package**

```bash
touch backend/app/knowledge/__init__.py
```

- [ ] **Step 3.2: Create `base.py`**

```python
# Layer 3 Knowledge — shared contract for all industry verticals
# (모든 산업 버티컬의 공유 계약 — VerticalMetrics TypedDict)
from typing import TypedDict

INDUSTRY_RESTAURANT    = "restaurant"
INDUSTRY_HOME_SERVICES = "home_services"


class VerticalMetrics(TypedDict):
    # Core KPIs — industry-agnostic (공통 KPI — 산업 무관)
    monthly_impact: float
    labor_savings: float
    conversion_rate: float      # LCR (restaurant) | JBR (home_services)
    upsell_value: float         # UV  (restaurant) | LRR (home_services)
    primary_revenue: float      # PHRC (restaurant) | FTR (home_services)
    avg_value: float            # avg_ticket | avg_job_value
    total_calls: int
    successful_calls: int
    using_real_busy_data: bool

    # Frontend rendering metadata (프론트엔드 렌더링 메타데이터)
    industry: str
    primary_revenue_label: str  # "Peak Hour Revenue" | "Field Time Revenue"
    conversion_label: str       # "Lead Conversion Rate" | "Job Booking Rate"
    avg_value_label: str        # "Avg Ticket" | "Avg Job Value"
```

- [ ] **Step 3.3: Commit**

```bash
git add backend/app/knowledge/
git commit -m "feat(knowledge): add Layer 3 VerticalMetrics base contract"
```

---

## Task 4: Knowledge Layer — `restaurant.py`

**Files:**
- Create: `backend/app/knowledge/restaurant.py`

- [ ] **Step 4.1: Create `restaurant.py`**

```python
# Layer 3 Knowledge — Restaurant vertical KPI calculator
# (레스토랑 버티컬 KPI 계산기 — PHRC/LCS/LCR/UV)
from app.knowledge.base import INDUSTRY_RESTAURANT, VerticalMetrics

_HOURLY_WAGE       = 20.0
_MISSED_CALL_RATE  = 0.20
_UPSELL_RATE       = 0.15
_AVG_UPSELL_AMOUNT = 5.0
_DEFAULT_AVG_TICKET = 50.0


def calculate_metrics(
    call_logs: list[dict],
    orders: list[dict],
    cfg: dict,
) -> VerticalMetrics:
    """Compute restaurant KPIs from pre-fetched call_logs, orders, and store config.
    (사전 조회된 데이터로 레스토랑 KPI 계산)
    """
    hourly_wage = float(cfg.get("hourly_wage") or _HOURLY_WAGE)

    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_dur_sec    = sum(int(c.get("duration") or 0) for c in call_logs)
    success_rate     = (successful_calls / total_calls * 100) if total_calls > 0 else 0.0

    paid_orders  = [o for o in orders if o.get("status") == "paid"]
    total_rev    = sum(float(o.get("total_amount") or 0) for o in paid_orders)
    avg_ticket   = (total_rev / len(paid_orders)) if paid_orders else _DEFAULT_AVG_TICKET

    lcs = round((total_dur_sec / 3600) * hourly_wage, 2)

    busy_calls      = [c for c in call_logs if c.get("is_store_busy") is True]
    busy_successful = sum(1 for c in busy_calls if c.get("call_status") == "Successful")
    using_real      = len(busy_calls) > 0

    if using_real:
        phrc = round(busy_successful * avg_ticket, 2)
    else:
        phrc = round(total_calls * _MISSED_CALL_RATE * (success_rate / 100) * avg_ticket, 2)

    uv             = round(total_calls * _UPSELL_RATE * _AVG_UPSELL_AMOUNT, 2)
    monthly_impact = round(phrc + lcs + uv, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=round(success_rate, 1),
        upsell_value=uv,
        primary_revenue=phrc,
        avg_value=round(avg_ticket, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry=INDUSTRY_RESTAURANT,
        primary_revenue_label="Peak Hour Revenue",
        conversion_label="Lead Conversion Rate",
        avg_value_label="Avg Ticket",
    )
```

- [ ] **Step 4.2: Commit**

```bash
git add backend/app/knowledge/restaurant.py
git commit -m "feat(knowledge): add restaurant vertical KPI calculator"
```

---

## Task 5: Knowledge Layer — `home_services.py`

**Files:**
- Create: `backend/app/knowledge/home_services.py`

- [ ] **Step 5.1: Create `home_services.py`**

```python
# Layer 3 Knowledge — Home Services vertical KPI calculator
# (홈서비스 버티컬 KPI 계산기 — FTR/JBR/LCS/LRR)
from app.knowledge.base import INDUSTRY_HOME_SERVICES, VerticalMetrics

_HOURLY_RATE       = 25.0   # Skilled trades rate higher than restaurant (기술직 시급)
_DEFAULT_AVG_JOB   = 400.0  # Fallback avg job value (기본 작업 평균가)
_LEAD_RESP_RATE    = 0.30   # 30% of calls become leads (리드 전환율)
_LEAD_CONV_RATE    = 0.10   # 10% additional lead-to-job conversion (추가 전환율)

_ACTIVE_STATUSES = {"booked", "completed"}


def calculate_metrics(
    call_logs: list[dict],
    jobs: list[dict],
    cfg: dict,
) -> VerticalMetrics:
    """Compute home-services KPIs from pre-fetched call_logs, jobs, and store config.
    call_logs.is_store_busy = True means contractor was on-site (현장 작업 중 수신 여부).
    FTR = field calls that resulted in a booked/completed job × avg_job_value.
    (FTR = 현장 중 수신 통화로 성사된 예약 건 × 평균 작업 단가)
    """
    hourly_rate = float(cfg.get("hourly_wage") or _HOURLY_RATE)

    total_calls      = len(call_logs)
    successful_calls = sum(1 for c in call_logs if c.get("call_status") == "Successful")
    total_dur_sec    = sum(int(c.get("duration") or 0) for c in call_logs)

    active_jobs  = [j for j in jobs if j.get("status") in _ACTIVE_STATUSES]
    job_values   = [float(j.get("job_value") or 0) for j in active_jobs]
    avg_job_val  = (sum(job_values) / len(job_values)) if job_values else _DEFAULT_AVG_JOB

    jbr = (len(active_jobs) / total_calls * 100) if total_calls > 0 else 0.0

    lcs = round((total_dur_sec / 3600) * hourly_rate, 2)

    # FTR: field calls that produced a booked/completed job (현장 통화 → 예약 성사 매출)
    field_call_ids = {
        c.get("call_id") for c in call_logs if c.get("is_store_busy") is True
    }
    field_booked = [j for j in active_jobs if j.get("call_log_id") in field_call_ids]
    using_real   = len(field_call_ids) > 0
    ftr          = round(len(field_booked) * avg_job_val, 2)

    lrr            = round(total_calls * _LEAD_RESP_RATE * avg_job_val * _LEAD_CONV_RATE, 2)
    monthly_impact = round(ftr + lcs + lrr, 2)

    return VerticalMetrics(
        monthly_impact=monthly_impact,
        labor_savings=lcs,
        conversion_rate=round(jbr, 1),
        upsell_value=lrr,
        primary_revenue=ftr,
        avg_value=round(avg_job_val, 2),
        total_calls=total_calls,
        successful_calls=successful_calls,
        using_real_busy_data=using_real,
        industry=INDUSTRY_HOME_SERVICES,
        primary_revenue_label="Field Time Revenue",
        conversion_label="Job Booking Rate",
        avg_value_label="Avg Job Value",
    )
```

- [ ] **Step 5.2: Commit**

```bash
git add backend/app/knowledge/home_services.py
git commit -m "feat(knowledge): add home_services vertical KPI calculator (FTR/JBR/LCS/LRR)"
```

---

## Task 6: Agency API — `agency.py`

**Files:**
- Create: `backend/app/api/agency.py`

- [ ] **Step 6.1: Create `agency.py`**

```python
# Agency API router — multi-store dashboard endpoints (에이전시 멀티스토어 대시보드 엔드포인트)
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_tenant_id
from app.core.config import settings
from app.knowledge import home_services, restaurant
from app.knowledge.base import INDUSTRY_HOME_SERVICES, VerticalMetrics

router = APIRouter(prefix="/api/agency", tags=["Agency"])

_SUPABASE_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}
_REST             = f"{settings.supabase_url}/rest/v1"
_DEFAULT_TZ       = "America/Los_Angeles"
_VALID_PERIODS    = {"today", "week", "month", "all"}


# ── Time helpers ──────────────────────────────────────────────────────────────

def _period_start(period: str, store_tz: str = _DEFAULT_TZ) -> str | None:
    now_utc = datetime.now(timezone.utc)
    if period == "today":
        tz        = ZoneInfo(store_tz)
        now_local = now_utc.astimezone(tz)
        start_loc = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_loc.astimezone(timezone.utc)
    elif period == "week":
        start_utc = now_utc - timedelta(days=7)
    elif period == "month":
        start_utc = now_utc - timedelta(days=30)
    else:
        return None
    return start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _resolve_agency(client: httpx.AsyncClient, owner_id: str) -> dict:
    resp = await client.get(
        f"{_REST}/agencies",
        headers=_SUPABASE_HEADERS,
        params={"owner_id": f"eq.{owner_id}", "select": "id,name"},
    )
    agencies = resp.json() if isinstance(resp.json(), list) else []
    if not agencies:
        raise HTTPException(status_code=403, detail="Not an agency account")
    return agencies[0]


async def _fetch_call_logs(
    client: httpx.AsyncClient, store_id: str, since: str | None
) -> list[dict]:
    params: dict[str, Any] = {
        "store_id": f"eq.{store_id}",
        "select": "call_id,call_status,duration,is_store_busy",
    }
    if since:
        params["start_time"] = f"gte.{since}"
    all_logs: list[dict] = []
    offset = 0
    while True:
        resp = await client.get(
            f"{_REST}/call_logs",
            headers=_SUPABASE_HEADERS,
            params={**params, "limit": "1000", "offset": str(offset)},
        )
        page = resp.json() if isinstance(resp.json(), list) else []
        all_logs.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return all_logs


async def _fetch_orders(
    client: httpx.AsyncClient, store_id: str, since: str | None
) -> list[dict]:
    params: dict[str, Any] = {
        "store_id": f"eq.{store_id}",
        "select": "total_amount,status",
    }
    if since:
        params["created_at"] = f"gte.{since}"
    resp = await client.get(f"{_REST}/orders", headers=_SUPABASE_HEADERS, params=params)
    return resp.json() if isinstance(resp.json(), list) else []


async def _fetch_jobs(
    client: httpx.AsyncClient, store_id: str, since: str | None
) -> list[dict]:
    params: dict[str, Any] = {
        "store_id": f"eq.{store_id}",
        "select": "call_log_id,job_value,status",
    }
    if since:
        params["created_at"] = f"gte.{since}"
    resp = await client.get(f"{_REST}/jobs", headers=_SUPABASE_HEADERS, params=params)
    return resp.json() if isinstance(resp.json(), list) else []


async def _calculate_store_metrics(
    client: httpx.AsyncClient, store: dict, period: str
) -> VerticalMetrics:
    store_id = store["id"]
    industry = store.get("industry", "restaurant")

    cfg_resp = await client.get(
        f"{_REST}/store_configs",
        headers=_SUPABASE_HEADERS,
        params={"store_id": f"eq.{store_id}", "select": "hourly_wage,timezone"},
    )
    cfg_list = cfg_resp.json() if isinstance(cfg_resp.json(), list) else []
    cfg      = cfg_list[0] if cfg_list else {}
    store_tz = cfg.get("timezone") or _DEFAULT_TZ
    since    = _period_start(period, store_tz)

    call_logs = await _fetch_call_logs(client, store_id, since)

    if industry == INDUSTRY_HOME_SERVICES:
        jobs = await _fetch_jobs(client, store_id, since)
        return home_services.calculate_metrics(call_logs, jobs, cfg)
    else:
        orders = await _fetch_orders(client, store_id, since)
        return restaurant.calculate_metrics(call_logs, orders, cfg)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AgencyInfo(BaseModel):
    id: str
    name: str


class StoreListItem(BaseModel):
    id: str
    name: str
    industry: str


class AgencyTotals(BaseModel):
    total_calls: int
    total_monthly_impact: float
    store_count: int
    avg_conversion_rate: float


class AgencyStoreMetrics(BaseModel):
    id: str
    name: str
    industry: str
    primary_revenue: float
    primary_revenue_label: str
    labor_savings: float
    conversion_rate: float
    conversion_label: str
    upsell_value: float
    monthly_impact: float
    total_calls: int
    avg_value: float
    avg_value_label: str
    using_real_busy_data: bool


class AgencyOverviewResponse(BaseModel):
    agency_name: str
    period: str
    totals: AgencyTotals
    stores: list[AgencyStoreMetrics]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/me", response_model=AgencyInfo)
async def get_agency_me(tenant_id: str = Depends(get_tenant_id)) -> AgencyInfo:
    """Return agency info for the authenticated agency user. (인증된 에이전시 사용자 정보 반환)"""
    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)
    return AgencyInfo(id=agency["id"], name=agency["name"])


@router.get("/stores", response_model=list[StoreListItem])
async def get_agency_stores(tenant_id: str = Depends(get_tenant_id)) -> list[StoreListItem]:
    """List all stores managed by this agency. (에이전시 관리 스토어 목록 반환)"""
    async with httpx.AsyncClient() as client:
        agency  = await _resolve_agency(client, tenant_id)
        resp    = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"agency_id": f"eq.{agency['id']}", "select": "id,name,industry"},
        )
        stores = resp.json() if isinstance(resp.json(), list) else []
    return [StoreListItem(id=s["id"], name=s["name"], industry=s.get("industry", "restaurant")) for s in stores]


@router.get("/overview", response_model=AgencyOverviewResponse)
async def get_agency_overview(
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> AgencyOverviewResponse:
    """Return aggregated KPIs + per-store metrics for agency overview. (집계 KPI + 스토어별 지표 반환)"""
    if period not in _VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period '{period}'")

    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)
        stores_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={"agency_id": f"eq.{agency['id']}", "select": "id,name,industry"},
        )
        stores = stores_resp.json() if isinstance(stores_resp.json(), list) else []

        store_metrics: list[AgencyStoreMetrics] = []
        for store in stores:
            m = await _calculate_store_metrics(client, store, period)
            store_metrics.append(AgencyStoreMetrics(
                id=store["id"], name=store["name"],
                industry=m["industry"],
                primary_revenue=m["primary_revenue"],
                primary_revenue_label=m["primary_revenue_label"],
                labor_savings=m["labor_savings"],
                conversion_rate=m["conversion_rate"],
                conversion_label=m["conversion_label"],
                upsell_value=m["upsell_value"],
                monthly_impact=m["monthly_impact"],
                total_calls=m["total_calls"],
                avg_value=m["avg_value"],
                avg_value_label=m["avg_value_label"],
                using_real_busy_data=m["using_real_busy_data"],
            ))

    total_calls  = sum(s.total_calls for s in store_metrics)
    total_impact = sum(s.monthly_impact for s in store_metrics)
    avg_conv     = (sum(s.conversion_rate for s in store_metrics) / len(store_metrics)) if store_metrics else 0.0

    return AgencyOverviewResponse(
        agency_name=agency["name"],
        period=period,
        totals=AgencyTotals(
            total_calls=total_calls,
            total_monthly_impact=round(total_impact, 2),
            store_count=len(store_metrics),
            avg_conversion_rate=round(avg_conv, 1),
        ),
        stores=store_metrics,
    )


@router.get("/store/{store_id}/metrics", response_model=AgencyStoreMetrics)
async def get_agency_store_metrics(
    store_id: str,
    period: str = "month",
    tenant_id: str = Depends(get_tenant_id),
) -> AgencyStoreMetrics:
    """Return KPIs for a single store (agency context). 403 if store not in agency. (에이전시 소속 단일 스토어 KPI)"""
    if period not in _VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period '{period}'")

    async with httpx.AsyncClient() as client:
        agency = await _resolve_agency(client, tenant_id)
        store_resp = await client.get(
            f"{_REST}/stores",
            headers=_SUPABASE_HEADERS,
            params={
                "id": f"eq.{store_id}",
                "agency_id": f"eq.{agency['id']}",
                "select": "id,name,industry",
            },
        )
        stores = store_resp.json() if isinstance(store_resp.json(), list) else []
        if not stores:
            raise HTTPException(status_code=403, detail="Store not found or access denied")

        store = stores[0]
        m = await _calculate_store_metrics(client, store, period)

    return AgencyStoreMetrics(
        id=store["id"], name=store["name"],
        industry=m["industry"],
        primary_revenue=m["primary_revenue"],
        primary_revenue_label=m["primary_revenue_label"],
        labor_savings=m["labor_savings"],
        conversion_rate=m["conversion_rate"],
        conversion_label=m["conversion_label"],
        upsell_value=m["upsell_value"],
        monthly_impact=m["monthly_impact"],
        total_calls=m["total_calls"],
        avg_value=m["avg_value"],
        avg_value_label=m["avg_value_label"],
        using_real_busy_data=m["using_real_busy_data"],
    )
```

- [ ] **Step 6.2: Commit**

```bash
git add backend/app/api/agency.py
git commit -m "feat(agency): add /api/agency/* endpoints (me/stores/overview/store metrics)"
```

---

## Task 7: Wire Up — `main.py` + Run Tests (Green)

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 7.1: Register agency_router in main.py**

Add these two lines to `backend/app/main.py` (after existing imports and router registrations):

```python
# Add after existing imports (line ~12):
from app.api.agency import router as agency_router

# Add after existing include_router calls (line ~34):
app.include_router(agency_router)          # Agency dashboard (에이전시 대시보드)
```

- [ ] **Step 7.2: Run all tests — verify Green**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

Expected: **80/80 PASS** (71 existing + 9 new agency tests). If any fail, check mock GET call ordering in the test against the actual GET call order in agency.py.

- [ ] **Step 7.3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(agency): register agency_router — all 80 tests green"
```

---

## Task 8: Synthetic Data — `gen_home_services_demo.py`

**Files:**
- Create: `backend/scripts/gen_home_services_demo.py`

- [ ] **Step 8.1: Create the script**

```python
#!/usr/bin/env python3
"""
Generate synthetic call_logs + jobs for JM Home Services store.
(JM Home Services 합성 데이터 생성 — call_logs 300건 + jobs 180건)
Run: cd backend && .venv/bin/python scripts/gen_home_services_demo.py
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL      = os.environ["SUPABASE_URL"]
SERVICE_ROLE_KEY  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {
    "apikey": SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
REST = f"{SUPABASE_URL}/rest/v1"

RNG = random.Random(99)   # seed=99 for reproducibility

JOB_TYPES    = ["paint", "repair", "carpet", "cleaning"]
JOB_WEIGHTS  = [0.30, 0.35, 0.15, 0.20]
JOB_VALUE_RANGES = {
    "paint":   (400, 1200),
    "repair":  (150,  800),
    "carpet":  (200,  600),
    "cleaning":(100,  350),
}
SENTIMENTS  = ["Positive", "Neutral", "Negative"]
CALL_STATUSES = ["Successful", "Unsuccessful"]
PHONES = ["+15031112222", "+15033334444", "+15035556666", "+15037778888", "+15039990000"]


def get_home_services_store_id() -> str:
    resp = httpx.get(
        f"{REST}/stores",
        headers=HEADERS,
        params={"industry": "eq.home_services", "select": "id,name"},
    )
    stores = resp.json()
    if not stores:
        raise SystemExit("ERROR: JM Home Services store not found. Run DB migration first.")
    print(f"Found store: {stores[0]['name']} ({stores[0]['id']})")
    return stores[0]["id"]


def generate_call_logs(store_id: str, n: int = 300) -> list[dict]:
    logs = []
    now  = datetime.now(timezone.utc)
    for i in range(n):
        days_ago    = RNG.uniform(0, 30)
        start_time  = now - timedelta(days=days_ago)
        duration    = RNG.randint(45, 480)
        is_busy     = RNG.random() < 0.70   # 70% field calls
        status      = RNG.choices(CALL_STATUSES, weights=[0.60, 0.40])[0]
        sentiment   = RNG.choices(SENTIMENTS,    weights=[0.45, 0.40, 0.15])[0]
        logs.append({
            "call_id":       f"hs-{i+1:04d}",
            "store_id":      store_id,
            "start_time":    start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "duration":      duration,
            "call_status":   status,
            "sentiment":     sentiment,
            "customer_phone": RNG.choice(PHONES),
            "is_store_busy": is_busy,
            "cost":          round(duration * 0.001, 4),
            "recording_url": None,
            "summary":       f"Customer inquiry — {RNG.choice(JOB_TYPES)} service requested.",
        })
    return logs


def generate_jobs(store_id: str, call_logs: list[dict]) -> list[dict]:
    """60% of successful field calls → booked/completed jobs. (성공한 현장 통화의 60% → 예약)"""
    field_successful = [
        c for c in call_logs
        if c["is_store_busy"] and c["call_status"] == "Successful"
    ]
    RNG.shuffle(field_successful)
    booked_calls = field_successful[: int(len(field_successful) * 0.60)]

    jobs = []
    for call in booked_calls:
        job_type = RNG.choices(JOB_TYPES, weights=JOB_WEIGHTS)[0]
        lo, hi   = JOB_VALUE_RANGES[job_type]
        job_val  = round(RNG.uniform(lo, hi), 2)
        scheduled = datetime.fromisoformat(call["start_time"].replace("Z", "+00:00"))
        scheduled += timedelta(days=RNG.randint(1, 14))
        status    = RNG.choices(["booked", "completed", "cancelled"], weights=[0.30, 0.60, 0.10])[0]
        jobs.append({
            "store_id":      store_id,
            "call_log_id":   call["call_id"],
            "job_type":      job_type,
            "scheduled_date": scheduled.strftime("%Y-%m-%d"),
            "job_value":     job_val,
            "status":        status,
        })
    return jobs


def upload(table: str, rows: list[dict]) -> None:
    BATCH = 100
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        resp  = httpx.post(f"{REST}/{table}", headers=HEADERS, json=chunk)
        if resp.status_code not in (200, 201):
            raise SystemExit(f"Upload failed [{table}]: {resp.status_code} {resp.text[:200]}")
    print(f"  ✓ Uploaded {len(rows)} rows → {table}")


if __name__ == "__main__":
    store_id  = get_home_services_store_id()

    print("Generating call_logs...")
    call_logs = generate_call_logs(store_id, n=300)

    print("Generating jobs...")
    jobs = generate_jobs(store_id, call_logs)

    print(f"Uploading {len(call_logs)} call_logs...")
    upload("call_logs", call_logs)

    print(f"Uploading {len(jobs)} jobs...")
    upload("jobs", jobs)

    print(f"\nDone! {len(call_logs)} call_logs, {len(jobs)} jobs for JM Home Services.")
    field_calls = sum(1 for c in call_logs if c["is_store_busy"])
    print(f"  Field calls (is_store_busy=True): {field_calls} / {len(call_logs)}")
```

- [ ] **Step 8.2: Run the script**

```bash
cd backend && .venv/bin/python scripts/gen_home_services_demo.py
```

Expected output:
```
Found store: JM Home Services (<uuid>)
Generating call_logs...
Generating jobs...
Uploading 300 call_logs...
  ✓ Uploaded 300 rows → call_logs
Uploading N jobs...
  ✓ Uploaded N rows → jobs
Done! 300 call_logs, ~100+ jobs for JM Home Services.
```

- [ ] **Step 8.3: Verify in Supabase**

Run in Supabase SQL Editor:
```sql
SELECT COUNT(*) FROM call_logs WHERE store_id = (SELECT id FROM stores WHERE industry='home_services');
SELECT COUNT(*) FROM jobs;
SELECT status, COUNT(*) FROM jobs GROUP BY status;
```

Expected: ~300 call_logs, ~100+ jobs.

- [ ] **Step 8.4: Commit**

```bash
git add backend/scripts/gen_home_services_demo.py
git commit -m "feat(data): add gen_home_services_demo.py — 300 call_logs + jobs (seed=99)"
```

---

## Task 9: Frontend — `verticalLabels.ts`

**Files:**
- Create: `frontend/src/core/verticalLabels.ts`

- [ ] **Step 9.1: Create verticalLabels.ts**

```typescript
// Industry vertical metadata — maps industry key to display labels and icon
// (산업 버티컬 메타데이터 — 아이콘 및 레이블 매핑)

export interface VerticalMeta {
  icon: string
  primaryRevenueLabel: string
  conversionLabel: string
  avgValueLabel: string
  industryLabel: string
}

export const VERTICAL_META: Record<string, VerticalMeta> = {
  restaurant: {
    icon: '🍽',
    primaryRevenueLabel: 'Peak Hour Revenue',
    conversionLabel:     'Lead Conversion Rate',
    avgValueLabel:       'Avg Ticket',
    industryLabel:       'Restaurant',
  },
  home_services: {
    icon: '🔧',
    primaryRevenueLabel: 'Field Time Revenue',
    conversionLabel:     'Job Booking Rate',
    avgValueLabel:       'Avg Job Value',
    industryLabel:       'Home Services',
  },
}

export function getVerticalMeta(industry: string): VerticalMeta {
  return VERTICAL_META[industry] ?? VERTICAL_META['restaurant']
}
```

- [ ] **Step 9.2: Commit**

```bash
git add frontend/src/core/verticalLabels.ts
git commit -m "feat(frontend): add verticalLabels.ts — industry icon+label mapping"
```

---

## Task 10: Frontend — Agency Layout

**Files:**
- Create: `frontend/src/views/agency/Layout.tsx`
- Create: `frontend/src/views/agency/Layout.module.css`

- [ ] **Step 10.1: Create `Layout.module.css`**

```css
/* Agency Layout styles — reuses same design tokens as FSR Store Layout */
.shell { display: flex; height: 100vh; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; }

/* ── Sidebar ── */
.sidebar { width: 220px; flex-shrink: 0; background: white; border-right: 1px solid #e2e8f0; display: flex; flex-direction: column; overflow-y: auto; }
.brand { display: flex; align-items: center; gap: 10px; padding: 18px 16px 14px; border-bottom: 1px solid #f1f5f9; }
.brandLogo { width: 32px; height: 32px; background: #6366f1; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.brandName { font-size: 14px; font-weight: 700; color: #0f172a; }
.sectionLabel { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; color: #94a3b8; padding: 14px 16px 4px; text-transform: uppercase; }
.agencyName { font-size: 13px; font-weight: 600; color: #334155; padding: 2px 16px 10px; border-bottom: 1px solid #f1f5f9; }
.nav { display: flex; flex-direction: column; padding: 4px 8px; }
.navItem { display: flex; align-items: center; gap: 9px; padding: 8px 10px; border-radius: 7px; font-size: 13.5px; color: #475569; text-decoration: none; transition: background 0.1s, color 0.1s; margin-bottom: 1px; }
.navItem:hover { background: #f1f5f9; color: #0f172a; }
.navItemActive { background: #eef2ff; color: #4f46e5; font-weight: 600; }
.navIcon { font-size: 15px; width: 20px; text-align: center; flex-shrink: 0; }

/* ── User section ── */
.userSection { margin-top: auto; padding: 12px 12px 14px; border-top: 1px solid #f1f5f9; display: flex; align-items: center; gap: 9px; }
.userAvatar { width: 30px; height: 30px; background: #0ea5e9; color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0; }
.userInfo { flex: 1; min-width: 0; }
.userEmail { font-size: 12px; color: #334155; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
.userRole { font-size: 10px; font-weight: 700; color: #0ea5e9; letter-spacing: 0.05em; }
.logoutBtn { background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 16px; padding: 4px 6px; border-radius: 5px; transition: background 0.1s; flex-shrink: 0; }
.logoutBtn:hover { background: #f1f5f9; color: #475569; }

/* ── Main area ── */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.topBar { height: 50px; border-bottom: 1px solid #e2e8f0; background: white; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; flex-shrink: 0; }
.topBarBrand { font-size: 13px; font-weight: 600; color: #475569; }
.liveBadge { font-size: 12px; color: #16a34a; font-weight: 600; }
.content { flex: 1; overflow-y: auto; padding: 24px; }
```

- [ ] **Step 10.2: Create `Layout.tsx`**

```tsx
// Agency Layout — sidebar with store selector + main content outlet
// (에이전시 레이아웃 — 스토어 셀렉터 사이드바 + 메인 콘텐츠 아웃렛)
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../../../core/AuthContext'
import api from '../../../core/api'
import { getVerticalMeta } from '../../../core/verticalLabels'
import styles from './Layout.module.css'

interface StoreItem { id: string; name: string; industry: string }

export default function AgencyLayout() {
  const { logout } = useAuth()
  const navigate   = useNavigate()
  const [stores, setStores]         = useState<StoreItem[]>([])
  const [agencyName, setAgencyName] = useState('JM Agency')

  useEffect(() => {
    api.get('/agency/me').then((r) => setAgencyName(r.data.name)).catch(() => {})
    api.get('/agency/stores').then((r) => setStores(r.data)).catch(() => {})
  }, [])

  const handleLogout = () => { logout(); navigate('/login') }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        {/* Brand */}
        <div className={styles.brand}>
          <div className={styles.brandLogo}>
            <svg viewBox="0 0 24 24" fill="white" width="18" height="18">
              <path d="M12 1a3 3 0 0 1 3 3v8a3 3 0 0 1-6 0V4a3 3 0 0 1 3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" strokeWidth="2" stroke="white" fill="none" strokeLinecap="round" />
            </svg>
          </div>
          <span className={styles.brandName}>JM AI Voice</span>
        </div>

        {/* Agency name */}
        <div className={styles.sectionLabel}>AGENCY</div>
        <div className={styles.agencyName}>{agencyName}</div>

        {/* Store list */}
        <div className={styles.sectionLabel} style={{ marginTop: 8 }}>STORES</div>
        <nav className={styles.nav}>
          <NavLink
            to="/agency/overview"
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
          >
            <span className={styles.navIcon}>⊞</span>
            All Stores
          </NavLink>
          {stores.map((store) => {
            const meta = getVerticalMeta(store.industry)
            return (
              <NavLink
                key={store.id}
                to={`/agency/store/${store.id}`}
                className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
              >
                <span className={styles.navIcon}>{meta.icon}</span>
                {store.name}
              </NavLink>
            )
          })}
        </nav>

        {/* User section */}
        <div className={styles.userSection}>
          <div className={styles.userAvatar}>A</div>
          <div className={styles.userInfo}>
            <div className={styles.userEmail}>Agency Admin</div>
            <div className={styles.userRole}>AGENCY</div>
          </div>
          <button className={styles.logoutBtn} onClick={handleLogout} title="Log Out">→</button>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.topBar}>
          <span className={styles.topBarBrand}>JM AI Voice Platform</span>
          <span className={styles.liveBadge}>● Live</span>
        </header>
        <div className={styles.content}>
          <Outlet />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 10.3: Commit**

```bash
git add frontend/src/views/agency/
git commit -m "feat(agency): add AgencyLayout with store selector sidebar"
```

---

## Task 11: Frontend — Agency Overview Page

**Files:**
- Create: `frontend/src/views/agency/Overview.tsx`
- Create: `frontend/src/views/agency/Overview.module.css`

- [ ] **Step 11.1: Create `Overview.module.css`**

```css
/* Agency Overview page styles */
.page { max-width: 1280px; }

.pageHeader { margin-bottom: 6px; }
.title { font-size: 26px; font-weight: 700; color: #0f172a; margin: 0 0 4px; }
.desc  { font-size: 13.5px; color: #64748b; margin: 0; }

/* ── Period + header row ── */
.headerRow { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
.periodRow { display: flex; gap: 6px; }
.periodBtn { padding: 5px 14px; border-radius: 6px; border: 1px solid #e2e8f0; background: white; font-size: 13px; color: #475569; cursor: pointer; transition: all 0.12s; }
.periodBtn:hover { background: #f8fafc; }
.periodBtnActive { background: #6366f1; border-color: #6366f1; color: white; font-weight: 600; }

/* ── Summary badges ── */
.summaryRow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.summaryCard { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; }
.summaryLabel { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; }
.summaryValue { font-size: 24px; font-weight: 700; color: #0f172a; }
.summaryUnit  { font-size: 13px; color: #64748b; margin-top: 2px; }

/* ── Store card grid ── */
.sectionTitle { font-size: 13px; font-weight: 700; letter-spacing: 0.06em; color: #64748b; text-transform: uppercase; margin-bottom: 12px; }
.storeGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; margin-bottom: 28px; }
.storeCard { background: white; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.storeCardHeader { display: flex; align-items: center; gap: 10px; }
.storeIcon { font-size: 22px; }
.storeCardName { font-size: 16px; font-weight: 700; color: #0f172a; }
.storeCardIndustry { font-size: 11px; color: #94a3b8; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
.storeDivider { border: none; border-top: 1px solid #f1f5f9; margin: 0; }
.storeKpiRow { display: flex; flex-direction: column; gap: 8px; }
.storeKpiItem { display: flex; justify-content: space-between; align-items: baseline; }
.storeKpiLabel { font-size: 12.5px; color: #64748b; }
.storeKpiValue { font-size: 14px; font-weight: 700; color: #0f172a; }
.impactRow { display: flex; justify-content: space-between; align-items: baseline; padding-top: 6px; border-top: 1px solid #f1f5f9; }
.impactLabel { font-size: 12.5px; font-weight: 600; color: #475569; }
.impactValue { font-size: 18px; font-weight: 800; color: #6366f1; }
.viewBtn { margin-top: 4px; padding: 8px 0; border-radius: 7px; border: 1px solid #e2e8f0; background: white; font-size: 13px; color: #4f46e5; cursor: pointer; font-weight: 600; transition: all 0.12s; width: 100%; }
.viewBtn:hover { background: #eef2ff; border-color: #6366f1; }

/* ── Needs attention ── */
.attentionBox { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 10px; padding: 16px 20px; }
.attentionTitle { font-size: 13px; font-weight: 700; color: #92400e; margin-bottom: 8px; }
.attentionItem { font-size: 13px; color: #78350f; display: flex; justify-content: space-between; padding: 4px 0; }

/* ── Loading / empty ── */
.loading { color: #94a3b8; font-size: 14px; padding: 40px 0; text-align: center; }
```

- [ ] **Step 11.2: Create `Overview.tsx`**

```tsx
// Agency Overview — aggregated KPIs + store card grid
// (에이전시 개요 — 집계 KPI + 스토어 카드 그리드)
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../../core/api'
import { getVerticalMeta } from '../../../core/verticalLabels'
import styles from './Overview.module.css'

type Period = 'today' | 'week' | 'month' | 'all'
const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

interface AgencyTotals {
  total_calls: number
  total_monthly_impact: number
  store_count: number
  avg_conversion_rate: number
}

interface StoreMetrics {
  id: string
  name: string
  industry: string
  primary_revenue: number
  primary_revenue_label: string
  labor_savings: number
  conversion_rate: number
  conversion_label: string
  upsell_value: number
  monthly_impact: number
  total_calls: number
  avg_value: number
  avg_value_label: string
}

interface OverviewData {
  agency_name: string
  period: string
  totals: AgencyTotals
  stores: StoreMetrics[]
}

const fmt$ = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toLocaleString()}`

export default function AgencyOverview() {
  const navigate = useNavigate()
  const [period, setPeriod]   = useState<Period>('month')
  const [data, setData]       = useState<OverviewData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get(`/agency/overview?period=${period}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false))
  }, [period])

  const attentionStores = data?.stores.filter((s) => s.conversion_rate < 50) ?? []

  return (
    <div className={styles.page}>
      <div className={styles.headerRow}>
        <div className={styles.pageHeader}>
          <h1 className={styles.title}>Agency Overall Performance</h1>
          <p className={styles.desc}>Aggregated across all stores.</p>
        </div>
        <div className={styles.periodRow}>
          {PERIODS.map(({ key, label }) => (
            <button
              key={key}
              className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
              onClick={() => setPeriod(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className={styles.loading}>Loading...</div>}

      {data && (
        <>
          {/* Summary badges */}
          <div className={styles.summaryRow}>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Total Calls</div>
              <div className={styles.summaryValue}>{data.totals.total_calls.toLocaleString()}</div>
              <div className={styles.summaryUnit}>across all stores</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Total Impact</div>
              <div className={styles.summaryValue}>{fmt$(data.totals.total_monthly_impact)}</div>
              <div className={styles.summaryUnit}>monthly economic value</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Stores</div>
              <div className={styles.summaryValue}>{data.totals.store_count}</div>
              <div className={styles.summaryUnit}>managed locations</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Avg Conversion</div>
              <div className={styles.summaryValue}>{data.totals.avg_conversion_rate}%</div>
              <div className={styles.summaryUnit}>across all verticals</div>
            </div>
          </div>

          {/* Store card grid */}
          <div className={styles.sectionTitle}>Store Performance</div>
          <div className={styles.storeGrid}>
            {data.stores.map((store) => {
              const meta = getVerticalMeta(store.industry)
              return (
                <div key={store.id} className={styles.storeCard}>
                  <div className={styles.storeCardHeader}>
                    <span className={styles.storeIcon}>{meta.icon}</span>
                    <div>
                      <div className={styles.storeCardName}>{store.name}</div>
                      <div className={styles.storeCardIndustry}>{meta.industryLabel}</div>
                    </div>
                  </div>
                  <hr className={styles.storeDivider} />
                  <div className={styles.storeKpiRow}>
                    <div className={styles.storeKpiItem}>
                      <span className={styles.storeKpiLabel}>{store.primary_revenue_label}</span>
                      <span className={styles.storeKpiValue}>{fmt$(store.primary_revenue)}</span>
                    </div>
                    <div className={styles.storeKpiItem}>
                      <span className={styles.storeKpiLabel}>Labor Savings</span>
                      <span className={styles.storeKpiValue}>{fmt$(store.labor_savings)}</span>
                    </div>
                    <div className={styles.storeKpiItem}>
                      <span className={styles.storeKpiLabel}>{store.conversion_label}</span>
                      <span className={styles.storeKpiValue}>{store.conversion_rate}%</span>
                    </div>
                  </div>
                  <div className={styles.impactRow}>
                    <span className={styles.impactLabel}>Monthly Impact</span>
                    <span className={styles.impactValue}>{fmt$(store.monthly_impact)}</span>
                  </div>
                  <button
                    className={styles.viewBtn}
                    onClick={() => navigate(`/agency/store/${store.id}`)}
                  >
                    View Store →
                  </button>
                </div>
              )
            })}
          </div>

          {/* Needs attention */}
          {attentionStores.length > 0 && (
            <>
              <div className={styles.sectionTitle}>Needs Attention</div>
              <div className={styles.attentionBox}>
                <div className={styles.attentionTitle}>
                  ⚠ Stores with conversion rate below 50%
                </div>
                {attentionStores.map((s) => (
                  <div key={s.id} className={styles.attentionItem}>
                    <span>{s.name}</span>
                    <span>{s.conversion_label}: {s.conversion_rate}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 11.3: Commit**

```bash
git add frontend/src/views/agency/Overview.tsx frontend/src/views/agency/Overview.module.css
git commit -m "feat(agency): add AgencyOverview with store card grid and KPI badges"
```

---

## Task 12: Frontend — Agency Store Detail Page

**Files:**
- Create: `frontend/src/views/agency/StoreDetail.tsx`
- Create: `frontend/src/views/agency/StoreDetail.module.css`

- [ ] **Step 12.1: Create `StoreDetail.module.css`**

```css
/* Agency StoreDetail styles */
.page { max-width: 900px; }
.breadcrumb { font-size: 13px; color: #64748b; margin-bottom: 12px; display: flex; align-items: center; gap: 6px; }
.breadcrumbLink { color: #6366f1; cursor: pointer; font-weight: 500; }
.breadcrumbLink:hover { text-decoration: underline; }
.title { font-size: 26px; font-weight: 700; color: #0f172a; margin: 0 0 4px; display: flex; align-items: center; gap: 10px; }
.industryBadge { font-size: 11px; font-weight: 700; color: #0ea5e9; background: #e0f2fe; border-radius: 20px; padding: 3px 10px; letter-spacing: 0.04em; text-transform: uppercase; }

.headerRow { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 10px; }
.periodRow { display: flex; gap: 6px; }
.periodBtn { padding: 5px 14px; border-radius: 6px; border: 1px solid #e2e8f0; background: white; font-size: 13px; color: #475569; cursor: pointer; transition: all 0.12s; }
.periodBtn:hover { background: #f8fafc; }
.periodBtnActive { background: #6366f1; border-color: #6366f1; color: white; font-weight: 600; }

.kpiGrid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 20px; }
@media (min-width: 700px) { .kpiGrid { grid-template-columns: repeat(4, 1fr); } }
.kpiCard { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 18px 16px; }
.kpiLabel { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px; }
.kpiValue { font-size: 22px; font-weight: 800; color: #0f172a; }
.kpiSub   { font-size: 12px; color: #64748b; margin-top: 4px; }
.impactCard { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 18px 20px; display: flex; justify-content: space-between; align-items: center; }
.impactLabel { font-size: 13px; font-weight: 700; color: #4338ca; }
.impactValue { font-size: 28px; font-weight: 800; color: #4f46e5; }
.loading { color: #94a3b8; font-size: 14px; padding: 40px 0; text-align: center; }
```

- [ ] **Step 12.2: Create `StoreDetail.tsx`**

```tsx
// Agency StoreDetail — single-store KPI view within agency context
// (에이전시 컨텍스트 내 단일 스토어 KPI 뷰)
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import api from '../../../core/api'
import { getVerticalMeta } from '../../../core/verticalLabels'
import styles from './StoreDetail.module.css'

type Period = 'today' | 'week' | 'month' | 'all'
const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week',  label: 'Week'  },
  { key: 'month', label: 'Month' },
  { key: 'all',   label: 'All'   },
]

interface StoreMetrics {
  id: string; name: string; industry: string
  primary_revenue: number; primary_revenue_label: string
  labor_savings: number
  conversion_rate: number; conversion_label: string
  upsell_value: number
  monthly_impact: number
  total_calls: number
  avg_value: number; avg_value_label: string
}

const fmt$ = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${n.toLocaleString()}`

export default function AgencyStoreDetail() {
  const { storeId } = useParams<{ storeId: string }>()
  const navigate    = useNavigate()
  const [period, setPeriod]   = useState<Period>('month')
  const [data, setData]       = useState<StoreMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!storeId) return
    setLoading(true)
    api.get(`/agency/store/${storeId}/metrics?period=${period}`)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false))
  }, [storeId, period])

  const meta = data ? getVerticalMeta(data.industry) : null

  return (
    <div className={styles.page}>
      {/* Breadcrumb */}
      <div className={styles.breadcrumb}>
        <span className={styles.breadcrumbLink} onClick={() => navigate('/agency/overview')}>
          ← All Stores
        </span>
        {data && <span>/ {data.name}</span>}
      </div>

      {loading && <div className={styles.loading}>Loading...</div>}

      {data && meta && (
        <>
          <div className={styles.headerRow}>
            <div>
              <h1 className={styles.title}>
                {meta.icon} {data.name}
                <span className={styles.industryBadge}>{meta.industryLabel}</span>
              </h1>
            </div>
            <div className={styles.periodRow}>
              {PERIODS.map(({ key, label }) => (
                <button
                  key={key}
                  className={`${styles.periodBtn} ${period === key ? styles.periodBtnActive : ''}`}
                  onClick={() => setPeriod(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* KPI Grid */}
          <div className={styles.kpiGrid}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>{data.primary_revenue_label}</div>
              <div className={styles.kpiValue}>{fmt$(data.primary_revenue)}</div>
              <div className={styles.kpiSub}>{data.avg_value_label}: {fmt$(data.avg_value)}</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>Labor Savings</div>
              <div className={styles.kpiValue}>{fmt$(data.labor_savings)}</div>
              <div className={styles.kpiSub}>AI call handling cost savings</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>{data.conversion_label}</div>
              <div className={styles.kpiValue}>{data.conversion_rate}%</div>
              <div className={styles.kpiSub}>{data.total_calls.toLocaleString()} total calls</div>
            </div>
            <div className={styles.kpiCard}>
              <div className={styles.kpiLabel}>
                {data.industry === 'home_services' ? 'Lead Revenue' : 'Upselling Value'}
              </div>
              <div className={styles.kpiValue}>{fmt$(data.upsell_value)}</div>
              <div className={styles.kpiSub}>additional AI-driven revenue</div>
            </div>
          </div>

          {/* Monthly Impact */}
          <div className={styles.impactCard}>
            <span className={styles.impactLabel}>Monthly Economic Impact</span>
            <span className={styles.impactValue}>{fmt$(data.monthly_impact)}</span>
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 12.3: Commit**

```bash
git add frontend/src/views/agency/StoreDetail.tsx frontend/src/views/agency/StoreDetail.module.css
git commit -m "feat(agency): add AgencyStoreDetail — per-store KPI view with breadcrumb"
```

---

## Task 13: Frontend — Update `App.tsx` Routing

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 13.1: Update App.tsx**

Replace the entire file content:

```tsx
import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './core/AuthContext'

const Login           = lazy(() => import('./views/Login'))
const StoreLayout     = lazy(() => import('./views/fsr/store/Layout'))
const Overview        = lazy(() => import('./views/fsr/store/Overview'))
const CallHistory     = lazy(() => import('./views/fsr/store/CallHistory'))
const Reservations    = lazy(() => import('./views/fsr/store/Reservations'))
const Analytics       = lazy(() => import('./views/fsr/store/Analytics'))
const Settings        = lazy(() => import('./views/fsr/store/Settings'))
const CctvOverlay     = lazy(() => import('./views/fsr/store/CctvOverlay'))
const AgencyLayout    = lazy(() => import('./views/agency/Layout'))
const AgencyOverview  = lazy(() => import('./views/agency/Overview'))
const AgencyStoreDetail = lazy(() => import('./views/agency/StoreDetail'))

const ComingSoon = ({ title }: { title: string }) => (
  <div style={{ padding: 32, color: '#64748b', fontSize: 18 }}>
    <strong>{title}</strong> — Coming Soon
  </div>
)

function RequireAuth({ children }: { children: JSX.Element }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return children
}

function homeRedirect(token: string | null, role: string | null) {
  if (!token) return '/login'
  return role === 'AGENCY' ? '/agency/overview' : '/fsr/store/overview'
}

function AppRoutes() {
  const { token, role } = useAuth()
  const home = homeRedirect(token, role)

  return (
    <Suspense fallback={<div style={{ padding: 32, color: '#64748b' }}>Loading...</div>}>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={token ? <Navigate to={home} replace /> : <Login />} />

        {/* Agency dashboard (에이전시 대시보드) */}
        <Route path="/agency" element={<RequireAuth><AgencyLayout /></RequireAuth>}>
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"         element={<AgencyOverview />} />
          <Route path="store/:storeId"   element={<AgencyStoreDetail />} />
          <Route path="dashboard"        element={<Navigate to="/agency/overview" replace />} />
        </Route>

        {/* FSR Store (store owner mode — store owner 모드) */}
        <Route path="/fsr/store" element={<RequireAuth><StoreLayout /></RequireAuth>}>
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview"        element={<Overview />} />
          <Route path="ai-voice-bot"    element={<ComingSoon title="AI Voice Bot" />} />
          <Route path="call-history"    element={<CallHistory />} />
          <Route path="reservations"    element={<Reservations />} />
          <Route path="analytics"       element={<Analytics />} />
          <Route path="settings"        element={<Settings />} />
          <Route path="security/solink" element={<CctvOverlay />} />
          <Route path="security/theft"  element={<ComingSoon title="Prevent Theft" />} />
        </Route>

        {/* Root redirect */}
        <Route path="/" element={<Navigate to={home} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AppRoutes />
    </BrowserRouter>
  )
}
```

- [ ] **Step 13.2: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(agency): add /agency/* routes, remove placeholder AgencyDashboard"
```

---

## Task 14: Full End-to-End Verification

- [ ] **Step 14.1: Start servers**

```bash
# Terminal 1 — backend
lsof -ti:8000 | xargs kill 2>/dev/null
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev
```

- [ ] **Step 14.2: Run full test suite**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

Expected: **80/80 PASS** (71 existing + 9 agency).

- [ ] **Step 14.3: Browser verification — Agency flow**

1. Open `http://localhost:5173` → redirected to `/login`
2. Log in as `jmagency@test.com` → redirected to `/agency/overview`
3. Verify sidebar shows: "JM Agency" + "All Stores" + "JM Cafe 🍽" + "JM Home Services 🔧"
4. Verify Overview shows 4 summary badges (Total Calls, Total Impact, Stores, Avg Conversion)
5. Verify 2 store cards with different KPI labels (Peak Hour Revenue vs Field Time Revenue)
6. Click "View Store →" on JM Cafe → `/agency/store/<id>` → KPI labels are restaurant-style
7. Click "View Store →" on JM Home Services → KPI labels are home_services-style
8. Verify breadcrumb "← All Stores" navigates back
9. Verify period selector (Today/Week/Month/All) updates KPIs

- [ ] **Step 14.4: Browser verification — Store flow (regression)**

1. Log out → log in as store user → `/fsr/store/overview` loads correctly
2. All 6 store pages (Overview, Call History, Reservations, Analytics, Settings, CCTV) still work

- [ ] **Step 14.5: Final commit**

```bash
git add -A
git commit -m "feat(phase2-a): complete Agency Dashboard + home_services vertical (80/80 tests)"
```

---

## Spec Coverage Checklist (Self-Review)

| Spec Section | Covered By |
|---|---|
| Agency Dashboard for jmagency@test.com | Task 1, 6, 10, 11, 13 |
| stores.industry column | Task 2 |
| JM Home Services store insert | Task 2 |
| jobs table | Task 2 |
| VerticalMetrics TypedDict | Task 3 |
| restaurant.py KPI calculator | Task 4 |
| home_services.py FTR/JBR/LCS/LRR | Task 5 |
| /api/agency/stores endpoint | Task 6 |
| /api/agency/overview endpoint | Task 6 |
| /api/agency/store/{id}/metrics | Task 6 |
| 403 on non-agency JWT | Task 1 (test), Task 6 (impl) |
| 403 on cross-agency store access | Task 1 (test), Task 6 (impl) |
| AgencyLayout sidebar | Task 10 |
| AgencyOverview store card grid | Task 11 |
| Needs Attention section | Task 11 |
| AgencyStoreDetail breadcrumb | Task 12 |
| verticalLabels.ts | Task 9 |
| App.tsx routing | Task 13 |
| Synthetic data 300 call_logs + jobs | Task 8 |
| TDD 8+ tests before implementation | Task 1 |
| Supabase offset pagination | Task 6 (_fetch_call_logs) |
