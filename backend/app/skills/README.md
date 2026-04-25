# app/skills/ — Layer 2: 7 Universal Shared Skills
# (레이어 2: 7대 범용 공유 스킬)

## Role
Vertical-agnostic business logic units. Each skill is a self-contained module that can be
composed by any industry vertical (FSR, Home Care, Retail) without modification.
(산업 중립적 비즈니스 로직 단위. 각 스킬은 모든 업종에서 수정 없이 조합 가능한 독립 모듈)

## 7 Skills
| Skill | Responsibility (담당) |
|-------|----------------------|
| `catalog/` | Search & filter products/menus (메뉴·상품 검색 및 필터) |
| `slot_filler/` | Collect structured data from conversation (대화에서 구조화 데이터 수집) |
| `scheduler/` | Reserve and manage resources (자원 예약 및 관리) |
| `estimator/` | Calculate quotes and pricing (견적·가격 계산) |
| `transaction/` | Process payments and invoices (결제·인보이스 처리) |
| `tracker/` | Track status of orders/jobs (주문·작업 상태 추적) |
| `feedback/` | Collect reviews and CRM data (리뷰 수집·CRM 데이터화) |

## Layer-Specific Coding Rules
- Skills MUST NOT import from `knowledge/` or `adapters/` — dependency flows downward only.
  (스킬은 knowledge/어댑터 레이어에서 임포트 금지 — 의존성은 단방향 하향)
- Each skill module must expose a single `execute(context: SkillContext) -> SkillResult` function.
  (각 스킬은 단일 `execute()` 함수를 공개 인터페이스로 제공)
- All skills are tenant-aware: `SkillContext` must carry `tenant_id`.
  (모든 스킬은 테넌트 인식 필수: `SkillContext`에 `tenant_id` 포함)
