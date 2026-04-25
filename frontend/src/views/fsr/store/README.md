# views/fsr/store/ — FSR Store Operational View
# (FSR 점주 운영 화면 — 단일 매장 실시간 운영 뷰)

## Role
Operational dashboard for a single FSR store owner or manager.
Real-time reservations, active voice call log, POS injection events, CCTV overlay status.
(단일 FSR 매장 점주·매니저용 운영 대시보드. 실시간 예약·음성 로그·POS 주입·CCTV 오버레이 상태)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `Dashboard.tsx` | Store operational main view (매장 운영 메인 뷰) |
| `LiveReservations.tsx` | Today's reservation timeline (오늘 예약 타임라인) |
| `VoiceCallLog.tsx` | Real-time AI call transcript (실시간 AI 통화 기록) |
| `PosOverlayStatus.tsx` | Solink overlay push status per event (이벤트별 오버레이 상태) |

## Coding Rules
- Scope all API calls with `store_id` (single tenant scope).
  (모든 API 호출은 `store_id`로 스코프 — 단일 테넌트 범위)
- Voice call log must stream via SSE — buffer max 100 entries before purging oldest.
  (음성 통화 로그는 SSE로 스트리밍 — 최대 100개 버퍼, 초과 시 가장 오래된 항목 제거)
