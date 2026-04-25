# app/models/ — Database Models & RLS Schemas
# (데이터 모델 — DB 모델 및 RLS 스키마)

## Role
SQLAlchemy ORM models and Pydantic schemas for all database tables.
Every model enforces the multi-tenant RLS design from DB_SCHEMA.md.
(모든 DB 테이블의 SQLAlchemy ORM 모델·Pydantic 스키마. DB_SCHEMA.md의 RLS 설계 강제 적용)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `store.py` | `stores` table model — multi-tenant root (다중테넌트 루트 테이블) |
| `menu_item.py` | `menu_items` table with `variant_id` (variant_id 포함 메뉴 모델) |
| `resource.py` | `resources` table — tables/technicians (테이블·기사 범용 자원 모델) |
| `pos_event.py` | `pos_events` table — relay audit log (릴레이 감사 로그) |
| `base.py` | SQLAlchemy base with tenant_id mixin (tenant_id mixin이 포함된 베이스) |

## Layer-Specific Coding Rules
- ALL models must inherit from `TenantBase` which auto-injects `tenant_id` column.
  (모든 모델은 `tenant_id` 컬럼을 자동 주입하는 `TenantBase` 상속 필수)
- Pydantic response schemas must never expose `loyverse_token` or raw API keys.
  (Pydantic 응답 스키마에 `loyverse_token` 또는 원시 API 키 노출 금지)
- Use Alembic for all migrations — no manual schema changes in production.
  (모든 마이그레이션은 Alembic 사용 — 프로덕션 수동 스키마 변경 금지)
