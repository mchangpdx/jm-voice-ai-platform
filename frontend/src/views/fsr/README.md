# views/fsr/ — Food Service Restaurant Module
# (FSR 뷰 모듈 — 식음료 업종 화면)

## Role
All UI views for the Food Service Restaurant vertical.
Covers reservations, real-time POS feed, CCTV text overlay status, and FSR KPI panels.
(식음료 업종 모든 UI 뷰. 예약·실시간 POS·CCTV 오버레이 상태·FSR KPI 패널 포함)

## Structure
| Directory | Role (역할) |
|-----------|------------|
| `agency/` | Multi-store MCRR, LCS, UV aggregated dashboard (다중 매장 KPI 집계 대시보드) |
| `store/` | Single-store operational: reservations, voice log, POS events (단일 매장 운영) |

## Key Files Expected (per role dir)
- `Dashboard.tsx` — Main view entry point (메인 뷰 진입점)
- `KpiPanel.tsx` — FSR KPI display (MCRR, LCS, UV, Table Turnover)
- `ReservationTable.tsx` — Booking list and management (예약 목록·관리)
- `PosEventFeed.tsx` — Real-time Loyverse event stream (실시간 POS 이벤트 스트림)

## Coding Rules
- KPI formulas displayed here must match PRD.md exactly (no rounding before display).
  (KPI 공식은 PRD.md와 정확히 일치 — 표시 전 반올림 금지)
- POS event feed must use WebSocket or SSE — no polling.
  (POS 이벤트 피드는 WebSocket 또는 SSE 사용 — 폴링 금지)
