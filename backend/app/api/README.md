# app/api/ — Vertical & Role-Based Route Handlers
# (API 레이어 — 업종·역할별 엔드포인트 라우터)

## Role
FastAPI router definitions organized by vertical and user role.
Each router group maps to a Matrix UI view (Agency vs Store × FSR/HomeCare/Retail).
(업종·역할별로 구성된 FastAPI 라우터. 각 라우터 그룹은 매트릭스 UI 뷰에 대응)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `v1/` | API version 1 routers (API v1 라우터) |
| `v1/fsr.py` | FSR endpoints (booking, POS, overlay) (FSR 엔드포인트) |
| `v1/homecare.py` | Home Care endpoints (estimate, schedule) (홈케어 엔드포인트) |
| `v1/retail.py` | Retail endpoints (catalog, inventory) (리테일 엔드포인트) |
| `v1/auth.py` | Auth endpoints (login, refresh, logout) (인증 엔드포인트) |
| `deps.py` | Shared FastAPI dependencies (공통 FastAPI 의존성) |

## Layer-Specific Coding Rules
- Every route must declare its required role via a FastAPI dependency.
  (모든 라우트는 FastAPI 의존성으로 역할 요구사항 선언 필수)
- Agency routes return aggregated data across multiple stores; Store routes return single-store data.
  (에이전시 라우트는 다중 매장 집계, 점주 라우트는 단일 매장 데이터 반환)
- No business logic in route handlers — delegate to skills.
  (라우트 핸들러에 비즈니스 로직 금지 — 스킬에 위임)
