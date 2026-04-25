# views/homecare/ — Home Care Service Module
# (홈케어 뷰 모듈 — 홈케어 서비스 화면)

## Role
All UI views for the Home Care vertical.
Covers estimation workflows, technician scheduling, job status tracking, and Home Care KPIs.
(홈케어 업종 모든 UI 뷰. 견적 워크플로·기사 스케줄·작업 상태 추적·KPI 포함)

## Structure
| Directory | Role (역할) |
|-----------|------------|
| `agency/` | HQ admin: lead management, technician overview, LCR dashboard (본사 관리자) |
| `store/` | Technician/provider: job list, route map, status updates (기사·업체용) |

## Key Files Expected (per role dir)
- `Dashboard.tsx` — Main view entry point (메인 뷰 진입점)
- `EstimateFlow.tsx` — Variable-based quote generation UI (변수 기반 견적 생성 UI)
- `TechnicianMap.tsx` — Live technician location map (기사 실시간 위치 지도)
- `JobQueue.tsx` — Ordered job list with status (상태별 작업 목록)

## Coding Rules
- Quote display must show both AI estimate and actual billed side-by-side for accuracy tracking.
  (견적 표시는 정확도 추적을 위해 AI 견적과 실제 청구액을 나란히 표시)
- Technician map updates must use WebSocket — no periodic HTTP polling.
  (기사 위치 지도는 WebSocket 업데이트 — HTTP 폴링 금지)
