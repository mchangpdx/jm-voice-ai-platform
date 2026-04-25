# app/core/ — Layer 1: Security & Intelligence Core
# (레이어 1: 보안 및 지능 핵심 — 인증·RLS·Gemini 엔진)

## Role
The foundation of the entire platform. Handles multi-tenant authentication, PostgreSQL RLS enforcement,
and orchestrates the Gemini AI engine for all skill invocations.
(플랫폼 전체의 기반. 멀티테넌트 인증, RLS 강제, Gemini AI 오케스트레이션 담당)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `auth.py` | JWT verification, session management (JWT 검증·세션 관리) |
| `security.py` | Password hashing, token rotation (비밀번호 해싱·토큰 갱신) |
| `rls.py` | RLS policy helpers — injects `tenant_id` into every query (RLS 정책 헬퍼) |
| `gemini_engine.py` | Gemini 2.0 Flash orchestrator for skill dispatch (Gemini AI 오케스트레이터) |
| `config.py` | Environment variable loading via pydantic-settings (환경변수 로딩) |
| `__init__.py` | Package init (패키지 초기화) |

## Layer-Specific Coding Rules
- All DB session factories MUST attach `tenant_id` via RLS helper before executing.
  (모든 DB 세션은 실행 전 RLS 헬퍼로 `tenant_id` 첨부 필수)
- `gemini_engine.py` assembles prompts in the order: Global → Context → Essential → Temporary.
  (Gemini 프롬프트 조립 순서: 전역 → 컨텍스트 → 핵심 → 임시)
- Never expose raw Gemini API keys — load from environment only.
  (Gemini API 키는 환경변수에서만 로딩, 코드에 하드코딩 금지)
