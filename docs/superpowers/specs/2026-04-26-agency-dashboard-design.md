# Agency Dashboard + Industry Vertical Abstraction — Design Spec
**Date:** 2026-04-26  
**Phase:** 2-A  
**Status:** Approved

---

## 1. Problem & Goals

### Context
JM Voice AI Platform is transitioning from a single-store SaaS tool to a multi-tenant Management OS. The Agency Dashboard enables one agency (JM Agency) to manage and monitor multiple SMB stores from a unified interface — analogous to Toast Central, Square Multi-Location, and ServiceTitan's franchise management views.

### Goals
1. Implement the Agency Dashboard so `jmagency@test.com` can view all managed stores in one place.
2. Prove architectural flexibility by supporting two distinct industry verticals — `restaurant` (JM Cafe) and `home_services` (JM Home Services) — within the same platform.
3. Build the Layer 3 Knowledge skeleton so future verticals require zero structural changes.

### Out of Scope (Phase 2-A)
- Billing / invoicing between agency and stores
- Agency-level settings management for stores
- Full store drill-down (all 6 pages) from agency context — Overview only
- AI Voice Bot, Menu Management, CRM, Prevent Theft pages

---

## 2. Industry Vertical Definitions

### 2-A. Restaurant (`restaurant`) — JM Cafe
Existing vertical. Voice AI answers calls during peak hours when staff are too busy.

| KPI | Full Name | Formula | Label |
|-----|-----------|---------|-------|
| PHRC | Peak Hour Revenue Capture | `busy_successful × avg_ticket` | "Peak Hour Revenue" |
| LCS | Labor Cost Savings | `(Σduration_sec ÷ 3600) × hourly_wage` | "Labor Savings" |
| LCR | Lead Conversion Rate | `(successful ÷ total) × 100` | "Lead Conversion Rate" |
| UV | Upselling Value | `total_calls × 0.15 × $5` | "Upselling Value" |
| Monthly Impact | Total Economic Impact | `PHRC + LCS + UV` | "Monthly Impact" |

### 2-B. Home Services (`home_services`) — JM Home Services
Professional home services (painting, repair, carpet cleaning, etc.) as found on Thumbtack/Angi. Solo contractors and small crews miss calls while working on-site — the AI captures those leads.

| KPI | Full Name | Formula | Label |
|-----|-----------|---------|-------|
| FTR | Field Time Revenue | `field_calls_booked × avg_job_value` | "Field Time Revenue" |
| LCS | Labor Cost Savings | `(Σduration_sec ÷ 3600) × hourly_rate` | "Labor Savings" |
| JBR | Job Booking Rate | `(booked_jobs ÷ total_calls) × 100` | "Job Booking Rate" |
| LRR | Lead Response Revenue | `total_calls × 0.30 × avg_job_value × 0.10` | "Lead Revenue" |
| Monthly Impact | Total Economic Impact | `FTR + LCS + LRR` | "Monthly Impact" |

**FTR Rationale:** On Thumbtack/Angi, a missed call = lost job to the next contractor. `call_logs.is_store_busy = true` reuses the existing busy-flag to mean "contractor was on-site when the call came in." `field_calls_booked` = jobs linked to those calls where job.status IN ('booked', 'completed').

---

## 3. Database Changes

### 3-A. `stores` table
```sql
ALTER TABLE stores ADD COLUMN industry TEXT NOT NULL DEFAULT 'restaurant';
UPDATE stores SET industry = 'restaurant' WHERE name = 'JM Cafe';

INSERT INTO stores (name, agency_id, industry, owner_id)
VALUES (
  'JM Home Services',
  '<existing_agency_id>',   -- e4d0c104-659c-4d49-a63b-5c16bf2d83bf
  'home_services',
  NULL                      -- no independent store-owner login in Phase 2-A
);
```

