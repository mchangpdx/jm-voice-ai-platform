# views/homecare/agency/ — Home Care HQ Admin View
# (홈케어 에이전시 관리 화면 — 본사·관리자용 뷰)

## Role
Headquarters or agency admin dashboard for home care businesses.
Aggregates LCR, Quote Accuracy, Lead Response Time, and Staff Utilization across all providers.
(홈케어 사업 본사·에이전시 대시보드. 모든 업체의 LCR·견적 정확도·응답 시간·가동률 집계)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `Dashboard.tsx` | HQ aggregated KPI overview (본사 집계 KPI 개요) |
| `LeadPipeline.tsx` | Multi-provider lead funnel view (다중 업체 리드 파이프라인) |
| `TechnicianOverview.tsx` | Aggregate technician utilization (기사 가동률 집계) |
| `QuoteAccuracyChart.tsx` | AI estimate vs actual billed chart (AI 견적 vs 실제 청구 차트) |

## Coding Rules
- LCR formula: `(Confirmed Jobs / Total Inquiries) * 100` — must match PRD.md exactly.
  (LCR 공식: `(확정 작업 / 전체 문의) * 100` — PRD.md와 정확히 일치)
- Aggregate views must never expose individual technician PII to agency admins.
  (집계 뷰에 개별 기사 개인정보 노출 금지)
