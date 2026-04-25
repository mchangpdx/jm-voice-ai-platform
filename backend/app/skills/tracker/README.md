# skills/tracker/ — Status Tracking Engine
# (트래커 스킬 — 상태 추적 엔진)

## Role
Provides real-time status tracking for any trackable entity: orders, bookings, technician jobs.
Aggregates status history and surfaces it to both Agency and Store dashboard views.
(주문·예약·기사 작업 등 모든 추적 가능 항목의 실시간 상태 제공. 에이전시·점주 대시보드에 노출)

## Key Files Expected
| File | Purpose (목적) |
|------|----------------|
| `__init__.py` | Exposes `execute()` entry point (실행 진입점 공개) |
| `status_store.py` | Read/write status records (상태 레코드 읽기·쓰기) |
| `history.py` | Status transition history log (상태 전환 이력 로그) |
| `notifier.py` | Webhook/push notification dispatch (웹훅·푸시 알림 발송) |

## Coding Rules
- Status values must be defined as Python `Enum` — no raw strings.
  (상태값은 Python `Enum`으로 정의 — 문자열 직접 사용 금지)
- All status changes must be appended to a history table, never overwritten.
  (모든 상태 변경은 이력 테이블에 추가, 덮어쓰기 금지)