### 3-B. `jobs` table (home_services only)
```sql
CREATE TABLE jobs (
  id             SERIAL PRIMARY KEY,
  store_id       UUID NOT NULL REFERENCES stores(id),
  call_log_id    TEXT REFERENCES call_logs(call_id),
  job_type       TEXT NOT NULL,   -- 'paint'|'repair'|'carpet'|'cleaning'
  scheduled_date DATE,
  job_value      DECIMAL(10,2) NOT NULL DEFAULT 0,
  status         TEXT NOT NULL,   -- 'quoted'|'booked'|'completed'|'cancelled'
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
`is_field_call` 컬럼은 jobs에 두지 않음. `call_logs.is_store_busy`가 동일 개념을 이미 담고 있으므로 `call_log_id` JOIN으로 파생 가능.

### 3-C. Synthetic Data (`backend/scripts/gen_home_services_demo.py`)
- `call_logs`: 300 rows, 30 days, JM Home Services store_id, seed=99, `is_store_busy=True` 70% (현장 작업 중 수신 시뮬레이션)
- `jobs`: 180 rows (call_logs 60% 예약 성사), job_value $150–$1,200
- Job types: paint 30%, repair 35%, carpet 15%, cleaning 20%

### 3-D. `agencies` table assumption
Current schema assumed: `agencies(id, name, owner_id)` where `owner_id` = Supabase user UUID of jmagency@test.com. Agency name updated to **"JM Agency"** in DB.

---

## 4. Backend Architecture

### 4-A. Layer 3 Knowledge Skeleton (`app/knowledge/`)

```
app/knowledge/
  __init__.py
  base.py            ← VerticalMetrics TypedDict + industry constants
  restaurant.py      ← KPI logic extracted from store.py (no behavior change)
  home_services.py   ← FTR / JBR / LCS / LRR calculation
```

**`base.py` — shared contract:**
```python
class VerticalMetrics(TypedDict):
    # Industry-agnostic fields (shared across all verticals)
    monthly_impact: float
    labor_savings: float
    conversion_rate: float        # LCR | JBR
    upsell_value: float           # UV | LRR
    primary_revenue: float        # PHRC | FTR
    avg_value: float              # avg_ticket | avg_job_value
    total_calls: int
    successful_calls: int
    using_real_busy_data: bool

    # Rendering metadata (frontend label resolution)
    industry: str                 # 'restaurant' | 'home_services'
    primary_revenue_label: str    # "Peak Hour Revenue" | "Field Time Revenue"
    conversion_label: str         # "Lead Conversion Rate" | "Job Booking Rate"
    avg_value_label: str          # "Avg Ticket" | "Avg Job Value"
```

**`restaurant.py`** — extracts existing PHRC/LCS/LCR/UV logic from `store.py` unchanged.  
**`home_services.py`** — implements same interface using `jobs` table instead of `orders`.

### 4-B. Agency API (`app/api/agency.py`)

**Authorization flow:**
```
JWT → tenant_id
  → agencies WHERE owner_id = tenant_id → agency (403 if not found)
  → stores WHERE agency_id = agency.id  → store list
```
Store-level requests additionally verify `store.agency_id == agency.id` to prevent cross-agency data access.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agency/stores` | List agency stores (id, name, industry, call_count) |
| GET | `/api/agency/overview?period=` | Aggregated KPIs + per-store VerticalMetrics array |
| GET | `/api/agency/store/{store_id}/metrics?period=` | Single store VerticalMetrics (industry-aware) |

