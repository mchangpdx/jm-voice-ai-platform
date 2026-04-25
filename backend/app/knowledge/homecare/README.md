# knowledge/homecare/ — Home Care Service Adapter
# (홈케어 지식 어댑터 — 홈케어 서비스 규칙 및 로직)

## Role
Home Care business logic: variable-based estimation (sq.ft, pollution level),
technician scheduling rules, lead management, and LCR/Quote Accuracy KPI helpers.
(홈케어 비즈니스 로직: 면적·오염도 기반 견적, 기사 스케줄 규칙, 리드 관리, KPI 헬퍼)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `adapter.py` | `KnowledgeAdapter` implementation (KnowledgeAdapter 구현) |
| `pricing_vars.py` | sq.ft and pollution level pricing tables (면적·오염도 가격표) |
| `technician_rules.py` | Assignment and availability constraints (기사 배정·가용성 제약) |
| `kpi.py` | LCR, Quote Accuracy, Lead Response Time, Staff Utilization (KPI 공식) |

## Coding Rules
- Pricing variables (`sq_ft`, `pollution_level`) must use predefined tier enums.
  (가격 변수는 사전 정의된 티어 enum 사용 필수)
- Lead Response Time target is <2 seconds — log any exceeding response for monitoring.
  (리드 응답 시간 목표 2초 미만 — 초과 응답은 모니터링용 로그 기록)
