# backend/tests/ — TDD Test Suites
# (TDD 테스트 스위트 — 단위·통합 테스트)

## Role
All test files for the backend. Tests must be written BEFORE implementation (TDD).
Organized by layer to mirror the `app/` structure.
(모든 백엔드 테스트. 구현 전 테스트 작성 필수(TDD). app/ 구조를 반영한 레이어별 구성)

## Key Files Expected
| Path | Purpose (목적) |
|------|----------------|
| `unit/core/` | Core auth and RLS unit tests (코어 인증·RLS 단위 테스트) |
| `unit/skills/` | Skill logic unit tests per skill (스킬별 단위 테스트) |
| `integration/` | End-to-end flow tests with real DB (실제 DB 통합 테스트) |
| `fixtures/` | Shared test data and factories (공유 테스트 데이터·팩토리) |
| `conftest.py` | pytest fixtures and async DB setup (pytest 픽스처·비동기 DB 설정) |

## Layer-Specific Coding Rules
- Unit tests mock external services (Solink, Loyverse, Gemini) — never call real APIs in unit tests.
  (단위 테스트는 외부 서비스 목업 — 단위 테스트에서 실제 API 호출 금지)
- Integration tests must use a dedicated test schema with RLS enabled.
  (통합 테스트는 RLS가 활성화된 전용 테스트 스키마 사용 필수)
- Test coverage target: ≥ 85% for all skill modules.
  (테스트 커버리지 목표: 모든 스킬 모듈 85% 이상)