**`/api/agency/overview` response shape:**
```json
{
  "agency_name": "JM Agency",
  "period": "month",
  "totals": {
    "total_calls": 1789,
    "total_monthly_impact": 23914.00,
    "store_count": 2
  },
  "stores": [
    {
      "id": "...", "name": "JM Cafe", "industry": "restaurant",
      "primary_revenue": 10001, "primary_revenue_label": "Peak Hour Revenue",
      "labor_savings": 1948, "conversion_rate": 61.9, "conversion_label": "Lead Conversion Rate",
      "monthly_impact": 13064, "total_calls": 1487
    },
    {
      "id": "...", "name": "JM Home Services", "industry": "home_services",
      "primary_revenue": 8400, "primary_revenue_label": "Field Time Revenue",
      "labor_savings": 1200, "conversion_rate": 54.3, "conversion_label": "Job Booking Rate",
      "monthly_impact": 10850, "total_calls": 302
    }
  ]
}
```

### 4-C. TDD Coverage (`test_agency_api.py`)
Tests written **before** implementation:
1. `test_agency_stores_returns_list` — valid JWT → 2 stores
2. `test_agency_stores_403_non_agency_user` — store JWT → 403
3. `test_agency_overview_aggregates_correctly` — totals = sum of stores
4. `test_agency_overview_period_filter` — today/week/month/all
5. `test_agency_store_metrics_restaurant` — PHRC/LCS/LCR labels
6. `test_agency_store_metrics_home_services` — FTR/JBR/LCS labels
7. `test_agency_store_metrics_cross_agency_forbidden` — 403 on foreign store_id
8. `test_agency_overview_missing_auth` — 401 on no token

### 4-D. `app/main.py` addition
```python
from app.api.agency import router as agency_router
app.include_router(agency_router)
```

---

## 5. Frontend Architecture

### 5-A. Routing (`App.tsx`)
```
/agency                         → AgencyLayout (new, lazy)
  index                         → redirect → /agency/overview
  /agency/overview              → AgencyOverview (aggregated)
  /agency/store/:storeId        → AgencyStoreDetail (per-store)

/agency/dashboard               → redirect → /agency/overview (backward compat)
```

### 5-B. New Files
```
frontend/src/views/agency/
  Layout.tsx            ← sidebar + outlet
  Layout.module.css
  Overview.tsx          ← aggregated KPIs + store card grid
  Overview.module.css
  StoreDetail.tsx       ← single-store KPI view (agency context)
  StoreDetail.module.css

frontend/src/core/
  verticalLabels.ts     ← industry → label/icon mapping
```

### 5-C. `verticalLabels.ts`
```typescript
export const VERTICAL_META: Record<string, {
  icon: string
  primaryRevenueLabel: string
  conversionLabel: string
  avgValueLabel: string
}> = {
  restaurant:     { icon: '🍽', primaryRevenueLabel: 'Peak Hour Revenue', conversionLabel: 'Lead Conversion Rate', avgValueLabel: 'Avg Ticket' },
  home_services:  { icon: '🔧', primaryRevenueLabel: 'Field Time Revenue', conversionLabel: 'Job Booking Rate',      avgValueLabel: 'Avg Job Value' },
}
```

### 5-D. AgencyLayout Sidebar
```
┌───────────────────────┐
│ 🎤 JM AI Voice        │  ← brand
├───────────────────────┤
│ AGENCY                │
│ JM Agency             │  ← agency name from API
├───────────────────────┤
│ STORES                │
│ ✓ All Stores          │  ← /agency/overview (default active)
│   JM Cafe          🍽 │  ← /agency/store/:id
│   JM Home Services 🔧 │  ← /agency/store/:id
├───────────────────────┤
│ jmagency@test.com     │
│ AGENCY          [→]   │  ← logout
└───────────────────────┘
```

