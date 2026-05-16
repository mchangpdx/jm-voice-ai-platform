# Phase 2 Backend Spec — Admin Mode Completion

**Date:** 2026-05-17
**Owner:** JM Tech One
**Context:** Phase 1 (frontend 3-tier role separation + read-only admin endpoints) shipped 2026-05-17. This document specifies the remaining backend work required to make the Admin Mode fully functional (CRUD, users management, system health, audit log, real RBAC).

---

## 0. Phase 1 Recap (already shipped, for context)

### Frontend
- `UserRole` enum extended: `'STORE' | 'AGENCY' | 'ADMIN'` (`src/core/AuthContext.tsx`)
- `AdminLayout` separated from `AgencyLayout` (`src/views/admin/Layout.tsx`)
- `/admin/*` routes guarded by `RequireRole allow={['ADMIN']}`
- Pages: `/admin/overview`, `/agencies`, `/stores`, `/users` (placeholder), `/system-health` (placeholder), `/marketing/architecture-proof`
- Cards / List / Compact view toggle shared component (`src/components/store-view/StoreViewToggle.tsx`)
- Daily Instructions sync between Store Overview and AI Voice Bot via custom event
- 403 error card on `AgencyOverview` (replaces silent fail)

### Backend
- `app/api/admin/platform.py` — read-only endpoints:
  - `GET /api/admin/overview` → agency/store counts, calls 30d, stores_by_vertical
  - `GET /api/admin/agencies` → list with owner_email + store_count
  - `GET /api/admin/stores?agency_id=` → cross-agency stores
- `require_admin` dependency — JWT decode + email match (TEMP, replaced in package E)

### DB data fix
- `UPDATE agencies SET owner_id = 'eaa4be1a-e83d-4fac-9893-9b1acfe6da2e'` (jmagency)
- Previous owner (admin@test.com) detached; admin now goes through email-based admin role

---

## A. Admin CRUD Endpoints (Agencies + Stores)

### Endpoints

```
PATCH  /api/admin/agencies/{agency_id}
  body: { name?: str, owner_email?: str }
  → resolve owner_email to user_id via Supabase admin users API
  → update agencies row
  → audit_log

POST   /api/admin/agencies
  body: { name: str, owner_email: str }
  → resolve owner_email → user_id (must exist in auth.users)
  → INSERT agencies
  → audit_log

DELETE /api/admin/agencies/{agency_id}
  → soft delete: UPDATE agencies SET is_active = false
  → reject if any active stores under this agency (409)
  → audit_log

PATCH  /api/admin/stores/{store_id}
  body: { name?: str, is_active?: bool }
  → audit_log

DELETE /api/admin/stores/{store_id}
  → soft delete: UPDATE stores SET is_active = false
  → audit_log

POST   /api/admin/stores/{store_id}/transfer
  body: { new_agency_id: str }
  → validate new_agency_id exists + is_active
  → UPDATE stores SET agency_id = new_agency_id
  → audit_log (before/after agency_id)
```

### DB Schema Changes

```sql
-- Add is_active to agencies (stores.is_active already exists)
ALTER TABLE agencies ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;

-- Index for filtering active agencies
CREATE INDEX IF NOT EXISTS idx_agencies_is_active ON agencies(is_active) WHERE is_active = true;
```

### Validation Rules

| Action | Rule | Status code |
|---|---|---|
| DELETE agency | Has active stores | 409 Conflict |
| POST agency | owner_email not in auth.users | 422 Unprocessable |
| POST agency | duplicate name | 409 Conflict |
| Transfer store | new_agency_id not active | 422 |
| Transfer store | same as current agency_id | 400 (no-op) |

### Tests (TDD waived per `feedback_implementation_first_testing.md`; add post-hoc)

- `tests/integration/test_admin_crud.py`
  - admin can rename agency
  - non-admin gets 403
  - delete agency with stores returns 409
  - transfer store updates agency_id and emits audit log

### Effort: ~60 min

---

## B. Users & Roles Management

### Endpoints

