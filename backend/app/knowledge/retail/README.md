# knowledge/retail/ — Retail Inventory Adapter
# (리테일 지식 어댑터 — 리테일 재고 및 상품 규칙)

## Role
Retail-specific rules for inventory management, product catalog composition,
stock threshold alerts, and POS transaction handling for brick-and-mortar stores.
(리테일 재고 관리, 상품 카탈로그 구성, 재고 임계치 알림, 오프라인 매장 POS 거래 규칙)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `adapter.py` | `KnowledgeAdapter` implementation (KnowledgeAdapter 구현) |
| `inventory_rules.py` | Stock level thresholds and reorder logic (재고 임계치·재주문 로직) |
| `catalog_builder.py` | Dynamic product catalog assembly (동적 상품 카탈로그 조립) |
| `prompts/` | Retail-specific Jinja2 prompt templates (리테일 Jinja2 프롬프트) |

## Coding Rules
- Stock availability checks must be real-time — no stale cache for `is_in_stock`.
  (`is_in_stock`는 실시간 확인 필수 — 오래된 캐시 사용 금지)
- All product references must carry `variant_id` for POS compatibility.
  (모든 상품 참조는 POS 호환을 위해 `variant_id` 포함 필수)
