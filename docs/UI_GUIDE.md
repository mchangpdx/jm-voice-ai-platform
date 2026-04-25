# UI_GUIDE.md - Matrix Layout Design Guide
# (매트릭스 레이아웃 디자인 가이드)

## 1. Matrix View Philosophy
The UI follows an Industry × Role matrix. Each cell (e.g., FSR × Agency) renders a distinct view.
(UI는 산업 × 역할 매트릭스를 따름. 각 셀은 고유한 뷰를 렌더링함)

## 2. Role Definitions
- **Agency View**: Aggregated multi-store dashboard for franchisors or service HQs. (에이전시용 집계 대시보드)
- **Store View**: Operational single-store UI for owners or technicians. (점주/기사용 운영 화면)

## 3. Industry Verticals
- **FSR** (Food Service Restaurant): Reservations, POS, CCTV relay. (식음료 업종)
- **Home Care**: Estimation, scheduling, technician tracking. (홈케어 서비스)
- **Retail**: Inventory, product catalog, transactions. (리테일/소매)

## 4. Component Hierarchy
```
views/
  {vertical}/
    agency/   ← Aggregated KPI panels, multi-store map
    store/    ← Operational panels, real-time voice feed
```

## 5. Coding Rules
- Never share state between Agency and Store views directly — route through the global store.
- All KPI calculations must mirror PRD.md formulas.
- Use lazy-loading per vertical to reduce initial bundle size.
