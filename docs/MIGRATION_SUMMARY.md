# Migration Summary — Legacy jm-saas-platform → JM Voice AI Platform OS
# (마이그레이션 요약 — 레거시 jm-saas-platform → JM Voice AI 플랫폼 OS)

## Legacy Stack vs New Stack

| Aspect | Legacy (jm-saas-platform) | New (jm-voice-ai-platform) |
|--------|--------------------------|----------------------------|
| Runtime | Node.js 20+ / Express | Python 3.12 / FastAPI |
| AI Engine | google-generativeai (JS) | google-generativeai (Python) |
| Database | Supabase (service role, direct queries) | Supabase + SQLAlchemy 2.0 async |
| Auth | agent_id → Supabase lookup | Supabase JWT → tenant_id (sub claim) |
| Queue | BullMQ (Redis) | (planned: Celery or ARQ) |
| Frontend | Next.js 14 + TypeScript | React 18 + Vite + TypeScript |
| Multi-tenancy | store_id per query | tenant_id via RLS TenantBase |

---

## 4-Layer Architecture Map

### Layer 1 — Core Intelligence (`backend/app/core/`)

| New File | Migrated From | What Changed |
|----------|--------------|--------------|
| `config.py` | `src/config/env.js` | Pydantic-settings replaces dotenv; strict validation at startup |
| `auth.py` | `src/middlewares/tenant.js` | JWT decoded locally (python-jose); no Supabase round-trip per request |
| `gemini.py` | `src/services/llm/gemini.js` | Model upgraded to `gemini-3.1-flash-lite`; factory pattern isolates config |
| `models/base.py` | (implicit in Supabase schema) | Explicit `TenantBase` enforces `tenant_id` on every SQLAlchemy model |

### Layer 2 — Universal Shared Skills (`backend/app/skills/`)

| Skill | New File | Migrated From | Status |
|-------|----------|--------------|--------|
| **Slot Filler** | `slot_filler/schemas.py` + `service.py` | `POS_TOOLS` in `src/services/llm/gemini.js` + `llmServer.js` handler | ✅ Done |
| Catalog Navigator | `catalog/service.py` | `check_menu` tool + `cronJobs.js` sync | 🔲 Planned |
| Scheduler | `scheduler/` | `cronJobs.js` (6 AM sync) | 🔲 Planned |
| Estimator | `estimator/` | Home Care sq.ft calculation | 🔲 Planned |
| Transaction | `transaction/` | `worker.js` POS + payment pipeline | 🔲 Planned |
| Tracker | `tracker/` | `call_logs` + BullMQ job status | 🔲 Planned |
| Feedback | `feedback/` | `save_customer_consent` tool | 🔲 Planned |

### Layer 3 — Vertical Knowledge (`backend/app/knowledge/`)

| Vertical | Status | Legacy Equivalent |
|----------|--------|-------------------|
| FSR (Food Service) | 🔲 Planned | System instruction in `gemini.js` + FSR-specific tools |
| Home Care | 🔲 Planned | Variable-based estimation logic |
| Retail | 🔲 Planned | (not in legacy scope) |

### Layer 4 — External Adapters (`backend/app/adapters/`)

| Adapter | Status | Migrated From |
|---------|--------|--------------|
| Loyverse | 🔲 Planned | `src/adapters/pos/loyverse.js` + `webhookRoutes.js` + `posService.js` |
| Solink | 🔲 Planned | `src/routes/solinkRoutes.js` (OAuth, video-link, cameras, snapshot) |
| Relay Engine | 🔲 Planned | `src/queue/worker.js` POS→Solink overlay pipeline |

---

## Key Design Decisions

### 1. tenant_id Rename
Legacy used `store_id` as the tenancy key. New platform standardizes on `tenant_id` across all models to align with Supabase's `auth.uid()` in RLS policies.

### 2. No BullMQ → Fire-and-Forget via FastAPI BackgroundTasks
Legacy used Redis + BullMQ for async jobs. New platform uses FastAPI `BackgroundTasks` for lightweight fire-and-forget, with Celery/ARQ as a future option for high-throughput scenarios.

### 3. JWT Local Decode
Legacy resolved `agent_id` with a Supabase DB round-trip per request. New platform decodes the JWT locally with python-jose — zero extra latency.

### 4. TDD-First
All new skill modules follow strict TDD: test files are written and confirmed failing before implementation. Coverage target: ≥ 85% per skill module.

---

## Test Coverage (Current)

| Module | Tests | Coverage |
|--------|-------|---------|
| `app/core/config.py` | 3 | ✅ ≥ 85% |
| `app/core/auth.py` | 4 | ✅ ≥ 85% |
| `app/core/gemini.py` | 3 | ✅ ≅ 100% |
| `app/skills/slot_filler/` | 5 | ✅ 95.65% |
| Total unit tests | **15** | |

---

## What Remains (Next Sprint)

1. `backend/app/models/menu_item.py` + `catalog/service.py` (Catalog Navigator)
2. Loyverse webhook adapter + receipt injection
3. Solink API bridge (OAuth, video-link, snapshot)
4. Reservation model + transaction pipeline
5. Frontend: Matrix UI shell (Agency vs Store views)
6. `scripts/execute.py` integration: all phases passing in CI
