# views/homecare/store/ — Home Care Provider/Technician View
# (홈케어 점주·기사 뷰 — 업체·기사용 운영 화면)

## Role
Operational view for home care service providers and their technicians.
Shows today's job queue, route optimization, real-time status updates, and quote management.
(홈케어 서비스 업체·기사용 운영 화면. 오늘 작업 목록·경로 최적화·실시간 상태·견적 관리)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `Dashboard.tsx` | Provider operational main view (업체 운영 메인 뷰) |
| `MyJobQueue.tsx` | Technician's assigned job list (기사 배정 작업 목록) |
| `StatusUpdater.tsx` | One-tap job status update buttons (한 번에 상태 업데이트 버튼) |
| `QuoteReview.tsx` | AI estimate review and adjustment (AI 견적 검토·조정) |

## Coding Rules
- Status updates must optimistically update the UI then confirm via API response.
  (상태 업데이트는 낙관적 UI 업데이트 후 API 응답으로 확인)
- Route map is read-only for technicians — no direct address editing in this view.
  (기사용 경로 지도는 읽기 전용 — 이 뷰에서 주소 직접 편집 금지)
