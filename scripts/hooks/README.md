# scripts/hooks/ — TDD & Security Auto-Checkers
# (TDD 및 보안 자동 검증 훅)

## Role
Git hooks and CI hooks that enforce TDD compliance, RLS presence, and security rules
before any commit or deployment is allowed.
(커밋·배포 허용 전 TDD 준수·RLS 존재·보안 규칙을 강제하는 Git 훅 및 CI 훅)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `pre-commit.sh` | Runs lint + rls-audit before every commit (커밋 전 린트·RLS 감사 실행) |
| `pre-push.sh` | Runs full test suite before push (푸시 전 전체 테스트 스위트 실행) |
| `tdd_check.py` | Verifies test file exists before implementation file (구현 전 테스트 파일 존재 확인) |
| `secret_scan.py` | Scans for hardcoded secrets or API keys (하드코딩 비밀·API 키 스캔) |

## Setup
```bash
cp scripts/hooks/pre-commit.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```
