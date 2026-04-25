# harness.md — One-Stop Execution Guide
# (하네스 실행 가이드 — 단일 진입점 실행 로직)

## Purpose
Phase-based execution harness for the JM Voice AI Platform.
Ensures TDD compliance, RLS validation, and relay testing before each deploy.
(단계별 실행 하네스. 배포 전 TDD 준수·RLS 검증·릴레이 테스트 보장)

## Execution Order
1. **lint** — Run ruff (backend) and eslint (frontend)
2. **type-check** — mypy (backend) and tsc (frontend)
3. **test-unit** — pytest unit tests with coverage ≥ 85%
4. **test-integration** — pytest integration tests against test DB
5. **rls-audit** — Verify all models have tenant_id and RLS policies
6. **relay-smoke** — Smoke test the Loyverse → Solink relay pipeline
7. **build** — vite build (frontend)
8. **deploy** — Trigger deployment if all phases pass

## Usage
```bash
python scripts/execute.py --phase all
python scripts/execute.py --phase test-unit
python scripts/execute.py --phase rls-audit
```
