# views/fsr/agency/ — FSR Agency Dashboard
# (FSR 에이전시 대시보드 — 다중 매장 집계 관리 화면)

## Role
Aggregated management view for franchise HQs or food service agencies.
Shows MCRR, LCS, UV, and Table Turnover Rate across all managed stores.
(프랜차이즈 본사·에이전시용 집계 관리 화면. 관리 매장 전체의 KPI 집계 표시)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `Dashboard.tsx` | Main agency FSR dashboard (에이전시 FSR 메인 대시보드) |
| `StoreRankingTable.tsx` | Store performance ranking (매장 성과 순위 테이블) |
| `KpiSummaryPanel.tsx` | Aggregated MCRR/LCS/UV totals (집계 KPI 합계 패널) |
| `AlertFeed.tsx` | Cross-store alerts and anomalies (다중 매장 알림·이상 감지) |

## Coding Rules
- Data scope: ALL stores under `agency_id` — enforce this in the API service call.
  (데이터 범위: `agency_id` 하의 모든 매장 — API 서비스 호출에서 강제)
- Never show individual store secrets (API keys, tokens) in agency view.
  (에이전시 뷰에 개별 매장 API 키·토큰 표시 금지)
