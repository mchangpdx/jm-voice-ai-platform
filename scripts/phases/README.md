# scripts/phases/ — Phase Definition Files
# (실행 단계 정의 파일)

## Role
YAML or JSON configuration files that define each execution phase:
commands, success criteria, timeout limits, and dependency order.
(각 실행 단계를 정의하는 YAML/JSON 설정 파일. 명령·성공 기준·타임아웃·의존성 순서 포함)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `lint.yaml` | Lint phase config (린트 단계 설정) |
| `test.yaml` | Test phase config with coverage thresholds (커버리지 임계치 포함 테스트 설정) |
| `rls_audit.yaml` | RLS audit rules and model whitelist (RLS 감사 규칙·모델 화이트리스트) |
| `relay_smoke.yaml` | Relay smoke test config with mock payloads (목 페이로드 릴레이 스모크 테스트 설정) |

## Phase File Format
```yaml
name: test-unit
command: pytest backend/tests/unit/
timeout_seconds: 120
success_criteria:
  exit_code: 0
  coverage_min: 85
depends_on: [lint, type-check]
```
