# skills/catalog/ — Product & Menu Catalog Search
# (카탈로그 스킬 — 메뉴·상품 검색 및 필터링)

## Role
Handles all search, filter, and retrieval of products or menu items from the tenant's inventory.
Supports fuzzy search, category filtering, and availability checks.
(테넌트 재고에서 상품·메뉴 검색, 필터, 조회 처리. 퍼지 검색·카테고리 필터·가용성 확인 지원)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `search.py` | Full-text and fuzzy search logic (전문·퍼지 검색 로직) |
| `filters.py` | Category, price range, availability filters (카테고리·가격·가용성 필터) |
| `models.py` | Pydantic schemas for catalog I/O (카탈로그 I/O Pydantic 스키마) |

## Coding Rules
- Always filter by `tenant_id` and `is_active=True` before returning results.
  (결과 반환 전 `tenant_id`와 `is_active=True` 필터 필수)
- `variant_id` must be preserved in all results for POS relay compatibility.
  (POS 릴레이 호환을 위해 `variant_id` 보존 필수)