```
GET /api/admin/users
  query: ?role=&search=&limit=&offset=
  → fetch from Supabase /auth/v1/admin/users (paginated)
  → enrich with: app_metadata.role, last_sign_in_at, owns_agency_id (if any), owns_store_id (if any)
  → return list

PATCH /api/admin/users/{user_id}/role
  body: { role: 'STORE' | 'AGENCY' | 'ADMIN' }
  → call Supabase admin users PATCH with app_metadata.role
  → audit_log
  → reject if attempting to demote the last ADMIN (409)

DELETE /api/admin/users/{user_id}
  → Supabase admin disable user (banned_until = "9999-12-31")
  → audit_log
  → reject if user owns any active agencies or stores (409, hint: transfer first)

POST /api/admin/users (Phase 2.5 — optional)
  body: { email, password, role }
  → Supabase admin create + assign role
```

### Impersonation (Phase 2.5 — defer)

Risky feature. Requires:
- Short-lived JWT minted on behalf of target user
- Banner in UI ("You are impersonating X")
- audit_log entry for every impersonation start/end

Recommend deferring until a specific support need arises.

### Effort: ~45 min (excluding impersonation)

---

## C. System Health Endpoints

### Endpoints

```
GET /api/admin/health/webhooks
  → Loyverse webhook state (from admin/sync_control.py)
  → freeze flag status + expiry
  → last successful sync per store

GET /api/admin/health/calls
  → 1h / 24h / 7d call counts
  → error rate (call_status='failed' / total)
  → avg duration, avg cost

GET /api/admin/health/api-errors
  → uvicorn access log parsing or in-memory ring buffer
  → 4xx / 5xx counts per endpoint, last N minutes
```

### Implementation Notes

- Webhooks: read from existing `admin/sync_control.py` state (in-memory or Redis if exists)
- Calls: aggregate from `call_logs` table
- API errors: cheapest implementation is a FastAPI middleware that pushes to a `collections.deque(maxlen=1000)`. For production, swap to Sentry/Datadog.

### Effort: ~30 min

---

## D. Audit Log

### Schema

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id UUID NOT NULL,
  actor_email TEXT,
  action TEXT NOT NULL,          -- 'agency.update', 'store.transfer', 'user.role_change', etc.
  target_type TEXT,              -- 'agency', 'store', 'user'
  target_id UUID,
  before JSONB,
  after JSONB,
  ip_address INET,
  user_agent TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_actor   ON audit_logs(actor_user_id, created_at DESC);
CREATE INDEX idx_audit_target  ON audit_logs(target_type, target_id, created_at DESC);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);

-- 90-day retention (configurable)
-- ALTER TABLE audit_logs SET (autovacuum_vacuum_scale_factor = 0.05);
```

### Helper

```python
# app/core/audit.py
from typing import Any
import httpx
from app.core.config import settings

_HEADERS = {
    "apikey": settings.supabase_service_role_key,
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
    "Content-Type": "application/json",
}
_REST = f"{settings.supabase_url}/rest/v1"