### 5-E. AgencyOverview Layout
```
Agency Overall Performance          [Today][Week][Month][All]
Aggregated across all stores.

[Total Calls] [Total Impact] [Stores] [Avg Conversion]   ← 4 summary badges

STORE PERFORMANCE
┌─────────────────────┐  ┌─────────────────────┐
│ JM Cafe 🍽           │  │ JM Home Services 🔧  │
│ restaurant          │  │ home_services        │
│──────────────────── │  │──────────────────── │
│ Peak Hour Revenue   │  │ Field Time Revenue   │
│ $10,001             │  │ $8,400               │
│ Labor Savings $1,948│  │ Labor Savings $1,200 │
│ Lead Conv.   61.9%  │  │ Job Booking  54.3%   │
│ Monthly Impact      │  │ Monthly Impact       │
│ $13,064             │  │ $10,850              │
│ [View Store →]      │  │ [View Store →]       │
└─────────────────────┘  └─────────────────────┘

NEEDS ATTENTION
Stores with conversion rate below 50%  (경고 배지)
```

### 5-F. AgencyStoreDetail
- Breadcrumb: `JM Agency > JM Home Services`
- KPI cards using industry-aware labels from `verticalLabels.ts`
- Period selector (Today / Week / Month / All)
- Back button → `/agency/overview`
- Phase 2-B에서 Call History / Reservations / Analytics 탭 추가

---

## 6. Data Flow Summary

```
jmagency@test.com 로그인
  → POST /api/auth/login → JWT
  → GET /api/store/me → 404 (store 없음)
  → role = 'AGENCY' (AuthContext)
  → redirect /agency/overview

AgencyOverview 마운트
  → GET /api/agency/overview?period=month
    → DB: agencies WHERE owner_id = tenant_id
    → DB: stores WHERE agency_id = agency.id  [2개 반환]
    → 각 store별 industry 감지 → knowledge layer 분기
      restaurant   → restaurant.py KPI 계산 (call_logs + orders)
      home_services→ home_services.py KPI 계산 (call_logs + jobs)
    → VerticalMetrics[] 반환
  → 스토어 카드 렌더링 (industry별 레이블)
```

---

## 7. Implementation Sequence

| 순서 | 작업 | 파일 | 비고 |
|------|------|------|------|
| 1 | TDD 테스트 작성 | `test_agency_api.py` | Red 단계 먼저 |
| 2 | DB 마이그레이션 | Supabase SQL Editor | industry 컬럼 + jobs 테이블 |
| 3 | 합성 데이터 생성 | `gen_home_services_demo.py` | seed=99, 300 call_logs |
| 4 | Knowledge 뼈대 | `app/knowledge/base.py` | VerticalMetrics 타입 |
| 5 | Restaurant KPI | `app/knowledge/restaurant.py` | store.py에서 추출 |
| 6 | Home Services KPI | `app/knowledge/home_services.py` | FTR/JBR/LCS/LRR |
| 7 | Agency API | `app/api/agency.py` | Green 단계 |
| 8 | main.py 등록 | `app/main.py` | agency_router 추가 |
| 9 | verticalLabels.ts | `frontend/src/core/` | 레이블 매핑 |
| 10 | AgencyLayout | `frontend/src/views/agency/` | 사이드바 |
| 11 | AgencyOverview | `frontend/src/views/agency/` | 스토어 카드 그리드 |
| 12 | AgencyStoreDetail | `frontend/src/views/agency/` | 개별 스토어 뷰 |
| 13 | App.tsx 라우팅 | `frontend/src/App.tsx` | /agency/* 경로 추가 |
| 14 | 전체 테스트 검증 | pytest | 기존 71개 + 신규 8개 |

---

## 8. Constraints & Invariants

- **RLS**: 모든 DB 쿼리는 `service_role_key`로 bypass, `agency_id` 격리 필수
- **TDD**: `test_agency_api.py` 반드시 구현 전 작성 (Red → Green)
- **Supabase max_rows=1000**: call_logs 집계 시 offset 페이지네이션 필수
- **industry 기본값**: `'restaurant'` (기존 store 하위 호환성)
- **홈서비스 owner_id**: Phase 2-A에서 NULL 허용 (에이전시 직속)
- **cross-agency 접근**: agency JWT로 타 agency store 접근 시 403 반환
- **에이전시명**: "JM Agency" (DB + UI 모두 적용)
