# src/views/ — Matrix Views (Industry × Role)
# (매트릭스 뷰 — 산업 × 역할 뷰 레이어)

## Role
Top-level view layer implementing the Industry × Role matrix.
Each subdirectory represents one cell in the matrix: vertical / role.
(산업 × 역할 매트릭스를 구현하는 최상위 뷰 레이어. 각 서브디렉토리는 매트릭스의 한 셀)

## Matrix Structure
```
views/
  fsr/          ← Food Service Restaurant (식음료 업종)
    agency/     ← Aggregated multi-store dashboard (다중 매장 집계 대시보드)
    store/      ← Operational single-store UI (단일 매장 운영 화면)
  homecare/     ← Home Care Services (홈케어 서비스)
    agency/     ← HQ admin view (본사 관리자 화면)
    store/      ← Technician/provider view (기사·업체 화면)
  retail/       ← Retail (리테일)
```

## Layer-Specific Coding Rules
- Each view imports only from `src/components/`, `src/services/`, and `src/store/`.
  (각 뷰는 `src/components/`, `src/services/`, `src/store/`에서만 임포트)
- Agency views must not mix single-store data with aggregated metrics on the same page.
  (에이전시 뷰에서 단일 매장 데이터와 집계 지표를 같은 페이지에 혼합 금지)
- All views are lazy-loaded via `React.lazy` at the router level.
  (모든 뷰는 라우터 수준에서 `React.lazy`로 지연 로딩)
