# backend/ — FastAPI Application Root
# (FastAPI 백엔드 루트 — 4계층 지능형 OS)

## Role
Houses the entire server-side application built with FastAPI and PostgreSQL (Supabase).
Implements a strict 4-layer architecture with mandatory Row-Level Security on every query.
(FastAPI와 Supabase PostgreSQL 기반의 서버 애플리케이션. 모든 쿼리에 RLS 강제 적용)

## Key Files Expected
| Path | Purpose (목적) |
|------|----------------|
| `app/core/` | Layer 1: Auth, RLS, Gemini engine (인증·보안·AI 엔진) |
| `app/skills/` | Layer 2: 7 universal shared skills (7대 범용 스킬) |
| `app/knowledge/` | Layer 3: Vertical knowledge adapters (산업별 지식 어댑터) |
| `app/adapters/` | Layer 4: External bridges (외부 연동 브릿지) |
| `app/api/` | Route handlers per vertical & role (엔드포인트 라우터) |
| `app/models/` | SQLAlchemy / Pydantic models (DB 모델) |
| `tests/` | TDD test suites — write tests FIRST (TDD 테스트 먼저 작성) |
| `requirements.txt` | Python dependencies (파이썬 의존성) |

## Layer-Specific Coding Rules
1. **RLS is non-negotiable**: Every DB query must include `tenant_id` filter.
   (모든 DB 쿼리에 `tenant_id` 필터 필수)
2. **TDD first**: Write the test before the implementation.
   (구현 전 테스트 먼저 작성)
3. **Fire-and-forget**: External relay calls (Solink/Loyverse) must be async and non-blocking.
   (외부 릴레이 호출은 비동기/논블로킹 방식으로)
4. **Layer isolation**: Skills must NOT import from knowledge/ or adapters/ directly.
   (스킬 레이어는 knowledge/어댑터 레이어에서 직접 임포트 금지)