async def audit_log(
    *,
    actor_user_id: str,
    actor_email: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Fire-and-forget audit log write. Never raises — never blocks the request.
    (감사 로그 기록 — 절대 요청을 막지 않음)
    """
    payload = {
        "actor_user_id": actor_user_id,
        "actor_email":   actor_email,
        "action":        action,
        "target_type":   target_type,
        "target_id":     target_id,
        "before":        before,
        "after":         after,
        "ip_address":    ip_address,
        "user_agent":    user_agent,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{_REST}/audit_logs", headers=_HEADERS, json=payload)
    except Exception:
        # Audit must never break the user request. Log to stderr only.
        import logging
        logging.getLogger("app.audit").exception("Audit log write failed")
```

### Hook into every mutation

Every PATCH/POST/DELETE in A, B, C must call `await audit_log(...)` with:
- `actor_user_id` from JWT sub
- `actor_email` from JWT email claim
- `action`, `target_type`, `target_id`, `before`, `after`
- Optional `ip_address` from `request.client.host`, `user_agent` from header

### Read Endpoint

```
GET /api/admin/audit-logs
  query: ?actor=&target_type=&target_id=&action=&since=&limit=&offset=
  → returns paginated list, default 50 per page, ordered by created_at DESC
```

### Frontend (Phase 2)

Page at `/admin/audit-log` — table with filter chips (action, actor, target_type) + date range picker. Effort: ~45 min frontend.

### Effort (backend only): ~60 min

---

## E. Real RBAC — app_metadata.role Migration

### Why

Current `require_admin` uses email match (`email == 'admin@test.com'`). This is:
- Fragile (typo, multiple admins)
- Not standard (Supabase has `app_metadata.role` for this)
- Blocks multi-admin onboarding

### One-time migration script

```python
# backend/scripts/seed_admin_role.py
"""One-time: set app_metadata.role='admin' for all current platform admins.
(현재 플랫폼 관리자 계정 모두에 app_metadata.role='admin' 부여)
"""
from dotenv import load_dotenv; load_dotenv('.env')
import asyncio, httpx
from app.core.config import settings

ADMIN_USER_IDS = [
    'ba885c40-a9ed-4fba-a307-fe3db8329377',  # admin@test.com
]

async def main():
    h = {
        'apikey': settings.supabase_service_role_key,
        'Authorization': f'Bearer {settings.supabase_service_role_key}',
        'Content-Type': 'application/json',
    }
    async with httpx.AsyncClient(timeout=15) as c:
        for uid in ADMIN_USER_IDS:
            r = await c.put(
                f'{settings.supabase_url}/auth/v1/admin/users/{uid}',
                headers=h,
                json={'app_metadata': {'role': 'admin'}},
            )
            print(uid, r.status_code, r.json().get('email'))

asyncio.run(main())
```

### Backend change

```python
# app/api/admin/platform.py — replace email match
# OLD:
#   email = (payload.get("email") or "").lower()
#   if email != ADMIN_EMAIL:
#       raise HTTPException(403, "Admin role required")
# NEW:
role = ((payload.get("app_metadata") or {}).get("role") or "").lower()
if role != "admin":
    raise HTTPException(403, "Admin role required")
```

Same change in any other place that uses email-based admin detection.

### Frontend change

```typescript
// src/core/AuthContext.tsx — replace email-based ADMIN
// OLD: if (normalizedEmail === ADMIN_EMAIL) role = 'ADMIN'
// NEW: decode JWT app_metadata.role from /auth/login response

// Backend should return { access_token, role } so frontend doesn't need to decode.
// Or: GET /api/auth/me → { id, email, role }
```

### Effort: ~30 min backend + ~20 min frontend

---

## Suggested Order

1. **D** Audit log infra first — so A/B/C mutations are auditable from day one
2. **A** Admin CRUD — highest user value
3. **E** RBAC migration — clean up email-match shortcut
4. **B** Users & Roles — depends on E for role PATCH semantics
5. **C** System Health — lowest urgency, builds on A's `is_active` plumbing

Total backend: ~3.5 hours.
Plus frontend wiring (Manage buttons, Users/Health pages, Audit log page): ~2.5 hours.
**Grand total: ~6 hours** = 1 focused session or 2 split sessions.

---

## Caveats / Memory Rules

- **No backend edits during live calls** (`uvicorn --reload` drops WebSocket 1012).
- **DB schema changes affect jm-saas-platform** if touching shared tables (`stores`, `agencies` are shared). `audit_logs` is voice-only, no coordination needed.
- **Loyverse webhook**: never DELETE/POST. Use freeze flag.
- **Tests**: implementation-first per user override (`feedback_implementation_first_testing.md`). Add tests post-hoc.

---

## Phase 3 (out of scope here, for completeness)

- Feature flags / kill switches (per-vertical rollout control)
- Broadcast notifications (email/SMS to all stores)
- Billing & usage dashboards
- Webhook re-delivery UI
- Multi-region / read-replica strategy
