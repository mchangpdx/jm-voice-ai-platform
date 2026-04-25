# knowledge/fsr/ — Food Service Restaurant Adapter
# (FSR 지식 어댑터 — 식음료 업종 규칙 및 매핑)

## Role
Contains all FSR-specific business logic: menu prompt assembly, table mapping,
POS variant_id resolution, and MCRR/LCS/UV KPI calculation helpers.
(FSR 비즈니스 로직: 메뉴 프롬프트 조립, 테이블 매핑, POS variant_id 해석, KPI 계산 헬퍼)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `adapter.py` | `KnowledgeAdapter` implementation (KnowledgeAdapter 구현) |
| `prompts/` | Jinja2 menu and booking prompt templates (메뉴·예약 Jinja2 프롬프트) |
| `kpi.py` | MCRR, LCS, UV, Table Turnover Rate formulas (KPI 공식) |
| `variant_map.py` | Loyverse `variant_id` lookup and validation (variant_id 조회·검증) |

## Coding Rules
- `variant_id` mapping must be validated against the live Loyverse inventory, not cached data.
  (variant_id 매핑은 캐시가 아닌 실시간 Loyverse 재고로 검증)
- KPI formulas must match PRD.md exactly: MCRR = AI Bookings × Avg Ticket Size.
  (KPI 공식은 PRD.md와 정확히 일치해야 함)
